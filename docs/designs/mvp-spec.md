# MVP Specification — Theme 4: Marine Fleet Utilization & Optimization

> **Status:** Schema Frozen (11:45 AM) — `apps/core/models.py`, `apps/core/constants.py`, `0001_initial.py`, and `seed_fleet` are locked on `main`. Both slices build cleanly on these shared contracts.

---

## 1. Problem & Target User
- **Target User:** KGOC / KJO Offshore Marine Fleet Dispatchers & Marine Operations Supervisors managing crew boats (`CB-01`–`CB-04`, `CB-07`: 16–22 pax), utility boats (`CB-05`, `CB-06`: 7–9 t cargo), and multi-purpose vessels (`CB-08`: 14 pax, 5 t cargo) between `Marine Base` and offshore platforms/terminals.
- **Core Pain Point:** 63.1% of historical sailings depart below 50% capacity (35.8% avg passenger utilization), 572.6 hours (13,438 L) are lost to non-productive idle time, and fuel-burn outliers up to 2.07× expected consumption require systematic engineering investigation without overriding marine weather/standby safety.

---

## 2. KJO Dataset Profile & Dual-Mode Data Strategy
- **Source File (gitignored, bundled as `apps/core/fixtures/kjo_dataset.json.gz`):** `KJO_Marine_Fleet_Hackathon_Participant_Dataset.xlsx` (8 sheets: `START HERE`, `Theme_Brief`, `Idea_Starters`, `Vessels`, `Trips`, `Availability`, `Requests`, `Data_Dictionary`).
- **Observed Schema & Metrics:**
  - **`Vessels` (8 rows):** `Vessel_ID` (`CB-01`–`CB-08`), `Vessel_Type`, `Passenger_Capacity`, `Cargo_Capacity_T`, `Underway_Rate_Lph`, `Idle_Rate_Lph`, `Cruise_Speed_kn`, `Shift_Hours_per_Day` (12), `Status`.
  - **`Trips` (976 rows) + `Requests` (976 rows, exact 1:1 join on `Trip_ID`):** Date range `2026-08-26` → `2026-11-23` (90 days). `Origin` (`Marine Base`), `Destination` (`Platform A/B/C`, `Offshore Terminal`, `Maintenance Area`), `Mission_Type` (`Passenger Transfer`, `Material Delivery`, `Maintenance Support`), `Departure_DT`, `Return_DT`, `Earliest_Departure_DT`, `Latest_Departure_DT`, `Underway_Hours`, `Onsite_Work_Hours`, `Nonproductive_Idle_Hours`, `Distance_nm`, `Passengers` (0–14), `Cargo_Tonnes` (0–6.72), `Weather` (`Calm`/`Moderate`/`Rough`), `Priority` (`Routine`/`Urgent`/`Critical`), `Flexible_Window` (`Yes`/`No`, 752 flexible), `Actual_Fuel_L`.
  - **`Availability` (720 rows = 8 × 90 days):** `Available` (585), `Weather Restricted` (97), `Maintenance` (38).
- **Key Edge Cases & Operating Rules Observed:**
  - **15 blank `Actual_Fuel_L` rows:** Treated as `"missing"` telemetry logs rather than zero fuel.
  - **Physics-based fuel anomalies:** Expected fuel = `(Underway_Hours × Underway_Rate_Lph) + ((Onsite_Work_Hours + Nonproductive_Idle_Hours) × Idle_Rate_Lph)`. Yields 22 severe high-burn outliers (`≥ 1.30×`, up to `2.07×` on `TR-00012 CB-08`) and 8 suspiciously low readings (`≤ 0.70×`). Per KJO guidance, alerts are framed as **engineering investigation flags** (never misconduct accusations).
  - **Productive vs. Non-productive waiting:** `Onsite_Work_Hours` is productive offshore support; `Nonproductive_Idle_Hours` (572.6 h total) is avoidable idle fuel waste.
  - **Consolidation potential:** 616 / 976 trips (63.1%) are under 50% max capacity, with ~168 mergeable same-day overlapping flexible pairs.
  - **Standby vessel:** `CB-07` (54 historical trips vs 115–155 for peers) is seeded with an active `standby_lock` `SafetyOverride`.
- **Dual-Mode Lifecycle:**
  - `seed_fleet --if-empty` (auto-run in `entrypoint.sh` on Cloud Run startup) loads 8 `Vessel`s, 720 `VesselAvailability` rows, 976 `completed` historical `Trip`s, **12 mock `pending` shift queue `Trip`s** (`TR-QUEUE-01`–`12` with clean pairs, rough-weather pair, standby-locked pair, fixed critical run, and high-load run), and **1 active `standby_lock` on `CB-07`**.

