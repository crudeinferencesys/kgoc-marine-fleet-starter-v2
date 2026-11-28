from datetime import date, datetime, time, timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.core.constants import (
    CONSOLIDATION_DETOUR_FUEL_PENALTY_FACTOR,
    DISPATCHER_MINUTES_SAVED_PER_MERGE,
    estimate_co2_kg,
    estimate_savings_kwd,
)
from apps.core.models import DispatchPlan, SafetyOverride, Trip, Vessel
from apps.optimizer.services import (
    MILK_RUN_DETOUR_FUEL_PENALTY_FACTOR,
    approve_dispatch_plan,
    revert_dispatch_plan,
    run_shift_optimizer,
)


def _kuwait_dt(day: date, clock: time) -> datetime:
    tz = timezone.get_default_timezone()
    return timezone.make_aware(datetime.combine(day, clock), tz)


class OptimizerFixturesMixin:
    def _create_standard_fleet(self) -> dict[str, Vessel]:
        specs = [
            ("CB-01", "Crew Boat", 22, 1.0, 102.0, 22.0, 16.0, 42.0, False),
            ("CB-02", "Crew Boat", 18, 0.5, 95.0, 20.0, 16.0, 42.0, False),
            ("CB-03", "Crew Boat", 16, 0.5, 90.0, 18.0, 16.0, 42.0, False),
            ("CB-05", "Utility Boat", 12, 7.0, 105.0, 25.0, 14.0, 55.0, False),
            ("CB-07", "Crew Boat", 16, 0.5, 88.0, 18.0, 16.0, 42.0, True),
            ("CB-08", "Multi-purpose Boat", 14, 5.0, 120.0, 30.0, 14.0, 62.0, False),
        ]
        vessels: dict[str, Vessel] = {}
        for vid, vtype, pax, cargo, underway, idle, speed, kwd, standby in specs:
            vessels[vid] = Vessel.objects.create(
                vessel_id=vid,
                vessel_type=vtype,
                passenger_capacity=pax,
                cargo_capacity_t=cargo,
                underway_rate_lph=underway,
                idle_rate_lph=idle,
                cruise_speed_kn=speed,
                hourly_operating_kwd=kwd,
                is_standby_designated=standby,
                status="In Service",
            )
        return vessels

    def _create_pending_trip(
        self,
        *,
        trip_id: str,
        vessel: Vessel,
        destination: str = "Platform A",
        day: date = date(2026, 11, 28),
        dep_time: time = time(8, 0),
        early_time: time = time(7, 30),
        late_time: time = time(9, 0),
        passengers: int = 5,
        cargo_tonnes: float = 0.1,
        weather: str = "Calm",
        priority: str = "Routine",
        flexible_window: bool = True,
        underway_hours: float = 2.2,
        onsite_work_hours: float = 0.35,
        idle_hours: float = 0.3,
    ) -> Trip:
        dep_dt = _kuwait_dt(day, dep_time)
        return Trip.objects.create(
            trip_id=trip_id,
            request_id=f"REQ-{trip_id}",
            vessel=vessel,
            trip_date=day,
            mission_type="Passenger Transfer",
            origin="Marine Base",
            destination=destination,
            earliest_departure_dt=_kuwait_dt(day, early_time),
            latest_departure_dt=_kuwait_dt(day, late_time),
            departure_dt=dep_dt,
            return_dt=dep_dt + timedelta(hours=underway_hours + onsite_work_hours + idle_hours),
            underway_hours=underway_hours,
            onsite_work_hours=onsite_work_hours,
            nonproductive_idle_hours=idle_hours,
            distance_nm=36.0,
            passengers=passengers,
            cargo_tonnes=cargo_tonnes,
            weather=weather,
            priority=priority,
            flexible_window=flexible_window,
            actual_fuel_l=None,
            status="pending",
            is_synthetic_queue=True,
        )


