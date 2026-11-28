from django.urls import path

from . import copilot_views

app_name = "copilot"

urlpatterns = [
    path("", copilot_views.index, name="index"),
    path("ping/", copilot_views.ping, name="ping"),
]
