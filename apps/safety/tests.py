import re

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from apps.core.models import SafetyOverride, Trip, Vessel
from apps.safety.forms import SafetyOverrideForm
from apps.safety.services import (
    create_quick_maintenance_hold,
    csv_safe,
    filter_anomalies,
    get_anomaly_inspector_data,
    get_holds_data,
    get_safety_kpis,
    get_safety_scope_meta,
    toggle_safety_override,
)


class SafetySliceSmokeTests(TestCase):
    def test_index_returns_200(self):
        response = self.client.get(reverse("safety:index"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Safety &amp; Fuel")

    def test_htmx_ping_post_returns_200(self):
        response = self.client.post(reverse("safety:ping"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "HTMX POST + CSRF verified")


class SafetyServiceUnitTests(TestCase):
    def test_services_handle_empty_db_gracefully(self):
        kpis = get_safety_kpis()
        self.assertEqual(kpis["completed_count"], 0)
        self.assertEqual(kpis["total_flagged_count"], 0)
        self.assertEqual(kpis["high_outliers_count"], 0)
        self.assertEqual(kpis["low_readings_count"], 0)
        self.assertEqual(kpis["missing_logs_count"], 0)
        self.assertEqual(kpis["max_fuel_ratio"], 0.0)
        self.assertEqual(kpis["excess_fuel_l"], 0.0)
        self.assertEqual(kpis["excess_fuel_kwd"], 0.0)
        self.assertEqual(kpis["excess_co2_kg"], 0.0)
        self.assertEqual(kpis["active_holds_count"], 0)
        self.assertEqual(kpis["affected_pending_trips_count"], 0)

        audit = filter_anomalies({})
        self.assertEqual(audit["total_filtered_count"], 0)
        self.assertEqual(len(audit["page_obj"]), 0)
        self.assertEqual(audit["preset_counts"]["flagged"], 0)

        holds = get_holds_data({})
        self.assertEqual(holds["holds_list"], [])
        self.assertEqual(holds["hold_counts"]["all"], 0)

        scope_meta = get_safety_scope_meta()
        self.assertEqual(scope_meta["vessels"], {})
        self.assertEqual(len(scope_meta["destinations"]), 6)

    def test_seeded_kjo_telemetry_numbers_and_zero_n_plus_one(self):
        call_command("seed_fleet")

        with self.assertNumQueries(4):
            kpis = get_safety_kpis()

        self.assertEqual(kpis["completed_count"], 976)
        self.assertEqual(kpis["total_flagged_count"], 62)
        self.assertEqual(kpis["high_outliers_count"], 39)
        self.assertEqual(kpis["calm_moderate_high_count"], 22)
        self.assertEqual(kpis["rough_high_count"], 17)
        self.assertEqual(kpis["low_readings_count"], 8)
        self.assertEqual(kpis["missing_logs_count"], 15)
        self.assertEqual(kpis["normal_count"], 914)
        self.assertEqual(kpis["max_fuel_ratio"], 2.07)
        self.assertEqual(kpis["excess_fuel_l"], 5869.7)
        self.assertEqual(kpis["excess_fuel_kwd"], 880.45)
        self.assertEqual(kpis["excess_co2_kg"], 15730.8)
        self.assertEqual(kpis["excess_co2_tonnes"], 15.7)
        self.assertEqual(kpis["active_holds_count"], 1)
        self.assertEqual(kpis["cleared_holds_count"], 0)
        self.assertEqual(kpis["total_holds_count"], 1)
        self.assertEqual(kpis["affected_pending_trips_count"], 1)
        self.assertEqual(kpis["pending_count"], 12)
        self.assertEqual(kpis["maintenance_days_total"], 38)
        self.assertEqual(kpis["weather_restricted_days_total"], 97)

        with self.assertNumQueries(2):
            audit = filter_anomalies({})

        self.assertEqual(audit["total_filtered_count"], 62)
        self.assertEqual(len(audit["page_obj"]), 8)
        self.assertEqual(audit["preset_counts"]["flagged"], 62)
        self.assertEqual(audit["preset_counts"]["high"], 39)
        self.assertEqual(audit["preset_counts"]["low"], 8)
        self.assertEqual(audit["preset_counts"]["missing"], 15)
        self.assertEqual(audit["preset_counts"]["normal"], 914)
        self.assertEqual(audit["preset_counts"]["all"], 976)
        self.assertEqual(audit["preset_counts"]["rough_high"], 17)
        self.assertEqual(audit["preset_counts"]["non_rough_high"], 22)

        top_row = audit["page_obj"][0]
        self.assertEqual(top_row.trip.trip_id, "TR-00012")
        self.assertEqual(top_row.trip.vessel.vessel_id, "CB-08")
        self.assertEqual(top_row.fuel_ratio, 2.07)
        self.assertEqual(top_row.expected_fuel_l, 352.2)
        self.assertEqual(top_row.actual_fuel_l, 728.8)
        self.assertEqual(top_row.fuel_excess_l, 376.6)
        self.assertEqual(top_row.excess_kwd, 56.49)
        self.assertEqual(top_row.excess_co2_kg, 1009.3)
        self.assertEqual(top_row.investigation_label, "Engine / Hull Audit")

    def test_anomaly_filters_more_facets_and_missing_excludes_pending(self):
        call_command("seed_fleet")

        # Missing logs strictly excludes the 12 pending shift queue rows
        missing = filter_anomalies({"anomaly": "missing"})
        self.assertEqual(missing["total_filtered_count"], 15)
        self.assertTrue(
            all(
                r.trip.status == "completed" and r.actual_fuel_l is None
                for r in missing["filtered_rows"]
            )
        )

        # Low readings led by TR-00619 (0.31x)
        low = filter_anomalies({"anomaly": "low"})
        self.assertEqual(low["total_filtered_count"], 8)
        self.assertEqual(low["filtered_rows"][0].trip.trip_id, "TR-00619")
        self.assertEqual(low["filtered_rows"][0].fuel_ratio, 0.31)
        self.assertEqual(low["filtered_rows"][0].investigation_label, "Flow-Meter Check")

        # High + non-rough yields exactly 22 engineering-priority rows
        non_rough_high = filter_anomalies({"anomaly": "high", "weather": "non_rough"})
        self.assertEqual(non_rough_high["total_filtered_count"], 22)
        self.assertEqual(non_rough_high["advanced_filter_count"], 2)
        self.assertTrue(
            all(
                r.anomaly_status == "high" and r.trip.weather != "Rough"
                for r in non_rough_high["filtered_rows"]
            )
        )

        # Min ratio threshold filter
        severe = filter_anomalies({"anomaly": "flagged", "min_ratio": "1.75"})
        self.assertGreater(severe["total_filtered_count"], 0)
        self.assertTrue(
            all(
                r.fuel_ratio is not None and r.fuel_ratio >= 1.75
                for r in severe["filtered_rows"]
            )
        )

        # Vessel, vessel_type, destination, mission_type, priority, search q
        cb08_pa = filter_anomalies(
            {
                "anomaly": "high",
                "vessel": "CB-08",
                "vessel_type": "Multi-purpose Boat",
                "destination": "Platform A",
                "q": "TR-00012",
            }
        )
        self.assertEqual(cb08_pa["total_filtered_count"], 1)
        self.assertEqual(cb08_pa["filtered_rows"][0].trip.trip_id, "TR-00012")

        # Hold state filter after activating hold on CB-08
        create_quick_maintenance_hold("TR-00012")
        held_rows = filter_anomalies({"anomaly": "flagged", "hold_state": "held"})
        self.assertGreater(held_rows["total_filtered_count"], 0)
        self.assertTrue(
            all(r.has_active_maintenance_hold for r in held_rows["filtered_rows"])
        )
        unheld_rows = filter_anomalies({"anomaly": "flagged", "hold_state": "unheld"})
        self.assertTrue(
            all(not r.has_active_maintenance_hold for r in unheld_rows["filtered_rows"])
        )
        self.assertEqual(
            held_rows["total_filtered_count"] + unheld_rows["total_filtered_count"],
            62,
        )

    def test_scope_meta_and_inspector_data(self):
        call_command("seed_fleet")
        scope_meta = get_safety_scope_meta()
        self.assertEqual(len(scope_meta["vessels"]), 8)
        cb07 = Vessel.objects.get(vessel_id="CB-07")
        self.assertEqual(
            scope_meta["vessels"][str(cb07.pk)]["active_rule_types"],
            ["standby_lock"],
        )
        self.assertEqual(scope_meta["vessels"][str(cb07.pk)]["pending_count"], 1)

        platform_c = next(
            d for d in scope_meta["destinations"] if d["value"] == "Platform C"
        )
        self.assertEqual(platform_c["pending_count"], 2)
        self.assertEqual(platform_c["rough_pending_count"], 2)
        self.assertFalse(platform_c["has_active_weather_hold"])

        fleet_rough = next(d for d in scope_meta["destinations"] if d["value"] == "")
        self.assertEqual(fleet_rough["label"], "All Rough-Sea Corridors")
        self.assertEqual(fleet_rough["rough_pending_count"], 2)

        inspector = get_anomaly_inspector_data("TR-00012")
        self.assertEqual(inspector["trip"].trip_id, "TR-00012")
        self.assertEqual(inspector["physics"]["expected_fuel_l"], 352.2)
        self.assertEqual(inspector["physics"]["actual_fuel_l"], 728.8)
        self.assertEqual(inspector["physics"]["fuel_ratio"], 2.07)
        self.assertEqual(inspector["physics"]["excess_kwd"], 56.49)
        self.assertEqual(inspector["vessel_availability_summary"]["maintenance_days"], 8)
        self.assertFalse(inspector["has_active_maintenance_hold"])
        self.assertLessEqual(len(inspector["vessel_recent_anomalies"]), 4)
        self.assertTrue(
            all(
                t.trip_id != "TR-00012" and t.fuel_anomaly_status != "normal"
                for t in inspector["vessel_recent_anomalies"]
            )
        )

    def test_csv_safe_escapes_formula_prefixes(self):
        for dangerous in ("=SUM(A1:A2)", "+CMD", "-1+1", "@HYPERLINK", "\tfoo", "\rbar"):
            self.assertTrue(csv_safe(dangerous).startswith("'"))
        self.assertEqual(csv_safe("TR-00012"), "TR-00012")
        self.assertEqual(csv_safe(None), "")


class SafetyOverrideFormTests(TestCase):
    def setUp(self):
        call_command("seed_fleet")
        self.cb01 = Vessel.objects.get(vessel_id="CB-01")
        self.cb07 = Vessel.objects.get(vessel_id="CB-07")
        self.cb08 = Vessel.objects.get(vessel_id="CB-08")

    def test_weather_hold_blank_reason_applies_smart_defaults_and_clears_vessel(self):
        form = SafetyOverrideForm(
            data={
                "rule_type": "weather_hold",
                "severity": "high",
                "vessel": self.cb01.pk,
                "destination": "Platform C",
                "created_by_role": "",
                "reason": "",
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        override = form.save_override()
        self.assertEqual(override.rule_type, "weather_hold")
        self.assertIsNone(override.vessel)
        self.assertEqual(override.destination, "Platform C")
        self.assertEqual(override.created_by_role, "Marine Operations Supervisor")
        self.assertIn("Platform C", override.reason)
        self.assertTrue(override.is_active)

    def test_fleet_wide_rough_weather_hold_succeeds(self):
        form = SafetyOverrideForm(
            data={
                "rule_type": "weather_hold",
                "severity": "critical",
                "destination": "",
                "created_by_role": "Port Captain",
                "reason": "",
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        override = form.save_override()
        self.assertEqual(override.destination, "")
        self.assertIsNone(override.vessel)
        self.assertEqual(override.created_by_role, "Port Captain")
        self.assertIn("rough", override.reason.lower())

    def test_vessel_holds_require_vessel_and_strip_destination(self):
        missing_vessel = SafetyOverrideForm(
            data={
                "rule_type": "maintenance_hold",
                "severity": "high",
                "vessel": "",
                "destination": "Platform C",
            }
        )
        self.assertFalse(missing_vessel.is_valid())
        self.assertIn("vessel", missing_vessel.errors)

        valid_maint = SafetyOverrideForm(
            data={
                "rule_type": "maintenance_hold",
                "severity": "critical",
                "vessel": self.cb08.pk,
                "destination": "Platform C",
                "reason": "",
            }
        )
        self.assertTrue(valid_maint.is_valid(), valid_maint.errors)
        override = valid_maint.save_override()
        self.assertEqual(override.vessel, self.cb08)
        self.assertEqual(override.destination, "")
        self.assertIn("CB-08", override.reason)

    def test_duplicate_active_hold_guard_blocks_identical_active_rules(self):
        # CB-07 already has an active seeded standby_lock
        dup_standby = SafetyOverrideForm(
            data={
                "rule_type": "standby_lock",
                "severity": "critical",
                "vessel": self.cb07.pk,
            }
        )
        self.assertFalse(dup_standby.is_valid())
        self.assertIn("CB-07", " ".join(dup_standby.non_field_errors()))

        # Weather hold duplicate guard
        first = SafetyOverrideForm(
            data={
                "rule_type": "weather_hold",
                "severity": "high",
                "destination": "Platform A",
            }
        )
        self.assertTrue(first.is_valid())
        created = first.save_override()

        dup_weather = SafetyOverrideForm(
            data={
                "rule_type": "weather_hold",
                "severity": "high",
                "destination": "Platform A",
            }
        )
        self.assertFalse(dup_weather.is_valid())
        self.assertIn("Platform A", " ".join(dup_weather.non_field_errors()))

        # Clearing the first rule allows creating a fresh one cleanly
        toggle_safety_override(created.pk)
        recreated = SafetyOverrideForm(
            data={
                "rule_type": "weather_hold",
                "severity": "high",
                "destination": "Platform A",
            }
        )
        self.assertTrue(recreated.is_valid(), recreated.errors)


class SafetyViewIntegrationTests(TestCase):
    def setUp(self):
        call_command("seed_fleet")
        self.cb07 = Vessel.objects.get(vessel_id="CB-07")
        self.cb08 = Vessel.objects.get(vessel_id="CB-08")
        self.cb07_lock = SafetyOverride.objects.get(
            rule_type="standby_lock", vessel=self.cb07
        )

    def test_index_loads_zero_scroll_default_and_bounded_queries(self):
        with self.assertNumQueries(6):
            response = self.client.get(reverse("safety:index"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["page_obj"]), 8)
        self.assertEqual(response.context["page_obj"][0].trip.trip_id, "TR-00012")
        self.assertContains(response, "TR-00012")
        self.assertContains(response, "2.07")
        self.assertContains(response, "safety-scope-meta-data")
        self.assertContains(response, "safety-kpi-strip")
        self.assertContains(response, "safety-anomaly-panel")
        self.assertContains(response, "safety-holds-panel")
        self.assertContains(response, "safety-hold-panel")
        self.assertContains(response, "safety-inspector-drawer")

    def test_anomalies_partial_filtering_and_pagination(self):
        page_15 = self.client.get(reverse("safety:anomalies"), data={"per_page": "15"})
        self.assertEqual(page_15.status_code, 200)
        self.assertEqual(len(page_15.context["page_obj"]), 15)

        missing_resp = self.client.get(
            reverse("safety:anomalies"), data={"anomaly": "missing"}
        )
        self.assertEqual(missing_resp.status_code, 200)
        self.assertEqual(missing_resp.context["total_filtered_count"], 15)
        self.assertNotContains(missing_resp, "TR-QUEUE-")

    def test_inspector_returns_physics_telemetry_and_404(self):
        resp = self.client.get(
            reverse("safety:inspect", kwargs={"trip_id": "TR-00012"})
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "TR-00012")
        self.assertContains(resp, "352.2")
        self.assertContains(resp, "728.8")
        self.assertContains(resp, "2.07")
        self.assertContains(resp, "56.49")

        missing = self.client.get(
            reverse("safety:inspect", kwargs={"trip_id": "TR-NO-SUCH-TRIP"})
        )
        self.assertEqual(missing.status_code, 404)

    def test_quick_maintenance_hold_persists_oob_and_is_idempotent(self):
        url = reverse("safety:quick_hold", kwargs={"trip_id": "TR-00012"})
        first = self.client.post(url)
        self.assertEqual(first.status_code, 200)
        self.assertContains(first, 'hx-swap-oob="outerHTML"')
        self.assertContains(first, "CB-08")

        holds = SafetyOverride.objects.filter(
            rule_type="maintenance_hold", vessel=self.cb08, is_active=True
        )
        self.assertEqual(holds.count(), 1)
        hold = holds.first()
        self.assertEqual(hold.source_trip.trip_id, "TR-00012")
        self.assertEqual(hold.severity, "critical")

        # Second click is idempotent — zero duplicates
        second = self.client.post(url)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(holds.count(), 1)
        self.assertContains(second, "already active")

    def test_create_hold_persists_oob_and_validation_errors_do_not_save(self):
        before = SafetyOverride.objects.count()
        create_url = reverse("safety:create_hold")

        # Default submit (mirrors Skip optional & submit with defaults)
        ok_resp = self.client.post(
            create_url,
            data={
                "rule_type": "weather_hold",
                "severity": "high",
                "destination": "Platform C",
                "created_by_role": "",
                "reason": "",
            },
        )
        self.assertEqual(ok_resp.status_code, 200)
        self.assertEqual(SafetyOverride.objects.count(), before + 1)
        self.assertContains(ok_resp, 'hx-swap-oob="outerHTML"')
        self.assertContains(ok_resp, "Platform C")

        # KPI affected pending trips should now be 3 (TR-QUEUE-07, TR-QUEUE-08, TR-QUEUE-09)
        self.assertEqual(ok_resp.context["kpis"]["affected_pending_trips_count"], 3)

        # Duplicate Platform C weather hold returns errors without saving
        dup_resp = self.client.post(
            create_url,
            data={
                "rule_type": "weather_hold",
                "severity": "high",
                "destination": "Platform C",
            },
        )
        self.assertEqual(dup_resp.status_code, 200)
        self.assertEqual(SafetyOverride.objects.count(), before + 1)
        self.assertContains(dup_resp, "already exists")

    def test_toggle_cb07_standby_lock_clear_and_reactivate_persists(self):
        toggle_url = reverse("safety:toggle_hold", kwargs={"pk": self.cb07_lock.pk})

        clear_resp = self.client.post(toggle_url)
        self.assertEqual(clear_resp.status_code, 200)
        self.assertContains(clear_resp, 'hx-swap-oob="outerHTML"')
        self.cb07_lock.refresh_from_db()
        self.assertFalse(self.cb07_lock.is_active)
        self.assertEqual(clear_resp.context["kpis"]["active_holds_count"], 0)
        self.assertEqual(clear_resp.context["kpis"]["affected_pending_trips_count"], 0)

        reactivate_resp = self.client.post(toggle_url)
        self.assertEqual(reactivate_resp.status_code, 200)
        self.cb07_lock.refresh_from_db()
        self.assertTrue(self.cb07_lock.is_active)
        self.assertEqual(reactivate_resp.context["kpis"]["active_holds_count"], 1)
        self.assertEqual(
            reactivate_resp.context["kpis"]["affected_pending_trips_count"], 1
        )

    def test_holds_partial_filters(self):
        resp = self.client.get(
            reverse("safety:holds"),
            data={"hold_status": "active", "rule_type": "standby_lock"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.context["holds_list"]), 1)
        self.assertContains(resp, "CB-07")

        cleared_resp = self.client.get(
            reverse("safety:holds"),
            data={"hold_status": "cleared"},
        )
        self.assertEqual(cleared_resp.status_code, 200)
        self.assertEqual(len(cleared_resp.context["holds_list"]), 0)

    def test_export_csv_returns_all_filtered_rows_and_escapes_formulas(self):
        # Inject a formula-like request_id on TR-00012 to verify spreadsheet formula escaping
        tr12 = Trip.objects.get(trip_id="TR-00012")
        tr12.request_id = "=HYPERLINK(\"http://evil.invalid\")"
        tr12.save(update_fields=["request_id"])

        resp = self.client.get(
            reverse("safety:export_csv"), data={"anomaly": "high"}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/csv", resp["Content-Type"])
        self.assertIn("kgoc_safety_fuel_audit.csv", resp["Content-Disposition"])

        lines = [line for line in resp.content.decode("utf-8").splitlines() if line]
        # 1 header + all 39 high outliers (not truncated to 8-row page)
        self.assertEqual(len(lines), 40)
        self.assertIn("TR-00012", lines[1])
        self.assertIn("'=HYPERLINK(", lines[1])

    def test_htmx_alpine_settle_safeguards_and_root_form_lookup(self):
        for resp in (
            self.client.get(reverse("safety:index")),
            self.client.get(reverse("safety:anomalies"), data={"anomaly": "high"}),
        ):
            self.assertEqual(resp.status_code, 200)
            self.assertContains(resp, 'id="safety-more-filters-modal"')
            self.assertContains(resp, 'style="display: none;"')
            self.assertContains(
                resp, ":class=\"{ 'flex': moreOpen, 'hidden': !moreOpen }\""
            )
            self.assertContains(resp, 'class="hidden fixed inset-0')
            self.assertNotContains(resp, 'class="fixed inset-0 z-50 flex')

        index_resp = self.client.get(reverse("safety:index"), data={"tab": "new_hold"})
        self.assertEqual(index_resp.status_code, 200)
        html = index_resp.content.decode("utf-8")
        self.assertContains(index_resp, 'id="safety-hold-form"')
        self.assertContains(index_resp, "getForm()")
        self.assertContains(index_resp, "this.$root")
        self.assertNotContains(index_resp, "this.$el")
        self.assertNotContains(index_resp, 'x-init="init()"')

        form_tag = re.search(r'<form[^>]*\bid="safety-hold-form"[^>]*>', html)
        self.assertIsNotNone(form_tag, "Missing #safety-hold-form")
        self.assertNotIn("x-show=", form_tag.group(0))

        self.assertContains(index_resp, 'id="optional-hold-details"')
        self.assertContains(index_resp, ":class=\"{ 'hidden': step !== 3 }\"")
        self.assertContains(index_resp, 'style="display: none;"')


class SafetyOptimizerCrossSliceTests(TestCase):
    """Verify SafetyOverride rules created/toggled in /safety/ constrain /optimizer/ live."""

    def setUp(self):
        call_command("seed_fleet")
        self.cb07 = Vessel.objects.get(vessel_id="CB-07")
        self.cb08 = Vessel.objects.get(vessel_id="CB-08")
        self.cb07_lock = SafetyOverride.objects.get(
            rule_type="standby_lock", vessel=self.cb07
        )

    def test_safety_holds_and_toggles_constrain_optimizer_solver(self):
        from apps.optimizer.services import run_shift_optimizer

        # Baseline: CB-07 locked by seeded standby_lock; CB-08 eligible; Platform A merges
        baseline = run_shift_optimizer(strict_weather=True, allow_milk_run=False)
        baseline_eligible_ids = {v.vessel_id for v in baseline["eligible_vessels"]}
        self.assertNotIn("CB-07", baseline_eligible_ids)
        self.assertIn("CB-08", baseline_eligible_ids)
        self.assertIn(
            "TR-QUEUE-01+TR-QUEUE-02",
            {m["merge_id"] for m in baseline["proposed_merges"]},
        )

        # 1. 1-click Maintenance Hold on TR-00012 (CB-08) blocks CB-08 in optimizer
        self.client.post(
            reverse("safety:quick_hold", kwargs={"trip_id": "TR-00012"})
        )
        after_maint = run_shift_optimizer(strict_weather=True, allow_milk_run=False)
        self.assertNotIn(
            "CB-08", {v.vessel_id for v in after_maint["eligible_vessels"]}
        )
        held_by_trip = {h["trip"].trip_id: h["category"] for h in after_maint["held_trips"]}
        self.assertEqual(held_by_trip["TR-QUEUE-10"], "maintenance_hold")
        self.assertEqual(held_by_trip["TR-QUEUE-12"], "maintenance_hold")

        # 2. Weather Hold on Platform A via /safety/holds/create/ blocks Platform A merge
        self.client.post(
            reverse("safety:create_hold"),
            data={
                "rule_type": "weather_hold",
                "severity": "high",
                "destination": "Platform A",
            },
        )
        after_weather = run_shift_optimizer(strict_weather=False, allow_milk_run=False)
        self.assertNotIn(
            "TR-QUEUE-01+TR-QUEUE-02",
            {m["merge_id"] for m in after_weather["proposed_merges"]},
        )
        weather_held = {h["trip"].trip_id: h["category"] for h in after_weather["held_trips"]}
        self.assertEqual(weather_held["TR-QUEUE-01"], "weather_hold")
        self.assertEqual(weather_held["TR-QUEUE-02"], "weather_hold")

        # 3. Clearing CB-07 standby_lock restores CB-07 eligibility; reactivating re-locks it
        toggle_url = reverse("safety:toggle_hold", kwargs={"pk": self.cb07_lock.pk})
        self.client.post(toggle_url)
        after_clear = run_shift_optimizer(strict_weather=True, allow_milk_run=False)
        self.assertIn("CB-07", {v.vessel_id for v in after_clear["eligible_vessels"]})

        self.client.post(toggle_url)
        after_relock = run_shift_optimizer(strict_weather=True, allow_milk_run=False)
        self.assertNotIn(
            "CB-07", {v.vessel_id for v in after_relock["eligible_vessels"]}
        )
        relock_held = {h["trip"].trip_id: h["category"] for h in after_relock["held_trips"]}
        self.assertEqual(relock_held["TR-QUEUE-09"], "standby_lock")
