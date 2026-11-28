"""Domain fuel-audit telemetry, anomaly filtering, and HSE hold services for Feature 3."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404

from apps.core.constants import (
    ASSUMED_DIESEL_KWD_PER_LITER,
    DESTINATIONS,
    MISSION_TYPES,
    PRIORITIES,
    VESSEL_TYPES,
    estimate_co2_kg,
)
from apps.core.models import SafetyOverride, Trip, Vessel, VesselAvailability

VALID_ANOMALY_FILTERS = frozenset({"flagged", "high", "low", "missing", "normal", "all"})
VALID_MIN_RATIOS = frozenset({"1.3", "1.5", "1.75"})
VALID_HOLD_STATES = frozenset({"held", "unheld"})
VALID_WEATHER_FILTERS = frozenset({"Calm", "Moderate", "Rough", "non_rough"})
VALID_HOLD_STATUSES = frozenset({"all", "active", "cleared"})
VALID_RULE_TYPES = frozenset({"weather_hold", "maintenance_hold", "standby_lock"})
VALID_PER_PAGE = frozenset({8, 15, 25})

ROLE_PRESETS: tuple[str, ...] = (
    "Marine Operations Supervisor",
    "HSE Officer",
    "Marine Superintendent",
    "Port Captain",
)


@dataclass(frozen=True)
class FuelAuditRow:
    """Enriched physics fuel-audit row for a single completed historical sailing."""

    trip: Trip
    anomaly_status: str
    expected_fuel_l: float
    actual_fuel_l: float | None
    fuel_ratio: float | None
    fuel_excess_l: float | None
    excess_positive_l: float
    excess_kwd: float
    excess_co2_kg: float
    investigation_label: str
    has_active_maintenance_hold: bool
    has_active_standby_lock: bool
    active_vessel_holds_count: int


@dataclass(frozen=True)
class HoldRow:
    """Enriched SafetyOverride rule with target display labels and pending-trip impact."""

    override: SafetyOverride
    target_label: str
    target_sublabel: str
    affected_pending_count: int
    affected_pending_ids: list[str]


@dataclass(frozen=True)
class _SafetySnapshot:
    """Single-pass prefetched dataset snapshot preventing redundant DB queries per request."""

    vessels: list[Vessel]
    completed_trips: list[Trip]
    pending_trips: list[Trip]
    overrides: list[SafetyOverride]
    avail_by_vessel: dict[int, dict[str, Any]]


def csv_safe(value: object) -> str:
    """Prevent CSV formula injection on spreadsheet export."""
    text = "" if value is None else str(value)
    if text and text[0] in ("=", "+", "-", "@", "\t", "\r"):
        return f"'{text}"
    return text


def _load_safety_snapshot() -> _SafetySnapshot:
    """Load all Safety & Fuel Audit inputs in 5 portable ORM queries (zero N+1)."""
    vessels = list(Vessel.objects.order_by("vessel_id"))
    completed_trips = list(
        Trip.objects.filter(status="completed").select_related("vessel")
    )
    pending_trips = list(
        Trip.objects.filter(status="pending")
        .select_related("vessel")
        .order_by("departure_dt", "trip_id")
    )
    overrides = list(
        SafetyOverride.objects.select_related(
            "vessel", "source_trip", "source_trip__vessel"
        ).order_by("-is_active", "-created_at")
    )
    avail_by_vessel = {
        row["vessel_id"]: row
        for row in VesselAvailability.objects.values("vessel_id").annotate(
            maintenance_days=Count("id", filter=Q(availability_status="Maintenance")),
            weather_restricted_days=Count(
                "id", filter=Q(availability_status="Weather Restricted")
            ),
        )
    }
    return _SafetySnapshot(
        vessels=vessels,
        completed_trips=completed_trips,
        pending_trips=pending_trips,
        overrides=overrides,
        avail_by_vessel=avail_by_vessel,
    )


def _investigation_label(trip: Trip, anomaly_status: str) -> str:
    """Return neutral engineering-investigation framing for a trip's fuel telemetry."""
    if anomaly_status == "high":
        return "Rough-Sea Burn Spike" if trip.weather == "Rough" else "Engine / Hull Audit"
    if anomaly_status == "low":
        return "Flow-Meter Check"
    if anomaly_status == "missing":
        return "Telemetry Log Gap"
    return "Nominal"


