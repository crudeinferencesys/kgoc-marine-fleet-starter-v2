"""Views and HTMX endpoints for Feature 4 (/copilot/ — AI Dispatch Co-Pilot)."""

from __future__ import annotations

import json
from typing import Any

from django.http import HttpRequest, HttpResponse, QueryDict
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core.models import DispatchPlan
from apps.optimizer.copilot_services import (
    COPILOT_SCENARIOS,
    apply_recommended_hse_hold,
    approve_ai_cleared_merges,
    get_saved_briefings,
    get_scenario,
    run_copilot_review,
    save_handover_briefing,
)


def _parse_bool_param(data: QueryDict, key: str, *, default: bool) -> bool:
    """Parse boolean toggle from GET/POST QueryDict supporting hidden+checkbox pairs."""
    values = data.getlist(key)
    if not values:
        return default
    raw = values[-1].strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


def _parse_briefing_json(raw: str) -> dict[str, Any] | None:
    """Safely deserialize an active briefing JSON payload posted from hidden form state."""
    if not raw or not raw.strip():
        return None
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(parsed, dict) or not parsed.get("executive_summary"):
        return None
    return parsed


def _build_copilot_context(
    *,
    scenario_key: str = "standard_handover",
    directive: str = "",
    strict_weather: bool = True,
    allow_milk_run: bool = False,
    invoke_ai: bool = False,
    ai_review_requested: bool = False,
    active_tab: str = "review",
    active_subtab: str = "verdicts",
    notice: str = "",
    notice_tone: str = "",
    review_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble unified context for /copilot/ and its HTMX workspace partial."""
    result = (
        review_result
        if review_result is not None
        else run_copilot_review(
            scenario_key=scenario_key,
            directive=directive,
            strict_weather=strict_weather,
            allow_milk_run=allow_milk_run,
            invoke_ai=invoke_ai,
        )
    )
    saved_briefings = get_saved_briefings()
    briefing = result["briefing"]

    return {
        "active_tab": active_tab if active_tab in ("review", "briefings") else "review",
        "active_subtab": active_subtab if active_subtab in ("verdicts", "safety") else "verdicts",
        "notice": notice,
        "notice_tone": notice_tone,
        "scenarios": COPILOT_SCENARIOS,
        "selected_scenario": result["scenario"],
        "scenario_key": result["scenario_key"],
        "directive": result["directive"],
        "effective_directive": result["effective_directive"],
        "strict_weather": result["strict_weather"],
        "allow_milk_run": result["allow_milk_run"],
        "ai_configured": result["ai_configured"],
        "ai_fallback_used": result["ai_fallback_used"],
        "ai_live_used": result["ai_live_used"],
        "ai_review_requested": ai_review_requested,
        "ai_status_note": result["ai_status_note"],
        "briefing": briefing,
        "briefing_json": json.dumps(briefing),
        "merge_assessments": result["merge_assessments"],
        "approve_count": result["approve_count"],
        "review_count": result["review_count"],
        "hold_count": result["hold_count"],
        "approved_merge_ids": result["approved_merge_ids"],
        "recommended_holds": result["recommended_holds"],
        "safety_flags_and_holds_count": (
            len(briefing["safety_flags"]) + len(result["recommended_holds"])
        ),
        "summary": result["summary"],
        "cleared_summary": result["cleared_summary"],
        "pending_count": result["pending_count"],
        "active_overrides": result["active_overrides"],
        "active_overrides_count": result["active_overrides_count"],
        "high_anomalies_count": result["high_anomalies_count"],
        "missing_logs_count": result["missing_logs_count"],
        "saved_briefings": saved_briefings,
        "saved_briefings_count": len(saved_briefings),
        "approved_plans_count": DispatchPlan.objects.filter(is_approved=True).count(),
    }


def index(request: HttpRequest) -> HttpResponse:
    """Standalone 4th Bonus AI feature landing view (AI Dispatch Co-Pilot)."""
    scenario_key = request.GET.get("scenario", "standard_handover")
    scenario = get_scenario(scenario_key)
    strict_weather = _parse_bool_param(
        request.GET, "strict_weather", default=scenario["strict_weather"]
    )
    allow_milk_run = _parse_bool_param(
        request.GET, "allow_milk_run", default=scenario["allow_milk_run"]
    )
    directive = request.GET.get("directive", "")
    active_tab = request.GET.get("tab", "review")

    context = _build_copilot_context(
        scenario_key=scenario["key"],
        directive=directive,
        strict_weather=strict_weather,
        allow_milk_run=allow_milk_run,
        invoke_ai=False,
        ai_review_requested=False,
        active_tab=active_tab,
    )
    return render(request, "optimizer/copilot.html", context)


@require_POST
def review(request: HttpRequest) -> HttpResponse:
    """HTMX POST endpoint invoking Gemini 4 structured risk review (with deterministic fallback)."""
    scenario_key = request.POST.get("scenario_key", "standard_handover")
    scenario = get_scenario(scenario_key)
    strict_weather = _parse_bool_param(
        request.POST, "strict_weather", default=scenario["strict_weather"]
    )
    allow_milk_run = _parse_bool_param(
        request.POST, "allow_milk_run", default=scenario["allow_milk_run"]
    )
    directive = request.POST.get("directive", "")

    result = run_copilot_review(
        scenario_key=scenario["key"],
        directive=directive,
        strict_weather=strict_weather,
        allow_milk_run=allow_milk_run,
        invoke_ai=True,
    )
    notice = (
        f"Live AI analysis completed for '{scenario['title']}'."
        if result["ai_live_used"]
        else f"Deterministic risk review ready for '{scenario['title']}'."
    )
    context = _build_copilot_context(
        ai_review_requested=True,
        active_tab="review",
        active_subtab="verdicts",
        notice=notice,
        notice_tone="indigo" if result["ai_live_used"] else "amber",
        review_result=result,
    )
    return render(request, "optimizer/partials/copilot_workspace.html", context)


@require_POST
def save_briefing(request: HttpRequest) -> HttpResponse:
    """HTMX POST endpoint persisting the current shift handover briefing to DispatchPlan."""
    scenario_key = request.POST.get("scenario_key", "standard_handover")
    scenario = get_scenario(scenario_key)
    strict_weather = _parse_bool_param(
        request.POST, "strict_weather", default=scenario["strict_weather"]
    )
    allow_milk_run = _parse_bool_param(
        request.POST, "allow_milk_run", default=scenario["allow_milk_run"]
    )
    directive = request.POST.get("directive", "")
    ai_fallback_used = _parse_bool_param(request.POST, "ai_fallback_used", default=True)

    current_review = run_copilot_review(
        scenario_key=scenario["key"],
        directive=directive,
        strict_weather=strict_weather,
        allow_milk_run=allow_milk_run,
        invoke_ai=False,
    )
    posted_briefing = _parse_briefing_json(request.POST.get("briefing_json", ""))
    briefing_to_save = posted_briefing or current_review["briefing"]

    _, notice = save_handover_briefing(
        briefing_dict=briefing_to_save,
        ai_fallback_used=ai_fallback_used,
        scenario_title=briefing_to_save.get("scenario_title") or scenario["title"],
        directive=directive or current_review["effective_directive"],
        strict_weather=strict_weather,
        allow_milk_run=allow_milk_run,
        solver_summary=current_review["cleared_summary"]
        if current_review["approve_count"] > 0
        else current_review["summary"],
    )

    if posted_briefing:
        current_review["briefing"] = posted_briefing
        current_review["ai_fallback_used"] = ai_fallback_used
        current_review["ai_live_used"] = not ai_fallback_used

    context = _build_copilot_context(
        ai_review_requested=not ai_fallback_used,
        active_tab="review",
        active_subtab="verdicts",
        notice=notice,
        notice_tone="emerald",
        review_result=current_review,
    )
    return render(request, "optimizer/partials/copilot_workspace.html", context)


@require_POST
def approve_recommended(request: HttpRequest) -> HttpResponse:
    """HTMX POST endpoint approving AI-cleared merges and attaching ai_briefing to DispatchPlan."""
    scenario_key = request.POST.get("scenario_key", "standard_handover")
    scenario = get_scenario(scenario_key)
    strict_weather = _parse_bool_param(
        request.POST, "strict_weather", default=scenario["strict_weather"]
    )
    allow_milk_run = _parse_bool_param(
        request.POST, "allow_milk_run", default=scenario["allow_milk_run"]
    )
    directive = request.POST.get("directive", "")
    ai_fallback_used = _parse_bool_param(request.POST, "ai_fallback_used", default=True)
    plan_name = request.POST.get("plan_name", "")

    pre_review = run_copilot_review(
        scenario_key=scenario["key"],
        directive=directive,
        strict_weather=strict_weather,
        allow_milk_run=allow_milk_run,
        invoke_ai=False,
    )
    posted_briefing = _parse_briefing_json(request.POST.get("briefing_json", ""))
    briefing_to_save = posted_briefing or pre_review["briefing"]

    merge_ids = request.POST.getlist("merge_ids")
    if not merge_ids:
        merge_ids = pre_review["approved_merge_ids"]

    plan, notice = approve_ai_cleared_merges(
        merge_ids=merge_ids,
        briefing_dict=briefing_to_save,
        ai_fallback_used=ai_fallback_used,
        strict_weather=strict_weather,
        allow_milk_run=allow_milk_run,
        plan_name=plan_name,
    )

    context = _build_copilot_context(
        scenario_key=scenario["key"],
        directive=directive,
        strict_weather=strict_weather,
        allow_milk_run=allow_milk_run,
        invoke_ai=False,
        active_tab="review",
        active_subtab="verdicts",
        notice=notice,
        notice_tone="emerald" if plan is not None else "amber",
    )
    return render(request, "optimizer/partials/copilot_workspace.html", context)


@require_POST
def apply_hold(request: HttpRequest) -> HttpResponse:
    """HTMX POST endpoint idempotently activating an AI-recommended HSE SafetyOverride."""
    scenario_key = request.POST.get("scenario_key", "standard_handover")
    scenario = get_scenario(scenario_key)
    strict_weather = _parse_bool_param(
        request.POST, "strict_weather", default=scenario["strict_weather"]
    )
    allow_milk_run = _parse_bool_param(
        request.POST, "allow_milk_run", default=scenario["allow_milk_run"]
    )
    directive = request.POST.get("directive", "")

    override, created, notice = apply_recommended_hse_hold(
        rule_type=request.POST.get("rule_type", ""),
        vessel_id=request.POST.get("vessel_id", ""),
        destination=request.POST.get("destination", ""),
        source_trip_id=request.POST.get("source_trip_id", ""),
        severity=request.POST.get("severity", "high"),
        reason=request.POST.get("reason", ""),
    )

    context = _build_copilot_context(
        scenario_key=scenario["key"],
        directive=directive,
        strict_weather=strict_weather,
        allow_milk_run=allow_milk_run,
        invoke_ai=False,
        active_tab="review",
        active_subtab="safety",
        notice=notice,
        notice_tone="emerald" if (override is not None and created) else "amber",
    )
    return render(request, "optimizer/partials/copilot_workspace.html", context)


@require_POST
def ping(request: HttpRequest) -> HttpResponse:
    """HTMX CSRF smoke endpoint for the standalone Co-Pilot route."""
    return render(
        request,
        "optimizer/partials/status_card.html",
        {"checked_at": timezone.localtime().strftime("%H:%M:%S")},
    )
