from datetime import time

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from apps.core.models import Trip, Vessel
from apps.trips.forms import TripBookingForm
from apps.trips.services import (
    filter_trips,
    generate_live_trip_ids,
    get_trips_kpis,
    get_vessels_meta,
)


class TripsSliceSmokeTests(TestCase):
    def test_index_returns_200(self):
        response = self.client.get(reverse("trips:index"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Trips &amp; Utilization")

    def test_htmx_ping_post_returns_200(self):
        response = self.client.post(reverse("trips:ping"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "HTMX POST + CSRF verified")


class TripsServiceUnitTests(TestCase):
    def test_kpis_handle_empty_db_gracefully(self):
        kpis = get_trips_kpis()
        self.assertEqual(kpis["historical_count"], 0)
        self.assertEqual(kpis["pending_count"], 0)
        self.assertEqual(kpis["avg_utilization_pct"], 0.0)
        self.assertEqual(kpis["vessel_breakdown"], [])
        self.assertEqual(
            kpis["vessel_chart_data"],
            {"labels": [], "avg_util": [], "half_empty_pct": []},
        )

    def test_seeded_kpis_and_vessels_meta_queries(self):
        call_command("seed_fleet")
        with self.assertNumQueries(4):
            kpis = get_trips_kpis()

        self.assertEqual(kpis["historical_count"], 976)
        self.assertEqual(kpis["pending_count"], 12)
        self.assertGreater(kpis["pending_half_empty_count"], 0)
        self.assertGreater(kpis["half_empty_count"], 0)
        self.assertGreater(kpis["idle_fuel_liters"], 0)
        self.assertEqual(len(kpis["vessel_breakdown"]), 8)
        self.assertEqual(len(kpis["vessel_chart_data"]["labels"]), 8)

        cb07_row = next(
            row for row in kpis["vessel_breakdown"] if row["vessel_id"] == "CB-07"
        )
        self.assertTrue(cb07_row["is_standby_designated"])
        self.assertEqual(cb07_row["active_override_count"], 1)

        meta = get_vessels_meta()
        self.assertEqual(len(meta), 8)
        cb07 = Vessel.objects.get(vessel_id="CB-07")
        self.assertEqual(len(meta[str(cb07.pk)]["active_overrides"]), 1)
        self.assertEqual(
            meta[str(cb07.pk)]["active_overrides"][0]["rule_type"], "standby_lock"
        )

    def test_filter_trips_ordering_and_filters(self):
        call_command("seed_fleet")
        all_result = filter_trips({})
        self.assertEqual(all_result["status_counts"]["all"], 988)
        self.assertEqual(all_result["status_counts"]["pending"], 12)
        self.assertEqual(all_result["status_counts"]["completed"], 976)
        self.assertEqual(len(all_result["page_obj"]), 25)
        first_12_statuses = [t.status for t in list(all_result["page_obj"])[:12]]
        self.assertEqual(first_12_statuses, ["pending"] * 12)

        filtered = filter_trips(
            {"status": "pending", "destination": "Platform A", "half_empty": "1", "q": "TR-QUEUE"}
        )
        self.assertGreater(filtered["total_filtered_count"], 0)
        for trip in filtered["page_obj"]:
            self.assertEqual(trip.status, "pending")
            self.assertEqual(trip.destination, "Platform A")
            self.assertTrue(trip.is_half_empty)

    def test_generate_live_trip_ids_increments(self):
        call_command("seed_fleet")
        self.assertEqual(generate_live_trip_ids(), ("TR-LIVE-001", "REQ-LIVE-001"))

        cb01 = Vessel.objects.get(vessel_id="CB-01")
        form = TripBookingForm(
            data={
                "vessel": cb01.pk,
                "destination": "Platform A",
                "mission_type": "Passenger Transfer",
                "departure_time": "08:30",
                "passengers": 5,
                "cargo_tonnes": 0.1,
                "weather": "Calm",
                "priority": "Routine",
                "flexible_window": True,
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        trip = form.save_pending_trip()
        self.assertEqual(trip.trip_id, "TR-LIVE-001")
        self.assertEqual(trip.request_id, "REQ-LIVE-001")
        self.assertEqual(generate_live_trip_ids(), ("TR-LIVE-002", "REQ-LIVE-002"))


class TripBookingFormTests(TestCase):
    def setUp(self):
        call_command("seed_fleet")
        self.cb01 = Vessel.objects.get(vessel_id="CB-01")
        self.cb03 = Vessel.objects.get(vessel_id="CB-03")

    def test_rejects_zero_passengers_and_zero_cargo(self):
        form = TripBookingForm(
            data={
                "vessel": self.cb01.pk,
                "destination": "Platform A",
                "mission_type": "Passenger Transfer",
                "departure_time": "08:30",
                "passengers": 0,
                "cargo_tonnes": 0.0,
                "weather": "Calm",
                "priority": "Routine",
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("at least 1 passenger", " ".join(form.non_field_errors()))

    def test_overload_block_recommends_capable_vessels(self):
        form = TripBookingForm(
            data={
                "vessel": self.cb03.pk,
                "destination": "Offshore Terminal",
                "mission_type": "Material Delivery",
                "departure_time": "09:00",
                "passengers": 4,
                "cargo_tonnes": 3.0,
                "weather": "Calm",
                "priority": "Routine",
            }
        )
        self.assertFalse(form.is_valid())
        error_text = " ".join(form.non_field_errors())
        self.assertIn("CB-03 max cargo is 0.5 t", error_text)
        self.assertIn("CB-05", error_text)
        self.assertIn("CB-06", error_text)

    def test_save_pending_trip_computes_windows_and_duration(self):
        form = TripBookingForm(
            data={
                "vessel": self.cb01.pk,
                "destination": "Platform A",
                "mission_type": "Passenger Transfer",
                "departure_time": time(8, 30).strftime("%H:%M"),
                "passengers": 5,
                "cargo_tonnes": 0.1,
                "weather": "Calm",
                "priority": "Routine",
                "flexible_window": True,
                "notes": "Shift crew transfer",
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        trip = form.save_pending_trip()
        self.assertEqual(trip.status, "pending")
        self.assertTrue(trip.is_synthetic_queue)
        self.assertEqual(trip.origin, "Marine Base")
        self.assertEqual(trip.distance_nm, 36.0)
        self.assertEqual(trip.underway_hours, round(36.0 / self.cb01.cruise_speed_kn, 2))
        self.assertIsNone(trip.actual_fuel_l)
        self.assertEqual(
            int((trip.departure_dt - trip.earliest_departure_dt).total_seconds() // 60),
            30,
        )
        self.assertEqual(
            int((trip.latest_departure_dt - trip.departure_dt).total_seconds() // 60),
            60,
        )


class TripsViewIntegrationTests(TestCase):
    def setUp(self):
        call_command("seed_fleet")
        self.cb01 = Vessel.objects.get(vessel_id="CB-01")
        self.cb03 = Vessel.objects.get(vessel_id="CB-03")

    def test_index_renders_kpis_and_json_payloads(self):
        response = self.client.get(reverse("trips:index"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "976")
        self.assertContains(response, "trips-vessel-chart-data")
        self.assertContains(response, "vessels-meta-data")
        self.assertContains(response, "TR-QUEUE-01")

    def test_create_valid_half_empty_trip_persists_and_swaps_oob(self):
        response = self.client.post(
            reverse("trips:create"),
            data={
                "vessel": self.cb01.pk,
                "destination": "Platform A",
                "mission_type": "Passenger Transfer",
                "departure_time": "08:30",
                "passengers": 5,
                "cargo_tonnes": 0.1,
                "weather": "Calm",
                "priority": "Routine",
                "flexible_window": "on",
                "notes": "Shift test ticket",
            },
        )
        self.assertEqual(response.status_code, 200)
        created = Trip.objects.get(trip_id="TR-LIVE-001")
        self.assertEqual(created.status, "pending")
        self.assertTrue(created.is_half_empty)
        self.assertContains(response, "TR-LIVE-001")
        self.assertContains(response, "Half-Empty")
        self.assertContains(response, 'hx-swap-oob="outerHTML"')
        self.assertEqual(Trip.objects.filter(status="pending").count(), 13)

    def test_create_overload_trip_returns_errors_without_saving(self):
        before_count = Trip.objects.count()
        response = self.client.post(
            reverse("trips:create"),
            data={
                "vessel": self.cb03.pk,
                "destination": "Offshore Terminal",
                "mission_type": "Material Delivery",
                "departure_time": "09:15",
                "passengers": 4,
                "cargo_tonnes": 3.0,
                "weather": "Calm",
                "priority": "Routine",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Trip.objects.count(), before_count)
        self.assertContains(response, "CB-03 max cargo is 0.5 t")
        self.assertContains(response, "CB-05")

    def test_ledger_partial_filters(self):
        response = self.client.get(
            reverse("trips:ledger"),
            data={"status": "pending", "vessel": "CB-01", "half_empty": "1"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "TR-QUEUE-01")
        self.assertNotContains(response, "TR-QUEUE-05")

    def test_cancel_trip_succeeds_for_pending_and_blocks_completed(self):
        pending_response = self.client.post(
            reverse("trips:cancel", kwargs={"trip_id": "TR-QUEUE-01"})
        )
        self.assertEqual(pending_response.status_code, 200)
        self.assertEqual(Trip.objects.get(trip_id="TR-QUEUE-01").status, "cancelled")
        self.assertContains(pending_response, "Cancelled pending trip TR-QUEUE-01")
        self.assertContains(pending_response, 'hx-swap-oob="outerHTML"')

        completed_trip = Trip.objects.filter(status="completed").first()
        completed_response = self.client.post(
            reverse("trips:cancel", kwargs={"trip_id": completed_trip.trip_id})
        )
        self.assertEqual(completed_response.status_code, 400)

    def test_dim_preset_filters_anomaly_and_weather(self):
        high_result = filter_trips({"status": "all", "anomaly": "high"})
        self.assertGreater(high_result["total_filtered_count"], 0)
        self.assertEqual(
            high_result["preset_counts"]["outliers"],
            high_result["total_filtered_count"],
        )
        self.assertTrue(
            all(t.fuel_anomaly_status == "high" for t in high_result["page_obj"])
        )

        missing_result = filter_trips({"status": "all", "anomaly": "missing"})
        self.assertGreater(missing_result["total_filtered_count"], 0)
        self.assertTrue(
            all(t.fuel_anomaly_status == "missing" for t in missing_result["page_obj"])
        )

        rough_result = filter_trips({"status": "all", "weather": "Rough"})
        self.assertGreater(rough_result["total_filtered_count"], 0)
        self.assertTrue(all(t.weather == "Rough" for t in rough_result["page_obj"]))

    def test_trip_inspector_returns_telemetry_siblings_and_404(self):
        # CB-07 pending trip should show standby lock HSE override and physics telemetry
        cb07_trip = Trip.objects.filter(vessel__vessel_id="CB-07", status="pending").first()
        self.assertIsNotNone(cb07_trip)

        response = self.client.get(
            reverse("trips:inspect", kwargs={"trip_id": cb07_trip.trip_id})
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, cb07_trip.trip_id)
        self.assertContains(response, "Physics-Based Fuel Audit")
        self.assertContains(response, "Standby Vessel Protection Lock")
        self.assertContains(response, "Same-Day Corridor Siblings")

        missing_response = self.client.get(
            reverse("trips:inspect", kwargs={"trip_id": "TR-DOES-NOT-EXIST"})
        )
        self.assertEqual(missing_response.status_code, 404)

    def test_index_renders_progressive_form_presets_and_inspector_drawer(self):
        response = self.client.get(reverse("trips:index"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Skip optional &amp; submit with defaults")
        self.assertContains(response, 'id="optional-trip-details"')
        self.assertContains(response, "field-control")
        self.assertContains(response, "Fuel Outliers")
        self.assertContains(response, "Missing Logs")
        self.assertContains(response, "Rough Weather")
        self.assertContains(response, 'id="trip-inspector-drawer"')
        self.assertContains(response, 'id="booking-drawer"')
        self.assertContains(response, "Advanced Filters")
        self.assertContains(response, "Export CSV")
        self.assertContains(response, "Trip Ledger")
        self.assertContains(response, "Fleet Analytics")

    def test_zero_scroll_pagination_and_filtered_csv_export(self):
        default_page = self.client.get(reverse("trips:index"))
        self.assertEqual(default_page.status_code, 200)
        self.assertEqual(len(default_page.context["page_obj"]), 8)

        page_15 = self.client.get(reverse("trips:ledger"), data={"per_page": "15"})
        self.assertEqual(page_15.status_code, 200)
        self.assertEqual(len(page_15.context["page_obj"]), 15)

        csv_response = self.client.get(
            reverse("trips:export_csv"),
            data={"status": "pending", "destination": "Platform A"},
        )
        self.assertEqual(csv_response.status_code, 200)
        self.assertIn("text/csv", csv_response["Content-Type"])
        self.assertIn("kgoc_fleet_trips.csv", csv_response["Content-Disposition"])
        body = csv_response.content.decode("utf-8")
        self.assertIn("TR-QUEUE-01", body)
        self.assertNotIn("TR-QUEUE-05", body)