def _engineering_guidance(trip: Trip, anomaly_status: str) -> str:
    """Return neutral engineering-focused diagnostic guidance for the Fuel Audit Inspector."""
    if anomaly_status == "high" and trip.weather == "Rough":
        return (
            "Elevated fuel burn occurred in Rough sea conditions. Cross-check wave-resistance "
            "allowance, thruster holding load, and propulsion logs before scheduling maintenance."
        )
    if anomaly_status == "high":
        return (
            "Fuel burn significantly exceeds physics baseline in non-rough sea conditions. "
            "Prioritize engineering check of hull fouling, propeller condition, injector tuning, "
            "and auxiliary generator runtime."
        )
    if anomaly_status == "low":
        return (
            "Reported fuel burn sits well below physics expectation. Schedule a flow-meter "
            "calibration check, tank sounding reconciliation, and engine-room logbook audit."
        )
    if anomaly_status == "missing":
        return (
            "Completed sailing has a blank actual-fuel telemetry entry (not zero fuel burn). "
            "Reconcile chief engineer fuel logbook with automated tank gauge records."
        )
    return (
        "Reported fuel consumption falls within the normal physics tolerance band (0.70x-1.30x). "
        "No engineering follow-up required."
    )


def _matching_pending_trips(
    override: SafetyOverride,
    pending_trips: list[Trip],
) -> list[Trip]:
    """Return pending shift trips affected by a SafetyOverride rule."""
    if override.rule_type in ("maintenance_hold", "standby_lock") and override.vessel_id:
        return [t for t in pending_trips if t.vessel_id == override.vessel_id]
    if override.rule_type == "weather_hold":
        if override.destination:
            return [t for t in pending_trips if t.destination == override.destination]
        return [t for t in pending_trips if t.weather == "Rough"]
    if override.vessel_id:
        return [t for t in pending_trips if t.vessel_id == override.vessel_id]
    return []


def build_hold_row(override: SafetyOverride, pending_trips: list[Trip]) -> HoldRow:
    """Construct a HoldRow summary for one SafetyOverride against the live pending queue."""
    if override.vessel is not None:
        target_label = override.vessel.vessel_id
        target_sublabel = (
            f"{override.vessel.vessel_type} · "
            f"{override.vessel.passenger_capacity}p/{override.vessel.cargo_capacity_t:.1f}t"
        )
    elif override.destination:
        target_label = override.destination
        target_sublabel = "Offshore Corridor"
    else:
        target_label = "All Rough-Sea Corridors"
        target_sublabel = "Fleet-Wide Rough Sea"

    matched = _matching_pending_trips(override, pending_trips)
    return HoldRow(
        override=override,
        target_label=target_label,
        target_sublabel=target_sublabel,
        affected_pending_count=len(matched),
        affected_pending_ids=[t.trip_id for t in matched],
    )


def _active_vessel_override_index(
    overrides: list[SafetyOverride],
) -> tuple[set[int], set[int], dict[int, int], dict[int, set[str]]]:
    """Index active vessel overrides for O(1) per-row lookup."""
    maint_vessel_ids: set[int] = set()
    standby_vessel_ids: set[int] = set()
    counts_by_vessel: dict[int, int] = defaultdict(int)
    rules_by_vessel: dict[int, set[str]] = defaultdict(set)

    for ov in overrides:
        if not ov.is_active or ov.vessel_id is None:
            continue
        counts_by_vessel[ov.vessel_id] += 1
        rules_by_vessel[ov.vessel_id].add(ov.rule_type)
        if ov.rule_type == "maintenance_hold":
            maint_vessel_ids.add(ov.vessel_id)
        elif ov.rule_type == "standby_lock":
            standby_vessel_ids.add(ov.vessel_id)

    return maint_vessel_ids, standby_vessel_ids, counts_by_vessel, rules_by_vessel


