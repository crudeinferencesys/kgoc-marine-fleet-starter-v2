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

## Key Code Anchors
- **Frozen Shared Models:** `apps/core/models.py`
- **Gemini Structured AI Wrapper:** `apps/core/ai.py` (`generate_structured`, `DispatchBriefing`) — uses **`gemini-4-hydrogen`** via `google-genai >= 3.5.0` Interactions API (never use legacy `gemini-2.5-*` or deprecated `temperature`/`top_p`/`top_k`)
- **Dataset Profiler CLI:** `apps/core/management/commands/inspect_dataset.py`
- **Shared Base Template (HTMX + DaisyUI + CSRF):** `templates/base.html`
- **Feature Slices:** `apps/trips/` (Teammate A), `apps/optimizer/` (Teammate B), `apps/safety/` (Shared/Coordinate)

## Quick Reminder Before Coding
- Are you on a `feat/*` branch (never `main`)?
- Did you avoid editing frozen shared files without explicit human confirmation?
- Did you run `python manage.py check && python manage.py makemigrations --check --dry-run && python manage.py test`?
