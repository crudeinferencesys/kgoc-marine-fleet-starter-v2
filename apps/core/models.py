"""
FROZEN SHARED SCHEMA FILE — Theme 4: Marine Fleet Utilization & Optimization.

Aligned with KJO_Marine_Fleet_Hackathon_Participant_Dataset.xlsx (Vessels,
Availability, Trips, Requests) plus DispatchPlan and SafetyOverride state.
Uses strictly portable Django ORM fields for SQLite / Cloud SQL PostgreSQL parity.
"""

from __future__ import annotations

from django.db import models

from .constants import (
    DESTINATIONS,
    FUEL_HIGH_ANOMALY_RATIO,
    FUEL_LOW_ANOMALY_RATIO,
    HALF_EMPTY_THRESHOLD_PCT,
    MISSION_TYPES,
    PRIORITIES,
    VESSEL_TYPES,
    WEATHER_STATES,
)


def _choices(values: tuple[str, ...]) -> list[tuple[str, str]]:
    return [(item, item) for item in values]


class TimestampedModel(models.Model):
    """Abstract base class providing creation and update timestamps."""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Vessel(TimestampedModel):
    """Offshore marine vessel specification and reference fuel/operating rates."""

    vessel_id = models.CharField(max_length=20, unique=True)
    vessel_type = models.CharField(max_length=40, choices=_choices(VESSEL_TYPES))
    passenger_capacity = models.PositiveIntegerField()
    cargo_capacity_t = models.FloatField()
    underway_rate_lph = models.FloatField()
    idle_rate_lph = models.FloatField()
    cruise_speed_kn = models.FloatField()
    shift_hours_per_day = models.FloatField(default=12.0)
    hourly_operating_kwd = models.FloatField(default=45.0)
    is_standby_designated = models.BooleanField(default=False)
    status = models.CharField(max_length=30, default="In Service")

    class Meta:
        ordering = ["vessel_id"]

    def __str__(self) -> str:
        return f"{self.vessel_id} ({self.vessel_type})"


class VesselAvailability(TimestampedModel):
    """Daily vessel availability, maintenance, and weather restriction log."""

    STATUS_CHOICES = [
        ("Available", "Available"),
        ("Weather Restricted", "Weather Restricted"),
        ("Maintenance", "Maintenance"),
    ]

    vessel = models.ForeignKey(Vessel, on_delete=models.CASCADE, related_name="availabilities")
    date = models.DateField(db_index=True)
    scheduled_shift_hours = models.FloatField(default=12.0)
    maintenance_hours = models.FloatField(default=0.0)
    weather_restricted_hours = models.FloatField(default=0.0)
    availability_status = models.CharField(
        max_length=30,
        choices=STATUS_CHOICES,
        default="Available",
    )

    class Meta:
        unique_together = [("vessel", "date")]
        ordering = ["-date", "vessel__vessel_id"]

    def __str__(self) -> str:
        return f"{self.vessel.vessel_id} · {self.date} · {self.availability_status}"


class DispatchPlan(TimestampedModel):
    """Persisted consolidation optimization run and Gemini AI handover briefing."""

    SCOPE_CHOICES = [
        ("pending", "Pending Shift"),
        ("backtest", "90-Day Backtest"),
    ]

    name = models.CharField(max_length=120)
    scope = models.CharField(max_length=20, choices=SCOPE_CHOICES, default="pending")
    baseline_trips = models.PositiveIntegerField(default=0)
    optimized_trips = models.PositiveIntegerField(default=0)
    trips_eliminated = models.PositiveIntegerField(default=0)
    fuel_liters_saved = models.FloatField(default=0.0)
    kwd_saved = models.FloatField(default=0.0)
    co2_kg_saved = models.FloatField(default=0.0)
    dispatcher_minutes_saved = models.PositiveIntegerField(default=0)
    plan_payload = models.JSONField(default=dict, blank=True)
    ai_briefing = models.JSONField(default=dict, blank=True)
    ai_fallback_used = models.BooleanField(default=False)
    is_approved = models.BooleanField(default=True)
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.name} (-{self.trips_eliminated} trips, {self.kwd_saved:.0f} KWD)"


