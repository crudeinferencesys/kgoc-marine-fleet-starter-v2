"""Feature 2 dispatch consolidation solver, plan approval, and revert services."""

from __future__ import annotations

from collections import defaultdict

from django.db import transaction
from django.utils import timezone

from apps.core.constants import (
    ASSUMED_DIESEL_KWD_PER_LITER,
    CONSOLIDATION_DETOUR_FUEL_PENALTY_FACTOR,
    DISPATCHER_MINUTES_SAVED_PER_MERGE,
    estimate_co2_kg,
    estimate_savings_kwd,
)
from apps.core.models import DispatchPlan, SafetyOverride, Trip, Vessel
from apps.core.services import get_control_tower_metrics

MILK_RUN_DETOUR_FUEL_PENALTY_FACTOR = 0.18
MILK_RUN_PLATFORM_CLUSTER = {"Platform A", "Platform B", "Platform C"}

_HELD_BADGE_LABELS = {
    "standby_lock": "Standby Lock",
    "maintenance_hold": "Maintenance Hold",
    "weather_hold": "Weather Hold",
    "rough_weather": "Rough Sea Hold",
    "fixed_window": "Fixed Window",
    "high_utilization": "High Utilization",
    "already_planned": "Approved Plan",
    "no_partner": "No Partner",
}


def _select_optimal_carrier(
    primary: Trip,
    absorbed: Trip,
    combined_pax: int,
    combined_cargo: float,
    eligible_vessels: list[Vessel],
) -> Vessel | None:
    """Return the lowest-cost eligible vessel able to carry combined pax and cargo."""
    fitting = [
        v
        for v in eligible_vessels
        if v.passenger_capacity >= combined_pax and v.cargo_capacity_t >= combined_cargo
    ]
    if not fitting:
        return None

    def _cost_key(vessel: Vessel) -> tuple[float, int, str]:
        fuel_l = (
            primary.underway_hours * vessel.underway_rate_lph
            + (primary.onsite_work_hours + primary.nonproductive_idle_hours) * vessel.idle_rate_lph
        )
        total_hours = (
            primary.underway_hours
            + primary.onsite_work_hours
            + primary.nonproductive_idle_hours
        )
        cost_kwd = (
            fuel_l * ASSUMED_DIESEL_KWD_PER_LITER
            + total_hours * vessel.hourly_operating_kwd
        )
        if vessel.vessel_id == primary.vessel.vessel_id:
            tie_pref = 0
        elif vessel.vessel_id == absorbed.vessel.vessel_id:
            tie_pref = 1
        else:
            tie_pref = 2
        return (round(cost_kwd, 6), tie_pref, vessel.vessel_id)

    return min(fitting, key=_cost_key)


def _build_merge_proposal(
    primary: Trip,
    absorbed: Trip,
    assigned_vessel: Vessel,
    combined_pax: int,
    combined_cargo: float,
    *,
    mode: str,
    detour_penalty_factor: float,
) -> dict:
    """Construct a structured Before -> After merge proposal dictionary."""
    a_earliest = primary.earliest_departure_dt or primary.departure_dt
    b_earliest = absorbed.earliest_departure_dt or absorbed.departure_dt
    recommended_departure_dt = max(a_earliest, b_earliest)

    pax_util = (
        (combined_pax / assigned_vessel.passenger_capacity) * 100.0
        if assigned_vessel.passenger_capacity > 0
        else 0.0
    )
    cargo_util = (
        (combined_cargo / assigned_vessel.cargo_capacity_t) * 100.0
        if assigned_vessel.cargo_capacity_t > 0
        else 0.0
    )
    combined_util_pct = round(max(pax_util, cargo_util), 1)

    fuel_saved_l = round(absorbed.expected_fuel_l * (1.0 - detour_penalty_factor), 1)
    hours_saved = round(absorbed.underway_hours + absorbed.nonproductive_idle_hours, 2)
    kwd_saved = estimate_savings_kwd(
        fuel_saved_l,
        hours_saved,
        absorbed.vessel.hourly_operating_kwd,
    )
    co2_kg_saved = estimate_co2_kg(fuel_saved_l)

    if mode == "milk_run":
        route_label = f"Marine Base → {primary.destination} → {absorbed.destination}"
    else:
        route_label = f"Marine Base → {primary.destination}"

    caution_flag = (
        "Rough Sea Advisory"
        if (primary.weather == "Rough" or absorbed.weather == "Rough")
        else ""
    )

    return {
        "merge_id": f"{primary.trip_id}+{absorbed.trip_id}",
        "mode": mode,
        "primary_trip": primary,
        "absorbed_trip": absorbed,
        "assigned_vessel": assigned_vessel,
        "vessel_reassigned": assigned_vessel.pk != primary.vessel_id,
        "route_label": route_label,
        "recommended_departure_dt": recommended_departure_dt,
        "combined_pax": combined_pax,
        "combined_cargo": combined_cargo,
        "combined_util_pct": combined_util_pct,
        "fuel_saved_l": fuel_saved_l,
        "hours_saved": hours_saved,
        "kwd_saved": kwd_saved,
        "co2_kg_saved": co2_kg_saved,
        "dispatcher_minutes_saved": DISPATCHER_MINUTES_SAVED_PER_MERGE,
        "caution_flag": caution_flag,
        "checked_default": True,
    }