def _build_audit_row(
    trip: Trip,
    maint_vessel_ids: set[int],
    standby_vessel_ids: set[int],
    counts_by_vessel: dict[int, int],
) -> FuelAuditRow:
    """Build a FuelAuditRow for one completed sailing."""
    status = trip.fuel_anomaly_status
    expected_fuel_l = trip.expected_fuel_l
    actual_fuel_l = trip.actual_fuel_l
    fuel_ratio = trip.fuel_ratio
    fuel_excess_l = trip.fuel_excess_l
    excess_positive_l = (
        round(max(0.0, fuel_excess_l), 1) if fuel_excess_l is not None else 0.0
    )
    excess_kwd = round(excess_positive_l * ASSUMED_DIESEL_KWD_PER_LITER, 2)
    excess_co2_kg = estimate_co2_kg(excess_positive_l)

    return FuelAuditRow(
        trip=trip,
        anomaly_status=status,
        expected_fuel_l=expected_fuel_l,
        actual_fuel_l=actual_fuel_l,
        fuel_ratio=fuel_ratio,
        fuel_excess_l=fuel_excess_l,
        excess_positive_l=excess_positive_l,
        excess_kwd=excess_kwd,
        excess_co2_kg=excess_co2_kg,
        investigation_label=_investigation_label(trip, status),
        has_active_maintenance_hold=trip.vessel_id in maint_vessel_ids,
        has_active_standby_lock=trip.vessel_id in standby_vessel_ids,
        active_vessel_holds_count=counts_by_vessel.get(trip.vessel_id, 0),
    )


def get_safety_kpis(*, _snapshot: _SafetySnapshot | None = None) -> dict[str, Any]:
    """Compute Feature 3 Fuel Audit & HSE Hold KPIs with zero N+1 queries."""
    if _snapshot is not None:
        completed_trips = _snapshot.completed_trips
        pending_trips = _snapshot.pending_trips
        overrides = _snapshot.overrides
        maintenance_days_total = sum(
            row.get("maintenance_days", 0) for row in _snapshot.avail_by_vessel.values()
        )
        weather_restricted_days_total = sum(
            row.get("weather_restricted_days", 0)
            for row in _snapshot.avail_by_vessel.values()
        )
    else:
        completed_trips = list(
            Trip.objects.filter(status="completed").select_related("vessel")
        )
        pending_trips = list(
            Trip.objects.filter(status="pending").only(
                "id", "trip_id", "vessel_id", "destination", "weather"
            )
        )
        overrides = list(
            SafetyOverride.objects.only(
                "id", "rule_type", "vessel_id", "destination", "is_active"
            )
        )
        avail_agg = VesselAvailability.objects.aggregate(
            maintenance_days_total=Count(
                "id", filter=Q(availability_status="Maintenance")
            ),
            weather_restricted_days_total=Count(
                "id", filter=Q(availability_status="Weather Restricted")
            ),
        )
        maintenance_days_total = avail_agg["maintenance_days_total"] or 0
        weather_restricted_days_total = avail_agg["weather_restricted_days_total"] or 0

    high_trips: list[Trip] = []
    calm_moderate_high_count = 0
    rough_high_count = 0
    low_readings_count = 0
    missing_logs_count = 0
    normal_count = 0
    max_fuel_ratio = 0.0

    for trip in completed_trips:
        ratio = trip.fuel_ratio
        if ratio is not None and ratio > max_fuel_ratio:
            max_fuel_ratio = ratio

        status = trip.fuel_anomaly_status
        if status == "high":
            high_trips.append(trip)
            if trip.weather == "Rough":
                rough_high_count += 1
            else:
                calm_moderate_high_count += 1
        elif status == "low":
            low_readings_count += 1
        elif status == "missing":
            missing_logs_count += 1
        else:
            normal_count += 1

    high_outliers_count = len(high_trips)
    total_flagged_count = high_outliers_count + low_readings_count + missing_logs_count

    excess_fuel_l = round(
        sum(max(0.0, t.fuel_excess_l or 0.0) for t in high_trips), 1
    )
    excess_fuel_kwd = round(excess_fuel_l * ASSUMED_DIESEL_KWD_PER_LITER, 2)
    excess_co2_kg = estimate_co2_kg(excess_fuel_l)
    excess_co2_tonnes = round(excess_co2_kg / 1000.0, 1)

    active_overrides = [ov for ov in overrides if ov.is_active]
    active_holds_count = len(active_overrides)
    total_holds_count = len(overrides)
    cleared_holds_count = total_holds_count - active_holds_count

    affected_pending_pks: set[int] = set()
    for ov in active_overrides:
        for trip in _matching_pending_trips(ov, pending_trips):
            affected_pending_pks.add(trip.pk)

    return {
        "completed_count": len(completed_trips),
        "total_flagged_count": total_flagged_count,
        "high_outliers_count": high_outliers_count,
        "calm_moderate_high_count": calm_moderate_high_count,
        "rough_high_count": rough_high_count,
        "low_readings_count": low_readings_count,
        "missing_logs_count": missing_logs_count,
        "normal_count": normal_count,
        "max_fuel_ratio": round(max_fuel_ratio, 2),
        "excess_fuel_l": excess_fuel_l,
        "excess_fuel_kwd": excess_fuel_kwd,
        "excess_co2_kg": excess_co2_kg,
        "excess_co2_tonnes": excess_co2_tonnes,
        "active_holds_count": active_holds_count,
        "cleared_holds_count": cleared_holds_count,
        "total_holds_count": total_holds_count,
        "affected_pending_trips_count": len(affected_pending_pks),
        "pending_count": len(pending_trips),
        "maintenance_days_total": maintenance_days_total,
        "weather_restricted_days_total": weather_restricted_days_total,
    }