class Trip(TimestampedModel):
    """Unified trip & booking request record (historical KJO trips + live pending queue)."""

    STATUS_CHOICES = [
        ("completed", "Completed"),
        ("pending", "Pending"),
        ("consolidated", "Consolidated"),
        ("cancelled", "Cancelled"),
    ]

    trip_id = models.CharField(max_length=32, unique=True)
    request_id = models.CharField(max_length=32, blank=True, default="")
    vessel = models.ForeignKey(Vessel, on_delete=models.PROTECT, related_name="trips")
    trip_date = models.DateField(db_index=True)
    mission_type = models.CharField(max_length=40, choices=_choices(MISSION_TYPES))
    origin = models.CharField(max_length=80, default="Marine Base")
    destination = models.CharField(max_length=80, choices=_choices(DESTINATIONS), db_index=True)
    submitted_dt = models.DateTimeField(null=True, blank=True)
    earliest_departure_dt = models.DateTimeField(null=True, blank=True)
    latest_departure_dt = models.DateTimeField(null=True, blank=True)
    departure_dt = models.DateTimeField(db_index=True)
    return_dt = models.DateTimeField(null=True, blank=True)
    underway_hours = models.FloatField(default=2.2)
    onsite_work_hours = models.FloatField(default=0.35)
    nonproductive_idle_hours = models.FloatField(default=0.5)
    distance_nm = models.FloatField(default=34.0)
    passengers = models.PositiveIntegerField(default=0)
    cargo_tonnes = models.FloatField(default=0.0)
    weather = models.CharField(max_length=20, choices=_choices(WEATHER_STATES), default="Calm")
    priority = models.CharField(max_length=20, choices=_choices(PRIORITIES), default="Routine")
    flexible_window = models.BooleanField(default=True)
    actual_fuel_l = models.FloatField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="completed", db_index=True)
    dispatch_plan = models.ForeignKey(
        DispatchPlan,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="trips",
    )
    consolidated_into = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="merged_from_trips",
    )
    is_synthetic_queue = models.BooleanField(default=False)
    notes = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-departure_dt", "-trip_id"]

    def __str__(self) -> str:
        return f"{self.trip_id} · {self.vessel.vessel_id} -> {self.destination}"

    @property
    def pax_utilization_pct(self) -> float:
        if self.vessel.passenger_capacity <= 0:
            return 0.0
        return round((self.passengers / self.vessel.passenger_capacity) * 100.0, 1)

    @property
    def cargo_utilization_pct(self) -> float:
        if self.vessel.cargo_capacity_t <= 0:
            return 0.0
        return round((self.cargo_tonnes / self.vessel.cargo_capacity_t) * 100.0, 1)

    @property
    def utilization_pct(self) -> float:
        return max(self.pax_utilization_pct, self.cargo_utilization_pct)

    @property
    def is_half_empty(self) -> bool:
        return self.utilization_pct < HALF_EMPTY_THRESHOLD_PCT

    @property
    def expected_fuel_l(self) -> float:
        underway_fuel = self.underway_hours * self.vessel.underway_rate_lph
        idle_fuel = (self.onsite_work_hours + self.nonproductive_idle_hours) * self.vessel.idle_rate_lph
        return round(underway_fuel + idle_fuel, 1)

    @property
    def fuel_ratio(self) -> float | None:
        if self.actual_fuel_l is None or self.expected_fuel_l <= 0:
            return None
        return round(self.actual_fuel_l / self.expected_fuel_l, 2)

    @property
    def fuel_excess_l(self) -> float | None:
        if self.actual_fuel_l is None:
            return None
        return round(self.actual_fuel_l - self.expected_fuel_l, 1)

    @property
    def idle_fuel_l(self) -> float:
        return round(self.nonproductive_idle_hours * self.vessel.idle_rate_lph, 1)

    @property
    def fuel_anomaly_status(self) -> str:
        ratio = self.fuel_ratio
        if ratio is None:
            return "missing"
        if ratio >= FUEL_HIGH_ANOMALY_RATIO:
            return "high"
        if ratio <= FUEL_LOW_ANOMALY_RATIO:
            return "low"
        return "normal"


class SafetyOverride(TimestampedModel):
    """Persisted offshore HSE rule (weather hold, maintenance hold, standby lock)."""

    RULE_TYPE_CHOICES = [
        ("weather_hold", "Sea-State / Weather Hold"),
        ("maintenance_hold", "Vessel Maintenance Hold"),
        ("standby_lock", "Standby Vessel Protection Lock"),
    ]
    SEVERITY_CHOICES = [
        ("advisory", "Advisory"),
        ("high", "High"),
        ("critical", "Critical"),
    ]

    rule_type = models.CharField(max_length=30, choices=RULE_TYPE_CHOICES, db_index=True)
    vessel = models.ForeignKey(
        Vessel,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="safety_overrides",
    )
    destination = models.CharField(max_length=80, blank=True, default="")
    source_trip = models.ForeignKey(
        Trip,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="safety_overrides",
    )
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES, default="high")
    reason = models.TextField()
    created_by_role = models.CharField(max_length=80, default="Marine Operations Supervisor")
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering = ["-is_active", "-created_at"]

    def __str__(self) -> str:
        target = self.vessel.vessel_id if self.vessel else (self.destination or "Fleet")
        state = "ACTIVE" if self.is_active else "Cleared"
        return f"[{state}] {self.get_rule_type_display()} · {target}"
