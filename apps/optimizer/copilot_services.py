"""Standalone Gemini 4 AI Dispatch Co-Pilot services for Feature 4 (/copilot/)."""

from __future__ import annotations

from collections import Counter
import textwrap
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.core.ai import (
    ActionableDispatchBriefing,
    MergeRiskAssessment,
    generate_structured,
    is_ai_configured,
)
from apps.core.constants import DESTINATIONS
from apps.core.models import DispatchPlan, SafetyOverride, Trip, Vessel
from apps.optimizer.services import approve_dispatch_plan, run_shift_optimizer

COPILOT_SCENARIOS: list[dict[str, Any]] = [
    {
        "key": "standard_handover",
        "title": "Standard Shift Handover",
        "subtitle": "Calm/moderate merges under HSE Strict Weather",
        "strict_weather": True,
        "allow_milk_run": False,
        "directive": (
            "Review all pending same-corridor merges under HSE Strict Weather, protect "
            "standby vessel CB-07, and prepare a concise shift handover briefing."
        ),
    },
    {
        "key": "rough_sea_audit",
        "title": "Rough-Sea HSE Audit",
        "subtitle": "Assess rough-weather pairs & corridor hold risks",
        "strict_weather": False,
        "allow_milk_run": False,
        "directive": (
            "Audit pending rough sea-state departures on Platform C, flag unsafe merges "
            "for hold or review, and recommend corridor weather protection."
        ),
    },
    {
        "key": "fuel_outlier_check",
        "title": "Fuel Outlier Investigation",
        "subtitle": "Flag high-burn vessels for engineering review",
        "strict_weather": True,
        "allow_milk_run": False,
        "directive": (
            "Cross-check pending vessel assignments against high fuel-burn engineering "
            "outliers (e.g. CB-08 TR-00012 at 2.07x) and recommend preventive maintenance holds."
        ),
    },
    {
        "key": "milk_run_push",
        "title": "Milk-Run Savings Push",
        "subtitle": "Evaluate multi-platform merges across A/B/C",
        "strict_weather": True,
        "allow_milk_run": True,
        "directive": (
            "Evaluate multi-platform milk-run consolidation across Platforms A, B, and C "
            "while verifying passenger/cargo margins and sea-state safety."
        ),
    },
]

_SCENARIOS_BY_KEY: dict[str, dict[str, Any]] = {
    item["key"]: item for item in COPILOT_SCENARIOS
}

COPILOT_SYSTEM_INSTRUCTION = (
    "You are the KGOC / KJO Offshore Marine Fleet AI Dispatch Co-Pilot. "
    "Evaluate proposed vessel consolidation merges strictly from offshore marine operations "
    "and HSE engineering principles. "
    "Rules: "
    "(1) Never recommend overriding active marine safety locks, maintenance holds, or rough-sea holds. "
    "(2) Frame all elevated fuel-burn anomalies strictly as neutral engineering investigation items "
    "(engine/hull/injector/sensor checks) — never imply misconduct or theft. "
    "(3) Use the exact `merge_id` strings provided in the prompt as `group_id` in `merge_assessments`, "
    "scoring each merge as `approve`, `review`, or `hold` with risk level `low`, `medium`, or `high`. "
    "(4) Keep summaries, flags, and shift handover notes concise, quantitative (KWD mock, L, kg CO2), "
    "and immediately actionable for an offshore Marine Operations Supervisor."
)


def get_scenario(scenario_key: str) -> dict[str, Any]:
    """Return the matching KJO Co-Pilot preset or fall back to standard_handover."""
    return _SCENARIOS_BY_KEY.get((scenario_key or "").strip(), COPILOT_SCENARIOS[0])


def _extract_pending_trips_from_solver(solver: dict[str, Any]) -> list[Trip]:
    """Collect all pending trips already loaded by run_shift_optimizer without extra queries."""
    seen: dict[int, Trip] = {}
    for merge in solver["proposed_merges"]:
        for key in ("primary_trip", "absorbed_trip"):
            trip = merge[key]
            seen[trip.pk] = trip
    for held in solver["held_trips"]:
        trip = held["trip"]
        seen[trip.pk] = trip
    return list(seen.values())