class OptimizerSliceSmokeTests(TestCase):
    def test_index_returns_200(self):
        response = self.client.get(reverse("optimizer:index"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Dispatch Optimizer")

    def test_htmx_ping_post_returns_200(self):
        response = self.client.post(reverse("optimizer:ping"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "HTMX POST + CSRF verified")


class OptimizerServiceTests(OptimizerFixturesMixin, TestCase):
    def test_empty_database_handled_gracefully(self):
        result = run_shift_optimizer()
        self.assertEqual(result["pending_count"], 0)
        self.assertEqual(result["proposed_merges"], [])
        self.assertEqual(result["held_trips"], [])
        self.assertEqual(result["summary"]["trips_eliminated"], 0)
        self.assertEqual(result["backtest"]["historical_trips"], 0)

    def test_same_corridor_consolidation_and_optimal_right_sizing(self):
        vessels = self._create_standard_fleet()
        # CB-07 locked by standby so CB-03 (cheapest remaining crew boat) wins carrier selection.
        SafetyOverride.objects.create(
            rule_type="standby_lock",
            vessel=vessels["CB-07"],
            severity="critical",
            reason="Standby vessel locked",
            is_active=True,
        )
        t1 = self._create_pending_trip(
            trip_id="TR-01",
            vessel=vessels["CB-01"],
            destination="Platform A",
            dep_time=time(7, 45),
            passengers=6,
            cargo_tonnes=0.15,
        )
        t2 = self._create_pending_trip(
            trip_id="TR-02",
            vessel=vessels["CB-02"],
            destination="Platform A",
            dep_time=time(8, 15),
            passengers=5,
            cargo_tonnes=0.10,
            underway_hours=2.1,
            onsite_work_hours=0.25,
            idle_hours=0.35,
        )

        result = run_shift_optimizer(strict_weather=True, allow_milk_run=False)
        self.assertEqual(len(result["proposed_merges"]), 1)
        merge = result["proposed_merges"][0]

        self.assertEqual(merge["merge_id"], "TR-01+TR-02")
        self.assertEqual(merge["mode"], "same_corridor")
        self.assertEqual(merge["primary_trip"].pk, t1.pk)
        self.assertEqual(merge["absorbed_trip"].pk, t2.pk)
        self.assertEqual(merge["assigned_vessel"].vessel_id, "CB-03")
        self.assertTrue(merge["vessel_reassigned"])
        self.assertEqual(merge["combined_pax"], 11)
        self.assertEqual(merge["combined_cargo"], 0.25)
        self.assertEqual(merge["route_label"], "Marine Base → Platform A")

        expected_fuel_saved = round(
            t2.expected_fuel_l * (1.0 - CONSOLIDATION_DETOUR_FUEL_PENALTY_FACTOR), 1
        )
        expected_hours_saved = round(t2.underway_hours + t2.nonproductive_idle_hours, 2)
        expected_kwd = estimate_savings_kwd(
            expected_fuel_saved, expected_hours_saved, vessels["CB-02"].hourly_operating_kwd
        )
        self.assertEqual(merge["fuel_saved_l"], expected_fuel_saved)
        self.assertEqual(merge["kwd_saved"], expected_kwd)
        self.assertEqual(merge["co2_kg_saved"], estimate_co2_kg(expected_fuel_saved))
        self.assertEqual(merge["dispatcher_minutes_saved"], DISPATCHER_MINUTES_SAVED_PER_MERGE)
        self.assertEqual(result["summary"]["trips_eliminated"], 1)
        self.assertEqual(result["summary"]["optimized_trips"], 1)

    def test_hse_guardrails_and_strict_weather_holds(self):
        vessels = self._create_standard_fleet()
        SafetyOverride.objects.create(
            rule_type="standby_lock",
            vessel=vessels["CB-07"],
            severity="critical",
            reason="Standby protected",
            is_active=True,
        )
        SafetyOverride.objects.create(
            rule_type="maintenance_hold",
            vessel=vessels["CB-05"],
            severity="high",
            reason="Engine inspection",
            is_active=True,
        )
        SafetyOverride.objects.create(
            rule_type="weather_hold",
            destination="Offshore Terminal",
            severity="high",
            reason="Swell > 2.5m",
            is_active=True,
        )

        self._create_pending_trip(trip_id="TR-STANDBY", vessel=vessels["CB-07"], destination="Platform A")
        self._create_pending_trip(trip_id="TR-MAINT", vessel=vessels["CB-05"], destination="Platform A")
        self._create_pending_trip(trip_id="TR-WHOLD", vessel=vessels["CB-01"], destination="Offshore Terminal")
        self._create_pending_trip(
            trip_id="TR-ROUGH-1", vessel=vessels["CB-02"], destination="Platform C", weather="Rough"
        )
        self._create_pending_trip(
            trip_id="TR-ROUGH-2", vessel=vessels["CB-03"], destination="Platform C", weather="Rough"
        )
        self._create_pending_trip(
            trip_id="TR-FIXED", vessel=vessels["CB-01"], destination="Platform B", flexible_window=False
        )
        self._create_pending_trip(
            trip_id="TR-HIGH",
            vessel=vessels["CB-08"],
            destination="Maintenance Area",
            passengers=4,
            cargo_tonnes=4.2,
        )
        self._create_pending_trip(
            trip_id="TR-SOLO",
            vessel=vessels["CB-08"],
            destination="Maintenance Area",
            dep_time=time(16, 0),
            early_time=time(15, 30),
            late_time=time(16, 30),
        )

        strict_res = run_shift_optimizer(strict_weather=True, allow_milk_run=False)
        self.assertEqual(strict_res["proposed_merges"], [])
        held_by_id = {h["trip"].trip_id: h for h in strict_res["held_trips"]}
        self.assertEqual(held_by_id["TR-STANDBY"]["category"], "standby_lock")
        self.assertEqual(held_by_id["TR-STANDBY"]["badge_tone"], "rose")
        self.assertEqual(held_by_id["TR-MAINT"]["category"], "maintenance_hold")
        self.assertEqual(held_by_id["TR-MAINT"]["badge_tone"], "rose")
        self.assertEqual(held_by_id["TR-WHOLD"]["category"], "weather_hold")
        self.assertEqual(held_by_id["TR-WHOLD"]["badge_tone"], "rose")
        self.assertEqual(held_by_id["TR-ROUGH-1"]["category"], "rough_weather")
        self.assertEqual(held_by_id["TR-FIXED"]["category"], "fixed_window")
        self.assertEqual(held_by_id["TR-FIXED"]["badge_tone"], "slate")
        self.assertEqual(held_by_id["TR-HIGH"]["category"], "high_utilization")
        self.assertEqual(held_by_id["TR-HIGH"]["badge_tone"], "slate")
        self.assertEqual(held_by_id["TR-SOLO"]["category"], "no_partner")
        self.assertEqual(held_by_id["TR-SOLO"]["badge_tone"], "amber")

        relaxed_res = run_shift_optimizer(strict_weather=False, allow_milk_run=False)
        self.assertEqual(len(relaxed_res["proposed_merges"]), 1)
        rough_merge = relaxed_res["proposed_merges"][0]
        self.assertEqual(rough_merge["merge_id"], "TR-ROUGH-1+TR-ROUGH-2")
        self.assertEqual(rough_merge["caution_flag"], "Rough Sea Advisory")

    def test_milk_run_merges_platform_cluster_when_enabled(self):
        vessels = self._create_standard_fleet()
        self._create_pending_trip(
            trip_id="TR-PA", vessel=vessels["CB-01"], destination="Platform A", passengers=4
        )
        t_pb = self._create_pending_trip(
            trip_id="TR-PB", vessel=vessels["CB-02"], destination="Platform B", passengers=5
        )
        # Non-cluster trips must not milk-run merge
        self._create_pending_trip(
            trip_id="TR-TERM", vessel=vessels["CB-05"], destination="Offshore Terminal", passengers=3
        )
        self._create_pending_trip(
            trip_id="TR-MAINT", vessel=vessels["CB-08"], destination="Maintenance Area", passengers=3
        )

        off_res = run_shift_optimizer(strict_weather=True, allow_milk_run=False)
        self.assertEqual(off_res["proposed_merges"], [])

        on_res = run_shift_optimizer(strict_weather=True, allow_milk_run=True)
        self.assertEqual(len(on_res["proposed_merges"]), 1)
        milk_merge = on_res["proposed_merges"][0]
        self.assertEqual(milk_merge["mode"], "milk_run")
        self.assertEqual(milk_merge["route_label"], "Marine Base → Platform A → Platform B")
        self.assertEqual(
            milk_merge["fuel_saved_l"],
            round(t_pb.expected_fuel_l * (1.0 - MILK_RUN_DETOUR_FUEL_PENALTY_FACTOR), 1),
        )

    def test_approve_and_revert_dispatch_plan_lifecycle(self):
        vessels = self._create_standard_fleet()
        SafetyOverride.objects.create(
            rule_type="standby_lock",
            vessel=vessels["CB-07"],
            severity="critical",
            reason="Standby locked",
            is_active=True,
        )
        t1 = self._create_pending_trip(
            trip_id="TR-A1", vessel=vessels["CB-01"], destination="Platform A", passengers=5
        )
        t2 = self._create_pending_trip(
            trip_id="TR-A2", vessel=vessels["CB-02"], destination="Platform A", passengers=4
        )

        empty_plan, err_msg = approve_dispatch_plan(
            selected_merge_ids=[],
            strict_weather=True,
            allow_milk_run=False,
        )
        self.assertIsNone(empty_plan)
        self.assertIn("Select at least one", err_msg)

        plan, ok_msg = approve_dispatch_plan(
            selected_merge_ids=["TR-A1+TR-A2"],
            strict_weather=True,
            allow_milk_run=False,
            plan_name="Morning Shift Alpha",
        )
        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan.name, "Morning Shift Alpha")
        self.assertTrue(plan.is_approved)
        self.assertEqual(plan.trips_eliminated, 1)
        self.assertEqual(plan.baseline_trips, 2)
        self.assertEqual(plan.optimized_trips, 1)
        self.assertIn("Approved", ok_msg)

        t1.refresh_from_db()
        t2.refresh_from_db()
        self.assertEqual(t1.status, "pending")
        self.assertEqual(t1.dispatch_plan_id, plan.pk)
        self.assertEqual(t1.vessel.vessel_id, "CB-03")  # right-sized from CB-01 to CB-03
        self.assertEqual(t2.status, "consolidated")
        self.assertEqual(t2.dispatch_plan_id, plan.pk)
        self.assertEqual(t2.consolidated_into_id, t1.pk)

        reverted_plan, rev_msg = revert_dispatch_plan(plan.pk)
        self.assertIsNotNone(reverted_plan)
        assert reverted_plan is not None
        self.assertFalse(reverted_plan.is_approved)
        self.assertIn("Reverted", rev_msg)

        t1.refresh_from_db()
        t2.refresh_from_db()
        self.assertEqual(t1.status, "pending")
        self.assertIsNone(t1.dispatch_plan_id)
        self.assertEqual(t1.vessel.vessel_id, "CB-01")  # restored original vessel
        self.assertEqual(t2.status, "pending")
        self.assertIsNone(t2.dispatch_plan_id)
        self.assertIsNone(t2.consolidated_into_id)


class OptimizerViewsIntegrationTests(OptimizerFixturesMixin, TestCase):
    def setUp(self):
        self.vessels = self._create_standard_fleet()
        self.t1 = self._create_pending_trip(
            trip_id="TR-V1", vessel=self.vessels["CB-01"], destination="Platform A", passengers=5
        )
        self.t2 = self._create_pending_trip(
            trip_id="TR-V2", vessel=self.vessels["CB-02"], destination="Platform A", passengers=4
        )
        self.r1 = self._create_pending_trip(
            trip_id="TR-R1",
            vessel=self.vessels["CB-02"],
            destination="Platform C",
            passengers=4,
            weather="Rough",
        )
        self.r2 = self._create_pending_trip(
            trip_id="TR-R2",
            vessel=self.vessels["CB-03"],
            destination="Platform C",
            passengers=5,
            weather="Rough",
        )

    def test_index_provides_solver_context(self):
        response = self.client.get(reverse("optimizer:index"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["pending_count"], 4)
        self.assertEqual(len(response.context["proposed_merges"]), 1)
        self.assertEqual(response.context["proposed_merges"][0]["merge_id"], "TR-V1+TR-V2")
        self.assertEqual(len(response.context["held_trips"]), 2)

    def test_solve_endpoint_respects_toggles(self):
        response = self.client.post(
            reverse("optimizer:solve"),
            {"strict_weather": ["1", "0"], "allow_milk_run": ["0", "1"]},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["strict_weather"])
        self.assertTrue(response.context["allow_milk_run"])
        self.assertEqual(len(response.context["proposed_merges"]), 2)
        self.assertEqual(response.context["active_tab"], "solver")

    def test_approve_and_revert_endpoints(self):
        empty_resp = self.client.post(
            reverse("optimizer:approve"),
            {"strict_weather": "1", "allow_milk_run": "0"},
        )
        self.assertEqual(empty_resp.status_code, 200)
        self.assertEqual(DispatchPlan.objects.count(), 0)
        self.assertIn("Select at least one", empty_resp.context["notice"])

        approve_resp = self.client.post(
            reverse("optimizer:approve"),
            {
                "strict_weather": "1",
                "allow_milk_run": "0",
                "merge_ids": ["TR-V1+TR-V2"],
                "plan_name": "Integration Plan",
            },
        )
        self.assertEqual(approve_resp.status_code, 200)
        plan = DispatchPlan.objects.get(name="Integration Plan")
        self.assertTrue(plan.is_approved)
        self.assertEqual(approve_resp.context["active_tab"], "solver")

        revert_resp = self.client.post(
            reverse("optimizer:revert_plan", args=[plan.pk]),
            {"strict_weather": "1", "allow_milk_run": "0"},
        )
        self.assertEqual(revert_resp.status_code, 200)
        plan.refresh_from_db()
        self.assertFalse(plan.is_approved)
        self.assertEqual(revert_resp.context["active_tab"], "plans")
