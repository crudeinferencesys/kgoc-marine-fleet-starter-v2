# CrudeInference — KGOC Marine Fleet Utilization & Optimization (Theme 4)

> **Live App URL (Zero Login Wall):** https://crudeinference.com (direct Cloud Run `me-central1`: https://kgoc-marine-fleet-93163341832.me-central1.run.app) — Publicly accessible with no authentication required.

---

## Problem & Target User

**Target User:** KGOC / KJO Offshore Marine Fleet Dispatchers and Marine Operations Supervisors coordinating daily sailings between `Marine Base` and offshore locations (`Platform A`, `Platform B`, `Platform C`, `Offshore Terminal`, `Maintenance Area`).

Across the 90-day KJO operational telemetry dataset (`8` vessels: crew boats `CB-01`–`CB-04` and `CB-07`, utility boats `CB-05`–`CB-06`, multi-purpose vessel `CB-08`; `976` historical trips; `720` `VesselAvailability` rows):
- **63.1%** (`616` sailings) depart below 50% capacity (**43.2%** avg max load, **35.8%** avg passenger utilization).
- **572.6 hours** (**13,440 L** diesel) are lost to avoidable non-productive platform idling vs. **374.5 hours** of productive onsite work.
- **39 trips** show high fuel-burn outliers (`>= 1.30×` expected physics consumption, up to `2.07×` on `TR-00012`), **8** show low readings (`<= 0.70×`), and **15** have blank `Actual_Fuel_L` telemetry logs.

## Before & After

- **Before:** Fragmented spreadsheets, manual radio/shift booking, and uncoordinated single-vessel dispatches leave over three-fifths of sailings half-empty, obscure idle fuel waste, and provide no automated check linking fuel anomalies or sea-state holds to daily vessel scheduling.
- **After:** A unified zero-scroll Django 5.2 LTS + HTMX 2 + Alpine.js 3 + Chart.js 4 Marine Command platform backed by Cloud SQL PostgreSQL that turns raw telemetry into consolidated multi-passenger/cargo dispatches, real-time HSE overrides, physics-based engineering fuel audits, and Gemini 4 shift handover briefings.

---

## Shipped Features (Control Tower + 3 Core Features + Bonus AI Feature 4)

All 5 workspace views are shipped on `main` and publicly testable without login:

1. **Control Tower (`/`):**
   - Zero-scroll executive cockpit with 4 clickable drill-down KPI cards (`43.2%` fleet utilization, `616` half-empty sailings, `29,640 KWD · mock` est. 90-day opportunity across `169` greedy backtest merges plus live approved `DispatchPlan` readout pill, and active HSE holds & fuel flags) over a 2×2 clickable Chart.js 4 grid.
2. **Feature 1 — Trips & Utilization (`/trips/`):**
   - 2-tab operational workspace (`Trip Ledger` + 3-step `Log New Trip` booking form persisted to PostgreSQL) with server-side overload validation (recommending capable higher-capacity vessels), `Consolidated` status badge & quick preset chip (`→ <trip_id>`), categorized `More Filters` modal, centered `#trip-inspector-modal` (`KWD` fuel audit, corridor siblings, `Dispatch Consolidation` banner), and filtered CSV export.
3. **Feature 2 — Dispatch Optimizer (`/optimizer/`):**
   - Gulf OSV consolidation engine combining overlapping flexible runs (`0.08` detour penalty) with lowest-cost eligible vessel right-sizing, configurable **`HSE Strict Weather`** (ON by default) and **`Milk-Run`** (`Platform A ↔ B ↔ C`, `0.18` detour penalty) toggles, hard `SafetyOverride` enforcement (including fleet-wide weather holds and `CB-07 Standby Lock`), checkbox cherry-picking, atomic **`Approve & Save Plan`** & 1-click **`Revert Plan`**, and a 90-day 5-corridor historical backtest.
4. **Feature 3 — Safety & Fuel Guard (`/safety/`):**
   - Physics-based fuel audit framing all **39 high outliers** strictly as neutral engineering investigation flags, **8** low readings, **15** `Missing Telemetry Log` entries, and `880 KWD · mock` avoidable burn; centered `#safety-inspector-modal` enriched with the **720-row `VesselAvailability`** readiness history; 1-click **`Maintenance Hold`** from flagged sailings; and 3-step **`Add HSE Hold`** CRUD constraining `/optimizer/` in real time.
5. **Bonus AI Feature 4 — AI Dispatch Co-Pilot (`/copilot/`):**
   - Powered by **Gemini 4 (`gemini-4-hydrogen`)** via the `google-genai` Interactions API and `ActionableDispatchBriefing` Pydantic structured output (with automatic deterministic fallback if `GEMINI_API_KEY` is unset or times out). Evaluates supervisor shift directives (or 4 KJO presets: `Standard Shift Handover`, `Rough-Sea HSE Audit`, `Fuel Outlier Investigation`, `Milk-Run Savings Push`) against live pending merges, active HSE locks, and fuel anomalies to produce per-merge `Approve` / `Review` / `Hold` verdicts and rationales, 1-click HSE hold activation, AI-cleared merge approval, and persisted Shift Handover Briefings in PostgreSQL.

