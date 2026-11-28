"""Unit, mocked-Gemini, persistence, and guardrail tests for Feature 4 (/copilot/)."""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.core.ai import ActionableDispatchBriefing, MergeRiskAssessment
from apps.core.models import DispatchPlan, SafetyOverride, Trip, Vessel
from apps.optimizer.copilot_services import (
    COPILOT_SCENARIOS,
    apply_recommended_hse_hold,
    approve_ai_cleared_merges,
    get_saved_briefings,
    run_copilot_review,
    save_handover_briefing,
)
from apps.optimizer.services import run_shift_optimizer


def _kuwait_dt(day: date, clock: time) -> datetime:
    tz = timezone.get_default_timezone()
    return timezone.make_aware(datetime.combine(day, clock), tz)


class CopilotServiceUnitTests(TestCase):
    def test_empty_db_handled_gracefully(self):
        result = run_copilot_review(invoke_ai=False)
        self.assertEqual(result["pending_count"], 0)
        self.assertEqual(result["merge_assessments"], [])
        self.assertEqual(result["approve_count"], 0)
        self.assertEqual(result["review_count"], 0)
        self.assertEqual(result["hold_count"], 0)
        self.assertEqual(result["recommended_holds"], [])
        self.assertTrue(result["ai_fallback_used"])
        self.assertTrue(result["briefing"]["executive_summary"])
        self.assertTrue(result["briefing"]["safety_flags"])
        self.assertEqual(get_saved_briefings(), [])

    def test_seeded_deterministic_verdicts_across_scenarios(self):
        call_command("seed_fleet")

        # 1. Standard Shift Handover (strict_weather=True, milk_run=False) -> 3 clean approves
        std = run_copilot_review(
            scenario_key="standard_handover",
            strict_weather=True,
            allow_milk_run=False,
            invoke_ai=False,
        )
        self.assertEqual(std["approve_count"], 3)
        self.assertEqual(std["review_count"], 0)
        self.assertEqual(std["hold_count"], 0)
        self.assertEqual(len(std["approved_merge_ids"]), 3)
        self.assertEqual(std["high_anomalies_count"], 39)
        self.assertEqual(std["missing_logs_count"], 15)

        # Recommended holds surface CB-08 Maintenance Hold (TR-00012) + Platform C Weather Hold
        holds_by_type = {h["rule_type"]: h for h in std["recommended_holds"]}
        self.assertIn("maintenance_hold", holds_by_type)
        self.assertEqual(holds_by_type["maintenance_hold"]["vessel_id"], "CB-08")
        self.assertEqual(holds_by_type["maintenance_hold"]["source_trip_id"], "TR-00012")
        self.assertFalse(holds_by_type["maintenance_hold"]["is_already_active"])
        self.assertIn("weather_hold", holds_by_type)
        self.assertEqual(holds_by_type["weather_hold"]["destination"], "Platform C")
        self.assertFalse(holds_by_type["weather_hold"]["is_already_active"])

        # 2. Rough-Sea Audit (strict_weather=False) -> Platform C rough pair gets HOLD verdict
        rough = run_copilot_review(
            scenario_key="rough_sea_audit",
            strict_weather=False,
            allow_milk_run=False,
            invoke_ai=False,
        )
        self.assertEqual(rough["approve_count"], 3)
        self.assertEqual(rough["hold_count"], 1)
        by_id = {c["group_id"]: c for c in rough["merge_assessments"]}
        self.assertEqual(by_id["TR-QUEUE-07+TR-QUEUE-08"]["verdict"], "hold")
        self.assertEqual(by_id["TR-QUEUE-07+TR-QUEUE-08"]["risk_level"], "high")

        # 3. Fuel Outlier Investigation -> flags CB-03 (TR-00138 1.98x) merges for review
        fuel = run_copilot_review(
            scenario_key="fuel_outlier_check",
            strict_weather=True,
            allow_milk_run=False,
            invoke_ai=False,
        )
        self.assertEqual(fuel["approve_count"], 1)
        self.assertEqual(fuel["review_count"], 2)
        fuel_by_id = {c["group_id"]: c for c in fuel["merge_assessments"]}
        self.assertEqual(fuel_by_id["TR-QUEUE-01+TR-QUEUE-02"]["verdict"], "review")
        self.assertIn("CB-03", fuel_by_id["TR-QUEUE-01+TR-QUEUE-02"]["rationale"])
        self.assertEqual(fuel_by_id["TR-QUEUE-05+TR-QUEUE-06"]["verdict"], "approve")

    def test_deterministic_review_verdicts_for_milk_run_and_outlier_carrier(self):
        cb01 = Vessel.objects.create(
            vessel_id="CB-01",
            vessel_type="Crew Boat",
            passenger_capacity=20,
            cargo_capacity_t=1.0,
            underway_rate_lph=100.0,
            idle_rate_lph=20.0,
            cruise_speed_kn=16.0,
            hourly_operating_kwd=42.0,
            status="In Service",
        )
        cb08 = Vessel.objects.create(
            vessel_id="CB-08",
            vessel_type="Multi-purpose Boat",
            passenger_capacity=14,
            cargo_capacity_t=5.0,
            underway_rate_lph=120.0,
            idle_rate_lph=30.0,
            cruise_speed_kn=14.0,
            hourly_operating_kwd=62.0,
            status="In Service",
        )
        day = date(2026, 11, 28)

        # Milk-run pair (Platform A + Platform B) -> review verdict
        Trip.objects.create(
            trip_id="TR-MR-1",
            vessel=cb01,
            trip_date=day,
            mission_type="Passenger Transfer",
            destination="Platform A",
            earliest_departure_dt=_kuwait_dt(day, time(8, 0)),
            latest_departure_dt=_kuwait_dt(day, time(9, 30)),
            departure_dt=_kuwait_dt(day, time(8, 15)),
            passengers=4,
            cargo_tonnes=0.1,
            weather="Calm",
            flexible_window=True,
            status="pending",
        )
        Trip.objects.create(
            trip_id="TR-MR-2",
            vessel=cb01,
            trip_date=day,
            mission_type="Passenger Transfer",
            destination="Platform B",
            earliest_departure_dt=_kuwait_dt(day, time(8, 0)),
            latest_departure_dt=_kuwait_dt(day, time(9, 30)),
            departure_dt=_kuwait_dt(day, time(8, 45)),
            passengers=4,
            cargo_tonnes=0.1,
            weather="Calm",
            flexible_window=True,
            status="pending",
        )
        milk_res = run_copilot_review(
            scenario_key="milk_run_push",
            strict_weather=True,
            allow_milk_run=True,
            invoke_ai=False,
        )
        self.assertEqual(milk_res["review_count"], 1)
        self.assertEqual(milk_res["merge_assessments"][0]["verdict"], "review")
        self.assertEqual(milk_res["merge_assessments"][0]["risk_level"], "medium")

        # Historical severe outlier (>=1.75x) on CB-08 + cargo merge requiring CB-08 -> review
        Trip.objects.create(
            trip_id="TR-HIST-HIGH",
            vessel=cb08,
            trip_date=date(2026, 10, 1),
            mission_type="Material Delivery",
            destination="Offshore Terminal",
            departure_dt=_kuwait_dt(date(2026, 10, 1), time(8, 0)),
            underway_hours=2.0,
            onsite_work_hours=0.5,
            nonproductive_idle_hours=0.5,
            passengers=2,
            cargo_tonnes=2.0,
            weather="Moderate",
            actual_fuel_l=560.0,  # Expected = 2*120 + 1*30 = 270 -> 2.07x
            status="completed",
        )
        Trip.objects.create(
            trip_id="TR-C8-1",
            vessel=cb08,
            trip_date=day,
            mission_type="Material Delivery",
            destination="Offshore Terminal",
            earliest_departure_dt=_kuwait_dt(day, time(10, 0)),
            latest_departure_dt=_kuwait_dt(day, time(11, 30)),
            departure_dt=_kuwait_dt(day, time(10, 15)),
            passengers=2,
            cargo_tonnes=1.5,
            weather="Calm",
            flexible_window=True,
            status="pending",
        )
        Trip.objects.create(
            trip_id="TR-C8-2",
            vessel=cb08,
            trip_date=day,
            mission_type="Material Delivery",
            destination="Offshore Terminal",
            earliest_departure_dt=_kuwait_dt(day, time(10, 0)),
            latest_departure_dt=_kuwait_dt(day, time(11, 30)),
            departure_dt=_kuwait_dt(day, time(10, 45)),
            passengers=2,
            cargo_tonnes=1.5,
            weather="Calm",
            flexible_window=True,
            status="pending",
        )
        outlier_res = run_copilot_review(
            scenario_key="fuel_outlier_check",
            strict_weather=True,
            allow_milk_run=False,
            invoke_ai=False,
        )
        by_id = {c["group_id"]: c for c in outlier_res["merge_assessments"]}
        self.assertEqual(by_id["TR-C8-1+TR-C8-2"]["verdict"], "review")
        self.assertIn("CB-08", by_id["TR-C8-1+TR-C8-2"]["rationale"])

    @patch("apps.optimizer.copilot_services.generate_structured")
    def test_mocked_live_gemini_briefing_and_missing_group_normalization(
        self, mock_generate
    ):
        call_command("seed_fleet")
        # Return assessments for only 1 of 3 merges to verify missing-group normalization
        mock_generate.return_value = (
            ActionableDispatchBriefing(
                executive_summary="Live Gemini 4 review: approve Platform A and B; review Terminal.",
                merge_assessments=[
                    MergeRiskAssessment(
                        group_id="TR-QUEUE-01+TR-QUEUE-02",
                        verdict="approve",
                        risk_level="low",
                        rationale="Gemini verified calm crew transfer on CB-03.",
                    ),
                    MergeRiskAssessment(
                        group_id="TR-QUEUE-05+TR-QUEUE-06",
                        verdict="review",
                        risk_level="medium",
                        rationale="Verify heavy valve skid lashing on Offshore Terminal run.",
                    ),
                ],
                safety_flags=["CB-07 standby lock verified active."],
                shift_handover_note="Hand over Platform C rough-weather watch to afternoon shift.",
                estimated_impact_note="Eliminates 2 trips with live Gemini confirmation.",
            ),
            None,
        )

        res = run_copilot_review(
            scenario_key="standard_handover",
            strict_weather=True,
            allow_milk_run=False,
            invoke_ai=True,
        )
        self.assertFalse(res["ai_fallback_used"])
        self.assertTrue(res["ai_live_used"])
        self.assertEqual(len(res["merge_assessments"]), 3)
        by_id = {c["group_id"]: c for c in res["merge_assessments"]}
        self.assertEqual(by_id["TR-QUEUE-01+TR-QUEUE-02"]["verdict"], "approve")
        self.assertIn("Gemini verified", by_id["TR-QUEUE-01+TR-QUEUE-02"]["rationale"])
        # Normalized from deterministic fallback because Gemini omitted TR-QUEUE-03+TR-QUEUE-04
        self.assertEqual(by_id["TR-QUEUE-03+TR-QUEUE-04"]["verdict"], "approve")
        self.assertEqual(by_id["TR-QUEUE-05+TR-QUEUE-06"]["verdict"], "review")
        self.assertEqual(res["approve_count"], 2)
        self.assertEqual(res["review_count"], 1)

        # Verify generate_structured was invoked with ActionableDispatchBriefing and thinking_level="medium"
        kwargs = mock_generate.call_args.kwargs
        self.assertIs(kwargs["response_schema"], ActionableDispatchBriefing)
        self.assertEqual(kwargs["thinking_level"], "medium")
        self.assertNotIn("temperature", kwargs)

    def test_persistence_helpers_and_idempotent_hold_application(self):
        call_command("seed_fleet")
        res = run_copilot_review(invoke_ai=False)

        saved_plan, save_msg = save_handover_briefing(
            briefing_dict=res["briefing"],
            ai_fallback_used=True,
            scenario_title="Standard Shift Handover",
            directive="Check standby",
            strict_weather=True,
            allow_milk_run=False,
            solver_summary=res["cleared_summary"],
        )
        self.assertFalse(saved_plan.is_approved)
        self.assertIn("Saved shift handover briefing", save_msg)
        self.assertEqual(len(get_saved_briefings()), 1)

        ov1, created1, msg1 = apply_recommended_hse_hold(
            rule_type="maintenance_hold",
            vessel_id="CB-08",
            source_trip_id="TR-00012",
            severity="critical",
        )
        self.assertIsNotNone(ov1)
        self.assertTrue(created1)
        self.assertIn("CB-08", msg1)
        self.assertEqual(ov1.source_trip.trip_id, "TR-00012")

        # Idempotent second call does not duplicate
        ov2, created2, _ = apply_recommended_hse_hold(
            rule_type="maintenance_hold",
            vessel_id="CB-08",
            source_trip_id="TR-00012",
        )
        self.assertEqual(ov1.pk, ov2.pk)
        self.assertFalse(created2)

        approved_plan, app_msg = approve_ai_cleared_merges(
            merge_ids=res["approved_merge_ids"],
            briefing_dict=res["briefing"],
            ai_fallback_used=False,
            strict_weather=True,
            allow_milk_run=False,
        )
        self.assertIsNotNone(approved_plan)
        assert approved_plan is not None
        self.assertTrue(approved_plan.is_approved)
        self.assertEqual(approved_plan.trips_eliminated, 3)
        self.assertFalse(approved_plan.ai_fallback_used)
        self.assertEqual(
            approved_plan.ai_briefing["executive_summary"],
            res["briefing"]["executive_summary"],
        )
        self.assertIn("Approved", app_msg)
        self.assertEqual(len(get_saved_briefings()), 2)


