from django.contrib import admin

from .models import DispatchPlan, SafetyOverride, Trip, Vessel, VesselAvailability


@admin.register(Vessel)
class VesselAdmin(admin.ModelAdmin):
    list_display = (
        "vessel_id",
        "vessel_type",
        "passenger_capacity",
        "cargo_capacity_t",
        "underway_rate_lph",
        "idle_rate_lph",
        "is_standby_designated",
        "status",
    )
    list_filter = ("vessel_type", "is_standby_designated", "status")


@admin.register(VesselAvailability)
class VesselAvailabilityAdmin(admin.ModelAdmin):
    list_display = (
        "vessel",
        "date",
        "availability_status",
        "maintenance_hours",
        "weather_restricted_hours",
    )
    list_filter = ("availability_status", "vessel")


@admin.register(Trip)
class TripAdmin(admin.ModelAdmin):
    list_display = (
        "trip_id",
        "vessel",
        "destination",
        "departure_dt",
        "passengers",
        "cargo_tonnes",
        "weather",
        "priority",
        "status",
    )
    list_filter = ("status", "destination", "weather", "priority", "flexible_window")
    search_fields = ("trip_id", "request_id", "destination")


@admin.register(DispatchPlan)
class DispatchPlanAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "scope",
        "trips_eliminated",
        "fuel_liters_saved",
        "kwd_saved",
        "ai_fallback_used",
        "is_approved",
        "created_at",
    )
    list_filter = ("scope", "is_approved", "ai_fallback_used")


@admin.register(SafetyOverride)
class SafetyOverrideAdmin(admin.ModelAdmin):
    list_display = (
        "rule_type",
        "vessel",
        "destination",
        "severity",
        "is_active",
        "created_at",
    )
    list_filter = ("rule_type", "severity", "is_active")
