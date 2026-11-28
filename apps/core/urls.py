from django.urls import include, path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.home, name="home"),
    path("export/fleet-summary.csv", views.export_fleet_summary_csv, name="export_fleet_csv"),
    path("copilot/", include("apps.optimizer.copilot_urls")),
    path("health/", views.healthz, name="health"),
    path("healthz", views.healthz, name="healthz"),
]
