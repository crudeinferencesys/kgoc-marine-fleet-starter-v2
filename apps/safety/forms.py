"""Forms and HSE validation rules for Feature 3 (Safety & Fuel Anomaly Guard)."""

from __future__ import annotations

from django import forms

from apps.core.constants import DESTINATIONS
from apps.core.models import SafetyOverride, Vessel

_SELECT_CLS = (
    "select select-bordered select-sm w-full bg-white text-slate-900 field-control"
)
_INPUT_CLS = (
    "input input-bordered input-sm w-full bg-white text-slate-900 field-control"
)
_TEXTAREA_CLS = (
    "textarea textarea-bordered textarea-sm w-full bg-white text-slate-900 field-control"
)

DESTINATION_HOLD_CHOICES: list[tuple[str, str]] = [
    ("", "All Rough-Sea Corridors"),
    *[(dest, dest) for dest in DESTINATIONS],
]


class SafetyOverrideForm(forms.Form):
    """Form to create and persist an offshore HSE SafetyOverride rule."""

    rule_type = forms.ChoiceField(
        choices=SafetyOverride.RULE_TYPE_CHOICES,
        initial="weather_hold",
        widget=forms.Select(attrs={"class": _SELECT_CLS}),
    )
    severity = forms.ChoiceField(
        choices=SafetyOverride.SEVERITY_CHOICES,
        initial="high",
        widget=forms.Select(attrs={"class": _SELECT_CLS}),
    )
    vessel = forms.ModelChoiceField(
        queryset=Vessel.objects.order_by("vessel_id"),
        required=False,
        empty_label="Select vessel",
        widget=forms.Select(attrs={"class": _SELECT_CLS}),
    )
    destination = forms.ChoiceField(
        choices=DESTINATION_HOLD_CHOICES,
        required=False,
        initial="Platform C",
        widget=forms.Select(attrs={"class": _SELECT_CLS}),
    )
    created_by_role = forms.CharField(
        required=False,
        max_length=80,
        initial="Marine Operations Supervisor",
        widget=forms.TextInput(
            attrs={
                "placeholder": "Marine Operations Supervisor",
                "class": _INPUT_CLS,
            }
        ),
    )
    reason = forms.CharField(
        required=False,
        max_length=400,
        widget=forms.Textarea(
            attrs={
                "rows": 2,
                "placeholder": (
                    "Optional engineering or sea-state rationale "
                    "(smart default applied if left blank)"
                ),
                "class": _TEXTAREA_CLS,
            }
        ),
    )

    def clean(self):
        cleaned_data = super().clean()
        rule_type: str | None = cleaned_data.get("rule_type")
        vessel: Vessel | None = cleaned_data.get("vessel")
        destination: str = (cleaned_data.get("destination") or "").strip()

        if not rule_type:
            return cleaned_data

        if rule_type == "weather_hold":
            cleaned_data["vessel"] = None
            if destination not in ("", *DESTINATIONS):
                self.add_error(
                    "destination",
                    "Select a valid offshore destination or All Rough-Sea Corridors.",
                )
                return cleaned_data
            cleaned_data["destination"] = destination

            if SafetyOverride.objects.filter(
                rule_type="weather_hold",
                destination=destination,
                is_active=True,
            ).exists():
                scope_label = destination or "All Rough-Sea Corridors"
                raise forms.ValidationError(
                    f"An active Sea-State / Weather Hold already exists for {scope_label}. "
                    "Clear the existing rule before adding another."
                )
        else:
            cleaned_data["destination"] = ""
            if vessel is None:
                self.add_error("vessel", "Select a target vessel for this HSE rule.")
                return cleaned_data

            if SafetyOverride.objects.filter(
                rule_type=rule_type,
                vessel=vessel,
                is_active=True,
            ).exists():
                rule_label = dict(SafetyOverride.RULE_TYPE_CHOICES).get(
                    rule_type, rule_type
                )
                raise forms.ValidationError(
                    f"An active {rule_label} already exists on {vessel.vessel_id}. "
                    "Clear the existing rule before adding another."
                )

        role = (cleaned_data.get("created_by_role") or "").strip()
        cleaned_data["created_by_role"] = role or "Marine Operations Supervisor"

        reason = (cleaned_data.get("reason") or "").strip()
        if not reason:
            if rule_type == "weather_hold":
                if destination:
                    reason = (
                        f"Sea-state weather hold enforced on {destination} corridor "
                        "due to elevated offshore swell — routine consolidation paused."
                    )
                else:
                    reason = (
                        "Fleet-wide rough sea-state hold enforced across offshore corridors "
                        "— rough-weather merges paused pending marine clearance."
                    )
            elif rule_type == "maintenance_hold" and vessel is not None:
                reason = (
                    f"Engineering maintenance hold placed on {vessel.vessel_id} "
                    "for fuel-burn and propulsion inspection — excluded from automated merges."
                )
            elif rule_type == "standby_lock" and vessel is not None:
                reason = (
                    f"Standby vessel protection lock enforced on {vessel.vessel_id} "
                    "— reserved for offshore emergency standby and excluded from routine merges."
                )
        cleaned_data["reason"] = reason

        return cleaned_data

    def save_override(self) -> SafetyOverride:
        """Persist the validated HSE hold rule as an active SafetyOverride."""
        return SafetyOverride.objects.create(
            rule_type=self.cleaned_data["rule_type"],
            vessel=self.cleaned_data.get("vessel"),
            destination=self.cleaned_data.get("destination") or "",
            severity=self.cleaned_data["severity"],
            reason=self.cleaned_data["reason"],
            created_by_role=self.cleaned_data["created_by_role"],
            is_active=True,
        )
