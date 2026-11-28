# Architecture Blueprint — KGOC Marine Fleet MVP

## 1. Deployment & Runtime (100% Google Cloud)
- **Live Domain & Compute:** `https://crudeinference.com` → Google Cloud Run (`me-central1`, `https://kgoc-marine-fleet-93163341832.me-central1.run.app`). Container startup runs `entrypoint.sh` → `manage.py migrate --noinput` → `manage.py seed_fleet --if-empty` → `gunicorn` on `$PORT` (`120s` timeout, `1Gi` memory, `max-instances=3`).
- **Database:**
  - Production: Cloud SQL for PostgreSQL 16 connected over Unix socket (`/cloudsql/<CLOUD_SQL_CONNECTION_NAME>`), `CONN_HEALTH_CHECKS: True`.
  - Local dev: SQLite (`db.sqlite3`) on laptops so both teammates can work fast over phone hotspots without Cloud SQL Auth Proxy.
  - Portability rule: Portable Django ORM fields only (no Postgres-only column types).
- **CI/CD:** GitHub Actions CI + Cloud Build trigger on pushes/merges to GitHub `main` -> builds container in Google Cloud -> deploys new Cloud Run revision automatically. Zero large Docker uploads over phone hotspots.
- **Static Files:** WhiteNoise (`CompressedStaticFilesStorage`) serving collected static assets directly from the Cloud Run container.

## 2. Application Stack
- **Backend:** Django 5.2 LTS + Python 3.12 (`pandas`, `scipy`, `openpyxl`, `google-genai >= 3.5.0`, `pydantic`).
- **Frontend:** Django Templates + HTMX 2 + Tailwind CSS Play CDN + DaisyUI 4.12 + Alpine.js 3 + Chart.js 4 in a slim `48px` zero-scroll shell (`templates/base.html`, zero Node build step, global `X-CSRFToken` header on `<body>`).
- **In-App Bonus AI:** `google-genai >= 3.5.0` Interactions API (`apps/core/ai.py`) calling `gemini-4-hydrogen` with Pydantic structured JSON outputs (`DispatchBriefing`, `MergeRiskAssessment`, `ActionableDispatchBriefing`), `GEMINI_API_KEY` from Google AI Studio / Secret Manager, and deterministic fallbacks on timeout or missing key.

## 3. Security & Judging Access
- **Public Judging Access:** Zero login/authentication wall on all routes (`/`, `/trips/`, `/optimizer/`, `/safety/`, `/copilot/`, `/health/` — note Cloud Run reserves `/healthz`, so `/health/` is used externally and omitted from the navbar chrome).
- **Proxy & CSRF:** `SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")` and `CSRF_TRUSTED_ORIGINS` includes `https://*.run.app` so HTMX POST requests work cleanly behind Cloud Run TLS termination.