def _collect_fuel_telemetry() -> tuple[list[Trip], int, dict[str, Trip]]:
    """Return high-burn completed trips sorted by severity, missing count, and top anomaly per vessel."""
    completed = list(Trip.objects.filter(status="completed").select_related("vessel"))
    high_trips: list[Trip] = []
    missing_count = 0
    for trip in completed:
        status = trip.fuel_anomaly_status
        if status == "high":
            high_trips.append(trip)
        elif status == "missing":
            missing_count += 1

    high_trips.sort(
        key=lambda t: (
            -(t.fuel_ratio or 0.0),
            -(t.fuel_excess_l or 0.0),
            t.trip_id,
        )
    )
    top_by_vessel: dict[str, Trip] = {}
    for trip in high_trips:
        top_by_vessel.setdefault(trip.vessel.vessel_id, trip)
    return high_trips, missing_count, top_by_vessel


def _build_recommended_holds(
    *,
    high_anomalies: list[Trip],
    pending_trips: list[Trip],
    active_overrides: list[SafetyOverride],
) -> list[dict[str, Any]]:
    """Build up to 2 concrete, DB-grounded HSE hold recommendations with live status."""
    recommendations: list[dict[str, Any]] = []

    active_maint_vessels = {
        ov.vessel.vessel_id
        for ov in active_overrides
        if ov.is_active and ov.rule_type == "maintenance_hold" and ov.vessel_id
    }
    active_weather_dests = {
        (ov.destination or "").strip()
        for ov in active_overrides
        if ov.is_active and ov.rule_type == "weather_hold"
    }

    if high_anomalies:
        # Prefer top non-rough engineering priority outlier; fall back to overall highest ratio.
        non_rough = [t for t in high_anomalies if t.weather != "Rough"]
        top = non_rough[0] if non_rough else high_anomalies[0]
        ratio = top.fuel_ratio or 0.0
        excess_l = max(0.0, top.fuel_excess_l or 0.0)
        actual_l = top.actual_fuel_l or 0.0
        recommendations.append(
            {
                "key": f"maint_{top.vessel.vessel_id}",
                "rule_type": "maintenance_hold",
                "rule_label": "Vessel Maintenance Hold",
                "target_label": top.vessel.vessel_id,
                "vessel_id": top.vessel.vessel_id,
                "destination": "",
                "source_trip_id": top.trip_id,
                "severity": "critical" if ratio >= 1.75 else "high",
                "title": f"Engineering Maintenance Hold · {top.vessel.vessel_id}",
                "metric_badge": (
                    f"{top.trip_id} · {ratio:.2f}× "
                    f"({actual_l:.0f} vs {top.expected_fuel_l:.0f} L)"
                ),
                "reason": (
                    f"Engineering fuel-burn inspection recommended for {top.vessel.vessel_id} "
                    f"following {top.trip_id} ({ratio:.2f}x baseline, +{excess_l:.1f} L excess). "
                    "Hold vessel from automated merges pending injector and hull diagnostics."
                ),
                "is_already_active": top.vessel.vessel_id in active_maint_vessels,
            }
        )

    rough_pending = [t for t in pending_trips if t.weather == "Rough"]
    if rough_pending:
        dest_counts = Counter(t.destination for t in rough_pending)
        rough_dest, rough_count = dest_counts.most_common(1)[0]
        rough_ids = [t.trip_id for t in rough_pending if t.destination == rough_dest]
        is_weather_active = (rough_dest in active_weather_dests) or (
            "" in active_weather_dests
        )
        recommendations.append(
            {
                "key": f"weather_{rough_dest.lower().replace(' ', '_')}",
                "rule_type": "weather_hold",
                "rule_label": "Sea-State / Weather Hold",
                "target_label": rough_dest,
                "vessel_id": "",
                "destination": rough_dest,
                "source_trip_id": "",
                "severity": "high",
                "title": f"Sea-State Weather Hold · {rough_dest}",
                "metric_badge": (
                    f"{rough_count} Rough pending run"
                    f"{'s' if rough_count != 1 else ''}"
                ),
                "reason": (
                    f"Rough sea-state reported on {rough_dest} corridor "
                    f"({', '.join(rough_ids)}). Activate corridor weather hold to block "
                    "routine consolidation until offshore swell subsides."
                ),
                "is_already_active": is_weather_active,
            }
        )

    return recommendations[:2]


