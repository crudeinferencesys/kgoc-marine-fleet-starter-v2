"""Aggregated fleet telemetry and 90-day backtest opportunity metrics for the Control Tower."""

from __future__ import annotations

import math
from collections import defaultdict

from django.utils import timezone

from apps.core.constants import (
    CONSOLIDATION_DETOUR_FUEL_PENALTY_FACTOR,
    DESTINATIONS,
    estimate_co2_kg,
    estimate_savings_kwd,
)
from apps.core.models import DispatchPlan, SafetyOverride, Trip, Vessel

TACTICAL_BASE = {
    "name": "Marine Base",
    "code": "KJO-BASE",
    "x": 125.0,
    "y": 255.0,
}

TACTICAL_DESTINATIONS: dict[str, dict] = {
    "Maintenance Area": {
        "x": 470.0,
        "y": 82.0,
        "distance_nm": 31.0,
        "code": "MNT-01",
        "kind": "maintenance",
    },
    "Platform A": {
        "x": 610.0,
        "y": 108.0,
        "distance_nm": 36.0,
        "code": "PLT-A",
        "kind": "platform",
    },
    "Platform B": {
        "x": 680.0,
        "y": 208.0,
        "distance_nm": 38.0,
        "code": "PLT-B",
        "kind": "platform",
    },
    "Offshore Terminal": {
        "x": 730.0,
        "y": 315.0,
        "distance_nm": 41.0,
        "code": "TRM-01",
        "kind": "terminal",
    },
    "Platform C": {
        "x": 725.0,
        "y": 422.0,
        "distance_nm": 43.0,
        "code": "PLT-C",
        "kind": "platform",
    },
}


