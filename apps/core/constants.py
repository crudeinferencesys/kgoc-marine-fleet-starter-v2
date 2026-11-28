"""
Shared domain constants and Pillar 4 impact formulas for Theme 4 (Marine Fleet).

Single source of truth imported by `apps/core/`, `apps/trips/`, `apps/optimizer/`,
and `apps/safety/` so all slices report consistent KWD, CO2, and anomaly numbers.
All operational prices and rates are clearly labeled mock benchmarks.
"""

ASSUMED_DIESEL_KWD_PER_LITER = 0.150
ASSUMED_KG_CO2_PER_LITER = 2.68
DISPATCHER_MINUTES_SAVED_PER_MERGE = 15
CONSOLIDATION_DETOUR_FUEL_PENALTY_FACTOR = 0.08

FUEL_HIGH_ANOMALY_RATIO = 1.30
FUEL_LOW_ANOMALY_RATIO = 0.70
HALF_EMPTY_THRESHOLD_PCT = 50.0

VESSEL_HOURLY_OPERATING_KWD = {
    "Crew Boat": 42.0,
    "Utility Boat": 55.0,
    "Multi-purpose Boat": 62.0,
}

VESSEL_TYPES = (
    "Crew Boat",
    "Utility Boat",
    "Multi-purpose Boat",
)

DESTINATIONS = (
    "Platform A",
    "Platform B",
    "Platform C",
    "Offshore Terminal",
    "Maintenance Area",
)

MISSION_TYPES = (
    "Passenger Transfer",
    "Material Delivery",
    "Maintenance Support",
)

WEATHER_STATES = (
    "Calm",
    "Moderate",
    "Rough",
)

PRIORITIES = (
    "Routine",
    "Urgent",
    "Critical",
)


def estimate_savings_kwd(
    fuel_liters_saved: float,
    vessel_hours_saved: float,
    hourly_operating_kwd: float = 48.0,
) -> float:
    """Return estimated operational savings in KWD from fuel + vessel operating hours saved."""
    fuel_kwd = max(0.0, float(fuel_liters_saved)) * ASSUMED_DIESEL_KWD_PER_LITER
    ops_kwd = max(0.0, float(vessel_hours_saved)) * float(hourly_operating_kwd)
    return round(fuel_kwd + ops_kwd, 2)


def estimate_co2_kg(fuel_liters_saved: float) -> float:
    """Return estimated CO2 emissions avoided in kg from diesel liters saved."""
    return round(max(0.0, float(fuel_liters_saved)) * ASSUMED_KG_CO2_PER_LITER, 1)
