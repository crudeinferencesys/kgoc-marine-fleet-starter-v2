# MVP Specification — Theme 4: Marine Fleet Utilization & Optimization

> **Status:** Schema Frozen — Features 1 (`/trips/`) and 2 (`/optimizer/`) + Executive Control Tower (`/`) are **shipped on `main`**; Feature 3 (`/safety/`) is active with Saleh, followed by Feature 4 (`/copilot/`).

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
- **Key Edge Cases & Operating Rules Observed (Live Seeded DB):**
  - **15 blank `Actual_Fuel_L` rows:** Explicitly handled as `"missing"` telemetry logs (`Missing Telemetry Log`) rather than zero fuel.
  - **Physics-based fuel anomalies:** Expected fuel = `(Underway_Hours × Underway_Rate_Lph) + ((Onsite_Work_Hours + Nonproductive_Idle_Hours) × Idle_Rate_Lph)`. Yields **39 severe high-burn outliers** (`>= 1.30×`, up to `2.07×` on `TR-00012 CB-08`), **8 low readings** (`<= 0.70×`), **15 missing logs**, and **914 nominal runs** across `976` completed trips. Per KJO `Idea_Starters` guidance, alerts are strictly framed as **engineering investigation flags** (never misconduct accusations).
  - **Productive vs. Non-productive waiting:** `Onsite_Work_Hours` (**374.5 h**) is productive offshore support; `Nonproductive_Idle_Hours` (**572.6 h**, **13,440 L** diesel) is avoidable idle fuel waste.
  - **Consolidation potential:** **616 / 976 trips (63.1%)** sail under 50% max capacity (**43.2%** avg max utilization, **35.8%** avg pax utilization), with **169 greedy backtest merges** (**41,132 L** diesel, **29,640 KWD**, **110.2 t CO₂** *mock*).
  - **Standby vessel & availability (`720` `VesselAvailability` rows):** `CB-07` (`54` historical trips vs `115–155` for peers) is seeded with an active `standby_lock` `SafetyOverride`; daily `VesselAvailability` tracks `Available` (`585`), `Weather Restricted` (`97`), and `Maintenance` (`38`).
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

## 4. Control Tower + 3 Standalone Core Features + 1 Standalone Bonus AI

### Executive Control Tower (`/` — Shipped, Salman)
- **Role:** Zero-scroll public landing cockpit (`1280×800` & `1440×900`) on a slim `48px` navy topbar (`AI Co-Pilot →` CTA in `topbar_actions`, zero Band-1 title/dev clutter).
- **Live DB Readouts:** 4 clickable KPI drill-down cards (`Fleet Utilization → /trips/`, `Half-Empty Sailings → /trips/?half_empty=1`, `Est. 90-Day Savings` + live approved plan pill `→ /optimizer/`, `HSE & Fuel Flags → /safety/`) over a 2×2 clickable Chart.js grid (Vessel Utilization vs. Volume, Half-Empty vs. Healthy Runs by Destination, Consolidation Savings vs. Avoidable Idle Fuel, Fuel Telemetry & HSE Readiness Health with live `CB-07 Standby Lock` pill).

### Feature 1 — Trip Ticketing & Utilization Ledger (`/trips/` — Shipped, Salman)
- **Goal:** Zero-scroll 2-tab workspace (`Trip Ledger` and 3-step `Log New Trip` workflow) across all 976 historical trips, 12 seeded queue requests, and live PostgreSQL shift bookings, with server-side vessel overload protection, quick presets (including conditional Emerald `Consolidated` chip & `→ <trip_id>` badge), categorized `More Filters` modal, filtered CSV export, and centered `#trip-inspector-modal` (`KWD` fuel telemetry, corridor siblings, `Dispatch Consolidation` banner).
- **Standalone & Testable:** Judges submit a new crew/cargo trip request -> saved to PostgreSQL -> utilization bar and half-empty flag update cleanly and enter `/optimizer/`.