def _classify_pending_trips(
    pending_trips: list[Trip],
    vessel_block_override: dict[int, SafetyOverride],
    dest_block_override: dict[str, SafetyOverride],
    *,
    strict_weather: bool,
) -> tuple[list[Trip], list[dict]]:
    """Separate pending trips into consolidation-eligible trips and held trips."""
    eligible_trips: list[Trip] = []
    held_trips: list[dict] = []

    def _add_held(trip: Trip, reason: str, badge_tone: str, category: str) -> None:
        held_trips.append(
            {
                "trip": trip,
                "reason": reason,
                "badge_tone": badge_tone,
                "category": category,
                "badge_label": _HELD_BADGE_LABELS.get(category, category.replace("_", " ").title()),
            }
        )

    for trip in pending_trips:
        if trip.vessel_id in vessel_block_override:
            override = vessel_block_override[trip.vessel_id]
            if override.rule_type == "standby_lock":
                _add_held(
                    trip,
                    f"Vessel {trip.vessel.vessel_id} protected by Standby Lock",
                    "rose",
                    "standby_lock",
                )
            else:
                _add_held(
                    trip,
                    f"Vessel {trip.vessel.vessel_id} on Maintenance Hold",
                    "rose",
                    "maintenance_hold",
                )
            continue

        if trip.destination in dest_block_override:
            _add_held(
                trip,
                f"{trip.destination} under active HSE Weather Hold",
                "rose",
                "weather_hold",
            )
            continue

        if strict_weather and trip.weather == "Rough":
            _add_held(
                trip,
                "Rough sea state (HSE Strict Weather active)",
                "rose",
                "rough_weather",
            )
            continue

        if not trip.flexible_window:
            _add_held(
                trip,
                "Fixed departure window (non-flexible)",
                "slate",
                "fixed_window",
            )
            continue

        if trip.utilization_pct >= 75.0:
            _add_held(
                trip,
                "Already high utilization (>=75%) — dedicated sailing optimal",
                "slate",
                "high_utilization",
            )
            continue

        if trip.dispatch_plan_id is not None and trip.dispatch_plan and trip.dispatch_plan.is_approved:
            _add_held(
                trip,
                f"Already assigned to {trip.dispatch_plan.name}",
                "slate",
                "already_planned",
            )
            continue

        eligible_trips.append(trip)

    return eligible_trips, held_trips


def _pair_group_trips(
    group_trips: list[Trip],
    eligible_vessels: list[Vessel],
    *,
    mode: str,
    detour_penalty_factor: float,
    require_distinct_destination: bool = False,
) -> tuple[list[dict], set[int]]:
    """Greedily pair overlapping trips in a sorted group with optimal carrier selection."""
    group_trips.sort(
        key=lambda t: (t.earliest_departure_dt or t.departure_dt, t.departure_dt, t.trip_id)
    )
    merges: list[dict] = []
    paired_pks: set[int] = set()
    n = len(group_trips)

    for i in range(n):
        a = group_trips[i]
        if a.pk in paired_pks:
            continue
        a_latest = a.latest_departure_dt or a.departure_dt
        for j in range(i + 1, n):
            b = group_trips[j]
            if b.pk in paired_pks:
                continue
            b_earliest = b.earliest_departure_dt or b.departure_dt
            if b_earliest > a_latest:
                break
            if require_distinct_destination and a.destination == b.destination:
                continue

            combined_pax = a.passengers + b.passengers
            combined_cargo = round(a.cargo_tonnes + b.cargo_tonnes, 2)
            best_vessel = _select_optimal_carrier(
                a,
                b,
                combined_pax,
                combined_cargo,
                eligible_vessels,
            )
            if best_vessel is None:
                continue

            paired_pks.add(a.pk)
            paired_pks.add(b.pk)
            merges.append(
                _build_merge_proposal(
                    a,
                    b,
                    best_vessel,
                    combined_pax,
                    combined_cargo,
                    mode=mode,
                    detour_penalty_factor=detour_penalty_factor,
                )
            )
            break

    return merges, paired_pks


