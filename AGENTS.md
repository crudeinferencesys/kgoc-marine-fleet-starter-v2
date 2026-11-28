# AGENTS.md — KGOC AI Hackathon (Theme 4: Marine Fleet)

> **Purpose:** Shared operating manual for both teammates' AI coding agents.
> Read this and load `.agents/skills/kgoc-elephant/SKILL.md` before writing code.

---

## 1. Mission & Judging Guardrails (Non-Negotiable)
- **Theme:** Theme 4 — Marine Fleet Utilization & Optimization (8 vessels / 976 trips dataset + synthetic extensions clearly labeled as mock data).
- **Hard Scope Limit:** Build **at most 3 working core features** + **1 embedded Bonus AI feature**. Never add dark mode toggles, auth/login screens, static fluff, or extra sub-pages that dilute the 3 core features.
- **No Login Wall:** Every judging URL (`/`, `/trips/`, `/optimizer/`, `/safety/`) MUST be publicly accessible without authentication.
- **Persist to Database:** User inputs (new trips, approved optimization plans, safety overrides) MUST save to the database (`apps/core/models.py` / slice models -> Cloud SQL PostgreSQL in prod).
- **Quantify Impact (Pillar 4):** Every optimization/anomaly view must show concrete estimated savings (trips eliminated, fuel liters saved, KWD saved, or supervisor hours saved).

---

## 2. Strict Git & GitHub Guardrails (Guardrailed PRs)
Two AI agents are editing this repository in parallel, and merging to `main` **auto-deploys to Cloud Run**. Follow these rules strictly:

1. **NEVER commit or push directly to `main`.**
   - Always create or check out a short-lived feature branch:
     `feat/<slice>-<short-task>` (e.g. `feat/trips-ingest-csv`, `feat/optimizer-solver`, `feat/safety-anomalies`).
2. **Pull before branching:**
   - Start every task from an up-to-date `main`: `git fetch origin && git checkout -b feat/<slice>-<task> origin/main`.
3. **Respect Slice Ownership (Prevent Merge Conflicts):**
   - **Teammate A owns:** `apps/trips/**` and `templates/trips/**`
   - **Teammate B owns:** `apps/optimizer/**` and `templates/optimizer/**`
   - **Coordinate verbally before touching:** `apps/safety/**`, `templates/safety/**`, `apps/core/**`, `docs/designs/**`
4. **FROZEN SHARED FILES (DO NOT MODIFY WITHOUT EXPLICIT HUMAN APPROVAL IN CHAT):**
   - `apps/core/models.py` (shared schema & migrations — freezing prevents `0002` migration graph collisions!)
   - `config/settings.py`
   - `config/urls.py`
   - `templates/base.html`
   - `requirements.txt`
   - `Dockerfile`, `entrypoint.sh`
   If a feature needs a change to any frozen file, stop and ask the user in chat first so both teammates coordinate and merge it cleanly in one small PR.
5. **Mandatory Pre-Push Gate:**
   Before committing or pushing any branch, you MUST run and pass:
   ```sh
   python manage.py check && python manage.py makemigrations --check --dry-run && python manage.py test
   ```
   Do not commit if `makemigrations --check --dry-run` detects ungenerated migrations or if any test fails.
6. **PR Workflow (via `github-mcp-server` or `gh pr create`):**
   - Keep PRs small and frequent (every 45–60 minutes).
   - Fill out `.github/pull_request_template.md`.
   - **NEVER auto-merge your own PR into `main`.** Stop after opening the PR and give the human the PR link to review and click Merge.
7. **Parallel PRs & Merge Conflict Resolution:**
   - When both teammates open PRs on separate slices (`apps/trips/` vs `apps/optimizer/`), they merge cleanly back-to-back without conflicts.
   - If a teammate merges first and GitHub flags a merge conflict on your open PR:
     1. Run `git fetch origin && git merge origin/main` on your `feat/*` branch.
     2. Resolve conflicts carefully while **preserving both teammates' changes** (never overwrite the other teammate's slice code or migrations).
     3. Re-run the Mandatory Pre-Push Gate (`python manage.py check && python manage.py makemigrations --check --dry-run && python manage.py test`).
     4. Push the updated `feat/*` branch and wait for the human to click Merge.
