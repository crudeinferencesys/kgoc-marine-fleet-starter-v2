from django.conf import settings
from django.db import connection
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render

from .ai import is_ai_configured
from .services import get_control_tower_metrics


def _database_engine_label() -> str:
    engine = settings.DATABASES["default"]["ENGINE"]
    if "postgresql" in engine:
        return "postgresql"
    if "sqlite3" in engine:
        return "sqlite3"
    return engine.rsplit(".", 1)[-1]


def home(request: HttpRequest) -> HttpResponse:
    """Render the Executive Control Tower with live fleet KPIs and slice launch cards."""
    context = {
        "metrics": get_control_tower_metrics(),
        "db_engine": _database_engine_label(),
        "ai_configured": is_ai_configured(),
        "gemini_model": settings.GEMINI_MODEL,
    }
    return render(request, "core/home.html", context)


def healthz(request: HttpRequest) -> JsonResponse:
    """Verify database connectivity for Cloud Run health checks and smoke tests."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception as exc:
        return JsonResponse(
            {
                "status": "error",
                "database": _database_engine_label(),
                "detail": exc.__class__.__name__,
            },
            status=503,
        )

    return JsonResponse(
        {
            "status": "ok",
            "database": _database_engine_label(),
            "ai_configured": is_ai_configured(),
            "gemini_model": settings.GEMINI_MODEL,
        },
        status=200,
    )