---

## 3. FROZEN Core Data Model (`apps/core/models.py` & `apps/core/constants.py`)
Portable Django ORM fields only (SQLite + Cloud SQL PostgreSQL parity).
- **`Vessel`**: `vessel_id` (unique), `vessel_type`, `passenger_capacity`, `cargo_capacity_t`, `underway_rate_lph`, `idle_rate_lph`, `cruise_speed_kn`, `shift_hours_per_day`, `hourly_operating_kwd`, `is_standby_designated`, `status`.
- **`VesselAvailability`**: `vessel` (FK), `date`, `scheduled_shift_hours`, `maintenance_hours`, `weather_restricted_hours`, `availability_status`.
- **`Trip`**: `trip_id` (unique), `request_id`, `vessel` (FK), `trip_date`, `mission_type`, `origin`, `destination`, `submitted_dt`, `earliest_departure_dt`, `latest_departure_dt`, `departure_dt`, `return_dt`, `underway_hours`, `onsite_work_hours`, `nonproductive_idle_hours`, `distance_nm`, `passengers`, `cargo_tonnes`, `weather`, `priority`, `flexible_window`, `actual_fuel_l` (nullable), `status` (`completed`/`pending`/`consolidated`/`cancelled`), `dispatch_plan` (nullable FK), `consolidated_into` (nullable self-FK), `is_synthetic_queue`, `notes`. Computed properties: `pax_utilization_pct`, `cargo_utilization_pct`, `utilization_pct`, `is_half_empty`, `expected_fuel_l`, `fuel_ratio`, `fuel_excess_l`, `idle_fuel_l`, `fuel_anomaly_status`.
- **`DispatchPlan`**: `name`, `scope` (`pending`/`backtest`), `baseline_trips`, `optimized_trips`, `trips_eliminated`, `fuel_liters_saved`, `kwd_saved`, `co2_kg_saved`, `dispatcher_minutes_saved`, `plan_payload` (`JSONField`), `ai_briefing` (`JSONField`), `ai_fallback_used`, `is_approved`, `approved_at`.
- **`SafetyOverride`**: `rule_type` (`weather_hold`/`maintenance_hold`/`standby_lock`), `vessel` (nullable FK), `destination`, `source_trip` (nullable FK), `severity`, `reason`, `created_by_role`, `is_active`.
- **Shared AI Contracts (`apps/core/ai.py`):** `DispatchBriefing`, `MergeRiskAssessment` (`approve`/`review`/`hold`), and `ActionableDispatchBriefing`.

---

## 4. Control Tower + 3 Standalone Core Features + 1 Embedded Bonus AI

### Executive Control Tower (`/` — Salman)
- **Role:** Public landing hub (zero login wall, all developer starter text removed).
- **Live DB Readouts:** Live KPI strip (Fleet Utilization %, Half-Empty Runs, Est. 90-Day KWD / Fuel / CO₂ Savings, Active HSE Holds), one Chart.js fleet utilization visual, and 3 clear action cards into Features 1–3.

### Feature 1 — Trip Ticketing & Utilization Ledger (`apps/trips/`, Salman)
- **Goal:** Track utilization KPIs across all 976 historical trips (plus non-productive idle fuel vs. productive onsite support) and provide an HTMX trip booking form that saves new `pending` trip requests directly to PostgreSQL.
- **Standalone & Testable:** Judges submit a new crew/cargo trip request -> saved to DB -> utilization bar and half-empty flag appear immediately, and the `pending` trip enters `/optimizer/`.

### Feature 2 — Dispatch Consolidation Optimizer (`apps/optimizer/`, Saleh)
- **Goal:** Python solver consolidating `pending` shift trips within passenger/cargo/time-window (`flexible_window`, `[earliest_departure_dt, latest_departure_dt]`) and active `SafetyOverride` HSE constraints, plus a 90-day historical backtest headline across the 976 completed trips (~168 mergeable pairs).
- **Standalone & Testable:** Judges click **Run Consolidation Solver** -> inspect Before → After diff cards, trips eliminated, fuel liters saved, KWD saved, CO₂ reduced, and dispatcher minutes saved -> click **Approve & Save Plan** to persist `DispatchPlan` (and update consolidated trips) in PostgreSQL. Links cleanly to the standalone 4th AI feature (`/copilot/`).

