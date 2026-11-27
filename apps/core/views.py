from django.conf import settings
from django.db import connection
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render

from .ai import is_ai_configured


def _database_engine_label() -> str:
    engine = settings.DATABASES["default"]["ENGINE"]
    if "postgresql" in engine:
        return "postgresql"
    if "sqlite3" in engine:
        return "sqlite3"
    return engine.rsplit(".", 1)[-1]


def home(request: HttpRequest) -> HttpResponse:
    """Render the system readiness overview and feature slice hub."""
    context = {
        "db_engine": _database_engine_label(),
        "ai_configured": is_ai_configured(),
        "gemini_model": settings.GEMINI_MODEL,
        "debug_mode": settings.DEBUG,
        "slices": [
            {
                "name": "1. Trips & Utilization",
                "owner": "Teammate A",
                "url_name": "trips:index",
                "path": "apps/trips/",
                "summary": "Ingest fleet trips, log new trip requests to DB, and flag half-empty runs.",
            },
            {
                "name": "2. Dispatch Optimizer",
                "owner": "Teammate B",
                "url_name": "optimizer:index",
                "path": "apps/optimizer/",
                "summary": "Python consolidation solver + KWD/fuel savings + AI Dispatch Co-Pilot.",
            },
            {
                "name": "3. Safety & Fuel",
                "owner": "Shared / Coordinate",
                "url_name": "safety:index",
                "path": "apps/safety/",
                "summary": "Fuel-burn anomaly detection + weather/standby constraint overrides.",
            },
        ],
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
