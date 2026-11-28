"""Views and HTMX partial endpoints for Feature 3 (Safety & Fuel Anomaly Guard)."""

from __future__ import annotations

import csv
from collections.abc import Mapping
from typing import Any

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from apps.core.constants import (
    DESTINATIONS,
    MISSION_TYPES,
    PRIORITIES,
    VESSEL_TYPES,
    WEATHER_STATES,
)
from apps.core.models import SafetyOverride
from apps.safety.forms import SafetyOverrideForm
from apps.safety.services import (
    ROLE_PRESETS,
    HoldRow,
    _load_safety_snapshot,
    build_hold_row,
    create_quick_maintenance_hold,
    csv_safe,
    filter_anomalies,
    get_anomaly_inspector_data,
    get_holds_data,
    get_safety_kpis,
    get_safety_scope_meta,
    toggle_safety_override,
)


def _merge_params(request: HttpRequest) -> dict[str, Any]:
    """Read filter query params from GET, falling back to POST values when provided via HTMX."""
    merged: dict[str, Any] = {}
    for key in (
        "anomaly",
        "min_ratio",
        "hold_state",
        "vessel",
        "vessel_type",
        "mission_type",
        "destination",
        "weather",
        "priority",
        "q",
        "page",
        "per_page",
        "hold_status",
        "rule_type",
    ):
        if key in request.GET:
            merged[key] = request.GET.get(key, "")
        elif request.method == "POST" and key in request.POST:
            merged[key] = request.POST.get(key, "")
    return merged


def _build_safety_context(
    *,
    anomaly_params: Mapping[str, Any] | None = None,
    hold_params: Mapping[str, Any] | None = None,
    form: SafetyOverrideForm | None = None,
    created_override: SafetyOverride | None = None,
    audit_notice: str = "",
    hold_notice: str = "",
    default_per_page: int = 8,
) -> dict[str, Any]:
    """Assemble the unified context dictionary shared across /safety/ and its HTMX partials."""
    snapshot = _load_safety_snapshot()
    kpis = get_safety_kpis(_snapshot=snapshot)
    audit = filter_anomalies(
        anomaly_params,
        default_per_page=default_per_page,
        _snapshot=snapshot,
    )
    holds = get_holds_data(hold_params, _snapshot=snapshot)
    scope_meta = get_safety_scope_meta(_snapshot=snapshot)

    created_hold: HoldRow | None = None
    if created_override is not None:
        created_hold = build_hold_row(created_override, snapshot.pending_trips)

    return {
        "kpis": kpis,
        "form": form if form is not None else SafetyOverrideForm(),
        "created_hold": created_hold,
        "audit_notice": audit_notice,
        "hold_notice": hold_notice,
        "page_obj": audit["page_obj"],
        "total_filtered_count": audit["total_filtered_count"],
        "per_page": audit["per_page"],
        "per_page_choices": [8, 15, 25],
        "preset_counts": audit["preset_counts"],
        "advanced_filter_count": audit["advanced_filter_count"],
        "filters": audit["filters"],
        "holds_list": holds["holds_list"],
        "hold_counts": holds["hold_counts"],
        "hold_filters": holds["hold_filters"],
        "safety_scope_meta": scope_meta,
        "vessels": snapshot.vessels,
        "vessel_types": list(VESSEL_TYPES),
        "destinations": list(DESTINATIONS),
        "mission_types": list(MISSION_TYPES),
        "weather_states": list(WEATHER_STATES),
        "priorities": list(PRIORITIES),
        "rule_type_choices": SafetyOverride.RULE_TYPE_CHOICES,
        "severity_choices": SafetyOverride.SEVERITY_CHOICES,
        "role_presets": list(ROLE_PRESETS),
    }


def index(request: HttpRequest) -> HttpResponse:
    """Feature 3 slice landing page (Safety & Fuel Anomaly Guard)."""
    context = _build_safety_context(
        anomaly_params=request.GET,
        hold_params=request.GET,
    )
    return render(request, "safety/index.html", context)


@require_GET
def anomalies_partial(request: HttpRequest) -> HttpResponse:
    """HTMX partial returning the filtered and paginated Fuel Audit table."""
    context = _build_safety_context(
        anomaly_params=request.GET,
        hold_params=request.GET,
    )
    return render(request, "safety/partials/anomaly_table.html", context)


@require_GET
def anomaly_inspector(request: HttpRequest, trip_id: str) -> HttpResponse:
    """HTMX partial returning full physics fuel breakdown and vessel HSE context."""
    context = get_anomaly_inspector_data(trip_id)
    return render(request, "safety/partials/anomaly_inspector.html", context)


