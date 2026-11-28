"""Idempotent management command to seed KJO vessels, 976 trips, availability, and live queue."""

from __future__ import annotations

import gzip
import json
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.core.constants import VESSEL_HOURLY_OPERATING_KWD
from apps.core.models import (
    DispatchPlan,
    SafetyOverride,
    Trip,
    Vessel,
    VesselAvailability,
)

KUWAIT_TZ = ZoneInfo("Asia/Kuwait")
DEFAULT_FIXTURE_PATH = (
    Path(__file__).resolve().parents[2] / "fixtures" / "kjo_dataset.json.gz"
)
QUEUE_DATE = date(2026, 11, 28)

MOCK_PENDING_QUEUE = [
    # Pair 1: Clean Platform A merge (CB-01 + CB-02, Calm, Flexible)
    {
        "trip_id": "TR-QUEUE-01",
        "request_id": "REQ-QUEUE-01",
        "vessel_id": "CB-01",
        "mission_type": "Passenger Transfer",
        "destination": "Platform A",
        "dep": time(7, 45),
        "early": time(7, 30),
        "late": time(9, 0),
        "underway_hours": 2.1,
        "onsite_work_hours": 0.3,
        "idle_hours": 0.4,
        "distance_nm": 36.0,
        "passengers": 6,
        "cargo_tonnes": 0.10,
        "weather": "Calm",
        "priority": "Routine",
        "flexible_window": True,
        "notes": "Morning crew rotation batch A1",
    },
    {
        "trip_id": "TR-QUEUE-02",
        "request_id": "REQ-QUEUE-02",
        "vessel_id": "CB-02",
        "mission_type": "Passenger Transfer",
        "destination": "Platform A",
        "dep": time(8, 15),
        "early": time(7, 30),
        "late": time(9, 0),
        "underway_hours": 2.1,
        "onsite_work_hours": 0.25,
        "idle_hours": 0.35,
        "distance_nm": 36.0,
        "passengers": 5,
        "cargo_tonnes": 0.10,
        "weather": "Calm",
        "priority": "Routine",
        "flexible_window": True,
        "notes": "Morning contractor transfer batch A2",
    },
    # Pair 2: Clean Platform B merge (CB-03 + CB-04, Calm, Flexible)
    {
        "trip_id": "TR-QUEUE-03",
        "request_id": "REQ-QUEUE-03",
        "vessel_id": "CB-03",
        "mission_type": "Maintenance Support",
        "destination": "Platform B",
        "dep": time(8, 10),
        "early": time(8, 0),
        "late": time(9, 30),
        "underway_hours": 2.3,
        "onsite_work_hours": 0.4,
        "idle_hours": 0.3,
        "distance_nm": 38.0,
        "passengers": 4,
        "cargo_tonnes": 0.10,
        "weather": "Calm",
        "priority": "Routine",
        "flexible_window": True,
        "notes": "Instrument inspection crew B1",
    },
    {
        "trip_id": "TR-QUEUE-04",
        "request_id": "REQ-QUEUE-04",
        "vessel_id": "CB-04",
        "mission_type": "Passenger Transfer",
        "destination": "Platform B",
        "dep": time(8, 50),
        "early": time(8, 0),
        "late": time(9, 30),
        "underway_hours": 2.2,
        "onsite_work_hours": 0.3,
        "idle_hours": 0.35,
        "distance_nm": 38.0,
        "passengers": 7,
        "cargo_tonnes": 0.15,
        "weather": "Calm",
        "priority": "Routine",
        "flexible_window": True,
        "notes": "Shift handover crew B2",
    },
    # Pair 3: Clean Offshore Terminal cargo merge (CB-05 + CB-06, Moderate, Flexible)
    {
        "trip_id": "TR-QUEUE-05",
        "request_id": "REQ-QUEUE-05",
        "vessel_id": "CB-05",
        "mission_type": "Material Delivery",
        "destination": "Offshore Terminal",
        "dep": time(9, 15),
        "early": time(9, 0),
        "late": time(10, 30),
        "underway_hours": 2.7,
        "onsite_work_hours": 0.5,
        "idle_hours": 0.45,
        "distance_nm": 41.0,
        "passengers": 3,
        "cargo_tonnes": 2.40,
        "weather": "Moderate",
        "priority": "Routine",
        "flexible_window": True,
        "notes": "Valve skids & deck consumables",
    },
    {
        "trip_id": "TR-QUEUE-06",
        "request_id": "REQ-QUEUE-06",
        "vessel_id": "CB-06",
        "mission_type": "Material Delivery",
        "destination": "Offshore Terminal",
        "dep": time(9, 55),
        "early": time(9, 0),
        "late": time(10, 30),
        "underway_hours": 2.7,
        "onsite_work_hours": 0.45,
        "idle_hours": 0.4,
        "distance_nm": 41.0,
        "passengers": 2,
        "cargo_tonnes": 3.10,
        "weather": "Moderate",
        "priority": "Routine",
        "flexible_window": True,
        "notes": "Chemical drums & hose pallets",
    },
    # Pair 4: Rough-weather Platform C pair (prime AI hold/review candidate)
    {
        "trip_id": "TR-QUEUE-07",
        "request_id": "REQ-QUEUE-07",
        "vessel_id": "CB-02",
        "mission_type": "Passenger Transfer",
        "destination": "Platform C",
        "dep": time(10, 15),
        "early": time(10, 0),
        "late": time(11, 30),
        "underway_hours": 2.5,
        "onsite_work_hours": 0.35,
        "idle_hours": 0.45,
        "distance_nm": 43.0,
        "passengers": 5,
        "cargo_tonnes": 0.10,
        "weather": "Rough",
        "priority": "Urgent",
        "flexible_window": True,
        "notes": "Urgent electrical tech crew in rough sea state",
    },
    {
        "trip_id": "TR-QUEUE-08",
        "request_id": "REQ-QUEUE-08",
        "vessel_id": "CB-03",
        "mission_type": "Maintenance Support",
        "destination": "Platform C",
        "dep": time(10, 45),
        "early": time(10, 0),
        "late": time(11, 30),
        "underway_hours": 2.5,
        "onsite_work_hours": 0.4,
        "idle_hours": 0.4,
        "distance_nm": 43.0,
        "passengers": 6,
        "cargo_tonnes": 0.20,
        "weather": "Rough",
        "priority": "Routine",
        "flexible_window": True,
        "notes": "Scaffold crew transfer in rough swell",
    },
    # Pair 5: Standby-vessel protected pair (CB-07 protected by standby_lock + CB-08)
    {
        "trip_id": "TR-QUEUE-09",
        "request_id": "REQ-QUEUE-09",
        "vessel_id": "CB-07",
        "mission_type": "Passenger Transfer",
        "destination": "Maintenance Area",
        "dep": time(11, 15),
        "early": time(11, 0),
        "late": time(12, 30),
        "underway_hours": 2.0,
        "onsite_work_hours": 0.3,
        "idle_hours": 0.3,
        "distance_nm": 31.0,
        "passengers": 3,
        "cargo_tonnes": 0.05,
        "weather": "Calm",
        "priority": "Routine",
        "flexible_window": True,
        "notes": "Standby relief run (CB-07 protected)",
    },
    {
        "trip_id": "TR-QUEUE-10",
        "request_id": "REQ-QUEUE-10",
        "vessel_id": "CB-08",
        "mission_type": "Maintenance Support",
        "destination": "Maintenance Area",
        "dep": time(11, 45),
        "early": time(11, 0),
        "late": time(12, 30),
        "underway_hours": 2.4,
        "onsite_work_hours": 0.6,
        "idle_hours": 0.35,
        "distance_nm": 31.0,
        "passengers": 4,
        "cargo_tonnes": 1.20,
        "weather": "Calm",
        "priority": "Routine",
        "flexible_window": True,
        "notes": "Welding gear & maintenance crew",
    },
    # Standalone Critical Fixed-Window Run (cannot merge)
    {
        "trip_id": "TR-QUEUE-11",
        "request_id": "REQ-QUEUE-11",
        "vessel_id": "CB-01",
        "mission_type": "Passenger Transfer",
        "destination": "Platform A",
        "dep": time(13, 0),
        "early": time(13, 0),
        "late": time(13, 20),
        "underway_hours": 2.0,
        "onsite_work_hours": 0.25,
        "idle_hours": 0.2,
        "distance_nm": 36.0,
        "passengers": 10,
        "cargo_tonnes": 0.20,
        "weather": "Calm",
        "priority": "Critical",
        "flexible_window": False,
        "notes": "Fixed-window critical HSE inspection team",
    },
    # Standalone High-Utilization Cargo Run (84% cargo load)
    {
        "trip_id": "TR-QUEUE-12",
        "request_id": "REQ-QUEUE-12",
        "vessel_id": "CB-08",
        "mission_type": "Material Delivery",
        "destination": "Offshore Terminal",
        "dep": time(14, 15),
        "early": time(14, 0),
        "late": time(15, 0),
        "underway_hours": 2.9,
        "onsite_work_hours": 0.6,
        "idle_hours": 0.3,
        "distance_nm": 41.0,
        "passengers": 4,
        "cargo_tonnes": 4.20,
        "weather": "Moderate",
        "priority": "Urgent",
        "flexible_window": True,
        "notes": "High-load compressor spares (84% deck capacity)",
    },
]


