"""Views and HTMX partial endpoints for Feature 1 (Trips & Utilization)."""

from __future__ import annotations

import csv
from collections.abc import Mapping
from typing import Any

from django.db.models import Q
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from apps.core.constants import (
    DESTINATIONS,
    MISSION_TYPES,
    PRIORITIES,
    VESSEL_TYPES,
    WEATHER_STATES,
)
from apps.core.models import SafetyOverride, Trip, Vessel
from apps.trips.forms import TripBookingForm
from apps.trips.services import filter_trips, get_trips_kpis, get_vessels_meta


def _csv_safe(value: object) -> str:
    """Prevent CSV formula injection on spreadsheet export."""
    text = "" if value is None else str(value)
    if text and text[0] in ("=", "+", "-", "@", "\t", "\r"):
        return f"'{text}"
    return text


def _build_trips_context(
    *,
    filter_params: Mapping[str, Any],
    form: TripBookingForm | None = None,
    created_trip: Trip | None = None,
    created_trip_overrides: list[SafetyOverride] | None = None,
    cancel_notice: str = "",
    default_per_page: int = 8,
) -> dict[str, Any]:
    """Assemble the unified context dictionary shared across /trips/ and its HTMX partials."""
    ledger = filter_trips(filter_params, default_per_page=default_per_page)
    return {
        "kpis": get_trips_kpis(),
        "form": form if form is not None else TripBookingForm(),
        "vessels_meta": get_vessels_meta(),
        "created_trip": created_trip,
        "created_trip_overrides": created_trip_overrides or [],
        "page_obj": ledger["page_obj"],
        "total_filtered_count": ledger["total_filtered_count"],
        "per_page": ledger["per_page"],
        "per_page_choices": [8, 15, 25],
        "status_counts": ledger["status_counts"],
        "preset_counts": ledger["preset_counts"],
        "advanced_filter_count": ledger["advanced_filter_count"],
        "filters": ledger["filters"],
        "vessels": list(Vessel.objects.order_by("vessel_id")),
        "vessel_types": list(VESSEL_TYPES),
        "destinations": list(DESTINATIONS),
        "mission_types": list(MISSION_TYPES),
        "weather_states": list(WEATHER_STATES),
        "priorities": list(PRIORITIES),
        "cancel_notice": cancel_notice,
    }


def index(request: HttpRequest) -> HttpResponse:
    """Feature 1 slice landing page (Trips & Utilization)."""
    context = _build_trips_context(filter_params=request.GET)
    return render(request, "trips/index.html", context)


@require_POST
def create_trip(request: HttpRequest) -> HttpResponse:
    """Create a pending shift trip via HTMX and OOB-refresh KPIs + ledger on success."""
    form = TripBookingForm(request.POST)
    if form.is_valid():
        created_trip = form.save_pending_trip()
        created_trip_overrides = list(
            SafetyOverride.objects.filter(
                vessel=created_trip.vessel, is_active=True
            ).order_by("-created_at")
        )
        context = _build_trips_context(
            filter_params={"status": "all"},
            form=TripBookingForm(),
            created_trip=created_trip,
            created_trip_overrides=created_trip_overrides,
        )
        return render(request, "trips/partials/booking_response.html", context)

    context = _build_trips_context(filter_params={"status": "all"}, form=form)
    return render(request, "trips/partials/booking_form.html", context)


@require_GET
def ledger_partial(request: HttpRequest) -> HttpResponse:
    """HTMX partial endpoint returning the filtered and paginated trip ledger table."""
    context = _build_trips_context(filter_params=request.GET)
    return render(request, "trips/partials/trip_table.html", context)