def build_deterministic_briefing(
    *,
    solver: dict[str, Any],
    scenario: dict[str, Any],
    directive: str,
    high_anomalies: list[Trip],
    missing_logs_count: int,
    top_anomaly_by_vessel: dict[str, Trip],
    pending_trips: list[Trip],
) -> ActionableDispatchBriefing:
    """Construct a complete, data-grounded ActionableDispatchBriefing without external API calls."""
    proposed_merges: list[dict[str, Any]] = solver["proposed_merges"]
    active_overrides: list[SafetyOverride] = solver["active_overrides"]

    active_maint_vessels = {
        ov.vessel.vessel_id
        for ov in active_overrides
        if ov.is_active and ov.rule_type == "maintenance_hold" and ov.vessel_id
    }

    assessments: list[MergeRiskAssessment] = []
    approve_merges: list[dict[str, Any]] = []
    review_count = 0
    hold_count = 0

    outlier_review_threshold = (
        1.85 if scenario["key"] == "fuel_outlier_check" else 2.00
    )

    for merge in proposed_merges:
        merge_id = merge["merge_id"]
        assigned = merge["assigned_vessel"]
        primary = merge["primary_trip"]
        absorbed = merge["absorbed_trip"]
        combined_util = merge["combined_util_pct"]
        assigned_outlier = top_anomaly_by_vessel.get(assigned.vessel_id)
        has_unheld_severe_outlier = (
            assigned_outlier is not None
            and (assigned_outlier.fuel_ratio or 0.0) >= outlier_review_threshold
            and assigned.vessel_id not in active_maint_vessels
        )

        if merge.get("caution_flag"):
            hold_count += 1
            assessments.append(
                MergeRiskAssessment(
                    group_id=merge_id,
                    verdict="hold",
                    risk_level="high",
                    rationale=(
                        f"Rough sea-state advisory on {merge['route_label']} "
                        f"({primary.trip_id} + {absorbed.trip_id}). Hold automated merge "
                        "and enforce corridor weather clearance before offshore transfer."
                    ),
                )
            )
        elif has_unheld_severe_outlier and assigned_outlier is not None:
            review_count += 1
            assessments.append(
                MergeRiskAssessment(
                    group_id=merge_id,
                    verdict="review",
                    risk_level="medium",
                    rationale=(
                        f"Assigned carrier {assigned.vessel_id} carries an unheld historical "
                        f"fuel-burn flag ({assigned_outlier.trip_id} at "
                        f"{assigned_outlier.fuel_ratio:.2f}x). Confirm engineering clearance "
                        "or assign an alternate vessel before dispatch."
                    ),
                )
            )
        elif merge.get("mode") == "milk_run":
            review_count += 1
            assessments.append(
                MergeRiskAssessment(
                    group_id=merge_id,
                    verdict="review",
                    risk_level="medium",
                    rationale=(
                        f"Multi-platform milk-run ({merge['route_label']}) saves "
                        f"{merge['fuel_saved_l']:.0f} L / +{merge['kwd_saved']:.0f} KWD (mock) "
                        "with +18% detour margin; verify multi-stop deck sequence with platform OIMs."
                    ),
                )
            )
        elif combined_util > 85.0:
            review_count += 1
            assessments.append(
                MergeRiskAssessment(
                    group_id=merge_id,
                    verdict="review",
                    risk_level="medium",
                    rationale=(
                        f"High combined utilization ({combined_util:.0f}% on {assigned.vessel_id}) "
                        "leaves narrow deck/seating margin; confirm final manifest before boarding."
                    ),
                )
            )
        else:
            approve_merges.append(merge)
            assessments.append(
                MergeRiskAssessment(
                    group_id=merge_id,
                    verdict="approve",
                    risk_level="low",
                    rationale=(
                        f"Clean {primary.weather.lower()}-sea corridor merge on "
                        f"{assigned.vessel_id} ({merge['combined_pax']}/{assigned.passenger_capacity} pax, "
                        f"{merge['combined_cargo']:.1f}/{assigned.cargo_capacity_t:.1f} t, "
                        f"{combined_util:.0f}% load) saving {merge['fuel_saved_l']:.0f} L "
                        f"and +{merge['kwd_saved']:.0f} KWD (mock)."
                    ),
                )
            )

    approve_count = len(approve_merges)

    safety_flags: list[str] = []
    for ov in active_overrides[:4]:
        target = (
            ov.vessel.vessel_id
            if ov.vessel is not None
            else (ov.destination or "All Rough-Sea Corridors")
        )
        safety_flags.append(
            f"{target}: {ov.get_rule_type_display()} active ({ov.get_severity_display()}) — enforced in solver."
        )

    rough_pending = [t for t in pending_trips if t.weather == "Rough"]
    if rough_pending:
        rough_dests = sorted({t.destination for t in rough_pending})
        rough_ids = ", ".join(t.trip_id for t in rough_pending[:4])
        safety_flags.append(
            f"Rough sea-state watch on {', '.join(rough_dests)}: "
            f"{len(rough_pending)} pending sailing(s) ({rough_ids}) require marine weather clearance."
        )

    if high_anomalies:
        top = high_anomalies[0]
        safety_flags.append(
            f"Engineering fuel audit: {len(high_anomalies)} high-burn historical sailings "
            f"(>=1.30x), led by {top.trip_id} on {top.vessel.vessel_id} at "
            f"{top.fuel_ratio:.2f}x (+{max(0.0, top.fuel_excess_l or 0.0):.1f} L) — inspect propulsion/hull."
        )

    if missing_logs_count > 0:
        safety_flags.append(
            f"Fuel telemetry hygiene: {missing_logs_count} completed sailings have blank fuel logs "
            "(missing telemetry entries, not zero burn) awaiting logbook reconciliation."
        )

    if not safety_flags:
        safety_flags.append(
            "No active HSE locks, rough-sea pending warnings, or fuel audit flags detected."
        )

    if proposed_merges:
        executive_summary = (
            f"{scenario['title']}: Evaluated {len(proposed_merges)} consolidation pair(s) "
            f"across {solver['pending_count']} pending shift requests with "
            f"{len(active_overrides)} active HSE lock(s). "
            f"Cleared {approve_count} low-risk merge(s) for immediate approval"
            f"{f', flagged {review_count} for supervisor review' if review_count else ''}"
            f"{f', and placed {hold_count} on HSE hold' if hold_count else ''}."
        )
    else:
        executive_summary = (
            f"{scenario['title']}: No additional merge pairs are available across "
            f"{solver['pending_count']} pending request(s) under current HSE guardrails "
            f"({len(active_overrides)} active lock(s)) and departure windows."
        )

    cleared_fuel = round(sum(m["fuel_saved_l"] for m in approve_merges), 1)
    cleared_kwd = round(sum(m["kwd_saved"] for m in approve_merges), 2)
    cleared_co2 = round(sum(m["co2_kg_saved"] for m in approve_merges), 1)
    cleared_mins = sum(m["dispatcher_minutes_saved"] for m in approve_merges)

    if approve_count > 0:
        estimated_impact_note = (
            f"Approving {approve_count} AI-cleared merge(s) eliminates {approve_count} "
            f"offshore run(s), saving {cleared_fuel:,.1f} L diesel, {cleared_kwd:,.0f} KWD (mock), "
            f"{cleared_co2:,.1f} kg CO2, and {cleared_mins} dispatcher mins."
        )
    elif proposed_merges:
        s = solver["summary"]
        estimated_impact_note = (
            f"0 merges auto-cleared; {len(proposed_merges)} proposal(s) require supervisor "
            f"review/hold before realizing up to {s['fuel_liters_saved']:,.1f} L / "
            f"{s['kwd_saved']:,.0f} KWD (mock)."
        )
    else:
        estimated_impact_note = (
            "Shift queue is currently consolidated under active HSE guardrails (0 additional trips to merge)."
        )

    handover_parts: list[str] = []
    if approve_count > 0:
        cleared_ids = ", ".join(m["merge_id"] for m in approve_merges[:4])
        handover_parts.append(f"Proceed with AI-cleared merges ({cleared_ids}).")
    if hold_count > 0:
        handover_parts.append(
            "Keep rough-weather departures held pending updated offshore sea-state forecast."
        )
    if active_overrides:
        lock_targets = ", ".join(
            ov.vessel.vessel_id if ov.vessel else (ov.destination or "Rough Corridors")
            for ov in active_overrides[:3]
        )
        handover_parts.append(f"Maintain active HSE protections on {lock_targets}.")
    if high_anomalies:
        top = high_anomalies[0]
        handover_parts.append(
            f"Schedule engineering fuel-burn check on {top.vessel.vessel_id} ({top.trip_id}, {top.fuel_ratio:.2f}x)."
        )
    if directive.strip():
        clean_focus = textwrap.shorten(directive.strip(), width=200, placeholder="…")
        handover_parts.append(f"Supervisor focus: {clean_focus}")
    shift_handover_note = " ".join(handover_parts) or (
        "All offshore vessels operating within nominal HSE and fuel parameters for next shift handover."
    )

    return ActionableDispatchBriefing(
        executive_summary=executive_summary,
        merge_assessments=assessments,
        safety_flags=safety_flags,
        shift_handover_note=shift_handover_note,
        estimated_impact_note=estimated_impact_note,
    )


