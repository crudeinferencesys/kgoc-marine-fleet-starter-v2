import csv

from django.conf import settings
from django.db import connection
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

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


@require_GET
def export_fleet_summary_csv(request: HttpRequest) -> HttpResponse:
    """Export per-vessel 90-day utilization and trip counts as CSV for deep-dive analysis."""
    metrics = get_control_tower_metrics()
    chart = metrics.get("vessel_chart_data", {})
    labels = chart.get("labels", [])
    avg_utils = chart.get("avg_util", [])
    half_empties = chart.get("half_empty_pct", [])
    trip_counts = chart.get("trip_counts", [])

    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="kgoc_fleet_summary.csv"'

    writer = csv.writer(response)
    writer.writerow(
        ["Vessel ID", "Avg Utilization (%)", "Half-Empty Rate (%)", "Completed Trips"]
    )
    for idx, vessel_id in enumerate(labels):
        safe_id = (
            f"'{vessel_id}"
            if isinstance(vessel_id, str) and vessel_id[:1] in ("=", "+", "-", "@", "\t", "\r")
            else vessel_id
        )
        avg_val = avg_utils[idx] if idx < len(avg_utils) else 0.0
        half_val = half_empties[idx] if idx < len(half_empties) else 0.0
        count_val = trip_counts[idx] if idx < len(trip_counts) else 0
        writer.writerow([safe_id, f"{avg_val:.1f}", f"{half_val:.1f}", count_val])

    return response
