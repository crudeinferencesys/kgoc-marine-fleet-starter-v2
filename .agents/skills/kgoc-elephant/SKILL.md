---
name: kgoc-elephant
description: >-
  Project Elephant context loader for the KGOC AI Hackathon (Theme 4: Marine Fleet
  Utilization & Optimization). Load at session start or after compaction to align
  with frozen schema, slice boundaries, Git PR rules, and judging criteria.
---

# KGOC Marine Fleet — Project Elephant Context

Read these authoritative files in order before proposing architecture or editing code:

1. **Operating Rules & Git Guardrails:** [AGENTS.md](../../../AGENTS.md)
2. **Hackathon Rules & Judging Criteria:** [docs/hackathon_brief.md](../../../docs/hackathon_brief.md)
3. **Design Sitemap & Slice Ownership:** [docs/designs/SITEMAP.md](../../../docs/designs/SITEMAP.md)
4. **Technical Architecture:** [docs/designs/architecture.md](../../../docs/designs/architecture.md)
5. **MVP Feature & Data Spec:** [docs/designs/mvp-spec.md](../../../docs/designs/mvp-spec.md)
6. **UI Design System (Mandatory for All Templates & Charts):** [docs/designs/design-system.md](../../../docs/designs/design-system.md)

## Key Code Anchors & Live Slice Status
- **Frozen Shared Schema & Constants:** `apps/core/models.py` (`Vessel`, `VesselAvailability`, `Trip`, `DispatchPlan`, `SafetyOverride`), `apps/core/constants.py` (Pillar 4 mock rates & detour factors).
- **Gemini Structured AI Wrapper:** `apps/core/ai.py` (`generate_structured`, `DispatchBriefing`, `MergeRiskAssessment`, `ActionableDispatchBriefing`) — uses **`gemini-4-hydrogen`** via `google-genai >= 3.5.0` Interactions API (never use legacy `gemini-2.5-*` or deprecated `temperature`/`top_p`/`top_k`).
- **Shared Slim Chrome (`48px`):** `templates/base.html` (HTMX + DaisyUI + Alpine + Chart.js + global `X-CSRFToken`; `/health/` stays out of navbar).
- **Control Tower (`/` — Shipped, Salman):** `apps/core/services.py`, `templates/core/home.html` (4 clickable KPIs w/ live approved-plan pill + 2×2 clickable Chart.js grid).
- **Feature 1 (`apps/trips/`, `/trips/` — Shipped, Salman):** Zero-scroll 2-tab ledger + 3-step `Log New Trip` workflow, `Consolidated` status/preset chip, centered `#trip-inspector-modal` (`KWD` telemetry + `Dispatch Consolidation` banner), filtered CSV export.
- **Feature 2 (`apps/optimizer/`, `/optimizer/` — Shipped, Salman):** Corridor consolidation (`0.08` penalty) + lowest-cost carrier right-sizing, optional `Platform A/B/C` Milk-Run (`0.18` penalty), `HSE Strict Weather` + hard `SafetyOverride` blocks (including fleet-wide weather holds), atomic `Approve & Save Plan`, 1-click `Revert Plan`, and 90-day 5-corridor backtest.
- **Feature 3 (`apps/safety/`, `/safety/` — Shipped, Saleh — PR #22/#23):** Physics fuel anomaly engineering investigation flags (`39` high / `8` low / `15` missing, `880 KWD · mock`), centered `#safety-inspector-modal` with **720 seeded `VesselAvailability` records**, 1-click `Maintenance Hold`, and 3-step `Add HSE Hold` CRUD (`weather_hold`, `maintenance_hold`, `standby_lock`) enforced by `/optimizer/`.
- **Feature 4 (Bonus AI `/copilot/` — Shipped, PR #25):** `apps/optimizer/copilot_urls.py`, `apps/optimizer/copilot_views.py`, `apps/optimizer/copilot_services.py`, `apps/optimizer/copilot_tests.py`, `templates/optimizer/copilot.html`, `templates/optimizer/partials/copilot_workspace.html` (URL names `core:copilot:index`, `review`, `save_briefing`, `approve_recommended`, `apply_hold`, `ping`; **88 automated tests passing across all 4 slices**).

## Quick Reminder Before Coding
- Are you on a `feat/*` branch off up-to-date `origin/main` (never `main`)?
- Did you avoid editing frozen shared files without explicit human confirmation?
- Do your views stay zero-scroll at `1280×800` and `1440×900`, omit emojis, and omit dev/DB/model badges (`DB: sqlite3`, `gemini-4-hydrogen`)?
- Are fuel anomalies framed as engineering investigation flags (never misconduct claims), blank fuel logs treated as missing telemetry, and all KWD/CO₂ estimates qualified as `· mock`?
- Did you run `python manage.py check && python manage.py makemigrations --check --dry-run && python manage.py test`?
