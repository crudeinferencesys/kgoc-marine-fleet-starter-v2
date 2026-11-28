from django.urls import path

from . import views

app_name = "safety"

urlpatterns = [
    path("", views.index, name="index"),
    path("anomalies/", views.anomalies_partial, name="anomalies"),
    path("anomalies/<str:trip_id>/hold/", views.quick_maintenance_hold, name="quick_hold"),
    path("inspect/<str:trip_id>/", views.anomaly_inspector, name="inspect"),
    path("holds/", views.holds_partial, name="holds"),
    path("holds/create/", views.create_hold, name="create_hold"),
    path("holds/<int:pk>/toggle/", views.toggle_hold, name="toggle_hold"),
    path("export/", views.export_anomalies_csv, name="export_csv"),
    path("ping/", views.ping, name="ping"),
]