def _build_backtest_summary() -> dict:
    """Transform Control Tower 90-day backtest metrics into optimizer summary + corridor rows."""
    metrics = get_control_tower_metrics()
    savings_data = metrics["savings_chart_data"]
    corridors = [
        {
            "destination": label,
            "merges": merges,
            "merge_fuel_l": merge_fuel,
            "idle_fuel_l": idle_fuel,
        }
        for label, merges, merge_fuel, idle_fuel in zip(
            savings_data["labels"],
            savings_data["merges"],
            savings_data["merge_fuel_l"],
            savings_data["idle_fuel_l"],
        )
    ]
    return {
        "historical_trips": metrics["historical_trips"],
        "trips_eliminated": metrics["backtest_trips_eliminated"],
        "fuel_saved_l": metrics["backtest_fuel_saved_l"],
        "kwd_saved": metrics["backtest_kwd_saved"],
        "co2_tonnes": metrics["backtest_co2_tonnes"],
        "corridors": corridors,
    }


def run_shift_optimizer(*, strict_weather: bool = True, allow_milk_run: bool = False) -> dict:
    """
    Solve the pending shift dispatch queue under active HSE SafetyOverrides,
    time-window overlap, and vessel capacity constraints.
    """
    pending_trips = list(
        Trip.objects.filter(status="pending")
        .select_related("vessel", "dispatch_plan")
        .order_by("trip_date", "departure_dt", "trip_id")
    )
    active_overrides = list(
        SafetyOverride.objects.filter(is_active=True).select_related("vessel")
    )
    in_service_vessels = list(
        Vessel.objects.filter(status="In Service").order_by("vessel_id")
    )

    vessel_block_override: dict[int, SafetyOverride] = {}
    dest_block_override: dict[str, SafetyOverride] = {}
    for override in active_overrides:
        if override.rule_type in ("standby_lock", "maintenance_hold") and override.vessel_id:
            vessel_block_override.setdefault(override.vessel_id, override)
        elif override.rule_type == "weather_hold" and override.destination.strip():
            dest_block_override.setdefault(override.destination.strip(), override)

    eligible_vessels = [
        v for v in in_service_vessels if v.pk not in vessel_block_override
    ]

    eligible_trips, held_trips = _classify_pending_trips(
        pending_trips,
        vessel_block_override,
        dest_block_override,
        strict_weather=strict_weather,
    )

    proposed_merges: list[dict] = []
    paired_pks: set[int] = set()

    # Pass 1: Same-corridor consolidation + optimal vessel right-sizing.
    corridor_groups: dict[tuple, list[Trip]] = defaultdict(list)
    for trip in eligible_trips:
        corridor_groups[(trip.trip_date, trip.destination)].append(trip)

    for key in sorted(corridor_groups.keys()):
        merges, group_paired = _pair_group_trips(
            corridor_groups[key],
            eligible_vessels,
            mode="same_corridor",
            detour_penalty_factor=CONSOLIDATION_DETOUR_FUEL_PENALTY_FACTOR,
        )
        proposed_merges.extend(merges)
        paired_pks.update(group_paired)

    # Pass 2: Optional multi-platform milk-run across Platform A / B / C.
    if allow_milk_run:
        milk_run_groups: dict[object, list[Trip]] = defaultdict(list)
        for trip in eligible_trips:
            if trip.pk not in paired_pks and trip.destination in MILK_RUN_PLATFORM_CLUSTER:
                milk_run_groups[trip.trip_date].append(trip)

        for trip_date in sorted(milk_run_groups.keys()):
            merges, group_paired = _pair_group_trips(
                milk_run_groups[trip_date],
                eligible_vessels,
                mode="milk_run",
                detour_penalty_factor=MILK_RUN_DETOUR_FUEL_PENALTY_FACTOR,
                require_distinct_destination=True,
            )
            proposed_merges.extend(merges)
            paired_pks.update(group_paired)

    for trip in eligible_trips:
        if trip.pk not in paired_pks:
            held_trips.append(
                {
                    "trip": trip,
                    "reason": "No overlapping compatible corridor partner",
                    "badge_tone": "amber",
                    "category": "no_partner",
                    "badge_label": _HELD_BADGE_LABELS["no_partner"],
                }
            )

    proposed_merges.sort(
        key=lambda m: (
            m["mode"] != "same_corridor",
            m["recommended_departure_dt"],
            m["merge_id"],
        )
    )

    held_trips.sort(
        key=lambda item: (
            item["trip"].trip_date,
            item["trip"].departure_dt,
            item["trip"].trip_id,
        )
    )

    baseline_trips = len(pending_trips)
    trips_eliminated = len(proposed_merges)
    summary = {
        "baseline_trips": baseline_trips,
        "trips_eliminated": trips_eliminated,
        "optimized_trips": baseline_trips - trips_eliminated,
        "fuel_liters_saved": round(sum(m["fuel_saved_l"] for m in proposed_merges), 1),
        "kwd_saved": round(sum(m["kwd_saved"] for m in proposed_merges), 2),
        "co2_kg_saved": round(sum(m["co2_kg_saved"] for m in proposed_merges), 1),
        "dispatcher_minutes_saved": sum(m["dispatcher_minutes_saved"] for m in proposed_merges),
    }

    saved_plans = list(
        DispatchPlan.objects.filter(scope="pending").order_by("-created_at")[:12]
    )

    return {
        "strict_weather": strict_weather,
        "allow_milk_run": allow_milk_run,
        "pending_count": baseline_trips,
        "eligible_vessels": eligible_vessels,
        "active_overrides": active_overrides,
        "proposed_merges": proposed_merges,
        "held_trips": held_trips,
        "summary": summary,
        "saved_plans": saved_plans,
        "backtest": _build_backtest_summary(),
    }