def build_tactical_map_data(
    vessels: list[Vessel],
    completed_trips: list[Trip],
    pending_trips: list[Trip],
    active_overrides: list[SafetyOverride],
) -> dict:
    """
    Build schematic offshore sector coordinates, curved maritime trajectories,
    weather/HSE hazard flags, and moored vessel positions using prefetched data (zero extra queries).
    """
    weather_rank = {"Calm": 1, "Moderate": 2, "Rough": 3}

    vessel_overrides: dict[int, list[SafetyOverride]] = defaultdict(list)
    dest_overrides: dict[str, list[SafetyOverride]] = defaultdict(list)
    for ov in active_overrides:
        if ov.vessel_id:
            vessel_overrides[ov.vessel_id].append(ov)
        if ov.destination:
            dest_overrides[ov.destination].append(ov)

    hist_by_dest: dict[str, list[Trip]] = defaultdict(list)
    trips_by_vessel_hist: dict[int, list[Trip]] = defaultdict(list)
    last_dest_by_vessel: dict[int, str] = {}
    for trip in completed_trips:
        hist_by_dest[trip.destination].append(trip)
        trips_by_vessel_hist[trip.vessel_id].append(trip)
        if trip.vessel_id not in last_dest_by_vessel:
            last_dest_by_vessel[trip.vessel_id] = trip.destination

    pending_by_dest: dict[str, list[Trip]] = defaultdict(list)
    for trip in pending_trips:
        pending_by_dest[trip.destination].append(trip)

    for dest_list in pending_by_dest.values():
        dest_list.sort(key=lambda t: (t.departure_dt, t.trip_id))

    destinations: list[dict] = []
    for dest_name in DESTINATIONS:
        meta = TACTICAL_DESTINATIONS[dest_name]
        p_trips = pending_by_dest.get(dest_name, [])
        h_trips = hist_by_dest.get(dest_name, [])
        d_ovs = dest_overrides.get(dest_name, [])

        half_empty_pending = sum(1 for t in p_trips if t.is_half_empty)
        h_count = len(h_trips)
        avg_util = round(sum(t.utilization_pct for t in h_trips) / h_count, 1) if h_count else 0.0
        worst_weather = max(
            (t.weather for t in p_trips),
            key=lambda w: weather_rank.get(w, 1),
            default="Calm",
        )
        has_weather_hold = any(ov.rule_type == "weather_hold" for ov in d_ovs)
        has_merge_opportunity = len(p_trips) >= 2 and half_empty_pending >= 1

        destinations.append(
            {
                "name": dest_name,
                "code": meta["code"],
                "kind": meta["kind"],
                "x": meta["x"],
                "y": meta["y"],
                "distance_nm": meta["distance_nm"],
                "pending_count": len(p_trips),
                "half_empty_pending_count": half_empty_pending,
                "historical_count": h_count,
                "avg_util_pct": avg_util,
                "worst_weather": worst_weather,
                "has_weather_hold": has_weather_hold,
                "has_merge_opportunity": has_merge_opportunity,
                "hse_reasons": [ov.reason for ov in d_ovs],
            }
        )

    routes: list[dict] = []
    x0, y0 = TACTICAL_BASE["x"], TACTICAL_BASE["y"]

    for dest_name, dest_trips in pending_by_dest.items():
        meta = TACTICAL_DESTINATIONS.get(
            dest_name,
            {"x": 650.0, "y": 240.0, "distance_nm": 36.0, "code": "OFF", "kind": "platform"},
        )
        x1, y1 = meta["x"], meta["y"]
        dx = x1 - x0
        dy = y1 - y0
        mx = (x0 + x1) / 2.0
        my = (y0 + y1) / 2.0
        length = math.hypot(dx, dy) or 1.0
        nx = -dy / length
        ny = dx / length
        bearing_deg = round((math.degrees(math.atan2(dx, -dy)) + 360.0) % 360.0)
        count = len(dest_trips)

        for idx, trip in enumerate(dest_trips):
            offset = -24.0 if count == 1 else (idx - (count - 1) / 2.0) * 46.0 - 10.0
            cx = round(mx + nx * offset, 1)
            cy = round(max(36.0, min(438.0, my + ny * offset)), 1)

            dep_local = timezone.localtime(trip.departure_dt)
            dep_min = dep_local.hour * 60 + dep_local.minute
            outbound_min = max(20, round((trip.underway_hours / 2.0) * 60.0))
            onsite_min = max(
                15, round((trip.onsite_work_hours + trip.nonproductive_idle_hours) * 60.0)
            )
            return_min = max(20, round((trip.underway_hours / 2.0) * 60.0))
            ret_total_min = dep_min + outbound_min + onsite_min + return_min

            trip_ovs = vessel_overrides.get(trip.vessel_id, []) + dest_overrides.get(
                dest_name, []
            )
            has_hse_lock = bool(trip_ovs)
            hse_badges = list(dict.fromkeys(ov.get_rule_type_display() for ov in trip_ovs))
            status_tone = (
                "rose"
                if (has_hse_lock or trip.weather == "Rough")
                else ("amber" if trip.is_half_empty else "teal")
            )

            routes.append(
                {
                    "trip_id": trip.trip_id,
                    "vessel_id": trip.vessel.vessel_id,
                    "vessel_type": trip.vessel.vessel_type,
                    "destination": dest_name,
                    "mission_type": trip.mission_type,
                    "distance_nm": round(float(trip.distance_nm), 1),
                    "cruise_speed_kn": round(float(trip.vessel.cruise_speed_kn), 1),
                    "passengers": int(trip.passengers),
                    "passenger_capacity": int(trip.vessel.passenger_capacity),
                    "cargo_tonnes": round(float(trip.cargo_tonnes), 2),
                    "cargo_capacity_t": round(float(trip.vessel.cargo_capacity_t), 1),
                    "utilization_pct": trip.utilization_pct,
                    "is_half_empty": trip.is_half_empty,
                    "weather": trip.weather,
                    "priority": trip.priority,
                    "flexible_window": trip.flexible_window,
                    "underway_hours": round(float(trip.underway_hours), 2),
                    "onsite_work_hours": round(float(trip.onsite_work_hours), 2),
                    "nonproductive_idle_hours": round(float(trip.nonproductive_idle_hours), 2),
                    "expected_fuel_l": trip.expected_fuel_l,
                    "dep_label": dep_local.strftime("%H:%M"),
                    "ret_label": f"{(ret_total_min // 60) % 24:02d}:{ret_total_min % 60:02d}",
                    "dep_min": dep_min,
                    "outbound_min": outbound_min,
                    "onsite_min": onsite_min,
                    "return_min": return_min,
                    "x0": x0,
                    "y0": y0,
                    "cx": cx,
                    "cy": cy,
                    "x1": x1,
                    "y1": y1,
                    "bearing_deg": bearing_deg,
                    "has_hse_lock": has_hse_lock,
                    "hse_badges": hse_badges,
                    "hse_reasons": [ov.reason for ov in trip_ovs],
                    "status_tone": status_tone,
                    "notes": trip.notes,
                }
            )

    routes.sort(key=lambda r: (r["dep_min"], r["trip_id"]))

    active_vessel_ids = {r["vessel_id"] for r in routes}
    moored_vessels: list[dict] = []
    moored_list = [v for v in vessels if v.vessel_id not in active_vessel_ids]
    for idx, vessel in enumerate(moored_list):
        v_ovs = vessel_overrides.get(vessel.pk, [])
        v_hist = trips_by_vessel_hist.get(vessel.pk, [])
        v_count = len(v_hist)
        v_avg_util = (
            round(sum(t.utilization_pct for t in v_hist) / v_count, 1) if v_count else 0.0
        )
        berth_y = round(max(120.0, min(400.0, 175.0 + idx * 42.0)), 1)
        moored_vessels.append(
            {
                "vessel_id": vessel.vessel_id,
                "vessel_type": vessel.vessel_type,
                "passenger_capacity": vessel.passenger_capacity,
                "cargo_capacity_t": round(float(vessel.cargo_capacity_t), 1),
                "cruise_speed_kn": round(float(vessel.cruise_speed_kn), 1),
                "has_hse_lock": bool(v_ovs),
                "hse_badges": list(dict.fromkeys(ov.get_rule_type_display() for ov in v_ovs)),
                "last_destination": last_dest_by_vessel.get(vessel.pk, "Marine Base"),
                "historical_trips": v_count,
                "avg_util_pct": v_avg_util,
                "x": 76.0,
                "y": berth_y,
            }
        )

    min_clock_min = 420
    max_clock_min = 870
    if routes:
        mid_points = sorted(r["dep_min"] + round(r["outbound_min"] * 0.65) for r in routes)
        median_min = mid_points[len(mid_points) // 2]
        default_clock_min = max(460, min(780, median_min))
    else:
        default_clock_min = 565

    return {
        "base": TACTICAL_BASE,
        "destinations": destinations,
        "routes": routes,
        "moored_vessels": moored_vessels,
        "merge_corridors": [d["name"] for d in destinations if d["has_merge_opportunity"]],
        "min_clock_min": min_clock_min,
        "max_clock_min": max_clock_min,
        "default_clock_min": default_clock_min,
    }


def get_control_tower_metrics() -> dict:
    """
    Compute live fleet utilization, idle-time, 90-day greedy consolidation opportunity,
    and HSE/fuel anomaly metrics using prefetched vessel relations (zero N+1).
    Handles an empty database gracefully.
    """
    vessels = list(Vessel.objects.order_by("vessel_id"))
    total_vessels = len(vessels)

    completed_trips = list(Trip.objects.filter(status="completed").select_related("vessel"))
    historical_trips = len(completed_trips)
    pending_trip_objs = list(
        Trip.objects.filter(status="pending")
        .select_related("vessel")
        .order_by("departure_dt", "trip_id")
    )
    pending_trips = len(pending_trip_objs)

    util_sum = 0.0
    pax_util_sum = 0.0
    half_empty_count = 0
    productive_onsite_hours = 0.0
    avoidable_idle_hours = 0.0
    idle_fuel_liters = 0.0
    severe_fuel_anomalies_count = 0
    low_fuel_anomalies_count = 0
    missing_fuel_logs_count = 0

    trips_by_vessel: dict[int, list[Trip]] = defaultdict(list)
    flexible_groups: dict[tuple, list[Trip]] = defaultdict(list)

    for trip in completed_trips:
        trips_by_vessel[trip.vessel_id].append(trip)
        util_sum += trip.utilization_pct
        pax_util_sum += trip.pax_utilization_pct
        if trip.is_half_empty:
            half_empty_count += 1

        productive_onsite_hours += trip.onsite_work_hours
        avoidable_idle_hours += trip.nonproductive_idle_hours
        idle_fuel_liters += trip.idle_fuel_l

        anomaly_status = trip.fuel_anomaly_status
        if anomaly_status == "high":
            severe_fuel_anomalies_count += 1
        elif anomaly_status == "low":
            low_fuel_anomalies_count += 1
        elif anomaly_status == "missing":
            missing_fuel_logs_count += 1

        if trip.flexible_window:
            flexible_groups[(trip.trip_date, trip.destination)].append(trip)

    avg_utilization_pct = round(util_sum / historical_trips, 1) if historical_trips else 0.0
    avg_pax_utilization_pct = (
        round(pax_util_sum / historical_trips, 1) if historical_trips else 0.0
    )
    half_empty_pct = (
        round((half_empty_count / historical_trips) * 100.0, 1) if historical_trips else 0.0
    )

    productive_onsite_hours = round(productive_onsite_hours, 1)
    avoidable_idle_hours = round(avoidable_idle_hours, 1)
    idle_fuel_liters = round(idle_fuel_liters, 1)
    total_onsite_and_idle = productive_onsite_hours + avoidable_idle_hours
    productive_share_pct = (
        round((productive_onsite_hours / total_onsite_and_idle) * 100.0, 1)
        if total_onsite_and_idle > 0
        else 0.0
    )

    # Fast 90-day greedy consolidation backtest over flexible completed trips.
    in_service_vessels = [v for v in vessels if v.status == "In Service"] or vessels
    max_vessel_pax = max((v.passenger_capacity for v in in_service_vessels), default=22)
    max_vessel_cargo = max((v.cargo_capacity_t for v in in_service_vessels), default=9.0)

    def _can_carry_combined(pax: int, cargo: float) -> bool:
        if not in_service_vessels:
            return pax <= max_vessel_pax and cargo <= max_vessel_cargo
        return any(
            v.passenger_capacity >= pax and v.cargo_capacity_t >= cargo
            for v in in_service_vessels
        )

    backtest_trips_eliminated = 0
    backtest_fuel_saved_l = 0.0
    backtest_hours_saved = 0.0

    for group_trips in flexible_groups.values():
        if len(group_trips) < 2:
            continue
        group_trips.sort(
            key=lambda t: (t.earliest_departure_dt or t.departure_dt, t.departure_dt, t.trip_id)
        )
        n = len(group_trips)
        used = [False] * n
        for i in range(n):
            if used[i]:
                continue
            a = group_trips[i]
            a_latest = a.latest_departure_dt or a.departure_dt
            for j in range(i + 1, n):
                if used[j]:
                    continue
                b = group_trips[j]
                b_earliest = b.earliest_departure_dt or b.departure_dt
                if b_earliest > a_latest:
                    break
                combined_pax = a.passengers + b.passengers
                combined_cargo = a.cargo_tonnes + b.cargo_tonnes
                if (
                    combined_pax <= max_vessel_pax
                    and combined_cargo <= max_vessel_cargo
                    and _can_carry_combined(combined_pax, combined_cargo)
                ):
                    used[i] = True
                    used[j] = True
                    backtest_trips_eliminated += 1
                    backtest_fuel_saved_l += b.expected_fuel_l * (
                        1.0 - CONSOLIDATION_DETOUR_FUEL_PENALTY_FACTOR
                    )
                    backtest_hours_saved += b.underway_hours + b.nonproductive_idle_hours
                    break

    backtest_fuel_saved_l = round(backtest_fuel_saved_l, 1)
    backtest_kwd_saved = estimate_savings_kwd(backtest_fuel_saved_l, backtest_hours_saved)
    backtest_co2_tonnes = round(estimate_co2_kg(backtest_fuel_saved_l) / 1000.0, 1)

    active_overrides_all = list(
        SafetyOverride.objects.filter(is_active=True).select_related("vessel")
    )
    active_hse_overrides_count = len(active_overrides_all)
    active_hse_overrides = active_overrides_all[:3]
    approved_plans_count = DispatchPlan.objects.filter(is_approved=True).count()

    chart_labels: list[str] = []
    chart_avg_util: list[float] = []
    chart_half_empty_pct: list[float] = []
    chart_trip_counts: list[int] = []

    for vessel in vessels:
        v_trips = trips_by_vessel.get(vessel.pk, [])
        v_count = len(v_trips)
        v_avg_util = (
            round(sum(t.utilization_pct for t in v_trips) / v_count, 1) if v_count else 0.0
        )
        v_half_empty = (
            round((sum(1 for t in v_trips if t.is_half_empty) / v_count) * 100.0, 1)
            if v_count
            else 0.0
        )
        chart_labels.append(vessel.vessel_id)
        chart_avg_util.append(v_avg_util)
        chart_half_empty_pct.append(v_half_empty)
        chart_trip_counts.append(v_count)

    return {
        "total_vessels": total_vessels,
        "historical_trips": historical_trips,
        "pending_trips": pending_trips,
        "avg_utilization_pct": avg_utilization_pct,
        "avg_pax_utilization_pct": avg_pax_utilization_pct,
        "half_empty_count": half_empty_count,
        "half_empty_pct": half_empty_pct,
        "productive_onsite_hours": productive_onsite_hours,
        "avoidable_idle_hours": avoidable_idle_hours,
        "idle_fuel_liters": idle_fuel_liters,
        "productive_share_pct": productive_share_pct,
        "backtest_trips_eliminated": backtest_trips_eliminated,
        "backtest_fuel_saved_l": backtest_fuel_saved_l,
        "backtest_kwd_saved": backtest_kwd_saved,
        "backtest_co2_tonnes": backtest_co2_tonnes,
        "active_hse_overrides_count": active_hse_overrides_count,
        "active_hse_overrides": active_hse_overrides,
        "severe_fuel_anomalies_count": severe_fuel_anomalies_count,
        "low_fuel_anomalies_count": low_fuel_anomalies_count,
        "missing_fuel_logs_count": missing_fuel_logs_count,
        "approved_plans_count": approved_plans_count,
        "vessel_chart_data": {
            "labels": chart_labels,
            "avg_util": chart_avg_util,
            "half_empty_pct": chart_half_empty_pct,
            "trip_counts": chart_trip_counts,
        },
        "tactical_map": build_tactical_map_data(
            vessels=vessels,
            completed_trips=completed_trips,
            pending_trips=pending_trip_objs,
            active_overrides=active_overrides_all,
        ),
    }