### Feature 3 — Safety & Fuel Anomaly Guard (`apps/safety/`, First Finisher)
- **Goal:** Detect physics-based fuel-burn outliers (`actual_fuel_l / expected_fuel_l >= 1.30` or `<= 0.70`, plus 15 missing logs) framed as engineering investigation flags across the 976 trips, and enforce **3 live PostgreSQL `SafetyOverride` HSE rules** constraining `/optimizer/` and `/copilot/`:
  1. **Sea-State / Weather Hold** on a destination/zone or Rough weather.
  2. **Vessel Maintenance Hold** (1-click trigger directly from any flagged fuel anomaly).
  3. **Standby Vessel Protection Lock** (`CB-07` pre-locked; toggleable/manageable in DB).
- **Standalone & Testable:** Judges inspect flagged fuel outliers, create/toggle an HSE hold saved to PostgreSQL, reload to verify persistence, and confirm `/optimizer/` respects the active safety block.

### Feature 4 (Standalone Bonus AI) — AI Dispatch Co-Pilot (`/copilot/`, `core:copilot:index`, Saleh)
- **Owned Files:** `apps/optimizer/copilot_urls.py`, `apps/optimizer/copilot_views.py`, `templates/optimizer/copilot.html` (implemented by Saleh right after Feature 2 `/optimizer/`).
- **Behaves Like a Standalone 4th Feature:** Dedicated sidebar entry (`04 · AI`), dedicated Control Tower launch card, and independent `/copilot/` URL with clear **Input → Output** + PostgreSQL persistence.
- **Inputs:** Supervisor shift directive or KJO scenario + live `pending` queue, active `SafetyOverride` rules, and fuel anomaly alerts from PostgreSQL.
- **Embedded AI Work & Outputs:** Calls `gemini-4-hydrogen` via the `google-genai` Interactions API using `ActionableDispatchBriefing` structured JSON output (with deterministic fallback if `GEMINI_API_KEY` is missing or times out). Scores each proposed merge (`approve` / `review` / `hold` + risk badge + rationale), enables 1-click HSE hold creation (`SafetyOverride`) and persisted shift handover briefings (`DispatchPlan`) in PostgreSQL.

---

## 5. Quantified Impact Formulas (`apps/core/constants.py` — Mock Benchmarks Labeled)
- `ASSUMED_DIESEL_KWD_PER_LITER = 0.150`
- `ASSUMED_KG_CO2_PER_LITER = 2.68`
- `DISPATCHER_MINUTES_SAVED_PER_MERGE = 15`
- `CONSOLIDATION_DETOUR_FUEL_PENALTY_FACTOR = 0.08`
- `VESSEL_HOURLY_OPERATING_KWD`: Crew Boat `42.0`, Utility Boat `55.0`, Multi-purpose Boat `62.0`
- **Formulas:** `estimate_savings_kwd(fuel_liters_saved, vessel_hours_saved, hourly_operating_kwd)` and `estimate_co2_kg(fuel_liters_saved)`.

---

## 6. Parallel Sprint Plan (Post-Schema Freeze)
- **Now (Parallel):**
  - **Salman (`feat/trips-*`):** Feature 1 (`/trips/`) + Executive Control Tower (`/`).
  - **Saleh (`feat/optimizer-*`):** Feature 2 (`/optimizer/`) + Actionable Gemini Co-Pilot (`ActionableDispatchBriefing`).
- **14:30 – 15:30 (`feat/safety-*`):** First finisher builds Feature 3 (`/safety/`) and verifies `SafetyOverride` integration.
- **15:30 – 17:00:** Feature freeze at 15:30 -> end-to-end live Cloud Run smoke test (`https://crudeinference.com`) -> finalize `README.md` with exact judge steps & mock-data disclaimer -> submit before 17:00.

---

## 7. Judging Live Test Script (End-to-End < 3 Minutes)
1. Open `/` — Executive Control Tower loads immediately with zero login prompt, live PostgreSQL KPIs (from 976 KJO trips), and fleet utilization chart.
2. Open `/trips/` -> submit a half-empty `pending` trip request -> reload page to verify PostgreSQL persistence and half-empty flag.
3. Open `/safety/` -> inspect physics-based fuel anomalies (`TR-00012` 2.07×) -> click **Maintenance Hold** (or add a **Weather Hold**) -> reload to verify persistence.
4. Open `/optimizer/` -> run consolidation solver -> verify `CB-07` standby lock & active HSE holds block unsafe merges -> click **Approve & Save Plan** -> reload to verify persisted `DispatchPlan`.
5. Open `/copilot/` -> enter a shift directive or run Gemini 4 Dispatch Co-Pilot review -> inspect per-merge `Approve`/`Review`/`Hold` risk verdicts, apply an AI-recommended HSE hold, and save the shift handover briefing to PostgreSQL.