def _audit_row_sort_key(row: FuelAuditRow) -> tuple[int, float, float, float, str]:
    """Severity-first deterministic sort so TR-00012 (2.07x) leads default audit views."""
    dep_ts = row.trip.departure_dt.timestamp()
    if row.anomaly_status == "high":
        return (
            0,
            -(row.fuel_ratio if row.fuel_ratio is not None else 0.0),
            -(row.fuel_excess_l if row.fuel_excess_l is not None else 0.0),
            -dep_ts,
            row.trip.trip_id,
        )
    if row.anomaly_status == "low":
        return (
            1,
            row.fuel_ratio if row.fuel_ratio is not None else 999.0,
            0.0,
            -dep_ts,
            row.trip.trip_id,
        )
    if row.anomaly_status == "missing":
        return (2, 0.0, 0.0, -dep_ts, row.trip.trip_id)
    return (3, 0.0, 0.0, -dep_ts, row.trip.trip_id)


def filter_anomalies(
    params: Mapping[str, Any] | None,
    *,
    default_per_page: int = 8,
    _snapshot: _SafetySnapshot | None = None,
) -> dict[str, Any]:
    """Filter, sort, and paginate historical completed sailings for fuel-anomaly audit."""
    query = params or {}

    raw_anomaly = str(query.get("anomaly") or "flagged").strip().lower()
    anomaly = raw_anomaly if raw_anomaly in VALID_ANOMALY_FILTERS else "flagged"

    raw_min_ratio = str(query.get("min_ratio") or "").strip()
    min_ratio = raw_min_ratio if raw_min_ratio in VALID_MIN_RATIOS else ""
    min_ratio_val = float(min_ratio) if min_ratio else None

    raw_hold_state = str(query.get("hold_state") or "").strip().lower()
    hold_state = raw_hold_state if raw_hold_state in VALID_HOLD_STATES else ""

    vessel = str(query.get("vessel") or "").strip()
    raw_vessel_type = str(query.get("vessel_type") or "").strip()
    vessel_type = raw_vessel_type if raw_vessel_type in VESSEL_TYPES else ""

    raw_mission = str(query.get("mission_type") or "").strip()
    mission_type = raw_mission if raw_mission in MISSION_TYPES else ""

    raw_dest = str(query.get("destination") or "").strip()
    destination = raw_dest if raw_dest in DESTINATIONS else ""

    raw_weather = str(query.get("weather") or "").strip()
    weather = raw_weather if raw_weather in VALID_WEATHER_FILTERS else ""

    raw_priority = str(query.get("priority") or "").strip()
    priority = raw_priority if raw_priority in PRIORITIES else ""

    q = str(query.get("q") or "").strip()
    q_lower = q.lower()

    page_num = query.get("page") or 1
    raw_per_page = str(query.get("per_page") or "").strip()
    if raw_per_page.isdigit() and int(raw_per_page) in VALID_PER_PAGE:
        per_page = int(raw_per_page)
    else:
        per_page = default_per_page

    if _snapshot is not None:
        completed_trips = _snapshot.completed_trips
        overrides = _snapshot.overrides
    else:
        completed_trips = list(
            Trip.objects.filter(status="completed").select_related("vessel")
        )
        overrides = list(
            SafetyOverride.objects.filter(is_active=True, vessel__isnull=False).only(
                "id", "rule_type", "vessel_id", "is_active"
            )
        )

    (
        maint_vessel_ids,
        standby_vessel_ids,
        counts_by_vessel,
        _,
    ) = _active_vessel_override_index(overrides)

    all_rows = [
        _build_audit_row(trip, maint_vessel_ids, standby_vessel_ids, counts_by_vessel)
        for trip in completed_trips
    ]

    high_count = sum(1 for r in all_rows if r.anomaly_status == "high")
    low_count = sum(1 for r in all_rows if r.anomaly_status == "low")
    missing_count = sum(1 for r in all_rows if r.anomaly_status == "missing")
    normal_count = sum(1 for r in all_rows if r.anomaly_status == "normal")
    rough_high_count = sum(
        1 for r in all_rows if r.anomaly_status == "high" and r.trip.weather == "Rough"
    )
    non_rough_high_count = high_count - rough_high_count

    preset_counts = {
        "flagged": high_count + low_count + missing_count,
        "high": high_count,
        "low": low_count,
        "missing": missing_count,
        "normal": normal_count,
        "all": len(all_rows),
        "rough_high": rough_high_count,
        "non_rough_high": non_rough_high_count,
    }

    filtered_rows: list[FuelAuditRow] = []
    for row in all_rows:
        trip = row.trip
        if anomaly == "flagged":
            if row.anomaly_status not in ("high", "low", "missing"):
                continue
        elif anomaly != "all" and row.anomaly_status != anomaly:
            continue

        if min_ratio_val is not None:
            if row.fuel_ratio is None or row.fuel_ratio < min_ratio_val:
                continue

        if hold_state == "held" and not row.has_active_maintenance_hold:
            continue
        if hold_state == "unheld" and row.has_active_maintenance_hold:
            continue

        if vessel and trip.vessel.vessel_id != vessel:
            continue
        if vessel_type and trip.vessel.vessel_type != vessel_type:
            continue
        if mission_type and trip.mission_type != mission_type:
            continue
        if destination and trip.destination != destination:
            continue
        if weather == "non_rough":
            if trip.weather == "Rough":
                continue
        elif weather and trip.weather != weather:
            continue
        if priority and trip.priority != priority:
            continue

        if q_lower:
            haystack = " ".join(
                (
                    trip.trip_id,
                    trip.request_id,
                    trip.vessel.vessel_id,
                    trip.destination,
                    trip.notes,
                )
            ).lower()
            if q_lower not in haystack:
                continue

        filtered_rows.append(row)

    filtered_rows.sort(key=_audit_row_sort_key)

    paginator = Paginator(filtered_rows, per_page)
    page_obj = paginator.get_page(page_num)

    advanced_filter_count = sum(
        1
        for active in (
            anomaly != "flagged",
            bool(min_ratio),
            bool(hold_state),
            bool(vessel),
            bool(vessel_type),
            bool(mission_type),
            bool(destination),
            bool(weather),
            bool(priority),
        )
        if active
    )

    return {
        "page_obj": page_obj,
        "filtered_rows": filtered_rows,
        "total_filtered_count": len(filtered_rows),
        "per_page": per_page,
        "preset_counts": preset_counts,
        "advanced_filter_count": advanced_filter_count,
        "filters": {
            "anomaly": anomaly,
            "min_ratio": min_ratio,
            "hold_state": hold_state,
            "vessel": vessel,
            "vessel_type": vessel_type,
            "mission_type": mission_type,
            "destination": destination,
            "weather": weather,
            "priority": priority,
            "q": q,
            "per_page": per_page,
        },
    }