def _aware_dt(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value)
    else:
        parsed = pd.Timestamp(value).to_pydatetime()
    if timezone.is_naive(parsed):
        return timezone.make_aware(parsed, KUWAIT_TZ)
    return parsed


def _parse_date(value: object) -> date:
    if isinstance(value, str):
        return date.fromisoformat(value[:10])
    return pd.Timestamp(value).date()


def _load_payload(file_path: Path) -> dict[str, list[dict]]:
    if not file_path.exists():
        raise CommandError(f"Seed source file not found: {file_path}")

    if file_path.name.endswith(".json.gz"):
        with gzip.open(file_path, "rt", encoding="utf-8") as fh:
            return json.load(fh)

    if file_path.suffix.lower() in {".xlsx", ".xls"}:
        xl = pd.read_excel(file_path, sheet_name=None)
        merged = xl["Trips"].merge(
            xl["Requests"][
                [
                    "Trip_ID",
                    "Request_ID",
                    "Submitted_DT",
                    "Earliest_Departure_DT",
                    "Latest_Departure_DT",
                    "Priority",
                    "Flexible_Window",
                ]
            ],
            on="Trip_ID",
            how="left",
        )
        trips = []
        for row in merged.to_dict("records"):
            fuel = None if pd.isna(row["Actual_Fuel_L"]) else float(row["Actual_Fuel_L"])
            trips.append(
                {
                    "Trip_ID": str(row["Trip_ID"]),
                    "Request_ID": "" if pd.isna(row["Request_ID"]) else str(row["Request_ID"]),
                    "Vessel_ID": str(row["Vessel_ID"]),
                    "Trip_Date": _parse_date(row["Trip_Date"]).isoformat(),
                    "Mission_Type": str(row["Mission_Type"]),
                    "Origin": str(row["Origin"]),
                    "Destination": str(row["Destination"]),
                    "Submitted_DT": None if pd.isna(row["Submitted_DT"]) else _aware_dt(row["Submitted_DT"]).isoformat(),
                    "Earliest_Departure_DT": None if pd.isna(row["Earliest_Departure_DT"]) else _aware_dt(row["Earliest_Departure_DT"]).isoformat(),
                    "Latest_Departure_DT": None if pd.isna(row["Latest_Departure_DT"]) else _aware_dt(row["Latest_Departure_DT"]).isoformat(),
                    "Departure_DT": _aware_dt(row["Departure_DT"]).isoformat(),
                    "Return_DT": None if pd.isna(row["Return_DT"]) else _aware_dt(row["Return_DT"]).isoformat(),
                    "Underway_Hours": float(row["Underway_Hours"]),
                    "Onsite_Work_Hours": float(row["Onsite_Work_Hours"]),
                    "Nonproductive_Idle_Hours": float(row["Nonproductive_Idle_Hours"]),
                    "Distance_nm": float(row["Distance_nm"]),
                    "Passengers": int(row["Passengers"]),
                    "Cargo_Tonnes": float(row["Cargo_Tonnes"]),
                    "Weather": str(row["Weather"]),
                    "Priority": "Routine" if pd.isna(row["Priority"]) else str(row["Priority"]),
                    "Flexible_Window": str(row["Flexible_Window"]).strip().lower() == "yes",
                    "Actual_Fuel_L": fuel,
                }
            )
        availability = [
            {
                "Vessel_ID": str(r["Vessel_ID"]),
                "Date": _parse_date(r["Date"]).isoformat(),
                "Scheduled_Shift_Hours": float(r["Scheduled_Shift_Hours"]),
                "Maintenance_Hours": float(r["Maintenance_Hours"]),
                "Weather_Restricted_Hours": float(r["Weather_Restricted_Hours"]),
                "Availability_Status": str(r["Availability_Status"]),
            }
            for r in xl["Availability"].to_dict("records")
        ]
        vessels = [
            {
                "Vessel_ID": str(r["Vessel_ID"]),
                "Vessel_Type": str(r["Vessel_Type"]),
                "Passenger_Capacity": int(r["Passenger_Capacity"]),
                "Cargo_Capacity_T": float(r["Cargo_Capacity_T"]),
                "Underway_Rate_Lph": float(r["Underway_Rate_Lph"]),
                "Idle_Rate_Lph": float(r["Idle_Rate_Lph"]),
                "Cruise_Speed_kn": float(r["Cruise_Speed_kn"]),
                "Shift_Hours_per_Day": float(r["Shift_Hours_per_Day"]),
                "Status": str(r["Status"]),
            }
            for r in xl["Vessels"].to_dict("records")
        ]
        return {"vessels": vessels, "availability": availability, "trips": trips}

    raise CommandError(f"Unsupported seed file format: {file_path.name}")


