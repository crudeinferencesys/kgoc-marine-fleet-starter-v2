"""Feature 2 views for the Gulf OSV Dispatch Consolidation Optimizer."""

from __future__ import annotations

from django.http import HttpRequest, HttpResponse, QueryDict
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .services import approve_dispatch_plan, revert_dispatch_plan, run_shift_optimizer


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


def _build_workspace_context(
    *,
    strict_weather: bool,
    allow_milk_run: bool,
    active_tab: str = "solver",
    notice: str = "",
    notice_tone: str = "",
) -> dict:
    result = run_shift_optimizer(
        strict_weather=strict_weather,
        allow_milk_run=allow_milk_run,
    )
    saved_plans = result["saved_plans"]
    return {
        "strict_weather": strict_weather,
        "allow_milk_run": allow_milk_run,
        "active_tab": active_tab,
        "notice": notice,
        "notice_tone": notice_tone,
        "pending_count": result["pending_count"],
        "eligible_vessels": result["eligible_vessels"],
        "active_overrides": result["active_overrides"],
        "active_overrides_count": len(result["active_overrides"]),
        "proposed_merges": result["proposed_merges"],
        "held_trips": result["held_trips"],
        "summary": result["summary"],
        "saved_plans": saved_plans,
        "saved_plans_count": len(saved_plans),
        "approved_plans_count": sum(1 for p in saved_plans if p.is_approved),
        "backtest": result["backtest"],
    }


def index(request: HttpRequest) -> HttpResponse:
    """Feature 2 slice landing page (Gulf OSV Dispatch Consolidation Optimizer)."""
    strict_weather = _parse_bool_param(request.GET, "strict_weather", default=True)
    allow_milk_run = _parse_bool_param(request.GET, "allow_milk_run", default=False)
    tab = request.GET.get("tab", "solver")
    active_tab = tab if tab in ("solver", "plans") else "solver"
    context = _build_workspace_context(
        strict_weather=strict_weather,
        allow_milk_run=allow_milk_run,
        active_tab=active_tab,
    )
    return render(request, "optimizer/index.html", context)


@require_POST
def solve(request: HttpRequest) -> HttpResponse:
    """HTMX partial endpoint to recompute shift consolidation proposals."""
    strict_weather = _parse_bool_param(request.POST, "strict_weather", default=True)
    allow_milk_run = _parse_bool_param(request.POST, "allow_milk_run", default=False)
    context = _build_workspace_context(
        strict_weather=strict_weather,
        allow_milk_run=allow_milk_run,
        active_tab="solver",
    )
    return render(request, "optimizer/partials/workspace.html", context)


@require_POST
def approve(request: HttpRequest) -> HttpResponse:
    """HTMX partial endpoint to approve selected merges and persist a DispatchPlan."""
    strict_weather = _parse_bool_param(request.POST, "strict_weather", default=True)
    allow_milk_run = _parse_bool_param(request.POST, "allow_milk_run", default=False)
    selected_merge_ids = request.POST.getlist("merge_ids")
    plan_name = request.POST.get("plan_name", "")

    plan, message = approve_dispatch_plan(
        selected_merge_ids=selected_merge_ids,
        strict_weather=strict_weather,
        allow_milk_run=allow_milk_run,
        plan_name=plan_name,
    )
    context = _build_workspace_context(
        strict_weather=strict_weather,
        allow_milk_run=allow_milk_run,
        active_tab="solver",
        notice=message,
        notice_tone="emerald" if plan is not None else "amber",
    )
    return render(request, "optimizer/partials/workspace.html", context)


@require_POST
def revert_plan(request: HttpRequest, plan_id: int) -> HttpResponse:
    """HTMX partial endpoint to revert an approved DispatchPlan and restore trips."""
    strict_weather = _parse_bool_param(request.POST, "strict_weather", default=True)
    allow_milk_run = _parse_bool_param(request.POST, "allow_milk_run", default=False)

    plan, message = revert_dispatch_plan(plan_id)
    context = _build_workspace_context(
        strict_weather=strict_weather,
        allow_milk_run=allow_milk_run,
        active_tab="plans",
        notice=message,
        notice_tone="emerald" if (plan is not None and not plan.is_approved) else "amber",
    )
    return render(request, "optimizer/partials/workspace.html", context)


@require_POST
def ping(request: HttpRequest) -> HttpResponse:
    """HTMX CSRF smoke endpoint confirming slice partial updates work."""
    return render(
        request,
        "optimizer/partials/status_card.html",
        {"checked_at": timezone.localtime().strftime("%H:%M:%S")},
    )