def approve_dispatch_plan(
    *,
    selected_merge_ids: list[str],
    strict_weather: bool,
    allow_milk_run: bool,
    plan_name: str = "",
) -> tuple[DispatchPlan | None, str]:
    """
    Recompute the solver server-side, persist an approved DispatchPlan for the
    selected merge IDs, and update primary/absorbed Trip records atomically.
    """
    selected_set = {mid.strip() for mid in selected_merge_ids if mid and mid.strip()}
    if not selected_set:
        return None, "Select at least one proposed merge to approve."

    with transaction.atomic():
        solver_result = run_shift_optimizer(
            strict_weather=strict_weather,
            allow_milk_run=allow_milk_run,
        )
        selected_merges = [
            m for m in solver_result["proposed_merges"] if m["merge_id"] in selected_set
        ]
        if not selected_merges:
            return None, "Select at least one proposed merge to approve."

        baseline_trips = solver_result["summary"]["baseline_trips"]
        trips_eliminated = len(selected_merges)
        optimized_trips = baseline_trips - trips_eliminated
        fuel_liters_saved = round(sum(m["fuel_saved_l"] for m in selected_merges), 1)
        kwd_saved = round(sum(m["kwd_saved"] for m in selected_merges), 2)
        co2_kg_saved = round(sum(m["co2_kg_saved"] for m in selected_merges), 1)
        dispatcher_minutes_saved = sum(
            m["dispatcher_minutes_saved"] for m in selected_merges
        )

        cleaned_name = (plan_name or "").strip()
        if not cleaned_name:
            cleaned_name = f"Shift Plan · {timezone.localtime().strftime('%Y-%m-%d %H:%M')}"
        cleaned_name = cleaned_name[:120]

        payload_merges = []
        for m in selected_merges:
            primary: Trip = m["primary_trip"]
            absorbed: Trip = m["absorbed_trip"]
            assigned_vessel: Vessel = m["assigned_vessel"]
            payload_merges.append(
                {
                    "merge_id": m["merge_id"],
                    "mode": m["mode"],
                    "route_label": m["route_label"],
                    "primary_trip_pk": primary.pk,
                    "primary_trip_id": primary.trip_id,
                    "absorbed_trip_pk": absorbed.pk,
                    "absorbed_trip_id": absorbed.trip_id,
                    "original_vessel_id": primary.vessel_id,
                    "original_vessel_code": primary.vessel.vessel_id,
                    "assigned_vessel_id": assigned_vessel.pk,
                    "assigned_vessel_code": assigned_vessel.vessel_id,
                    "vessel_reassigned": m["vessel_reassigned"],
                    "combined_pax": m["combined_pax"],
                    "combined_cargo": m["combined_cargo"],
                    "combined_util_pct": m["combined_util_pct"],
                    "fuel_saved_l": m["fuel_saved_l"],
                    "kwd_saved": m["kwd_saved"],
                    "co2_kg_saved": m["co2_kg_saved"],
                    "dispatcher_minutes_saved": m["dispatcher_minutes_saved"],
                }
            )

        plan = DispatchPlan.objects.create(
            name=cleaned_name,
            scope="pending",
            baseline_trips=baseline_trips,
            optimized_trips=optimized_trips,
            trips_eliminated=trips_eliminated,
            fuel_liters_saved=fuel_liters_saved,
            kwd_saved=kwd_saved,
            co2_kg_saved=co2_kg_saved,
            dispatcher_minutes_saved=dispatcher_minutes_saved,
            plan_payload={
                "strict_weather": strict_weather,
                "allow_milk_run": allow_milk_run,
                "merges": payload_merges,
            },
            is_approved=True,
            approved_at=timezone.now(),
        )

        for m in selected_merges:
            primary = m["primary_trip"]
            absorbed = m["absorbed_trip"]
            assigned_vessel = m["assigned_vessel"]

            primary_fields = ["dispatch_plan", "updated_at"]
            primary.dispatch_plan = plan
            if m["vessel_reassigned"]:
                primary.vessel = assigned_vessel
                primary_fields.append("vessel")
            primary.save(update_fields=primary_fields)

            absorbed.status = "consolidated"
            absorbed.dispatch_plan = plan
            absorbed.consolidated_into = primary
            absorbed.save(
                update_fields=["status", "dispatch_plan", "consolidated_into", "updated_at"]
            )

    return plan, f"Approved '{plan.name}' (-{trips_eliminated} trips, {kwd_saved:.0f} KWD saved)."


