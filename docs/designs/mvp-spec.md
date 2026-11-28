# MVP Specification — Theme 4: Marine Fleet Utilization & Optimization

> **Status:** Pre-Kickoff Blueprint Locked (10:30 AM) — finalize Section 2 & confirm exact columns in Section 3 right after running `python manage.py inspect_dataset <path>` at 11:00 AM (fallback to synthetic generator if dataset is delayed >15 min), then run one focused Goldfish check before freezing `apps/core/models.py`.

---

## 1. Problem & Target User
- **Target User:** KGOC / KJO Offshore Marine Fleet Dispatchers & Marine Operations Supervisors managing crew boats (16–22 pax), utility boats (7–9 tons cargo), multipurpose vessels, and standby vessels operating between marine bases and offshore platforms.
- **Core Pain Point:** Frequent under-utilized / half-empty sailings, unflagged fuel-burn anomalies, and manual shift scheduling that misses safe consolidation opportunities across overlapping platform runs.

---

## 2. Organizer Dataset Inspection & Dual-Mode Data Strategy
- **Expected Source (11:00 AM):** Organizer-provided Theme 4 mock dataset (8 vessels, 976 trips over 90 days).
  - **15-Min Contingency Rule:** If the organizer dataset is unavailable or delayed >15 minutes past 11:00 AM, immediately fall back to a realistic synthetic `seed_fleet` generator (8 vessels, 976 completed trips over 90 days), clearly labeled as mock/synthetic data.
- **Actual Sheets & Columns Observed:** *(Paste `python manage.py inspect_dataset <path>` summary here at 11:00 AM)*
- **Key Edge Cases Observed:** *(e.g. cancellations, zero-cargo/pax positioning runs, missing timestamps, extreme fuel outliers)*
- **Dual-Mode Lifecycle (Historical + Live Shift Queue):**
  - Seed the **976 `completed` historical trips** across 90 days (powers `/trips/` utilization analytics, `/safety/` statistical fuel-burn anomaly detection, and the 90-day historical backtest headline in `/optimizer/`).
  - Seed **~12 mock `pending` "Today's Shift Queue" requests** alongside any new judge-booked trips submitted via `/trips/` so live consolidation, HSE constraint enforcement, and DB persistence work immediately on `/optimizer/`.

---

## 3. Draft Frozen Core Data Model (`apps/core/models.py` — Portable ORM Only)
*(Confirm exact column names/types at 11:00 AM after dataset inspection, implement once in `apps/core/models.py`, commit `0001_initial.py` + idempotent `seed_fleet` command to `main`, and freeze. Use portable Django ORM fields only — no Postgres-only column types.)*

- **`Vessel`**
  - `name`, `vessel_type` (`crew` / `utility` / `multipurpose` / `standby`), `pax_capacity`, `cargo_capacity_tons`, `hourly_fuel_lph`, `daily_charter_kwd`, `is_standby`, `status`
- **`Trip`**
  - `vessel` (`ForeignKey`), `origin`, `destination`, `departure_time`, `duration_hours`, `pax_count`, `cargo_tons`, `fuel_liters`, `weather_state`, `status` (`completed` / `pending` / `consolidated` / `cancelled`), `dispatch_plan` (nullable `ForeignKey`), `notes`
- **`DispatchPlan`**
  - `name`, `baseline_trips`, `optimized_trips`, `trips_eliminated`, `fuel_liters_saved`, `kwd_saved`, `co2_kg_saved`, `plan_payload` (`JSONField`), `ai_briefing` (`JSONField`), `ai_fallback_used`, `is_approved`
- **`SafetyOverride`**
  - `rule_type` (`weather_hold` / `maintenance_hold` / `standby_lock`), `vessel` (nullable `ForeignKey`), `platform_or_zone`, `source_trip` (nullable `ForeignKey`), `reason`, `is_active`

---

## 4. Control Tower + 3 Standalone Core Features + 1 Embedded Bonus AI

### Executive Control Tower (`/` — Salman)
- **Role:** Public landing hub (zero login wall, all developer starter text removed).
- **Live DB Readouts:** Live KPI strip (Fleet Utilization %, Half-Empty Runs, Est. 90-Day KWD / Fuel / CO₂ Savings, Active HSE Holds), one Chart.js fleet utilization visual, and 3 clear action cards into Features 1–3.

### Feature 1 — Trip Ticketing & Utilization Ledger (`apps/trips/`, Salman)
- **Goal:** Track utilization KPIs across all 976 historical trips and provide an HTMX trip booking form that saves new `pending` trip requests directly to PostgreSQL.
- **Standalone & Testable:** Judges submit a new crew/cargo trip request -> saved to DB -> utilization rate and half-empty flag appear immediately, and the `pending` trip enters the live Optimizer queue.

