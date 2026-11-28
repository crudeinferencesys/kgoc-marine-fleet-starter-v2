import io
import tempfile
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pandas as pd
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.core.ai import (
    ActionableDispatchBriefing,
    DispatchBriefing,
    generate_structured,
)
from apps.core.models import DispatchPlan, SafetyOverride, Trip, Vessel, VesselAvailability
from apps.core.services import get_control_tower_metrics


class CoreSmokeTests(TestCase):
    def test_home_renders_with_global_htmx_csrf_header_and_clean_slim_topbar(self):
        response = self.client.get(reverse("core:home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "X-CSRFToken")
        self.assertContains(response, "KGOC Marine Fleet")
        self.assertContains(response, "CrudeInference")
        self.assertNotContains(response, reverse("core:health"))
        self.assertNotContains(response, "DB: sqlite3")
        self.assertNotContains(response, "gemini-4-hydrogen")
        self.assertContains(response, "Plus Jakarta Sans")
        self.assertContains(response, "JetBrains Mono")
        self.assertContains(response, "#0A1628")
        self.assertContains(response, "--p: 56% 0.11 180")

    def test_home_renders_top_bar_navigation_without_burger_menu(self):
        response = self.client.get(reverse("core:home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="primary-top-nav"')
        self.assertContains(response, reverse("core:home"))
        self.assertContains(response, reverse("trips:index"))
        self.assertContains(response, reverse("optimizer:index"))
        self.assertContains(response, reverse("safety:index"))
        self.assertContains(response, reverse("core:copilot:index"))
        self.assertContains(response, "04 · AI")
        self.assertNotContains(response, 'id="command-sidebar"')
        self.assertNotContains(response, "Toggle navigation menu")

    def test_home_renders_scroll_awareness_and_calm_validation_shell(self):
        response = self.client.get(reverse("core:home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="scroll-progress-bar"')
        self.assertContains(response, "animation-timeline: scroll(root block)")
        self.assertContains(
            response,
            "@supports ((animation-timeline: view()) and (animation-range: entry))",
        )
        self.assertContains(response, 'id="topbar-scroll-context"')
        self.assertContains(response, 'id="back-to-top-btn"')
        self.assertContains(response, ".field-control:user-invalid")
        self.assertContains(response, "IntersectionObserver")

    @override_settings(GEMINI_MODEL="gemini-4-hydrogen")
    def test_health_and_healthz_report_ok_database_and_model(self):
        for url_name in ("core:health", "core:healthz"):
            response = self.client.get(reverse(url_name))
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["status"], "ok")
            self.assertEqual(payload["database"], "sqlite3")
            self.assertIn("ai_configured", payload)
            self.assertEqual(payload["gemini_model"], "gemini-4-hydrogen")

    @override_settings(GEMINI_API_KEY="")
    def test_generate_structured_handles_missing_api_key_gracefully(self):
        result, error = generate_structured(
            prompt="Summarize vessel utilization.",
            response_schema=DispatchBriefing,
        )
        self.assertIsNone(result)
        self.assertIsNotNone(error)
        self.assertIn("GEMINI_API_KEY", error)

    @override_settings(GEMINI_API_KEY="test-key", GEMINI_MODEL="gemini-4-hydrogen")
    @patch("apps.core.ai.genai.Client")
    def test_generate_structured_uses_interactions_api_without_temperature(self, mock_client_cls):
        expected = DispatchBriefing(
            executive_summary="Merge two half-empty runs.",
            recommended_actions=["Consolidate Trip A and Trip B"],
            safety_flags=[],
            estimated_impact_note="Saves 1 trip and 420 L fuel.",
        )
        mock_client = MagicMock()
        mock_client.interactions.create.return_value = SimpleNamespace(
            output_text=expected.model_dump_json(),
            steps=[],
        )
        mock_client_cls.return_value = mock_client

        result, error = generate_structured(
            prompt="Summarize vessel utilization.",
            response_schema=DispatchBriefing,
            system_instruction="Be concise.",
        )

        self.assertIsNone(error)
        self.assertEqual(result, expected)
        kwargs = mock_client.interactions.create.call_args.kwargs
        self.assertEqual(kwargs["model"], "gemini-4-hydrogen")
        self.assertEqual(kwargs["response_format"]["mime_type"], "application/json")
        self.assertEqual(kwargs["generation_config"], {"thinking_level": "medium"})
        self.assertNotIn("temperature", kwargs["generation_config"])
        self.assertEqual(kwargs["system_instruction"], "Be concise.")

    @override_settings(GEMINI_API_KEY="test-key", GEMINI_MODEL="gemini-4-hydrogen")
    @patch("apps.core.ai.genai.Client")
    def test_generate_structured_strips_markdown_json_fences(self, mock_client_cls):
        expected = DispatchBriefing(
            executive_summary="Fenced output parsed cleanly.",
            recommended_actions=["Keep single standby boat"],
            safety_flags=["High swell warning"],
            estimated_impact_note="Saves 180 KWD.",
        )
        mock_client = MagicMock()
        mock_client.interactions.create.return_value = SimpleNamespace(
            output_text=f"```json\n{expected.model_dump_json()}\n```",
            steps=[],
        )
        mock_client_cls.return_value = mock_client

        result, error = generate_structured(
            prompt="Summarize fenced output.",
            response_schema=DispatchBriefing,
        )

        self.assertIsNone(error)
        self.assertEqual(result, expected)

    @override_settings(GEMINI_API_KEY="test-key", GEMINI_MODEL="gemini-4-hydrogen")
    @patch("apps.core.ai.genai.Client")
    def test_generate_structured_returns_error_on_sdk_exception(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client.interactions.create.side_effect = RuntimeError("boom")
        mock_client_cls.return_value = mock_client

        result, error = generate_structured(
            prompt="Trigger SDK error.",
            response_schema=DispatchBriefing,
        )

        self.assertIsNone(result)
        self.assertEqual(error, "Gemini request failed: RuntimeError")

    def test_inspect_dataset_csv_and_multisheet_xlsx(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            csv_path = tmp_path / "trips.csv"
            xlsx_path = tmp_path / "fleet.xlsx"

            trips_df = pd.DataFrame(
                {
                    "trip_id": [f"T-{i:03d}" for i in range(1, 16)],
                    "vessel": ["Al-Khafji" if i % 2 == 0 else "Safaniya" for i in range(1, 16)],
                    "departure_time": [f"2026-11-{(i % 28) + 1:02d} 08:00" for i in range(1, 16)],
                    "fuel_liters": [400 + i * 10 for i in range(1, 16)],
                }
            )
            vessels_df = pd.DataFrame(
                {
                    "vessel_name": ["Al-Khafji", "Safaniya"],
                    "pax_capacity": [20, 18],
                }
            )

            trips_df.to_csv(csv_path, index=False)
            with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
                vessels_df.to_excel(writer, sheet_name="Vessels", index=False)
                trips_df.to_excel(writer, sheet_name="Trips", index=False)

            csv_out = io.StringIO()
            call_command("inspect_dataset", str(csv_path), stdout=csv_out)
            csv_text = csv_out.getvalue()
            self.assertIn("15 rows x 4 columns", csv_text)
            self.assertIn("sample_values", csv_text)
            self.assertIn("Date / Datetime Ranges", csv_text)
            self.assertIn("departure_time", csv_text)

            xlsx_all_out = io.StringIO()
            call_command("inspect_dataset", str(xlsx_path), stdout=xlsx_all_out)
            xlsx_all_text = xlsx_all_out.getvalue()
            self.assertIn("Sheets (2): Vessels, Trips", xlsx_all_text)
            self.assertIn("Sheet / Table: Vessels", xlsx_all_text)
            self.assertIn("2 rows x 2 columns", xlsx_all_text)
            self.assertIn("Sheet / Table: Trips", xlsx_all_text)
            self.assertIn("15 rows x 4 columns", xlsx_all_text)

            xlsx_single_out = io.StringIO()
            call_command("inspect_dataset", str(xlsx_path), sheet="Vessels", stdout=xlsx_single_out)
            xlsx_single_text = xlsx_single_out.getvalue()
            self.assertIn("Sheet / Table: Vessels", xlsx_single_text)
            self.assertNotIn("Sheet / Table: Trips", xlsx_single_text)

    def test_seed_fleet_and_idempotency(self):
        out1 = io.StringIO()
        call_command("seed_fleet", if_empty=True, stdout=out1)
        self.assertEqual(Vessel.objects.count(), 8)
        self.assertEqual(VesselAvailability.objects.count(), 720)
        self.assertEqual(Trip.objects.filter(status="completed").count(), 976)
        self.assertEqual(Trip.objects.filter(status="pending", is_synthetic_queue=True).count(), 12)
        self.assertEqual(
            SafetyOverride.objects.filter(
                rule_type="standby_lock", vessel__vessel_id="CB-07", is_active=True
            ).count(),
            1,
        )

        out2 = io.StringIO()
        call_command("seed_fleet", if_empty=True, stdout=out2)
        self.assertIn("skipping", out2.getvalue())
        self.assertEqual(Vessel.objects.count(), 8)
        self.assertEqual(Trip.objects.count(), 988)

    def test_trip_utilization_and_fuel_anomaly_properties(self):
        vessel = Vessel.objects.create(
            vessel_id="CB-TEST",
            vessel_type="Crew Boat",
            passenger_capacity=20,
            cargo_capacity_t=1.0,
            underway_rate_lph=100.0,
            idle_rate_lph=20.0,
            cruise_speed_kn=18.0,
        )
        dep = timezone.make_aware(datetime(2026, 11, 28, 8, 0), ZoneInfo("Asia/Kuwait"))

        # Expected fuel = 2.0 * 100 + (0.5 + 0.5) * 20 = 220.0 L
        normal_trip = Trip.objects.create(
            trip_id="TR-T1",
            vessel=vessel,
            trip_date=date(2026, 11, 28),
            mission_type="Passenger Transfer",
            destination="Platform A",
            departure_dt=dep,
            underway_hours=2.0,
            onsite_work_hours=0.5,
            nonproductive_idle_hours=0.5,
            passengers=5,
            cargo_tonnes=0.1,
            actual_fuel_l=220.0,
        )
        self.assertEqual(normal_trip.utilization_pct, 25.0)
        self.assertTrue(normal_trip.is_half_empty)
        self.assertEqual(normal_trip.expected_fuel_l, 220.0)
        self.assertEqual(normal_trip.fuel_ratio, 1.0)
        self.assertEqual(normal_trip.fuel_excess_l, 0.0)
        self.assertEqual(normal_trip.idle_fuel_l, 10.0)
        self.assertEqual(normal_trip.fuel_anomaly_status, "normal")

        high_trip = Trip.objects.create(
            trip_id="TR-T2",
            vessel=vessel,
            trip_date=date(2026, 11, 28),
            mission_type="Passenger Transfer",
            destination="Platform A",
            departure_dt=dep,
            underway_hours=2.0,
            onsite_work_hours=0.5,
            nonproductive_idle_hours=0.5,
            passengers=15,
            cargo_tonnes=0.2,
            actual_fuel_l=330.0,
        )
        self.assertFalse(high_trip.is_half_empty)
        self.assertEqual(high_trip.fuel_ratio, 1.5)
        self.assertEqual(high_trip.fuel_anomaly_status, "high")

        low_trip = Trip.objects.create(
            trip_id="TR-T3",
            vessel=vessel,
            trip_date=date(2026, 11, 28),
            mission_type="Passenger Transfer",
            destination="Platform A",
            departure_dt=dep,
            underway_hours=2.0,
            onsite_work_hours=0.5,
            nonproductive_idle_hours=0.5,
            passengers=10,
            cargo_tonnes=0.1,
            actual_fuel_l=140.0,
        )
        self.assertEqual(low_trip.fuel_anomaly_status, "low")

        missing_trip = Trip.objects.create(
            trip_id="TR-T4",
            vessel=vessel,
            trip_date=date(2026, 11, 28),
            mission_type="Passenger Transfer",
            destination="Platform A",
            departure_dt=dep,
            underway_hours=2.0,
            onsite_work_hours=0.5,
            nonproductive_idle_hours=0.5,
            passengers=10,
            cargo_tonnes=0.1,
            actual_fuel_l=None,
        )
        self.assertIsNone(missing_trip.fuel_ratio)
        self.assertEqual(missing_trip.fuel_anomaly_status, "missing")

    def test_actionable_dispatch_briefing_schema_validation(self):
        payload = {
            "executive_summary": "Approve 2 calm merges; hold rough-weather merge.",
            "merge_assessments": [
                {
                    "group_id": "GRP-1",
                    "verdict": "approve",
                    "risk_level": "low",
                    "rationale": "Combined load is 50% capacity in Calm weather.",
                },
                {
                    "group_id": "GRP-2",
                    "verdict": "hold",
                    "risk_level": "high",
                    "rationale": "Rough weather requires separate standby margin.",
                },
            ],
            "safety_flags": ["CB-07 protected by standby lock"],
            "shift_handover_note": "Monitor Platform C sea state before noon.",
            "estimated_impact_note": "Eliminates 2 trips and saves 390 KWD.",
        }
        brief = ActionableDispatchBriefing.model_validate(payload)
        self.assertEqual(len(brief.merge_assessments), 2)
        self.assertEqual(brief.merge_assessments[1].verdict, "hold")

    def test_control_tower_renders_live_seeded_kpis_and_four_charts(self):
        call_command("seed_fleet", if_empty=True, stdout=io.StringIO())
        response = self.client.get(reverse("core:home"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Teammate A")
        self.assertNotContains(response, "DB: sqlite3")
        self.assertNotContains(response, "gemini-4-hydrogen")
        self.assertNotContains(response, "Book Shift Trip")
        self.assertNotContains(response, "Open Optimizer")
        self.assertContains(response, "Control Tower")
        self.assertContains(response, "976")
        self.assertContains(response, "CB-07 Standby Lock")
        for chart_id in (
            "control-tower-vessel-chart",
            "control-tower-destination-chart",
            "control-tower-savings-chart",
            "control-tower-fuel-health-chart",
        ):
            self.assertContains(response, chart_id)
        for drill_url in (
            reverse("trips:index"),
            f"{reverse('trips:index')}?half_empty=1",
            reverse("optimizer:index"),
            reverse("safety:index"),
        ):
            self.assertContains(response, drill_url)

    def test_control_tower_metrics_chart_shapes_empty_and_seeded(self):
        empty_metrics = get_control_tower_metrics()
        self.assertEqual(empty_metrics["historical_trips"], 0)
        self.assertEqual(len(empty_metrics["destination_chart_data"]["labels"]), 5)
        self.assertEqual(empty_metrics["destination_chart_data"]["healthy_counts"], [0, 0, 0, 0, 0])
        self.assertEqual(empty_metrics["savings_chart_data"]["merges"], [0, 0, 0, 0, 0])
        self.assertEqual(empty_metrics["fuel_health_chart_data"]["counts"], [0, 0, 0, 0])

        call_command("seed_fleet", if_empty=True, stdout=io.StringIO())
        seeded_metrics = get_control_tower_metrics()
        self.assertEqual(seeded_metrics["historical_trips"], 976)
        self.assertEqual(
            sum(seeded_metrics["destination_chart_data"]["healthy_counts"])
            + sum(seeded_metrics["destination_chart_data"]["half_empty_counts"]),
            976,
        )
        self.assertEqual(
            sum(seeded_metrics["savings_chart_data"]["merges"]),
            seeded_metrics["backtest_trips_eliminated"],
        )
        self.assertEqual(sum(seeded_metrics["fuel_health_chart_data"]["counts"]), 976)

    def test_copilot_4th_feature_route_and_navigation(self):
        home_response = self.client.get(reverse("core:home"))
        self.assertEqual(home_response.status_code, 200)
        self.assertContains(home_response, reverse("core:copilot:index"))
        self.assertContains(home_response, "04 · AI")

        copilot_response = self.client.get(reverse("core:copilot:index"))
        self.assertEqual(copilot_response.status_code, 200)
        self.assertContains(copilot_response, "AI Dispatch Co-Pilot")

        ping_response = self.client.post(reverse("core:copilot:ping"))
        self.assertEqual(ping_response.status_code, 200)
        self.assertContains(ping_response, "HTMX POST + CSRF verified")

    def test_control_tower_metrics_aggregates_approved_dispatch_plans(self):
        empty_metrics = get_control_tower_metrics()
        self.assertEqual(empty_metrics["approved_plans_count"], 0)
        self.assertEqual(empty_metrics["approved_plans_trips_eliminated"], 0)
        self.assertEqual(empty_metrics["approved_plans_fuel_saved_l"], 0.0)
        self.assertEqual(empty_metrics["approved_plans_kwd_saved"], 0.0)

        DispatchPlan.objects.create(
            name="Shift Plan A",
            scope="pending",
            baseline_trips=6,
            optimized_trips=4,
            trips_eliminated=2,
            fuel_liters_saved=450.25,
            kwd_saved=215.555,
            is_approved=True,
        )
        DispatchPlan.objects.create(
            name="Shift Plan B",
            scope="pending",
            baseline_trips=4,
            optimized_trips=3,
            trips_eliminated=1,
            fuel_liters_saved=200.1,
            kwd_saved=100.111,
            is_approved=True,
        )
        DispatchPlan.objects.create(
            name="Reverted Plan C",
            scope="pending",
            baseline_trips=8,
            optimized_trips=3,
            trips_eliminated=5,
            fuel_liters_saved=999.0,
            kwd_saved=999.0,
            is_approved=False,
        )

        metrics = get_control_tower_metrics()
        self.assertEqual(metrics["approved_plans_count"], 2)
        self.assertEqual(metrics["approved_plans_trips_eliminated"], 3)
        self.assertEqual(metrics["approved_plans_fuel_saved_l"], 650.4)
        self.assertEqual(metrics["approved_plans_kwd_saved"], 315.67)

    def test_control_tower_renders_approved_dispatch_plan_pill_when_present(self):
        before_resp = self.client.get(reverse("core:home"))
        self.assertEqual(before_resp.status_code, 200)
        self.assertNotContains(before_resp, "live plan")

        DispatchPlan.objects.create(
            name="Approved Shift Run",
            scope="pending",
            baseline_trips=6,
            optimized_trips=4,
            trips_eliminated=2,
            fuel_liters_saved=420.0,
            kwd_saved=210.0,
            is_approved=True,
        )

        after_resp = self.client.get(reverse("core:home"))
        self.assertEqual(after_resp.status_code, 200)
        self.assertContains(after_resp, "1 live plan")
        self.assertContains(after_resp, "-2 trips")
        self.assertContains(after_resp, "+210 live")