def revert_dispatch_plan(plan_id: int) -> tuple[DispatchPlan | None, str]:
    """
    Atomically revert an approved pending-shift DispatchPlan and restore all
    consolidated/reassigned trips back to the pending dispatch queue.
    """
    plan = DispatchPlan.objects.filter(pk=plan_id, scope="pending").first()
    if plan is None:
        return None, "Dispatch plan not found."
    if not plan.is_approved:
        return plan, f"'{plan.name}' is already reverted."

    payload = plan.plan_payload if isinstance(plan.plan_payload, dict) else {}
    orig_vessel_by_pk: dict[int, int] = {}
    orig_vessel_by_trip_id: dict[str, int] = {}
    for entry in payload.get("merges", []):
        if not isinstance(entry, dict):
            continue
        orig_vid = entry.get("original_vessel_id")
        if orig_vid is None:
            continue
        if entry.get("primary_trip_pk") is not None:
            orig_vessel_by_pk[int(entry["primary_trip_pk"])] = int(orig_vid)
        if entry.get("primary_trip_id"):
            orig_vessel_by_trip_id[str(entry["primary_trip_id"])] = int(orig_vid)

    with transaction.atomic():
        linked_trips = list(Trip.objects.filter(dispatch_plan=plan))
        for trip in linked_trips:
            update_fields = ["dispatch_plan", "updated_at"]
            if trip.status == "consolidated":
                trip.status = "pending"
                trip.consolidated_into = None
                update_fields.extend(["status", "consolidated_into"])
            trip.dispatch_plan = None

            orig_vessel_id = orig_vessel_by_pk.get(trip.pk) or orig_vessel_by_trip_id.get(
                trip.trip_id
            )
            if orig_vessel_id is not None and trip.vessel_id != orig_vessel_id:
                trip.vessel_id = orig_vessel_id
                update_fields.append("vessel")

            trip.save(update_fields=update_fields)

        plan.is_approved = False
        plan.save(update_fields=["is_approved", "updated_at"])

    return plan, f"Reverted '{plan.name}' and restored trips to the pending queue."