def _build_copilot_prompt(
    *,
    scenario: dict[str, Any],
    directive: str,
    strict_weather: bool,
    allow_milk_run: bool,
    solver: dict[str, Any],
    high_anomalies: list[Trip],
    missing_logs_count: int,
) -> str:
    """Build a compact, strictly factual operational prompt for Gemini 4 Interactions API."""
    lines = [
        f"Scenario: {scenario['title']}",
        f"Supervisor Directive: {directive}",
        f"Policy Settings: HSE Strict Weather={'ON' if strict_weather else 'OFF'}, Milk-Run={'ON' if allow_milk_run else 'OFF'}",
        f"Pending Queue: {solver['pending_count']} trips | Proposed Merges: {len(solver['proposed_merges'])} | Held Trips: {len(solver['held_trips'])}",
        "",
        "PROPOSED MERGES (use exact merge_id as group_id):",
    ]
    if solver["proposed_merges"]:
        for m in solver["proposed_merges"]:
            lines.append(
                f"- merge_id={m['merge_id']} | route={m['route_label']} | mode={m['mode']} | "
                f"carrier={m['assigned_vessel'].vessel_id} ({m['assigned_vessel'].vessel_type}) | "
                f"load={m['combined_pax']}/{m['assigned_vessel'].passenger_capacity} pax, "
                f"{m['combined_cargo']:.1f}/{m['assigned_vessel'].cargo_capacity_t:.1f} t ({m['combined_util_pct']:.1f}%) | "
                f"weather={m['primary_trip'].weather}/{m['absorbed_trip'].weather} | "
                f"caution={m['caution_flag'] or 'None'} | "
                f"savings={m['fuel_saved_l']:.1f} L, {m['kwd_saved']:.0f} KWD (mock), {m['co2_kg_saved']:.1f} kg CO2"
            )
    else:
        lines.append("- None (queue already consolidated or held by HSE constraints).")

    lines.append("")
    lines.append("ACTIVE HSE SAFETY OVERRIDES:")
    if solver["active_overrides"]:
        for ov in solver["active_overrides"]:
            target = ov.vessel.vessel_id if ov.vessel else (ov.destination or "All Rough-Sea Corridors")
            lines.append(f"- [{ov.severity.upper()}] {ov.get_rule_type_display()} on {target}: {ov.reason}")
    else:
        lines.append("- None")

    lines.append("")
    lines.append(
        f"TOP ENGINEERING FUEL-BURN OUTLIERS ({len(high_anomalies)} total >=1.30x, {missing_logs_count} missing logs):"
    )
    for t in high_anomalies[:3]:
        lines.append(
            f"- {t.trip_id} ({t.vessel.vessel_id}, {t.destination}, {t.weather}): "
            f"{t.actual_fuel_l:.1f} L actual vs {t.expected_fuel_l:.1f} L expected ({t.fuel_ratio:.2f}x)"
        )
    if not high_anomalies:
        lines.append("- None")

    return "\n".join(lines)


