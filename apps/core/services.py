"""Aggregated fleet telemetry and 90-day backtest opportunity metrics for the Control Tower."""

from __future__ import annotations

from collections import defaultdict

from apps.core.constants import (
    CONSOLIDATION_DETOUR_FUEL_PENALTY_FACTOR,
    estimate_co2_kg,
    estimate_savings_kwd,
)
from apps.core.models import DispatchPlan, SafetyOverride, Trip, Vessel


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
    pending_trips = Trip.objects.filter(status="pending").count()

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
    }
