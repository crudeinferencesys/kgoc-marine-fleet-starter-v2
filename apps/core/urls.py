from django.urls import include, path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.home, name="home"),
    path("copilot/", include("apps.optimizer.copilot_urls")),
    path("health/", views.healthz, name="health"),
    path("healthz", views.healthz, name="healthz"),
]