8. **Secrets Hygiene:**
   - NEVER commit `.env`, API keys (`GEMINI_API_KEY`), service-account JSONs, `db.sqlite3`, or raw external CSV/XLSX data files unless explicitly approved.

---

## 3. Architecture & Stack Conventions
- **Backend:** Django 5.2 LTS. Local dev uses SQLite (`db.sqlite3`); Cloud Run prod uses Cloud SQL PostgreSQL via Unix socket (`/cloudsql/<CLOUD_SQL_CONNECTION_NAME>`).
- **SQLite / Postgres Parity Rule:** NEVER use PostgreSQL-only Django ORM fields (`ArrayField`, `HStoreField`, `CIEmailField`) or raw Postgres-specific SQL. Stick to portable Django ORM fields (`CharField`, `TextField`, `IntegerField`, `FloatField`, `DecimalField`, `BooleanField`, `DateTimeField`, `JSONField`, `ForeignKey`).
- **Frontend:** Zero-build CDN stack in `templates/base.html` (**Tailwind CSS Play CDN + DaisyUI 4.12 + HTMX 2 + Alpine.js 3 + Chart.js 4**).
  - Follow `docs/designs/design-system.md` strictly for palette, typography (`tabular-nums`), KPI cards, tables, HTMX loading states, Gemini AI Co-Pilot styling, and Chart.js configs so parallel slices look unified.
  - Rely on the global `hx-headers='{"X-CSRFToken": "{{ csrf_token }}"}'` already set on `<body>`.
  - Keep HTMX responses as small, focused HTML partials under `templates/<slice>/partials/`.
  - Design mobile-responsive layouts (`grid-cols-1 md:grid-cols-...`, DaisyUI cards/tables/badges).
- **Bonus AI Feature:** Always call Gemini through `apps/core/ai.py` (`generate_structured(...)`) using **`gemini-4-hydrogen`** (`GEMINI_MODEL=gemini-4-hydrogen` in `.env` and Cloud Run) on the **`google-genai >= 3.5.0` Interactions API** (`client.interactions.create(...)`) + Pydantic schemas. **NEVER** use deprecated/legacy models (`gemini-2.5-*`, `gemini-2.0-*`, `gemini-1.5-*`), **NEVER** import legacy `google-generativeai`, and **NEVER** pass deprecated `temperature`/`top_p`/`top_k` to Gemini 4 (tune `thinking_level` instead). Every AI-powered endpoint MUST include a deterministic fallback message/output when `GEMINI_API_KEY` is unset or times out.

---

## 4. EGM Lite Cadence (Quota-Conscious Context Sharing)
Both teammates share one Google AI Ultra Antigravity quota pool and a 6-hour sprint window:
1. **Load context first:** Read `.agents/skills/kgoc-elephant/SKILL.md` and `docs/designs/SITEMAP.md`.
2. **One upfront Goldfish check:** At kickoff (after running `python manage.py inspect_dataset <path>` and updating `docs/designs/mvp-spec.md`), run **one** focused Goldfish review (`/egm:egm-review-loop` using `design_critic` + `implementation_readiness`) on `docs/designs/mvp-spec.md`.
3. **No mid-sprint 5-stage EGM swarms:** Once `apps/core/models.py` and `docs/designs/mvp-spec.md` are merged to `main`, build in fast vertical slices with normal tests + PR reviews instead of spawning heavy multi-agent review swarms on every small edit.
4. **Update docs only when contracts change:** If a schema or feature contract changes, update `docs/designs/mvp-spec.md` in the same PR so your teammate's Elephant stays in sync.