### Feature 2 — Dispatch Consolidation Optimizer (`apps/optimizer/`, Saleh)
- **Goal:** Python solver consolidating `pending` shift trips within safe passenger (16–22), cargo (7–9 t), time-window, and active `SafetyOverride` HSE constraints, plus a 90-day historical backtest headline across the 976 completed trips.
- **Standalone & Testable:** Judges click **Run Consolidation Solver** -> inspect trips eliminated, fuel liters saved, KWD saved, CO₂ reduced, and dispatcher hours saved -> click **Approve & Save Plan** to persist the consolidated schedule (`DispatchPlan`) to PostgreSQL.

### Bonus AI — Actionable Dispatch Co-Pilot (`apps/core/ai.py` + `apps/optimizer/`, Saleh)
- **Embedded AI Work:** Calls `gemini-4-hydrogen` via the `google-genai` Interactions API + Pydantic structured JSON output (with a deterministic fallback if `GEMINI_API_KEY` is missing or times out).
- **Visible App Impact (Required for Bonus Points):** Scores every proposed merge (`approve` / `review` / `hold` + risk badge + concise rationale), **automatically unchecks high-risk merges in the UI**, and saves the structured shift handover briefing inside `DispatchPlan` in PostgreSQL.

### Feature 3 — Safety & Fuel Anomaly Guard (`apps/safety/`, First Finisher)
- **Goal:** Detect statistical fuel-burn outliers per vessel/class across the 976 trips (quantifying excess liters & KWD wasted) and enforce **3 live PostgreSQL `SafetyOverride` HSE rules** that directly constrain `/optimizer/` and feed into the Gemini Co-Pilot:
  1. **Sea-State / Weather Hold** on a platform, zone, or fleet.
  2. **Vessel Maintenance Hold** (1-click trigger directly from any flagged fuel anomaly).
  3. **Standby Vessel Protection Lock** preventing standby boats from being pulled into routine cargo/pax consolidation.
- **Standalone & Testable:** Judges inspect flagged fuel outliers, create/toggle an HSE hold saved to PostgreSQL, reload to verify persistence, and confirm `/optimizer/` respects the active safety block.

---

## 5. Quantified Impact Formulas (Pillar 4 — Mock Benchmark Assumptions Clearly Labeled)
All KWD, fuel, CO₂, and dispatcher-hour figures use transparent mock operational benchmarks documented in `README.md`:
- **Trips Eliminated:** `baseline_trips - optimized_trips`
- **Fuel Saved (Liters):** `sum(eliminated_trip_expected_fuel) - consolidation_detour_penalty`
- **CO₂ Avoided (kg):** `fuel_liters_saved * ASSUMED_KG_CO2_PER_LITER` (benchmark: `2.68 kg CO₂/L`)
- **Cost Saved (KWD):** `(fuel_liters_saved * ASSUMED_DIESEL_KWD_PER_LITER) + (vessel_hours_saved * ASSUMED_HOURLY_OPERATING_KWD)` (benchmark baseline e.g. `0.150 KWD/L` marine diesel + vessel hourly operating rate)
- **Dispatcher Time Saved:** Estimated minutes saved per shift vs. manual spreadsheet matching.

---

## 6. 11:00 AM Kickoff & Parallel Execution Split (Salman vs. Saleh)
- **11:00 – 11:15 (Salman):** Inspect organizer dataset with `python manage.py inspect_dataset <path>` (trigger synthetic fallback if delayed >15 min).
- **11:15 – 11:40 (Salman):** Update Section 2 & 3 of this spec, run one focused Goldfish check, implement `apps/core/models.py` + `0001_initial.py` + idempotent `seed_fleet`, and merge **1 Schema PR** to `main`.
- **11:40 – 14:30 (Parallel):**
  - **Salman (`feat/trips-*`):** Feature 1 (`/trips/`) + Executive Control Tower (`/`).
  - **Saleh (`feat/optimizer-*`):** Feature 2 (`/optimizer/`) + Actionable Gemini Co-Pilot.
- **14:30 – 15:30 (`feat/safety-*`):** Whoever finishes first implements Feature 3 (`/safety/`) and wires `SafetyOverride` into `/optimizer/` and the Gemini prompt.
- **15:30 – 17:00:** Feature freeze at 15:30 -> end-to-end live Cloud Run smoke test -> finalize `README.md` with exact judge steps & mock-data disclaimer -> submit before 17:00.

---

## 7. Judging Live Test Script (End-to-End < 3 Minutes)
1. Open `/` — Executive Control Tower loads immediately with zero login prompt, live PostgreSQL KPIs, and fleet utilization chart.
2. Open `/trips/` -> submit a half-empty `pending` trip request -> reload page to verify PostgreSQL persistence and half-empty flag.
3. Open `/safety/` -> inspect statistical fuel-burn anomalies -> click **Maintenance Hold** (or add a **Weather Hold** / **Standby Lock**) -> reload to verify persistence.
4. Open `/optimizer/` -> run consolidation solver -> verify active HSE holds block unsafe merges -> click **AI Dispatch Co-Pilot** -> inspect per-merge risk badges, auto-unchecked high-risk merge, and handover brief -> click **Approve & Save Plan** -> reload to verify persisted `DispatchPlan`.
