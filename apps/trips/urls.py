from django.urls import path

from . import views

app_name = "trips"

urlpatterns = [
    path("", views.index, name="index"),
    path("create/", views.create_trip, name="create"),
    path("ledger/", views.ledger_partial, name="ledger"),
    path("<str:trip_id>/inspect/", views.trip_inspector, name="inspect"),
    path("<str:trip_id>/cancel/", views.cancel_trip, name="cancel"),
    path("ping/", views.ping, name="ping"),
]