def _compute_cleared_summary(
    assessment_cards: list[dict[str, Any]],
    baseline_trips: int,
) -> dict[str, Any]:
    """Compute quantified Pillar 4 impact strictly across AI-approved merges."""
    cleared = [card["merge"] for card in assessment_cards if card["verdict"] == "approve"]
    eliminated = len(cleared)
    return {
        "baseline_trips": baseline_trips,
        "trips_eliminated": eliminated,
        "optimized_trips": max(0, baseline_trips - eliminated),
        "fuel_liters_saved": round(sum(m["fuel_saved_l"] for m in cleared), 1),
        "kwd_saved": round(sum(m["kwd_saved"] for m in cleared), 2),
        "co2_kg_saved": round(sum(m["co2_kg_saved"] for m in cleared), 1),
        "dispatcher_minutes_saved": sum(m["dispatcher_minutes_saved"] for m in cleared),
    }


def run_copilot_review(
    *,
    scenario_key: str = "standard_handover",
    directive: str = "",
    strict_weather: bool = True,
    allow_milk_run: bool = False,
    invoke_ai: bool = True,
) -> dict[str, Any]:
    """
    Run a full AI Dispatch Co-Pilot risk review grounded in live DB solver, HSE overrides,
    and historical fuel anomalies, with guaranteed deterministic fallback.
    """
    scenario = get_scenario(scenario_key)
    custom_directive = (directive or "").strip()
    effective_directive = custom_directive or scenario["directive"]

    solver = run_shift_optimizer(
        strict_weather=strict_weather,
        allow_milk_run=allow_milk_run,
    )
    pending_trips = _extract_pending_trips_from_solver(solver)
    high_anomalies, missing_logs_count, top_anomaly_by_vessel = _collect_fuel_telemetry()
    recommended_holds = _build_recommended_holds(
        high_anomalies=high_anomalies,
        pending_trips=pending_trips,
        active_overrides=solver["active_overrides"],
    )

    deterministic = build_deterministic_briefing(
        solver=solver,
        scenario=scenario,
        directive=effective_directive,
        high_anomalies=high_anomalies,
        missing_logs_count=missing_logs_count,
        top_anomaly_by_vessel=top_anomaly_by_vessel,
        pending_trips=pending_trips,
    )

    ai_fallback_used = True
    ai_status_note = ""
    chosen_briefing = deterministic

    if invoke_ai:
        prompt = _build_copilot_prompt(
            scenario=scenario,
            directive=effective_directive,
            strict_weather=strict_weather,
            allow_milk_run=allow_milk_run,
            solver=solver,
            high_anomalies=high_anomalies,
            missing_logs_count=missing_logs_count,
        )
        ai_result, ai_error = generate_structured(
            prompt=prompt,
            response_schema=ActionableDispatchBriefing,
            system_instruction=COPILOT_SYSTEM_INSTRUCTION,
            timeout_seconds=18.0,
            thinking_level="medium",
        )
        if ai_result is not None:
            chosen_briefing = ai_result
            ai_fallback_used = False
        else:
            ai_fallback_used = True
            ai_status_note = ai_error or "Deterministic operational fallback active."
    else:
        ai_status_note = (
            "Operational preview loaded — click Run AI Risk Review for live synthesis."
        )

    # Normalize merge_assessments so every live proposed merge has an exact assessment card.
    chosen_by_id = {
        a.group_id.strip(): a for a in chosen_briefing.merge_assessments if a.group_id
    }
    fallback_by_id = {
        a.group_id.strip(): a for a in deterministic.merge_assessments if a.group_id
    }

    assessment_cards: list[dict[str, Any]] = []
    for merge in solver["proposed_merges"]:
        mid = merge["merge_id"]
        matched = chosen_by_id.get(mid) or fallback_by_id.get(mid)
        if matched is None:
            matched = MergeRiskAssessment(
                group_id=mid,
                verdict="review",
                risk_level="medium",
                rationale="Verify capacity and offshore corridor conditions before approving.",
            )
        assessment_cards.append(
            {
                "group_id": mid,
                "verdict": matched.verdict,
                "risk_level": matched.risk_level,
                "rationale": matched.rationale,
                "merge": merge,
            }
        )

    approve_count = sum(1 for c in assessment_cards if c["verdict"] == "approve")
    review_count = sum(1 for c in assessment_cards if c["verdict"] == "review")
    hold_count = sum(1 for c in assessment_cards if c["verdict"] == "hold")
    approved_merge_ids = [
        c["group_id"] for c in assessment_cards if c["verdict"] == "approve"
    ]

    safety_flags = [
        str(flag).strip() for flag in chosen_briefing.safety_flags if str(flag).strip()
    ] or list(deterministic.safety_flags)

    briefing_dict: dict[str, Any] = {
        "executive_summary": (
            chosen_briefing.executive_summary.strip()
            or deterministic.executive_summary
        ),
        "merge_assessments": [
            {
                "group_id": c["group_id"],
                "verdict": c["verdict"],
                "risk_level": c["risk_level"],
                "rationale": c["rationale"],
            }
            for c in assessment_cards
        ],
        "safety_flags": safety_flags,
        "shift_handover_note": (
            chosen_briefing.shift_handover_note.strip()
            or deterministic.shift_handover_note
        ),
        "estimated_impact_note": (
            chosen_briefing.estimated_impact_note.strip()
            or deterministic.estimated_impact_note
        ),
        "scenario_key": scenario["key"],
        "scenario_title": scenario["title"],
        "directive": effective_directive,
        "approve_count": approve_count,
        "review_count": review_count,
        "hold_count": hold_count,
    }

    cleared_summary = _compute_cleared_summary(
        assessment_cards,
        solver["summary"]["baseline_trips"],
    )

    return {
        "scenario": scenario,
        "scenario_key": scenario["key"],
        "directive": custom_directive,
        "effective_directive": effective_directive,
        "strict_weather": strict_weather,
        "allow_milk_run": allow_milk_run,
        "ai_configured": is_ai_configured(),
        "ai_fallback_used": ai_fallback_used,
        "ai_live_used": not ai_fallback_used,
        "ai_status_note": ai_status_note,
        "briefing": briefing_dict,
        "merge_assessments": assessment_cards,
        "approve_count": approve_count,
        "review_count": review_count,
        "hold_count": hold_count,
        "approved_merge_ids": approved_merge_ids,
        "recommended_holds": recommended_holds,
        "solver": solver,
        "summary": solver["summary"],
        "cleared_summary": cleared_summary,
        "pending_count": solver["pending_count"],
        "active_overrides": solver["active_overrides"],
        "active_overrides_count": len(solver["active_overrides"]),
        "high_anomalies_count": len(high_anomalies),
        "missing_logs_count": missing_logs_count,
    }


