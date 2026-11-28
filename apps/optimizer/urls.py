from django.urls import path

from . import views

app_name = "optimizer"

urlpatterns = [
    path("", views.index, name="index"),
    path("solve/", views.solve, name="solve"),
    path("approve/", views.approve, name="approve"),
    path("plans/<int:plan_id>/revert/", views.revert_plan, name="revert_plan"),
    path("ping/", views.ping, name="ping"),
]
