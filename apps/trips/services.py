"""Domain telemetry, filtering, and ID generation services for Feature 1 (Trips & Utilization)."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from typing import Any

from django.core.paginator import Paginator
from django.db.models import Count, Q

from apps.core.constants import (
    ASSUMED_DIESEL_KWD_PER_LITER,
    ASSUMED_KG_CO2_PER_LITER,
    HALF_EMPTY_THRESHOLD_PCT,
    MISSION_TYPES,
    PRIORITIES,
    VESSEL_TYPES,
)
from apps.core.models import SafetyOverride, Trip, Vessel, VesselAvailability

DESTINATION_DISTANCES_NM: dict[str, float] = {
    "Platform A": 36.0,
    "Platform B": 38.0,
    "Platform C": 43.0,
    "Offshore Terminal": 41.0,
    "Maintenance Area": 31.0,
}


def get_trips_kpis() -> dict[str, Any]:
    """Compute fleet utilization KPIs, per-vessel breakdown, and Chart.js data with zero N+1 queries."""
    trips = list(
        Trip.objects.select_related("vessel").filter(status__in=["completed", "pending"])
    )
    historical_trips = [trip for trip in trips if trip.status == "completed"]
    pending_trips = [trip for trip in trips if trip.status == "pending"]

    historical_count = len(historical_trips)
    pending_count = len(pending_trips)
    pending_half_empty_count = sum(
        1 for trip in pending_trips if trip.utilization_pct < HALF_EMPTY_THRESHOLD_PCT
    )

    if historical_count > 0:
        avg_utilization_pct = round(
            sum(trip.utilization_pct for trip in historical_trips) / historical_count, 1
        )
        avg_pax_utilization_pct = round(
            sum(trip.pax_utilization_pct for trip in historical_trips) / historical_count, 1
        )
        half_empty_count = sum(
            1 for trip in historical_trips if trip.utilization_pct < HALF_EMPTY_THRESHOLD_PCT
        )
        half_empty_pct = round((half_empty_count / historical_count) * 100.0, 1)
        productive_onsite_hours = round(
            sum(trip.onsite_work_hours for trip in historical_trips), 1
        )
        avoidable_idle_hours = round(
            sum(trip.nonproductive_idle_hours for trip in historical_trips), 1
        )
        idle_fuel_liters = round(sum(trip.idle_fuel_l for trip in historical_trips), 1)
        idle_fuel_kwd = round(idle_fuel_liters * ASSUMED_DIESEL_KWD_PER_LITER, 2)
        idle_co2_tonnes = round((idle_fuel_liters * ASSUMED_KG_CO2_PER_LITER) / 1000.0, 2)
    else:
        avg_utilization_pct = 0.0
        avg_pax_utilization_pct = 0.0
        half_empty_count = 0
        half_empty_pct = 0.0
        productive_onsite_hours = 0.0
        avoidable_idle_hours = 0.0
        idle_fuel_liters = 0.0
        idle_fuel_kwd = 0.0
        idle_co2_tonnes = 0.0

    trips_by_vessel: dict[int, list[Trip]] = defaultdict(list)
    for trip in historical_trips:
        trips_by_vessel[trip.vessel_id].append(trip)

    avail_by_vessel = {
        row["vessel_id"]: row
        for row in VesselAvailability.objects.values("vessel_id").annotate(
            maintenance_days=Count("id", filter=Q(availability_status="Maintenance")),
            weather_restricted_days=Count(
                "id", filter=Q(availability_status="Weather Restricted")
            ),
        )
    }
    overrides_by_vessel = {
        row["vessel_id"]: row["cnt"]
        for row in SafetyOverride.objects.filter(is_active=True, vessel__isnull=False)
        .values("vessel_id")
        .annotate(cnt=Count("id"))
    }

    vessel_breakdown: list[dict[str, Any]] = []
    for vessel in Vessel.objects.order_by("vessel_id"):
        v_trips = trips_by_vessel.get(vessel.pk, [])
        v_count = len(v_trips)
        if v_count > 0:
            v_avg_util = round(sum(t.utilization_pct for t in v_trips) / v_count, 1)
            v_half_empty = sum(
                1 for t in v_trips if t.utilization_pct < HALF_EMPTY_THRESHOLD_PCT
            )
            v_half_empty_pct = round((v_half_empty / v_count) * 100.0, 1)
        else:
            v_avg_util = 0.0
            v_half_empty_pct = 0.0

        avail_row = avail_by_vessel.get(vessel.pk, {})
        vessel_breakdown.append(
            {
                "vessel_id": vessel.vessel_id,
                "vessel_type": vessel.vessel_type,
                "passenger_capacity": vessel.passenger_capacity,
                "cargo_capacity_t": vessel.cargo_capacity_t,
                "trip_count": v_count,
                "avg_util_pct": v_avg_util,
                "half_empty_pct": v_half_empty_pct,
                "maintenance_days": avail_row.get("maintenance_days", 0),
                "weather_restricted_days": avail_row.get("weather_restricted_days", 0),
                "is_standby_designated": vessel.is_standby_designated,
                "active_override_count": overrides_by_vessel.get(vessel.pk, 0),
            }
        )

    vessel_chart_data = {
        "labels": [row["vessel_id"] for row in vessel_breakdown],
        "avg_util": [row["avg_util_pct"] for row in vessel_breakdown],
        "half_empty_pct": [row["half_empty_pct"] for row in vessel_breakdown],
    }

    return {
        "historical_count": historical_count,
        "pending_count": pending_count,
        "pending_half_empty_count": pending_half_empty_count,
        "avg_utilization_pct": avg_utilization_pct,
        "avg_pax_utilization_pct": avg_pax_utilization_pct,
        "half_empty_count": half_empty_count,
        "half_empty_pct": half_empty_pct,
        "productive_onsite_hours": productive_onsite_hours,
        "avoidable_idle_hours": avoidable_idle_hours,
        "idle_fuel_liters": idle_fuel_liters,
        "idle_fuel_kwd": idle_fuel_kwd,
        "idle_co2_tonnes": idle_co2_tonnes,
        "vessel_breakdown": vessel_breakdown,
        "vessel_chart_data": vessel_chart_data,
    }


def get_vessels_meta() -> dict[str, dict[str, Any]]:
    """Return vessel capacity specs and active HSE overrides keyed by string primary key."""
    overrides_by_vessel: dict[int, list[dict[str, str]]] = defaultdict(list)
    for ov in SafetyOverride.objects.filter(is_active=True, vessel__isnull=False).order_by(
        "-created_at"
    ):
        overrides_by_vessel[ov.vessel_id].append(
            {
                "rule_type": ov.rule_type,
                "rule_label": ov.get_rule_type_display(),
                "severity": ov.severity,
                "reason": ov.reason,
            }
        )

    return {
        str(vessel.pk): {
            "vessel_id": vessel.vessel_id,
            "vessel_type": vessel.vessel_type,
            "passenger_capacity": vessel.passenger_capacity,
            "cargo_capacity_t": vessel.cargo_capacity_t,
            "cruise_speed_kn": vessel.cruise_speed_kn,
            "is_standby_designated": vessel.is_standby_designated,
            "active_overrides": overrides_by_vessel.get(vessel.pk, []),
        }
        for vessel in Vessel.objects.order_by("vessel_id")
    }


def filter_trips(params: Mapping[str, Any], *, default_per_page: int = 25) -> dict[str, Any]:
    """Filter and paginate trips with pending shift rows prioritized ahead of historical sailings."""
    raw_status = str(params.get("status") or "all").strip().lower()
    valid_statuses = {"all", "pending", "completed", "consolidated", "cancelled"}
    status = raw_status if raw_status in valid_statuses else "all"

    vessel = str(params.get("vessel") or "").strip()
    raw_vessel_type = str(params.get("vessel_type") or "").strip()
    vessel_type = raw_vessel_type if raw_vessel_type in VESSEL_TYPES else ""
    destination = str(params.get("destination") or "").strip()
    raw_mission = str(params.get("mission_type") or "").strip()
    mission_type = raw_mission if raw_mission in MISSION_TYPES else ""
    raw_flex = str(params.get("flexible_window") or "").strip()
    flexible_window = raw_flex if raw_flex in {"1", "0"} else ""

    raw_min_pax = str(params.get("min_pax") or "").strip()
    min_pax: int | None = int(raw_min_pax) if raw_min_pax.isdigit() else None
    raw_min_cargo = str(params.get("min_cargo") or "").strip()
    min_cargo: float | None = None
    if raw_min_cargo:
        try:
            parsed_cargo = float(raw_min_cargo)
            if parsed_cargo >= 0:
                min_cargo = parsed_cargo
        except ValueError:
            min_cargo = None

    half_empty = str(params.get("half_empty") or "").strip()
    raw_load_band = str(params.get("load_band") or "").strip().lower()
    load_band = (
        raw_load_band if raw_load_band in {"under_50", "50_70", "over_70"} else ""
    )

    raw_anomaly = str(params.get("anomaly") or "").strip().lower()
    anomaly = (
        raw_anomaly if raw_anomaly in {"high", "low", "missing", "normal"} else ""
    )
    raw_weather = str(params.get("weather") or "").strip()
    weather = raw_weather if raw_weather in {"Calm", "Moderate", "Rough"} else ""
    raw_priority = str(params.get("priority") or "").strip()
    priority = raw_priority if raw_priority in PRIORITIES else ""
    idle_only = "1" if str(params.get("idle_only") or "").strip() == "1" else ""
    q = str(params.get("q") or "").strip()
    page_num = params.get("page") or 1

    raw_per_page = str(params.get("per_page") or "").strip()
    if raw_per_page.isdigit() and int(raw_per_page) in {8, 15, 25}:
        per_page = int(raw_per_page)
    else:
        per_page = default_per_page

    all_non_cancelled = list(
        Trip.objects.select_related("vessel", "consolidated_into", "dispatch_plan").exclude(
            status="cancelled"
        )
    )
    status_counts = {
        "all": len(all_non_cancelled),
        "pending": sum(1 for trip in all_non_cancelled if trip.status == "pending"),
        "consolidated": sum(
            1 for trip in all_non_cancelled if trip.status == "consolidated"
        ),
        "completed": sum(1 for trip in all_non_cancelled if trip.status == "completed"),
    }
    preset_counts = {
        **status_counts,
        "half_empty": sum(1 for trip in all_non_cancelled if trip.is_half_empty),
        "outliers": sum(
            1 for trip in all_non_cancelled if trip.fuel_anomaly_status == "high"
        ),
        "missing_fuel": sum(
            1 for trip in all_non_cancelled if trip.fuel_anomaly_status == "missing"
        ),
        "rough_weather": sum(1 for trip in all_non_cancelled if trip.weather == "Rough"),
    }

    qs = Trip.objects.select_related("vessel", "consolidated_into", "dispatch_plan")
    if status == "all":
        qs = qs.exclude(status="cancelled")
    else:
        qs = qs.filter(status=status)

    if vessel:
        qs = qs.filter(vessel__vessel_id=vessel)
    if vessel_type:
        qs = qs.filter(vessel__vessel_type=vessel_type)
    if destination:
        qs = qs.filter(destination=destination)
    if mission_type:
        qs = qs.filter(mission_type=mission_type)
    if flexible_window == "1":
        qs = qs.filter(flexible_window=True)
    elif flexible_window == "0":
        qs = qs.filter(flexible_window=False)
    if min_pax is not None:
        qs = qs.filter(passengers__gte=min_pax)
    if min_cargo is not None:
        qs = qs.filter(cargo_tonnes__gte=min_cargo)
    if weather:
        qs = qs.filter(weather=weather)
    if priority:
        qs = qs.filter(priority=priority)
    if idle_only == "1":
        qs = qs.filter(nonproductive_idle_hours__gte=0.75)
    if q:
        qs = qs.filter(
            Q(trip_id__icontains=q) | Q(request_id__icontains=q) | Q(notes__icontains=q)
        )

    trips = list(qs)
    if half_empty == "1":
        trips = [trip for trip in trips if trip.is_half_empty]
    if load_band == "under_50":
        trips = [trip for trip in trips if trip.utilization_pct < 50.0]
    elif load_band == "50_70":
        trips = [trip for trip in trips if 50.0 <= trip.utilization_pct < 70.0]
    elif load_band == "over_70":
        trips = [trip for trip in trips if trip.utilization_pct >= 70.0]
    if anomaly:
        trips = [trip for trip in trips if trip.fuel_anomaly_status == anomaly]

    # Pending queue rows first, consolidated second, completed historical sailings third.
    status_rank = {"pending": 0, "consolidated": 1, "completed": 2}
    trips.sort(
        key=lambda t: (
            status_rank.get(t.status, 3),
            0 if (t.status == "pending" and t.trip_id.startswith("TR-LIVE-")) else 1,
            (
                -t.created_at.timestamp()
                if (t.status == "pending" and t.trip_id.startswith("TR-LIVE-"))
                else 0.0
            ),
            t.departure_dt.timestamp() if t.status == "pending" else -t.departure_dt.timestamp(),
            -(t.pk or 0),
        )
    )

    paginator = Paginator(trips, per_page)
    page_obj = paginator.get_page(page_num)

    min_pax_str = str(min_pax) if min_pax is not None else ""
    min_cargo_str = f"{min_cargo:g}" if min_cargo is not None else ""
    advanced_filter_count = sum(
        1
        for active in (
            status != "all",
            bool(destination),
            bool(mission_type),
            bool(flexible_window),
            bool(vessel),
            bool(vessel_type),
            bool(min_pax_str),
            bool(min_cargo_str),
            bool(load_band),
            bool(weather),
            bool(priority),
            bool(anomaly),
            idle_only == "1",
        )
        if active
    )

    return {
        "page_obj": page_obj,
        "filtered_trips": trips,
        "total_filtered_count": len(trips),
        "per_page": per_page,
        "status_counts": status_counts,
        "preset_counts": preset_counts,
        "advanced_filter_count": advanced_filter_count,
        "filters": {
            "status": status,
            "vessel": vessel,
            "vessel_type": vessel_type,
            "destination": destination,
            "mission_type": mission_type,
            "flexible_window": flexible_window,
            "min_pax": min_pax_str,
            "min_cargo": min_cargo_str,
            "half_empty": half_empty,
            "load_band": load_band,
            "anomaly": anomaly,
            "weather": weather,
            "priority": priority,
            "idle_only": idle_only,
            "q": q,
            "per_page": per_page,
        },
    }


def generate_live_trip_ids() -> tuple[str, str]:
    """Generate the next unique ('TR-LIVE-NNN', 'REQ-LIVE-NNN') identifier pair."""
    existing_trip_ids = set(
        Trip.objects.filter(trip_id__startswith="TR-LIVE-").values_list("trip_id", flat=True)
    )
    existing_req_ids = set(
        Trip.objects.filter(request_id__startswith="REQ-LIVE-").values_list(
            "request_id", flat=True
        )
    )

    max_num = 0
    for code in existing_trip_ids | existing_req_ids:
        suffix = code.rsplit("-", 1)[-1]
        if suffix.isdigit():
            max_num = max(max_num, int(suffix))

    next_num = max_num + 1
    while True:
        trip_id = f"TR-LIVE-{next_num:03d}"
        request_id = f"REQ-LIVE-{next_num:03d}"
        if trip_id not in existing_trip_ids and request_id not in existing_req_ids:
            return trip_id, request_id
        next_num += 1