def save_handover_briefing(
    *,
    briefing_dict: dict[str, Any],
    ai_fallback_used: bool,
    scenario_title: str,
    directive: str,
    strict_weather: bool,
    allow_milk_run: bool,
    solver_summary: dict[str, Any],
) -> tuple[DispatchPlan, str]:
    """Persist an AI shift handover briefing into DispatchPlan (portable ORM)."""
    timestamp = timezone.localtime().strftime("%b %d %H:%M")
    clean_title = (scenario_title or "Shift Handover").strip()
    name = f"AI Brief · {clean_title} ({timestamp})"[:120]

    plan = DispatchPlan.objects.create(
        name=name,
        scope="pending",
        baseline_trips=int(solver_summary.get("baseline_trips", 0)),
        optimized_trips=int(solver_summary.get("optimized_trips", 0)),
        trips_eliminated=int(solver_summary.get("trips_eliminated", 0)),
        fuel_liters_saved=float(solver_summary.get("fuel_liters_saved", 0.0)),
        kwd_saved=float(solver_summary.get("kwd_saved", 0.0)),
        co2_kg_saved=float(solver_summary.get("co2_kg_saved", 0.0)),
        dispatcher_minutes_saved=int(solver_summary.get("dispatcher_minutes_saved", 0)),
        plan_payload={
            "kind": "ai_handover_brief",
            "strict_weather": bool(strict_weather),
            "allow_milk_run": bool(allow_milk_run),
            "directive": (directive or "").strip()[:300],
        },
        ai_briefing=briefing_dict,
        ai_fallback_used=bool(ai_fallback_used),
        is_approved=False,
    )
    return plan, f"Saved shift handover briefing '{plan.name}'."