def get_holds_data(
    params: Mapping[str, Any] | None = None,
    *,
    _snapshot: _SafetySnapshot | None = None,
) -> dict[str, Any]:
    """Return filtered SafetyOverride HoldRows and rule/status counts (zero N+1)."""
    query = params or {}

    raw_status = str(query.get("hold_status") or "all").strip().lower()
    hold_status = raw_status if raw_status in VALID_HOLD_STATUSES else "all"

    raw_rule_type = str(query.get("rule_type") or "").strip().lower()
    rule_type = raw_rule_type if raw_rule_type in VALID_RULE_TYPES else ""

    if _snapshot is not None:
        overrides = _snapshot.overrides
        pending_trips = _snapshot.pending_trips
    else:
        overrides = list(
            SafetyOverride.objects.select_related(
                "vessel", "source_trip", "source_trip__vessel"
            ).order_by("-is_active", "-created_at")
        )
        pending_trips = list(
            Trip.objects.filter(status="pending")
            .select_related("vessel")
            .order_by("departure_dt", "trip_id")
        )

    hold_counts = {
        "all": len(overrides),
        "active": sum(1 for ov in overrides if ov.is_active),
        "cleared": sum(1 for ov in overrides if not ov.is_active),
        "weather_hold": sum(1 for ov in overrides if ov.rule_type == "weather_hold"),
        "maintenance_hold": sum(
            1 for ov in overrides if ov.rule_type == "maintenance_hold"
        ),
        "standby_lock": sum(1 for ov in overrides if ov.rule_type == "standby_lock"),
    }

    filtered_overrides: list[SafetyOverride] = []
    for ov in overrides:
        if hold_status == "active" and not ov.is_active:
            continue
        if hold_status == "cleared" and ov.is_active:
            continue
        if rule_type and ov.rule_type != rule_type:
            continue
        filtered_overrides.append(ov)

    holds_list = [build_hold_row(ov, pending_trips) for ov in filtered_overrides]

    return {
        "holds_list": holds_list,
        "hold_counts": hold_counts,
        "hold_filters": {
            "hold_status": hold_status,
            "rule_type": rule_type,
        },
    }