@require_POST
def quick_maintenance_hold(request: HttpRequest, trip_id: str) -> HttpResponse:
    """Activate a 1-click Vessel Maintenance Hold from any anomaly row with OOB refreshes."""
    _, _, audit_notice = create_quick_maintenance_hold(trip_id)
    params = _merge_params(request)
    context = _build_safety_context(
        anomaly_params=params,
        hold_params=params,
        audit_notice=audit_notice,
    )
    return render(request, "safety/partials/quick_hold_response.html", context)


@require_GET
def holds_partial(request: HttpRequest) -> HttpResponse:
    """HTMX partial returning the filtered Active HSE Holds rule panel."""
    context = _build_safety_context(
        anomaly_params=request.GET,
        hold_params=request.GET,
    )
    return render(request, "safety/partials/holds_panel.html", context)


@require_POST
def create_hold(request: HttpRequest) -> HttpResponse:
    """Create a persisted SafetyOverride via HTMX and OOB-refresh KPIs, holds, and audit table."""
    form = SafetyOverrideForm(request.POST)
    if form.is_valid():
        created_override = form.save_override()
        context = _build_safety_context(
            anomaly_params=request.GET,
            hold_params={"hold_status": "all"},
            form=SafetyOverrideForm(),
            created_override=created_override,
        )
        return render(request, "safety/partials/hold_response.html", context)

    context = _build_safety_context(
        anomaly_params=request.GET,
        hold_params=request.GET,
        form=form,
    )
    return render(request, "safety/partials/hold_form.html", context)


@require_POST
def toggle_hold(request: HttpRequest, pk: int) -> HttpResponse:
    """Toggle a SafetyOverride active/cleared and OOB-refresh KPIs, audit table, and form meta."""
    _, hold_notice = toggle_safety_override(pk)
    params = _merge_params(request)
    context = _build_safety_context(
        anomaly_params=request.GET,
        hold_params=params,
        hold_notice=hold_notice,
    )
    return render(request, "safety/partials/toggle_response.html", context)


@require_GET
def export_anomalies_csv(request: HttpRequest) -> HttpResponse:
    """Download the currently filtered fuel-audit dataset as formula-safe CSV."""
    audit = filter_anomalies(request.GET)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = (
        'attachment; filename="kgoc_safety_fuel_audit.csv"'
    )

    writer = csv.writer(response)
    writer.writerow(
        [
            "Trip ID",
            "Request ID",
            "Date",
            "Vessel",
            "Vessel Type",
            "Destination",
            "Mission",
            "Weather",
            "Priority",
            "Underway Hours",
            "Onsite Hours",
            "Idle Hours",
            "Expected Fuel (L)",
            "Actual Fuel (L)",
            "Fuel Ratio",
            "Excess Fuel (L)",
            "Est. Excess Cost (KWD)",
            "Est. Excess CO2 (kg)",
            "Anomaly Status",
            "Engineering Flag",
            "Maint Hold Active",
        ]
    )

    for row in audit["filtered_rows"]:
        trip = row.trip
        writer.writerow(
            [
                csv_safe(trip.trip_id),
                csv_safe(trip.request_id),
                trip.trip_date.isoformat(),
                csv_safe(trip.vessel.vessel_id),
                csv_safe(trip.vessel.vessel_type),
                csv_safe(trip.destination),
                csv_safe(trip.mission_type),
                csv_safe(trip.weather),
                csv_safe(trip.priority),
                f"{trip.underway_hours:.2f}",
                f"{trip.onsite_work_hours:.2f}",
                f"{trip.nonproductive_idle_hours:.2f}",
                f"{row.expected_fuel_l:.1f}",
                f"{row.actual_fuel_l:.1f}" if row.actual_fuel_l is not None else "",
                f"{row.fuel_ratio:.2f}" if row.fuel_ratio is not None else "",
                f"{row.fuel_excess_l:.1f}" if row.fuel_excess_l is not None else "",
                f"{row.excess_kwd:.2f}",
                f"{row.excess_co2_kg:.1f}",
                csv_safe(row.anomaly_status),
                csv_safe(row.investigation_label),
                csv_safe("Yes" if row.has_active_maintenance_hold else "No"),
            ]
        )

    return response


@require_POST
def ping(request: HttpRequest) -> HttpResponse:
    """HTMX CSRF smoke endpoint confirming slice partial updates work."""
    return render(
        request,
        "safety/partials/status_card.html",
        {"checked_at": timezone.localtime().strftime("%H:%M:%S")},
    )