def approve_ai_cleared_merges(
    *,
    merge_ids: list[str],
    briefing_dict: dict[str, Any],
    ai_fallback_used: bool,
    strict_weather: bool,
    allow_milk_run: bool,
    plan_name: str = "",
) -> tuple[DispatchPlan | None, str]:
    """Approve AI-cleared merges atomically and attach ai_briefing onto the persisted DispatchPlan."""
    cleaned_ids = [mid.strip() for mid in merge_ids if mid and mid.strip()]
    if not cleaned_ids:
        return None, "No AI-cleared merges available to approve under current settings."

    default_name = (
        plan_name.strip()
        or f"AI Cleared Plan · {timezone.localtime().strftime('%b %d %H:%M')}"
    )

    with transaction.atomic():
        plan, message = approve_dispatch_plan(
            selected_merge_ids=cleaned_ids,
            strict_weather=strict_weather,
            allow_milk_run=allow_milk_run,
            plan_name=default_name,
        )
        if plan is None:
            return None, message

        plan.ai_briefing = briefing_dict
        plan.ai_fallback_used = bool(ai_fallback_used)
        plan.save(update_fields=["ai_briefing", "ai_fallback_used", "updated_at"])

    return plan, message


def apply_recommended_hse_hold(
    *,
    rule_type: str,
    vessel_id: str = "",
    destination: str = "",
    source_trip_id: str = "",
    severity: str = "high",
    reason: str = "",
) -> tuple[SafetyOverride | None, bool, str]:
    """Idempotently activate an AI-recommended HSE SafetyOverride rule."""
    clean_rule = (rule_type or "").strip()
    if clean_rule not in {"weather_hold", "maintenance_hold", "standby_lock"}:
        return None, False, "Unsupported HSE hold rule type."

    clean_severity = (
        severity.strip() if (severity or "").strip() in {"advisory", "high", "critical"} else "high"
    )
    clean_reason = (reason or "").strip()[:400]

    if clean_rule == "weather_hold":
        clean_dest = (destination or "").strip()
        if clean_dest not in ("", *DESTINATIONS):
            return None, False, "Invalid destination corridor for weather hold."

        existing = SafetyOverride.objects.filter(
            rule_type="weather_hold",
            destination=clean_dest,
            is_active=True,
        ).first()
        scope_label = clean_dest or "All Rough-Sea Corridors"
        if existing is not None:
            return (
                existing,
                False,
                f"Sea-State / Weather Hold already active on {scope_label}.",
            )

        if not clean_reason:
            clean_reason = (
                f"AI Co-Pilot recommended sea-state weather hold enforced on {scope_label}."
            )

        override = SafetyOverride.objects.create(
            rule_type="weather_hold",
            vessel=None,
            destination=clean_dest,
            severity=clean_severity,
            reason=clean_reason,
            created_by_role="AI Dispatch Co-Pilot (Supervisor Approved)",
            is_active=True,
        )
        return (
            override,
            True,
            f"Activated Sea-State / Weather Hold on {scope_label} — now enforced in Safety & Optimizer.",
        )

    clean_vessel_id = (vessel_id or "").strip()
    vessel = Vessel.objects.filter(vessel_id=clean_vessel_id).first()
    if vessel is None:
        return None, False, f"Vessel '{clean_vessel_id}' not found."

    existing = SafetyOverride.objects.filter(
        rule_type=clean_rule,
        vessel=vessel,
        is_active=True,
    ).first()
    if existing is not None:
        return (
            existing,
            False,
            f"{existing.get_rule_type_display()} already active on {vessel.vessel_id}.",
        )

    source_trip = (
        Trip.objects.filter(trip_id=source_trip_id.strip()).first()
        if (source_trip_id or "").strip()
        else None
    )
    if not clean_reason:
        clean_reason = (
            f"AI Co-Pilot recommended engineering hold on {vessel.vessel_id} "
            "pending mechanical and fuel-burn inspection."
        )

    override = SafetyOverride.objects.create(
        rule_type=clean_rule,
        vessel=vessel,
        destination="",
        source_trip=source_trip,
        severity=clean_severity,
        reason=clean_reason,
        created_by_role="AI Dispatch Co-Pilot (Supervisor Approved)",
        is_active=True,
    )
    return (
        override,
        True,
        f"Activated {override.get_rule_type_display()} on {vessel.vessel_id} — now enforced in Safety & Optimizer.",
    )


def get_saved_briefings() -> list[DispatchPlan]:
    """Return persisted DispatchPlans carrying non-empty ai_briefing (SQLite & Postgres portable)."""
    recent = list(DispatchPlan.objects.order_by("-created_at")[:30])
    return [
        plan
        for plan in recent
        if isinstance(plan.ai_briefing, dict) and bool(plan.ai_briefing)
    ]