---

## How to Use & Judge Quick-Test Steps (< 3 Minutes)

1. **Control Tower (`/`):** Confirm zero-scroll KPI cards (`43.2%`, `616`, `29,640 KWD · mock`, `1` active hold / `CB-07 Standby Lock`) and click any KPI card or chart to drill into its slice.
2. **Feature 1 (`/trips/`):** Click `Half-Empty` or `Fuel Outliers` chips, click `TR-00012` to inspect its `2.07×` fuel audit in `#trip-inspector-modal`, then open **`Log New Trip`** → test overload blocking on `CB-03` with `3.0 t` cargo (recommends `CB-05`/`CB-06`) → submit a valid `5 pax` / `0.1 t` shift booking and reload to verify PostgreSQL persistence.
3. **Feature 2 (`/optimizer/`):** Inspect the clean pending merges (`TR-QUEUE-01..06`) while `CB-07` (`TR-QUEUE-09`) and rough-weather `Platform C` (`TR-QUEUE-07/08`) are held. Toggle **`HSE Strict Weather`** off to preview rough-sea advisories or **`Milk-Run`** on for multi-platform loops, then click **`Approve & Save Plan`** → check `/` KPI 3 (`live plan` pill) and `/trips/?status=consolidated` → click **`Revert Plan`** under `Saved Plans & Backtest` to restore cleanly.
4. **Feature 3 (`/safety/`):** Filter `High Outliers`, click `TR-00012` (`CB-08`) to inspect its `VesselAvailability` history in `#safety-inspector-modal`, click **`Maintenance Hold`** (or create a `Weather Hold` via **`Add HSE Hold`**), reload to verify persistence, and confirm `/optimizer/` blocks that vessel/corridor immediately (clear the test hold afterward to reset).
5. **Bonus AI (`/copilot/`):** Select **`Rough-Sea HSE Audit`** or **`Fuel Outlier Investigation`** (or enter a custom shift directive), click **`Run Co-Pilot Review`**, inspect per-merge `Approve` / `Review` / `Hold` verdicts, trigger 1-click **`Apply Hold`** or **`Approve AI-Cleared Merges`**, and click **`Save Shift Handover Briefing`** to persist to PostgreSQL.

---

## Data & Mock Benchmark Assumptions (`apps/core/constants.py`)

All operational numbers and financial figures are **mock/synthetic operational benchmarks** derived from `KJO_Marine_Fleet_Hackathon_Participant_Dataset.xlsx` (`8` vessels, `976` completed trips from `2026-08-26` to `2026-11-23`, `720` `VesselAvailability` rows, plus `12` synthetic `TR-QUEUE-*` shift requests and `1` active `standby_lock` on `CB-07`):
- `ASSUMED_DIESEL_KWD_PER_LITER = 0.150` KWD/L
- `ASSUMED_KG_CO2_PER_LITER = 2.68` kg CO₂/L
- `CONSOLIDATION_DETOUR_FUEL_PENALTY_FACTOR = 0.08` (same-corridor), `MILK_RUN_DETOUR_FUEL_PENALTY_FACTOR = 0.18` (multi-platform loop in `apps/optimizer/services.py`)
- `DISPATCHER_MINUTES_SAVED_PER_MERGE = 15` minutes
- `VESSEL_HOURLY_OPERATING_KWD`: Crew Boat `42.0` KWD/h, Utility Boat `55.0` KWD/h, Multi-purpose Boat `62.0` KWD/h
- `FUEL_HIGH_ANOMALY_RATIO = 1.30`, `FUEL_LOW_ANOMALY_RATIO = 0.70`, `HALF_EMPTY_THRESHOLD_PCT = 50.0`
- High fuel outliers (`>= 1.30×` expected physics burn) are flagged strictly for engineering investigation (no misconduct claims); blank `Actual_Fuel_L` rows are reported explicitly as `Missing Telemetry Log` rather than zero fuel.

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

Inspect an organizer CSV/Excel workbook:
```sh
python manage.py inspect_dataset path/to/fleet_trips.xlsx
```

Run the full pre-PR verification gate (**88 tests** across all 4 slices):
```sh
python manage.py check && python manage.py makemigrations --check --dry-run && python manage.py test
```

## Limitations

- Built as a hackathon MVP using mock/synthetic fleet data and assumed KWD fuel/charter rates — never use synthetic capacity, fuel, or weather entries for live offshore dispatch decisions.
- Optimization uses single-day heuristic window/capacity pairing rather than live AIS vessel tracking or real-time MetOcean telemetry feeds.
