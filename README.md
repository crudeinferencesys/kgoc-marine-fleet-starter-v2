# KGOC Marine Fleet Utilization & Optimization (Theme 4 — CrudeInference)

> **Live App URL:** https://crudeinference.com (redirects to Cloud Run `me-central1`: https://kgoc-marine-fleet-93163341832.me-central1.run.app) — Publicly accessible with no login required.

## Problem
Offshore marine fleet dispatchers supporting KGOC/KJO joint operations coordinate crew boats (`CB-01`–`CB-04`, `CB-07`), utility boats (`CB-05`, `CB-06`), and multi-purpose vessels (`CB-08`) between `Marine Base` and offshore platforms/terminals. In the 90-day operational dataset (`976` completed trips):
- **63.1%** (`616` sailings) depart below 50% max capacity (**43.2%** avg load, **35.8%** avg passenger utilization).
- **572.6 hours** (**13,440 L** diesel) are lost to avoidable non-productive idling vs. **374.5 hours** of productive onsite work.
- **39 trips** show high fuel-burn outliers (`>= 1.30×` expected physics consumption, up to `2.07×`), **8** show low readings (`<= 0.70×`), and **15** have missing fuel logs.

## Target User
KGOC / KJO Marine Fleet Dispatchers and Offshore Operations Supervisors managing daily vessel assignments, utilization, fuel audits, and sea-state/standby HSE constraints.

## Solution
A zero-scroll Django 5.2 LTS + HTMX 2 + Alpine.js 3 + Chart.js 4 web application backed by Cloud SQL PostgreSQL on Google Cloud Run (`me-central1`):
1. **Control Tower (`/`):** Single-screen cockpit with 4 clickable drill-down KPIs (live approved-plan savings + 90-day benchmark opportunity) and a 2×2 clickable Chart.js grid.
2. **Feature 1 — Trips & Utilization (`/trips/`):** 2-tab operational workspace (`Trip Ledger` + 3-step `Log New Trip` booking form) with live capacity overload guardrails, `Consolidated` status tracking, categorized filter modal, centered telemetry inspector modal, and CSV export.
3. **Feature 2 — Dispatch Optimizer (`/optimizer/`):** Gulf OSV consolidation engine combining overlapping flexible runs (`0.08` detour penalty), lowest-cost eligible vessel right-sizing, optional multi-stop `Milk-Run` (`Platform A ↔ B ↔ C`, `0.18` detour penalty), hard `SafetyOverride` / `HSE Strict Weather` enforcement, atomic `Approve & Save Plan`, and 1-click `Revert Plan`.
4. **Feature 3 — Safety & Fuel Guard (`/safety/`, Active):** Physics-based fuel anomaly investigation flags (framed strictly as engineering investigations), vessel readiness from all **720 seeded `VesselAvailability` rows**, and live `SafetyOverride` holds obeyed across `/optimizer/`.
5. **Feature 4 (Standalone Bonus AI) — AI Dispatch Co-Pilot (`/copilot/`, Next Sprint):** Gemini 4 (`gemini-4-hydrogen` via the `google-genai` Interactions API) structured merge risk review and shift handover brief (`ActionableDispatchBriefing`) with deterministic fallback.

---

## Judge Test Steps (Quick Verification)
1. **Control Tower (`/`):** Verify zero-scroll KPI cards (`43.2%` utilization, `616` half-empty sailings, `29,640 KWD` est. 90-day opportunity, `1` active hold / `CB-07 Standby Lock`) and click any KPI or chart to drill into its feature.
2. **Feature 1 (`/trips/`):** Filter via `Half-Empty` / `Fuel Outliers` chips, click any Trip ID (e.g. `TR-00012` or `TR-QUEUE-01`) to open the centered Telemetry Inspector modal (`KWD` audit & siblings), then switch to **`Log New Trip`** to submit a new `pending` request persisted in PostgreSQL (and test overload rejection on `CB-03` with `> 0.5 t` cargo).
3. **Feature 2 (`/optimizer/`):** Inspect the 3 clean pending consolidations (`TR-QUEUE-01..06`) while `CB-07` (`TR-QUEUE-09`) and rough-weather `Platform C` (`TR-QUEUE-07/08`) remain safely held. Toggle **`HSE Strict Weather`** off to preview rough-weather merges with an amber advisory, toggle **`Milk-Run`** on for multi-platform candidates, then click **`Approve & Save Plan`** → check `/` KPI 3 (`live plan` pill) and `/trips/?status=consolidated` (`Consolidated → TR-...`) → click **`Revert Plan`** under `Saved Plans & Backtest` to restore cleanly.

---

## Data & Mock Benchmark Assumptions (`apps/core/constants.py`)
All data in this application is **mock/synthetic operational data** (derived from `KJO_Marine_Fleet_Hackathon_Participant_Dataset.xlsx`: `8` vessels, `976` historical trips over `2026-08-26` → `2026-11-23`, `720` `VesselAvailability` rows, plus `12` synthetic `TR-QUEUE-*` shift requests and `1` active `standby_lock` on `CB-07`). Assumed mock pricing & operational parameters used for unvalidated Pillar 4 estimates:
- `ASSUMED_DIESEL_KWD_PER_LITER = 0.150` KWD/L
- `ASSUMED_KG_CO2_PER_LITER = 2.68` kg CO₂/L
- `CONSOLIDATION_DETOUR_FUEL_PENALTY_FACTOR = 0.08` (same-corridor), `MILK_RUN_DETOUR_FUEL_PENALTY_FACTOR = 0.18` (cross-platform loop)
- `DISPATCHER_MINUTES_SAVED_PER_MERGE = 15` minutes
- `VESSEL_HOURLY_OPERATING_KWD`: Crew Boat `42.0` KWD/h, Utility Boat `55.0` KWD/h, Multi-purpose Boat `62.0` KWD/h
- High fuel outliers (`>= 1.30×` physics expected burn) are flagged for engineering review only (no misconduct claims); blank `Actual_Fuel_L` rows are reported as missing logs rather than zero.

---

## Local Development Setup
```sh
uv venv --python 3.12 .venv
source .venv/bin/activate
uv pip install -r requirements.txt
cp .env.example .env
python manage.py migrate
python manage.py seed_fleet --if-empty
python manage.py runserver
```

To inspect an organizer CSV/Excel dataset quickly:
```sh
python manage.py inspect_dataset path/to/fleet_trips.xlsx
```

To run pre-PR verification checks:
```sh
python manage.py check && python manage.py makemigrations --check --dry-run && python manage.py test
```

## Limitations
- Designed as a hackathon MVP using mock/synthetic fleet data and assumed KWD fuel/charter rates — never use synthetic capacity or weather values for live offshore dispatch decisions.
- Optimization uses single-day heuristic window/capacity pairing rather than live AIS tracking or MetOcean telemetry feeds.
