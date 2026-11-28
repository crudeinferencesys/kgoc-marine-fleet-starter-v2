from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core.ai import is_ai_configured
from apps.core.models import DispatchPlan, SafetyOverride, Trip


def index(request: HttpRequest) -> HttpResponse:
    """Standalone 4th Bonus AI feature landing view (AI Dispatch Co-Pilot)."""
    context = {
        "ai_configured": is_ai_configured(),
        "gemini_model": settings.GEMINI_MODEL,
        "pending_count": Trip.objects.filter(status="pending").count(),
        "active_overrides_count": SafetyOverride.objects.filter(is_active=True).count(),
        "approved_plans_count": DispatchPlan.objects.filter(is_approved=True).count(),
    }
    return render(request, "optimizer/copilot.html", context)


@require_POST
def ping(request: HttpRequest) -> HttpResponse:
    """HTMX CSRF smoke endpoint for the standalone Co-Pilot route."""
    return render(
        request,
        "optimizer/partials/status_card.html",
        {"checked_at": timezone.localtime().strftime("%H:%M:%S")},
    )
