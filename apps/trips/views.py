"""Views and HTMX partial endpoints for Feature 1 (Trips & Utilization)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from apps.core.constants import DESTINATIONS
from apps.core.models import SafetyOverride, Trip, Vessel
from apps.trips.forms import TripBookingForm
from apps.trips.services import filter_trips, get_trips_kpis, get_vessels_meta


def _build_trips_context(
    *,
    filter_params: Mapping[str, Any],
    form: TripBookingForm | None = None,
    created_trip: Trip | None = None,
    created_trip_overrides: list[SafetyOverride] | None = None,
    cancel_notice: str = "",
) -> dict[str, Any]:
    """Assemble the unified context dictionary shared across /trips/ and its HTMX partials."""
    ledger = filter_trips(filter_params)
    return {
        "kpis": get_trips_kpis(),
        "form": form if form is not None else TripBookingForm(),
        "vessels_meta": get_vessels_meta(),
        "created_trip": created_trip,
        "created_trip_overrides": created_trip_overrides or [],
        "page_obj": ledger["page_obj"],
        "total_filtered_count": ledger["total_filtered_count"],
        "status_counts": ledger["status_counts"],
        "filters": ledger["filters"],
        "vessels": list(Vessel.objects.order_by("vessel_id")),
        "destinations": list(DESTINATIONS),
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