@require_GET
def export_trips_csv(request: HttpRequest) -> HttpResponse:
    """Download the currently filtered fleet trip ledger as CSV for deep-dive analysis."""
    ledger = filter_trips(request.GET)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="kgoc_fleet_trips.csv"'

    writer = csv.writer(response)
    writer.writerow(
        [
            "Trip ID",
            "Request ID",
            "Date",
            "Departure",
            "Vessel",
            "Vessel Type",
            "Origin",
            "Destination",
            "Mission",
            "Passengers",
            "Pax Capacity",
            "Cargo (t)",
            "Cargo Capacity (t)",
            "Utilization (%)",
            "Half Empty",
            "Expected Fuel (L)",
            "Actual Fuel (L)",
            "Fuel Ratio",
            "Fuel Anomaly",
            "Weather",
            "Priority",
            "Flexible Window",
            "Status",
            "Notes",
        ]
    )

    for trip in ledger["filtered_trips"]:
        dep_local = timezone.localtime(trip.departure_dt)
        writer.writerow(
            [
                _csv_safe(trip.trip_id),
                _csv_safe(trip.request_id),
                trip.trip_date.isoformat(),
                dep_local.strftime("%H:%M"),
                _csv_safe(trip.vessel.vessel_id),
                _csv_safe(trip.vessel.vessel_type),
                _csv_safe(trip.origin),
                _csv_safe(trip.destination),
                _csv_safe(trip.mission_type),
                trip.passengers,
                trip.vessel.passenger_capacity,
                f"{trip.cargo_tonnes:.2f}",
                f"{trip.vessel.cargo_capacity_t:.1f}",
                f"{trip.utilization_pct:.1f}",
                "Yes" if trip.is_half_empty else "No",
                f"{trip.expected_fuel_l:.1f}",
                f"{trip.actual_fuel_l:.1f}" if trip.actual_fuel_l is not None else "",
                f"{trip.fuel_ratio:.2f}" if trip.fuel_ratio is not None else "",
                _csv_safe(trip.fuel_anomaly_status),
                _csv_safe(trip.weather),
                _csv_safe(trip.priority),
                "Yes" if trip.flexible_window else "No",
                _csv_safe(trip.status),
                _csv_safe(trip.notes),
            ]
        )

    return response


@require_GET
def trip_inspector(request: HttpRequest, trip_id: str) -> HttpResponse:
    """HTMX partial returning full physics fuel, capacity, and HSE telemetry for one trip."""
    trip = get_object_or_404(
        Trip.objects.select_related("vessel", "dispatch_plan", "consolidated_into"),
        trip_id=trip_id,
    )
    active_overrides = list(
        SafetyOverride.objects.filter(is_active=True)
        .filter(Q(vessel=trip.vessel) | Q(destination=trip.destination))
        .select_related("vessel")
        .order_by("-created_at")
    )
    sibling_trips = list(
        Trip.objects.select_related("vessel")
        .filter(trip_date=trip.trip_date, destination=trip.destination)
        .exclude(pk=trip.pk)
        .exclude(status="cancelled")
        .order_by("departure_dt")[:4]
    )
    return render(
        request,
        "trips/partials/trip_inspector.html",
        {
            "trip": trip,
            "active_overrides": active_overrides,
            "sibling_trips": sibling_trips,
        },
    )


@require_POST
def cancel_trip(request: HttpRequest, trip_id: str) -> HttpResponse:
    """Cancel a pending shift trip and OOB-refresh the KPI strip."""
    trip = get_object_or_404(Trip.objects.select_related("vessel"), trip_id=trip_id)
    if trip.status != "pending":
        return HttpResponseBadRequest("Only pending shift trips can be cancelled.")

    trip.status = "cancelled"
    trip.save(update_fields=["status", "updated_at"])
    cancel_notice = (
        f"Cancelled pending trip {trip.trip_id} ({trip.vessel.vessel_id} → {trip.destination})."
    )
    context = _build_trips_context(
        filter_params=request.GET,
        cancel_notice=cancel_notice,
    )
    return render(request, "trips/partials/cancel_response.html", context)


@require_POST
def ping(request: HttpRequest) -> HttpResponse:
    """HTMX CSRF smoke endpoint confirming slice partial updates work."""
    return render(
        request,
        "trips/partials/status_card.html",
        {"checked_at": timezone.localtime().strftime("%H:%M:%S")},
    )
