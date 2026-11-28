from django.urls import path

from . import copilot_views

app_name = "copilot"

urlpatterns = [
    path("", copilot_views.index, name="index"),
    path("review/", copilot_views.review, name="review"),
    path("save-briefing/", copilot_views.save_briefing, name="save_briefing"),
    path(
        "approve-recommended/",
        copilot_views.approve_recommended,
        name="approve_recommended",
    ),
    path("apply-hold/", copilot_views.apply_hold, name="apply_hold"),
    path("ping/", copilot_views.ping, name="ping"),
]