class Command(BaseCommand):
    help = "Seed KJO Theme 4 vessels, availability, 976 historical trips, 12 pending queue trips, and standby lock."

    def add_arguments(self, parser):
        parser.add_argument(
            "--if-empty",
            action="store_true",
            help="Exit without modifying data if vessels already exist in the database.",
        )
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete existing fleet records before seeding cleanly.",
        )
        parser.add_argument(
            "--file",
            type=str,
            default=str(DEFAULT_FIXTURE_PATH),
            help="Optional path to .json.gz or .xlsx seed source.",
        )

    def handle(self, *args, **options):
        if options["if_empty"] and Vessel.objects.exists():
            self.stdout.write("seed_fleet: database already populated; skipping.")
            return

        payload = _load_payload(Path(options["file"]).expanduser())

        with transaction.atomic():
            if options["reset"]:
                SafetyOverride.objects.all().delete()
                Trip.objects.all().delete()
                DispatchPlan.objects.all().delete()
                VesselAvailability.objects.all().delete()
                Vessel.objects.all().delete()
            elif Vessel.objects.exists():
                self.stdout.write("seed_fleet: records already exist (pass --reset to reload); skipping.")
                return

            vessel_objs = [
                Vessel(
                    vessel_id=row["Vessel_ID"],
                    vessel_type=row["Vessel_Type"],
                    passenger_capacity=int(row["Passenger_Capacity"]),
                    cargo_capacity_t=float(row["Cargo_Capacity_T"]),
                    underway_rate_lph=float(row["Underway_Rate_Lph"]),
                    idle_rate_lph=float(row["Idle_Rate_Lph"]),
                    cruise_speed_kn=float(row["Cruise_Speed_kn"]),
                    shift_hours_per_day=float(row["Shift_Hours_per_Day"]),
                    hourly_operating_kwd=VESSEL_HOURLY_OPERATING_KWD.get(row["Vessel_Type"], 48.0),
                    is_standby_designated=(row["Vessel_ID"] == "CB-07"),
                    status=row["Status"],
                )
                for row in payload["vessels"]
            ]
            Vessel.objects.bulk_create(vessel_objs)
            vessel_by_id = {v.vessel_id: v for v in Vessel.objects.all()}

            avail_objs = [
                VesselAvailability(
                    vessel=vessel_by_id[row["Vessel_ID"]],
                    date=_parse_date(row["Date"]),
                    scheduled_shift_hours=float(row["Scheduled_Shift_Hours"]),
                    maintenance_hours=float(row["Maintenance_Hours"]),
                    weather_restricted_hours=float(row["Weather_Restricted_Hours"]),
                    availability_status=row["Availability_Status"],
                )
                for row in payload["availability"]
            ]
            VesselAvailability.objects.bulk_create(avail_objs, batch_size=500)

            trip_objs = [
                Trip(
                    trip_id=row["Trip_ID"],
                    request_id=row.get("Request_ID", ""),
                    vessel=vessel_by_id[row["Vessel_ID"]],
                    trip_date=_parse_date(row["Trip_Date"]),
                    mission_type=row["Mission_Type"],
                    origin=row["Origin"],
                    destination=row["Destination"],
                    submitted_dt=_aware_dt(row.get("Submitted_DT")),
                    earliest_departure_dt=_aware_dt(row.get("Earliest_Departure_DT")),
                    latest_departure_dt=_aware_dt(row.get("Latest_Departure_DT")),
                    departure_dt=_aware_dt(row["Departure_DT"]),
                    return_dt=_aware_dt(row.get("Return_DT")),
                    underway_hours=float(row["Underway_Hours"]),
                    onsite_work_hours=float(row["Onsite_Work_Hours"]),
                    nonproductive_idle_hours=float(row["Nonproductive_Idle_Hours"]),
                    distance_nm=float(row["Distance_nm"]),
                    passengers=int(row["Passengers"]),
                    cargo_tonnes=float(row["Cargo_Tonnes"]),
                    weather=row["Weather"],
                    priority=row.get("Priority", "Routine"),
                    flexible_window=bool(row.get("Flexible_Window", True)),
                    actual_fuel_l=row["Actual_Fuel_L"],
                    status="completed",
                    is_synthetic_queue=False,
                )
                for row in payload["trips"]
            ]

            submitted_base = timezone.make_aware(datetime.combine(QUEUE_DATE, time(6, 0)), KUWAIT_TZ)
            for item in MOCK_PENDING_QUEUE:
                dep_dt = timezone.make_aware(datetime.combine(QUEUE_DATE, item["dep"]), KUWAIT_TZ)
                early_dt = timezone.make_aware(datetime.combine(QUEUE_DATE, item["early"]), KUWAIT_TZ)
                late_dt = timezone.make_aware(datetime.combine(QUEUE_DATE, item["late"]), KUWAIT_TZ)
                total_hours = item["underway_hours"] + item["onsite_work_hours"] + item["idle_hours"]
                ret_dt = dep_dt + timedelta(hours=total_hours)
                trip_objs.append(
                    Trip(
                        trip_id=item["trip_id"],
                        request_id=item["request_id"],
                        vessel=vessel_by_id[item["vessel_id"]],
                        trip_date=QUEUE_DATE,
                        mission_type=item["mission_type"],
                        origin="Marine Base",
                        destination=item["destination"],
                        submitted_dt=submitted_base,
                        earliest_departure_dt=early_dt,
                        latest_departure_dt=late_dt,
                        departure_dt=dep_dt,
                        return_dt=ret_dt,
                        underway_hours=item["underway_hours"],
                        onsite_work_hours=item["onsite_work_hours"],
                        nonproductive_idle_hours=item["idle_hours"],
                        distance_nm=item["distance_nm"],
                        passengers=item["passengers"],
                        cargo_tonnes=item["cargo_tonnes"],
                        weather=item["weather"],
                        priority=item["priority"],
                        flexible_window=item["flexible_window"],
                        actual_fuel_l=None,
                        status="pending",
                        is_synthetic_queue=True,
                        notes=item["notes"],
                    )
                )

            Trip.objects.bulk_create(trip_objs, batch_size=500)

            SafetyOverride.objects.create(
                rule_type="standby_lock",
                vessel=vessel_by_id["CB-07"],
                severity="critical",
                reason="CB-07 designated Offshore Standby Crew Vessel for KJO Sector — protected from routine trip consolidation merges.",
                is_active=True,
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {Vessel.objects.count()} vessels, "
                f"{VesselAvailability.objects.count()} availability records, "
                f"{Trip.objects.filter(status='completed').count()} historical trips, "
                f"{Trip.objects.filter(status='pending').count()} pending shift requests, and "
                f"{SafetyOverride.objects.filter(is_active=True).count()} active HSE lock."
            )
        )
