from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.home, name="home"),
    path("health/", views.healthz, name="health"),
    path("healthz", views.healthz, name="healthz"),
]