class CopilotViewsIntegrationTests(TestCase):
    def setUp(self):
        call_command("seed_fleet")

    def test_index_and_ping_smoke_plus_guardrail_html(self):
        resp = self.client.get(reverse("core:copilot:index"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "AI Dispatch Co-Pilot")
        self.assertContains(resp, 'id="copilot-workspace"')
        self.assertEqual(len(resp.context["scenarios"]), len(COPILOT_SCENARIOS))

        # Guardrail checks: zero developer/DB/model strings, zero this.$el
        for forbidden in (
            "gemini-4-hydrogen",
            "PostgreSQL",
            "Test HTMX + CSRF",
            "Feature 04",
            "copilot_views.py",
            "this.$el",
        ):
            self.assertNotContains(resp, forbidden)

        ping_resp = self.client.post(reverse("core:copilot:ping"))
        self.assertEqual(ping_resp.status_code, 200)
        self.assertContains(ping_resp, "HTMX POST + CSRF verified")

    @override_settings(GEMINI_API_KEY="")
    def test_review_endpoint_falls_back_cleanly_without_api_key(self):
        resp = self.client.post(
            reverse("core:copilot:review"),
            {
                "scenario_key": "rough_sea_audit",
                "strict_weather": ["0"],
                "allow_milk_run": ["0"],
                "directive": "Check Platform C rough swell",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context["ai_fallback_used"])
        self.assertEqual(resp.context["hold_count"], 1)
        self.assertContains(resp, "Deterministic Fallback")
        self.assertNotContains(resp, "gemini-4-hydrogen")

    @patch("apps.optimizer.copilot_services.generate_structured")
    def test_review_endpoint_renders_live_ai_analysis_when_gemini_succeeds(
        self, mock_generate
    ):
        mock_generate.return_value = (
            ActionableDispatchBriefing(
                executive_summary="Live Gemini 4 confirmed 3 safe calm-corridor merges.",
                merge_assessments=[
                    MergeRiskAssessment(
                        group_id="TR-QUEUE-01+TR-QUEUE-02",
                        verdict="approve",
                        risk_level="low",
                        rationale="Calm sea, optimal CB-03 crew capacity.",
                    ),
                ],
                safety_flags=["CB-07 standby vessel remains protected."],
                shift_handover_note="Approve calm crew merges and hold rough Platform C trips.",
                estimated_impact_note="Saves 3 trips and 492 KWD (mock).",
            ),
            None,
        )
        resp = self.client.post(
            reverse("core:copilot:review"),
            {
                "scenario_key": "standard_handover",
                "strict_weather": ["0", "1"],
                "allow_milk_run": ["0"],
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.context["ai_fallback_used"])
        self.assertTrue(resp.context["ai_live_used"])
        self.assertContains(resp, "Live AI Analysis")
        self.assertContains(resp, "Live Gemini 4 confirmed 3 safe calm-corridor merges.")

    def test_save_briefing_endpoint_persists_and_appears_in_saved_briefings(self):
        brief_payload = {
            "executive_summary": "Persisted executive handover brief.",
            "merge_assessments": [],
            "safety_flags": ["CB-07 standby lock active."],
            "shift_handover_note": "Monitor Platform C swell.",
            "estimated_impact_note": "Saves 492 KWD (mock).",
            "scenario_title": "Standard Shift Handover",
            "approve_count": 3,
            "review_count": 0,
            "hold_count": 0,
        }
        resp = self.client.post(
            reverse("core:copilot:save_briefing"),
            {
                "scenario_key": "standard_handover",
                "strict_weather": "1",
                "allow_milk_run": "0",
                "ai_fallback_used": "0",
                "briefing_json": json.dumps(brief_payload),
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["saved_briefings_count"], 1)
        saved = DispatchPlan.objects.first()
        self.assertIsNotNone(saved)
        assert saved is not None
        self.assertFalse(saved.is_approved)
        self.assertEqual(
            saved.ai_briefing["executive_summary"],
            "Persisted executive handover brief.",
        )

        # Reloading /copilot/?tab=briefings still displays persisted briefing
        reload_resp = self.client.get(reverse("core:copilot:index"), {"tab": "briefings"})
        self.assertEqual(reload_resp.status_code, 200)
        self.assertEqual(reload_resp.context["active_tab"], "briefings")
        self.assertContains(reload_resp, "Persisted executive handover brief.")

    def test_approve_recommended_endpoint_consolidates_trips_and_saves_briefing(self):
        resp = self.client.post(
            reverse("core:copilot:approve_recommended"),
            {
                "scenario_key": "standard_handover",
                "strict_weather": "1",
                "allow_milk_run": "0",
                "merge_ids": ["TR-QUEUE-01+TR-QUEUE-02", "TR-QUEUE-03+TR-QUEUE-04"],
                "plan_name": "AI Cleared Morning Plan",
            },
        )
        self.assertEqual(resp.status_code, 200)
        plan = DispatchPlan.objects.get(name="AI Cleared Morning Plan")
        self.assertTrue(plan.is_approved)
        self.assertEqual(plan.trips_eliminated, 2)
        self.assertTrue(bool(plan.ai_briefing))
        self.assertEqual(Trip.objects.get(trip_id="TR-QUEUE-02").status, "consolidated")
        self.assertEqual(Trip.objects.get(trip_id="TR-QUEUE-04").status, "consolidated")
        self.assertEqual(resp.context["saved_briefings_count"], 1)

    def test_apply_hold_endpoint_persists_and_constrains_optimizer(self):
        resp = self.client.post(
            reverse("core:copilot:apply_hold"),
            {
                "scenario_key": "fuel_outlier_check",
                "strict_weather": "1",
                "allow_milk_run": "0",
                "rule_type": "maintenance_hold",
                "vessel_id": "CB-08",
                "source_trip_id": "TR-00012",
                "severity": "critical",
                "reason": "Engineering fuel-burn inspection for TR-00012 (2.07x).",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["active_subtab"], "safety")
        self.assertTrue(
            SafetyOverride.objects.filter(
                rule_type="maintenance_hold",
                vessel__vessel_id="CB-08",
                is_active=True,
            ).exists()
        )
        # Cross-slice confirmation: optimizer immediately enforces the new CB-08 hold
        solver = run_shift_optimizer(strict_weather=True, allow_milk_run=False)
        self.assertNotIn("CB-08", {v.vessel_id for v in solver["eligible_vessels"]})
        held_map = {h["trip"].trip_id: h["category"] for h in solver["held_trips"]}
        self.assertEqual(held_map["TR-QUEUE-10"], "maintenance_hold")

        # Applying Platform C weather hold also constrains optimizer even with strict_weather=False
        w_resp = self.client.post(
            reverse("core:copilot:apply_hold"),
            {
                "scenario_key": "rough_sea_audit",
                "strict_weather": "0",
                "allow_milk_run": "0",
                "rule_type": "weather_hold",
                "destination": "Platform C",
                "severity": "high",
            },
        )
        self.assertEqual(w_resp.status_code, 200)
        solver_relaxed = run_shift_optimizer(strict_weather=False, allow_milk_run=False)
        relaxed_held = {h["trip"].trip_id: h["category"] for h in solver_relaxed["held_trips"]}
        self.assertEqual(relaxed_held["TR-QUEUE-07"], "weather_hold")
        self.assertEqual(relaxed_held["TR-QUEUE-08"], "weather_hold")