def get_safety_scope_meta(*, _snapshot: _SafetySnapshot | None = None) -> dict[str, Any]:
    """Return vessel & destination scope telemetry for Step 2 cards and smart auto-selection."""
    snapshot = _snapshot if _snapshot is not None else _load_safety_snapshot()

    high_by_vessel: dict[int, int] = defaultdict(int)
    high_by_dest: dict[str, int] = defaultdict(int)
    rough_high_count = 0
    for trip in snapshot.completed_trips:
        if trip.fuel_anomaly_status == "high":
            high_by_vessel[trip.vessel_id] += 1
            high_by_dest[trip.destination] += 1
            if trip.weather == "Rough":
                rough_high_count += 1

    pending_by_vessel: dict[int, int] = defaultdict(int)
    pending_by_dest: dict[str, int] = defaultdict(int)
    rough_pending_by_dest: dict[str, int] = defaultdict(int)
    total_rough_pending = 0
    for trip in snapshot.pending_trips:
        pending_by_vessel[trip.vessel_id] += 1
        pending_by_dest[trip.destination] += 1
        if trip.weather == "Rough":
            rough_pending_by_dest[trip.destination] += 1
            total_rough_pending += 1

    _, _, _, rules_by_vessel = _active_vessel_override_index(snapshot.overrides)
    active_weather_destinations = {
        ov.destination
        for ov in snapshot.overrides
        if ov.is_active and ov.rule_type == "weather_hold"
    }

    vessels_map: dict[str, dict[str, Any]] = {}
    for vessel in snapshot.vessels:
        avail = snapshot.avail_by_vessel.get(vessel.pk, {})
        vessels_map[str(vessel.pk)] = {
            "pk": vessel.pk,
            "vessel_id": vessel.vessel_id,
            "vessel_type": vessel.vessel_type,
            "passenger_capacity": vessel.passenger_capacity,
            "cargo_capacity_t": vessel.cargo_capacity_t,
            "is_standby_designated": vessel.is_standby_designated,
            "high_outliers_count": high_by_vessel.get(vessel.pk, 0),
            "pending_count": pending_by_vessel.get(vessel.pk, 0),
            "maintenance_days": avail.get("maintenance_days", 0),
            "active_rule_types": sorted(rules_by_vessel.get(vessel.pk, set())),
        }

    destinations_list: list[dict[str, Any]] = [
        {
            "value": dest,
            "label": dest,
            "pending_count": pending_by_dest.get(dest, 0),
            "rough_pending_count": rough_pending_by_dest.get(dest, 0),
            "high_outliers_count": high_by_dest.get(dest, 0),
            "has_active_weather_hold": dest in active_weather_destinations,
        }
        for dest in DESTINATIONS
    ]
    destinations_list.append(
        {
            "value": "",
            "label": "All Rough-Sea Corridors",
            "pending_count": total_rough_pending,
            "rough_pending_count": total_rough_pending,
            "high_outliers_count": rough_high_count,
            "has_active_weather_hold": "" in active_weather_destinations,
        }
    )

    return {
        "vessels": vessels_map,
        "vessel_list": list(vessels_map.values()),
        "destinations": destinations_list,
    }


