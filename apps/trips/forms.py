"""Forms and booking validation for Feature 1 (Trips & Utilization)."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django import forms
from django.utils import timezone

from apps.core.constants import DESTINATIONS, MISSION_TYPES, PRIORITIES, WEATHER_STATES
from apps.core.models import Trip, Vessel
from apps.trips.services import DESTINATION_DISTANCES_NM, generate_live_trip_ids

KUWAIT_TZ = ZoneInfo("Asia/Kuwait")
SHIFT_QUEUE_DATE = date(2026, 11, 28)

_SELECT_CLS = "select select-bordered select-sm w-full bg-white text-slate-900 field-control"
_INPUT_CLS = "input input-bordered input-sm w-full bg-white text-slate-900 font-mono tabular-nums field-control"


class TripBookingForm(forms.Form):
    """Form to submit a live pending shift trip request with capacity & overload checks."""

    vessel = forms.ModelChoiceField(
        queryset=Vessel.objects.all(),
        empty_label=None,
        widget=forms.Select(attrs={"class": _SELECT_CLS}),
    )
    destination = forms.ChoiceField(
        choices=[(item, item) for item in DESTINATIONS],
        widget=forms.Select(attrs={"class": _SELECT_CLS}),
    )
    mission_type = forms.ChoiceField(
        choices=[(item, item) for item in MISSION_TYPES],
        widget=forms.Select(attrs={"class": _SELECT_CLS}),
    )
    departure_time = forms.TimeField(
        initial=time(8, 30),
        widget=forms.TimeInput(format="%H:%M", attrs={"type": "time", "class": _INPUT_CLS}),
    )
    passengers = forms.IntegerField(
        min_value=0,
        initial=5,
        widget=forms.NumberInput(attrs={"min": 0, "step": 1, "class": _INPUT_CLS}),
    )
    cargo_tonnes = forms.FloatField(
        min_value=0.0,
        initial=0.1,
        widget=forms.NumberInput(attrs={"min": 0, "step": "0.1", "class": _INPUT_CLS}),
    )
    weather = forms.ChoiceField(
        choices=[(item, item) for item in WEATHER_STATES],
        initial="Calm",
        widget=forms.Select(attrs={"class": _SELECT_CLS}),
    )
    priority = forms.ChoiceField(
        choices=[(item, item) for item in PRIORITIES],
        initial="Routine",
        widget=forms.Select(attrs={"class": _SELECT_CLS}),
    )
    flexible_window = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={"class": "checkbox checkbox-primary checkbox-sm"}),
    )
    notes = forms.CharField(
        required=False,
        max_length=240,
        widget=forms.TextInput(
            attrs={
                "placeholder": "Optional shift transfer or deck manifest note",
                "class": "input input-bordered input-sm w-full bg-white text-slate-900 field-control",
            }
        ),
    )

    def clean(self):
        cleaned_data = super().clean()
        vessel: Vessel | None = cleaned_data.get("vessel")
        passengers: int | None = cleaned_data.get("passengers")
        cargo_tonnes: float | None = cleaned_data.get("cargo_tonnes")

        if vessel is None or passengers is None or cargo_tonnes is None:
            return cleaned_data

        if passengers <= 0 and cargo_tonnes <= 0:
            raise forms.ValidationError(
                "Enter at least 1 passenger or cargo weight above 0.0 t."
            )

        pax_over = passengers > vessel.passenger_capacity
        cargo_over = cargo_tonnes > vessel.cargo_capacity_t
        if pax_over or cargo_over:
            capable = list(
                Vessel.objects.filter(
                    passenger_capacity__gte=passengers,
                    cargo_capacity_t__gte=cargo_tonnes,
                ).order_by("vessel_id")[:2]
            )
            if cargo_over and not pax_over:
                limit_msg = f"{vessel.vessel_id} max cargo is {vessel.cargo_capacity_t:.1f} t"
                suggestion_text = " or ".join(
                    f"{v.vessel_id} ({v.cargo_capacity_t:.1f} t)" for v in capable
                )
            elif pax_over and not cargo_over:
                limit_msg = f"{vessel.vessel_id} max passengers is {vessel.passenger_capacity} pax"
                suggestion_text = " or ".join(
                    f"{v.vessel_id} ({v.passenger_capacity} pax)" for v in capable
                )
            else:
                limit_msg = (
                    f"{vessel.vessel_id} max capacity is "
                    f"{vessel.passenger_capacity} pax / {vessel.cargo_capacity_t:.1f} t"
                )
                suggestion_text = " or ".join(
                    f"{v.vessel_id} ({v.passenger_capacity} pax, {v.cargo_capacity_t:.1f} t)"
                    for v in capable
                )

            if suggestion_text:
                raise forms.ValidationError(f"{limit_msg} — try {suggestion_text}.")
            raise forms.ValidationError(
                f"{limit_msg} — no single fleet vessel fits {passengers} pax and {cargo_tonnes:.1f} t."
            )

        return cleaned_data

    def save_pending_trip(self) -> Trip:
        """Persist the validated booking as a pending shift Trip in Asia/Kuwait timezone."""
        vessel: Vessel = self.cleaned_data["vessel"]
        destination: str = self.cleaned_data["destination"]
        dep_time: time = self.cleaned_data["departure_time"]
        flexible = bool(self.cleaned_data.get("flexible_window"))

        trip_id, request_id = generate_live_trip_ids()
        departure_dt = timezone.make_aware(
            datetime.combine(SHIFT_QUEUE_DATE, dep_time), KUWAIT_TZ
        )
        earliest_departure_dt = departure_dt - timedelta(minutes=30 if flexible else 0)
        latest_departure_dt = departure_dt + timedelta(minutes=60 if flexible else 15)

        distance_nm = DESTINATION_DISTANCES_NM.get(destination, 36.0)
        underway_hours = round(distance_nm / vessel.cruise_speed_kn, 2)
        onsite_work_hours = 0.35
        nonproductive_idle_hours = 0.3
        return_dt = departure_dt + timedelta(
            hours=underway_hours + onsite_work_hours + nonproductive_idle_hours
        )

        return Trip.objects.create(
            trip_id=trip_id,
            request_id=request_id,
            vessel=vessel,
            trip_date=SHIFT_QUEUE_DATE,
            mission_type=self.cleaned_data["mission_type"],
            origin="Marine Base",
            destination=destination,
            submitted_dt=timezone.now(),
            earliest_departure_dt=earliest_departure_dt,
            latest_departure_dt=latest_departure_dt,
            departure_dt=departure_dt,
            return_dt=return_dt,
            underway_hours=underway_hours,
            onsite_work_hours=onsite_work_hours,
            nonproductive_idle_hours=nonproductive_idle_hours,
            distance_nm=distance_nm,
            passengers=self.cleaned_data["passengers"],
            cargo_tonnes=round(float(self.cleaned_data["cargo_tonnes"]), 2),
            weather=self.cleaned_data["weather"],
            priority=self.cleaned_data["priority"],
            flexible_window=flexible,
            actual_fuel_l=None,
            status="pending",
            is_synthetic_queue=True,
            notes=(self.cleaned_data.get("notes") or "").strip(),
        )