### Feature 2 — Dispatch Consolidation Optimizer (`/optimizer/` — Shipped, Salman)
- **Goal:** Gulf OSV zero-scroll 2-tab workspace (`Shift Queue Solver` and `Saved Plans & Backtest`):
  - **Same-Corridor Consolidation (`0.08` detour penalty) + Lowest-Cost Carrier Right-Sizing** across eligible `In Service` vessels.
  - **Optional `Allow Milk-Run` Toggle (`0.18` detour penalty):** Multi-stop consolidation across adjacent platforms (`Platform A ↔ Platform B ↔ Platform C`) for unpaired flexible runs.
  - **Hard HSE & Weather Guardrails:** Always blocks active `SafetyOverride` vessels/destinations (`CB-07 Standby Lock`), plus configurable **`HSE Strict Weather`** toggle (ON by default; OFF adds an amber `Rough Sea Advisory` for explicit supervisor sign-off) and explicit unmerged reasons in the `Held / Unmerged Queue`.
  - **Approve & Revert Persistence:** Checkbox cherry-picking -> atomic **`Approve & Save Plan`** (`DispatchPlan` + `consolidated` `Trip` linkage + `/` & `/trips/` cross-slice updates) + 1-click **`Revert Plan`** to restore pending runs and original vessels.

### Feature 3 — Safety & Fuel Anomaly Guard (`/safety/` — Active, Saleh)
- **Goal:** Detect physics-based fuel-burn outliers (`39` severe high outliers `>= 1.30×` up to `2.07×`, `8` low readings `<= 0.70×`, `15` missing logs) framed strictly as engineering investigation flags, surface vessel operational readiness across the **720 seeded `VesselAvailability` rows** (`585` Available, `97` Weather Restricted, `38` Maintenance — matching KJO `Idea_Starters`), and manage **3 live PostgreSQL `SafetyOverride` HSE rules** immediately enforced by `/optimizer/` and `/copilot/`:
  1. **Sea-State / Weather Hold** on a destination/zone.
  2. **Vessel Maintenance Hold** (1-click trigger from flagged fuel outliers or availability logs).
  3. **Standby Vessel Protection Lock** (`CB-07` pre-locked; toggleable/manageable in DB).
- **Standalone & Testable:** Judges inspect fuel anomalies and vessel availability, create/toggle an HSE hold saved to PostgreSQL, reload to verify persistence, and confirm `/optimizer/` immediately respects the active block.

### Feature 4 (Standalone Bonus AI) — AI Dispatch Co-Pilot (`/copilot/`, `core:copilot:index` — Next Sprint)
- **Owned Files:** `apps/optimizer/copilot_urls.py`, `apps/optimizer/copilot_views.py`, `templates/optimizer/copilot.html`.
- **Behaves Like a Standalone 4th Feature:** Dedicated topbar entry (`04 · AI`), topbar CTA from `/` and `/optimizer/`, and independent `/copilot/` URL with clear **Input → Output** + PostgreSQL persistence.
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

## 6. Current Sprint Status & Parallel Roadmap
- **Shipped on `main` (Salman):** Core frozen schema & `seed_fleet`, Zero-Scroll Executive Control Tower (`/`), Feature 1 (`/trips/` w/ 2-tab ledger + 3-step booking + centered `#trip-inspector-modal` + `Consolidated` cross-link), and Feature 2 (`/optimizer/` w/ corridor pooling, Milk-Run, HSE Strict Weather, Approve & Revert).
- **Active Now (Saleh):** Feature 3 (`/safety/`) — physics fuel-burn outliers (`39` high / `8` low / `15` missing), `VesselAvailability` readiness view (`720` rows), and live `SafetyOverride` CRUD integrated with `/optimizer/`.
- **Next Sprint:** Wire Feature 4 (`/copilot/` via `core:copilot:index`) with live `gemini-4-hydrogen` `ActionableDispatchBriefing` + final end-to-end Cloud Run QA (`https://crudeinference.com`) + hackathon submission before 17:00.

---

## 7. Judging Live Test Script (End-to-End < 3 Minutes)
1. Open `/` — Executive Control Tower loads immediately with zero login prompt, live PostgreSQL KPIs (from 976 KJO trips), and fleet utilization chart.
2. Open `/trips/` -> submit a half-empty `pending` trip request -> reload page to verify PostgreSQL persistence and half-empty flag.
3. Open `/safety/` -> inspect physics-based fuel anomalies (`TR-00012` 2.07×) -> click **Maintenance Hold** (or add a **Weather Hold**) -> reload to verify persistence.
4. Open `/optimizer/` -> run consolidation solver -> verify `CB-07` standby lock & active HSE holds block unsafe merges -> click **Approve & Save Plan** -> reload to verify persisted `DispatchPlan`.
5. Open `/copilot/` -> enter a shift directive or run Gemini 4 Dispatch Co-Pilot review -> inspect per-merge `Approve`/`Review`/`Hold` risk verdicts, apply an AI-recommended HSE hold, and save the shift handover briefing to PostgreSQL.