def get_anomaly_inspector_data(trip_id: str) -> dict[str, Any]:
    """Return full physics breakdown, vessel availability, and HSE context for one trip."""
    trip = get_object_or_404(
        Trip.objects.select_related("vessel", "dispatch_plan"),
        trip_id=trip_id,
    )

    status = trip.fuel_anomaly_status
    underway_fuel_l = round(trip.underway_hours * trip.vessel.underway_rate_lph, 1)
    total_idle_hours = round(trip.onsite_work_hours + trip.nonproductive_idle_hours, 2)
    idle_and_onsite_fuel_l = round(total_idle_hours * trip.vessel.idle_rate_lph, 1)
    expected_fuel_l = trip.expected_fuel_l
    actual_fuel_l = trip.actual_fuel_l
    fuel_ratio = trip.fuel_ratio
    fuel_excess_l = trip.fuel_excess_l
    excess_positive_l = (
        round(max(0.0, fuel_excess_l), 1) if fuel_excess_l is not None else 0.0
    )
    excess_kwd = round(excess_positive_l * ASSUMED_DIESEL_KWD_PER_LITER, 2)
    excess_co2_kg = estimate_co2_kg(excess_positive_l)

    physics = {
        "underway_hours": round(trip.underway_hours, 2),
        "underway_rate_lph": round(trip.vessel.underway_rate_lph, 1),
        "underway_fuel_l": underway_fuel_l,
        "onsite_work_hours": round(trip.onsite_work_hours, 2),
        "nonproductive_idle_hours": round(trip.nonproductive_idle_hours, 2),
        "total_idle_hours": total_idle_hours,
        "idle_rate_lph": round(trip.vessel.idle_rate_lph, 1),
        "idle_and_onsite_fuel_l": idle_and_onsite_fuel_l,
        "nonproductive_idle_fuel_l": trip.idle_fuel_l,
        "expected_fuel_l": expected_fuel_l,
        "actual_fuel_l": actual_fuel_l,
        "fuel_ratio": fuel_ratio,
        "fuel_excess_l": fuel_excess_l,
        "excess_positive_l": excess_positive_l,
        "excess_kwd": excess_kwd,
        "excess_co2_kg": excess_co2_kg,
    }

    day_availability = VesselAvailability.objects.filter(
        vessel=trip.vessel, date=trip.trip_date
    ).first()

    avail_agg = VesselAvailability.objects.filter(vessel=trip.vessel).aggregate(
        available_days=Count("id", filter=Q(availability_status="Available")),
        maintenance_days=Count("id", filter=Q(availability_status="Maintenance")),
        maintenance_hours=Sum("maintenance_hours"),
        weather_restricted_days=Count(
            "id", filter=Q(availability_status="Weather Restricted")
        ),
        weather_restricted_hours=Sum("weather_restricted_hours"),
    )
    vessel_availability_summary = {
        "available_days": avail_agg["available_days"] or 0,
        "maintenance_days": avail_agg["maintenance_days"] or 0,
        "maintenance_hours": round(float(avail_agg["maintenance_hours"] or 0.0), 1),
        "weather_restricted_days": avail_agg["weather_restricted_days"] or 0,
        "weather_restricted_hours": round(
            float(avail_agg["weather_restricted_hours"] or 0.0), 1
        ),
    }

    override_q = Q(vessel=trip.vessel) | Q(
        rule_type="weather_hold", destination=trip.destination
    )
    if trip.weather == "Rough":
        override_q |= Q(rule_type="weather_hold", destination="")
    active_overrides = list(
        SafetyOverride.objects.filter(is_active=True)
        .filter(override_q)
        .select_related("vessel", "source_trip")
        .order_by("-created_at")
    )
    has_active_maintenance_hold = any(
        ov.rule_type == "maintenance_hold" and ov.vessel_id == trip.vessel_id
        for ov in active_overrides
    )

    same_vessel_completed = list(
        Trip.objects.filter(status="completed", vessel=trip.vessel)
        .exclude(pk=trip.pk)
        .select_related("vessel")
        .order_by("-departure_dt", "-trip_id")
    )
    vessel_recent_anomalies = [
        candidate
        for candidate in same_vessel_completed
        if candidate.fuel_anomaly_status != "normal"
    ][:4]

    return {
        "trip": trip,
        "anomaly_status": status,
        "investigation_label": _investigation_label(trip, status),
        "physics": physics,
        "engineering_guidance": _engineering_guidance(trip, status),
        "day_availability": day_availability,
        "vessel_availability_summary": vessel_availability_summary,
        "active_overrides": active_overrides,
        "has_active_maintenance_hold": has_active_maintenance_hold,
        "vessel_recent_anomalies": vessel_recent_anomalies,
    }


