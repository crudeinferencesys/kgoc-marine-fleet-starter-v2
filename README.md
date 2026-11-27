# KGOC Marine Fleet Utilization & Optimization (Theme 4)

> **Live App URL:** https://kgoc-marine-fleet-93163341832.me-central1.run.app (Publicly accessible — no login required)

## Problem
Offshore marine fleet dispatchers supporting KGOC/KJO joint operations coordinate crew boats, utility boats, multipurpose vessels, and standby vessels across bases and offshore platforms. Without consolidated visibility, overlapping trips sail half-empty, fuel-burn anomalies go unnoticed, and dispatchers spend hours reconciling requests manually.

## Target User
Marine Fleet Dispatchers and Offshore Operations Supervisors planning daily vessel runs under passenger, cargo, and sea-state safety constraints.

## Solution
A responsive Django + HTMX web application backed by Cloud SQL PostgreSQL and hosted on Google Cloud Run that:
1. Tracks fleet utilization and logs new trip requests to PostgreSQL.
2. Runs a Python consolidation optimizer to eliminate under-utilized sailings while respecting capacity and safety rules.
3. Flags fuel-burn outliers and enforces live weather/standby constraints.
4. Embeds a Gemini AI Dispatch Co-Pilot (`google-genai` structured output) to explain trade-offs and draft shift handover briefings.

---

## The 3 Core Features
1. **Trips & Utilization (`apps/trips/`):** *(Fill exact judge test steps after final merge)*
2. **Dispatch Optimizer (`apps/optimizer/`):** *(Fill exact judge test steps after final merge)*
3. **Safety & Fuel Guard (`apps/safety/`):** *(Fill exact judge test steps after final merge)*

## Bonus AI Feature (Embedded Gemini Co-Pilot)
- **Inputs:** Current trip batch metrics, vessel capacities, consolidation candidates, and active weather/safety holds.
- **Logic:** Uses `google-genai` (`gemini-2.5-flash`) with Pydantic `DispatchBriefing` structured JSON output (`apps/core/ai.py`) to justify trip merges, flag operational risks, and summarize shift savings (with a deterministic fallback if unavailable).
- **How Judges Can Test:** Open `/optimizer/`, run optimization, and click **Generate AI Dispatch Briefing**.

---

## Data Used (Mock / Synthetic Disclaimer)
All data in this application is **mock/synthetic operational data** (derived from the hackathon's optional 8-vessel / 976-trip 90-day mock dataset and/or synthetic test fixtures) used strictly for demonstration. It does **not** represent live or proprietary KGOC operational records.

*(Document exact fuel price in KWD/L, charter cost assumptions, and any synthetic columns here before 17:00.)*

---

## Local Development Setup
```sh
uv venv --python 3.12 .venv
source .venv/bin/activate
uv pip install -r requirements.txt
cp .env.example .env
python manage.py migrate
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
- Designed as a 1-day hackathon MVP using mock/synthetic fleet data and assumed KWD fuel/charter rates.
- Optimization uses single-day heuristic/MILP grouping rather than real-time AIS/metocean telemetry integration.