def create_quick_maintenance_hold(trip_id: str) -> tuple[SafetyOverride, bool, str]:
    """Idempotently activate a Vessel Maintenance Hold linked to a flagged sailing."""
    trip = get_object_or_404(Trip.objects.select_related("vessel"), trip_id=trip_id)

    existing = (
        SafetyOverride.objects.filter(
            rule_type="maintenance_hold",
            vessel=trip.vessel,
            is_active=True,
        )
        .select_related("vessel", "source_trip")
        .first()
    )
    if existing is not None:
        source_ref = existing.source_trip.trip_id if existing.source_trip else "active rule"
        notice = (
            f"Maintenance hold already active on {trip.vessel.vessel_id} "
            f"(linked to {source_ref}) — no duplicate hold created."
        )
        return existing, False, notice

    ratio = trip.fuel_ratio
    status = trip.fuel_anomaly_status
    if status == "high" and ratio is not None and trip.actual_fuel_l is not None:
        excess_l = max(0.0, trip.fuel_excess_l or 0.0)
        reason = (
            f"Engineering fuel audit hold from {trip.trip_id} ({trip.trip_date.isoformat()}): "
            f"{trip.actual_fuel_l:.1f} L actual vs {trip.expected_fuel_l:.1f} L expected "
            f"({ratio:.2f}x, +{excess_l:.1f} L). Inspect injectors, propulsion, and hull fouling."
        )
    elif status == "low" and ratio is not None and trip.actual_fuel_l is not None:
        reason = (
            f"Flow-meter calibration hold from {trip.trip_id} ({trip.trip_date.isoformat()}): "
            f"{trip.actual_fuel_l:.1f} L actual vs {trip.expected_fuel_l:.1f} L expected "
            f"({ratio:.2f}x). Audit fuel sensor calibration and tank sounding log."
        )
    elif status == "missing":
        reason = (
            f"Telemetry log audit hold from {trip.trip_id} ({trip.trip_date.isoformat()}): "
            f"missing actual fuel entry against {trip.expected_fuel_l:.1f} L physics baseline. "
            f"Verify engine-room logbook and fuel sensor feed."
        )
    else:
        reason = (
            f"Preventive engineering maintenance hold from {trip.trip_id} "
            f"({trip.trip_date.isoformat()}) on {trip.vessel.vessel_id}."
        )

    severity = "critical" if (ratio is not None and ratio >= 1.75) else "high"
    override = SafetyOverride.objects.create(
        rule_type="maintenance_hold",
        vessel=trip.vessel,
        destination="",
        source_trip=trip,
        severity=severity,
        reason=reason,
        created_by_role="Marine Operations Supervisor",
        is_active=True,
    )
    notice = (
        f"Activated {override.get_severity_display()} Maintenance Hold on "
        f"{trip.vessel.vessel_id} from {trip.trip_id}."
    )
    return override, True, notice


def toggle_safety_override(pk: int) -> tuple[SafetyOverride, str]:
    """Toggle a SafetyOverride between active and cleared while preventing duplicate active rules."""
    override = get_object_or_404(
        SafetyOverride.objects.select_related("vessel", "source_trip"),
        pk=pk,
    )
    target = (
        override.vessel.vessel_id
        if override.vessel is not None
        else (override.destination or "All Rough-Sea Corridors")
    )

    if override.is_active:
        override.is_active = False
        override.save(update_fields=["is_active", "updated_at"])
        notice = f"Cleared {override.get_rule_type_display()} on {target}."
        return override, notice

    duplicate_qs = SafetyOverride.objects.filter(
        rule_type=override.rule_type,
        is_active=True,
    ).exclude(pk=override.pk)
    if override.rule_type == "weather_hold":
        duplicate_qs = duplicate_qs.filter(destination=override.destination)
    else:
        duplicate_qs = duplicate_qs.filter(vessel=override.vessel)

    if duplicate_qs.exists():
        notice = (
            f"Cannot reactivate: an active {override.get_rule_type_display()} "
            f"already applies to {target}."
        )
        return override, notice

    override.is_active = True
    override.save(update_fields=["is_active", "updated_at"])
    notice = f"Reactivated {override.get_rule_type_display()} on {target}."
    return override, notice
