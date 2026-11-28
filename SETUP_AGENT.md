# SETUP_AGENT.md — Automated Laptop & GCP Bootstrap Runbook

> **How to use this file:** Open this repository in Antigravity (**Antigravity App**, **Antigravity for IDEs**, or `agy` CLI — **NOT** standalone Antigravity IDE) and prompt:
> - On Teammate A's laptop (Repo Owner + GCP Owner): `"Follow SETUP_AGENT.md for Laptop A"`
> - On Teammate B's laptop (Collaborator): `"Follow SETUP_AGENT.md for Laptop B"`

---

## Agent Execution Rules
1. Determine the laptop role first (`Laptop A` = Repo Owner + GCP Owner; `Laptop B` = Collaborator). If the user did not specify which laptop this is, ask before running commands.
2. Execute `[AUTO]` steps directly without unnecessary confirmation.
3. At every `[PAUSE FOR HUMAN]` step, stop and give the user clear, copy-pasteable instructions for the interactive browser OAuth login, secret paste, or UI click—do NOT attempt to bypass authentication or invent credentials.
4. **Never echo, log, or commit secrets** (`GEMINI_API_KEY`, `DB_PASSWORD`, `DJANGO_SECRET_KEY`, `.env`).
5. **Never commit or push directly to `main`.** Even the setup verification PR in Phase 3 MUST use a `feat/*` branch and wait for the human to click Merge.

---

## Pre-Flight Check (Both Laptops)

### 1. `[AUTO]` Check OS, CLIs & Python Tooling
Run a single diagnostic command to check OS, `git`, `gh`, `uv`, `python3`, and (for Laptop A) `gcloud`:
- **macOS:** Check `uname -s`, `which git gh uv python3 gcloud`. Install any missing tool via Homebrew (`brew install git gh uv` and `brew install --cask google-cloud-sdk` for Laptop A).
- **Windows:** Check `git --version`, `gh --version`, `uv --version`, `gcloud --version`. If missing, guide or install via `winget install Git.Git GitHub.cli astral-sh.uv` (and `Google.CloudSDK` for Laptop A).

### 2. `[AUTO + PAUSE IF MISSING]` Verify Antigravity Plugins & Context
1. Confirm `AGENTS.md` and `.agents/skills/kgoc-elephant/SKILL.md` are readable.
2. Verify which plugins/tools are active:
   - Required on **both** laptops: `egm` (and confirm `invoke_subagent` works, proving the user is NOT in standalone Antigravity IDE), `github-mcp-server`, `context7`, `gemini-api`, and `google-cloud-developer`.
   - If `github-mcp-server` is unauthenticated, pause and instruct the user to sign in via the Plugins Manager (to their **own** GitHub account on that laptop).
   - Remind the user to **disable unused plugins** (`n8n-skills`, `vercel-plugin`, `gdrive`, etc.) so unused MCP tool schemas do not consume the shared Family Antigravity quota.

---

## Phase 1 — Git, GitHub CLI & Local Django Verification (Both Laptops)

### 1. `[AUTO + PAUSE IF MISSING]` Git Identity & GitHub CLI Auth
1. Check `git config --get user.name` and `git config --get user.email`. If unset, ask the user for their name and GitHub email and set both.
2. Check `gh auth status`.
   - `[PAUSE FOR HUMAN]` if not logged in: tell the user to run `gh auth login` (choose `GitHub.com -> HTTPS -> Yes -> Login with a web browser`) in their terminal and reply when complete.
3. Check `git remote -v`:
   - Confirm `origin` points to the **team repository** (`<AccountA>/kgoc-marine-fleet-starter`), **not** upstream `Salmanisco/kgoc-marine-fleet-starter` (unless `<AccountA>` intentionally owns it). Warn immediately if `origin` points to the wrong repo or if the two laptops cloned different forks.
4. Run `git fetch origin && git status` to confirm `origin/main` is reachable and the working tree is clean.

### 2. `[AUTO]` Create Virtualenv & Install Dependencies
```sh
uv venv --python 3.12 .venv
# macOS/Linux:
uv pip install --python .venv/bin/python -r requirements.txt
# Windows PowerShell:
# uv pip install --python .venv\Scripts\python.exe -r requirements.txt
```

### 3. `[PAUSE FOR HUMAN]` Configure Local `.env`
1. `[AUTO]` If `.env` does not exist, copy `.env.example` to `.env`.
2. Check (without printing its value!) whether `GEMINI_API_KEY=` in `.env` has a non-empty value.
3. `[PAUSE FOR HUMAN]` if empty: ask the user to paste their Google AI Studio `GEMINI_API_KEY` into `.env` locally (never paste secrets into chat if avoidable, or delete/do not commit `.env`).

### 4. `[AUTO]` Run Full Local Django Verification & Live Smoke Test
Run inside the project root using `.venv/bin/python` (or `.venv\Scripts\python.exe` on Windows):
1. `python manage.py migrate --noinput`
2. `python manage.py check`
3. `python manage.py makemigrations --check --dry-run`
4. `python manage.py test`
5. `python manage.py inspect_dataset --help`
6. Start a brief local test (`manage.py runserver 127.0.0.1:8009` in background for 3 seconds, curl `http://127.0.0.1:8009/`, `http://127.0.0.1:8009/health/`, and `http://127.0.0.1:8009/trips/`, then stop the server). Verify `/health/` returns `{"status": "ok", "database": "sqlite3", "ai_configured": true, "gemini_model": "gemini-4-hydrogen"}` (or note if `GEMINI_API_KEY` was intentionally left blank).

> **Laptop B Checkpoint:** If this is **Laptop B**, **STOP HERE**, print the Final Status Summary Table, and confirm readiness for tomorrow's `feat/optimizer-*` or `feat/trips-*` branch workflow.

---

## Phase 2 — 100% GCP Provisioning (Laptop A ONLY)

### 1. `[AUTO + PAUSE IF MISSING]` Verify `gcloud` Auth & Billing
1. Check `gcloud auth list --filter=status:ACTIVE --format="value(account)"` and `gcloud auth application-default print-access-token >/dev/null 2>&1`.
   - `[PAUSE FOR HUMAN]` if either is missing: tell the user to run `gcloud auth login` and `gcloud auth application-default login` in their terminal.
2. Run `gcloud projects list` and `gcloud billing accounts list`.
   - `[PAUSE FOR HUMAN]`: Ask the user to confirm:
     1. Which billing account ID to link (the one with their AI Studio / Google AI Ultra credits + \$5 prepayment).
     2. Whether to create a new GCP project (`kgoc-fleet-<YYMMDD>`) or reuse an existing AI Studio project.
     3. Region (`me-central1` recommended; fallback `europe-west1` or `us-central1` if needed).

### 2. `[AUTO]` Enable APIs, IAM & Cloud SQL PostgreSQL 16
Once confirmed, run with the chosen `PROJECT_ID`, `BILLING_ACCOUNT_ID`, and `REGION`:
1. Create/select project and link billing (`gcloud projects create` if new, `gcloud config set project "$PROJECT_ID"`, `gcloud billing projects link`).
2. Enable APIs:
   ```sh
   gcloud services enable \
     run.googleapis.com \
     sqladmin.googleapis.com \
     cloudbuild.googleapis.com \
     artifactregistry.googleapis.com
   ```
3. Grant Cloud Run's default runtime service account Cloud SQL access:
   ```sh
   PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format="value(projectNumber)")
   gcloud projects add-iam-policy-binding "$PROJECT_ID" \
     --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
     --role="roles/cloudsql.client"
   ```
4. Provision Cloud SQL PostgreSQL 16 (`db-f1-micro`, 10GB HDD, instance `kgoc-pg`), database `kgoc_fleet`, and user `kgoc_app` with a strong generated password (store `DB_PASS` only in shell env during deploy — never write to tracked files or echo in chat).
   - If `me-central1` returns a region/quota error on a brand-new account, notify the user and retry in `europe-west1`.

### 3. `[AUTO]` Initial Cloud Run Deploy & Live Production Verification
1. Read `GEMINI_API_KEY` from local `.env` into a shell variable without printing it, generate a fresh `DJANGO_SECRET_KEY` (`openssl rand -hex 32`), and run:
   ```sh
   gcloud run deploy kgoc-marine-fleet \
     --source . \
     --region "$REGION" \
     --allow-unauthenticated \
     --add-cloudsql-instances "$CLOUD_SQL_CONNECTION_NAME" \
     --set-env-vars "DEBUG=False,DJANGO_SECRET_KEY=$DJANGO_SECRET_KEY,CLOUD_SQL_CONNECTION_NAME=$CLOUD_SQL_CONNECTION_NAME,DB_NAME=kgoc_fleet,DB_USER=kgoc_app,DB_PASSWORD=$DB_PASS,GEMINI_API_KEY=$GEMINI_API_KEY,GEMINI_MODEL=gemini-4-hydrogen"
   ```
2. Capture the deployed Cloud Run URL (`SERVICE_URL`) and verify live endpoints via `curl` (note Cloud Run reserves `/healthz`, so use `/health/`):
   - `curl -sf "$SERVICE_URL/health/"` -> MUST show `"status": "ok"`, `"database": "postgresql"`, and `"ai_configured": true`.
   - `curl -sf -o /dev/null -w "%{http_code}" "$SERVICE_URL/"` -> `200`.
   - `curl -sf -o /dev/null -w "%{http_code}" "$SERVICE_URL/trips/"` -> `200`.
   - `curl -sf -o /dev/null -w "%{http_code}" "$SERVICE_URL/optimizer/"` -> `200`.
   - `curl -sf -o /dev/null -w "%{http_code}" "$SERVICE_URL/safety/"` -> `200`.

---

## Phase 3 — GitHub Continuous Deployment & PR Smoke Test (Laptop A ONLY)

### 1. `[PAUSE FOR HUMAN]` Connect GitHub Repo to Cloud Run
Guide the user through the 1-minute Cloud Console click path:
1. Open **Google Cloud Console -> Cloud Run -> `kgoc-marine-fleet`**.
2. Click **Set up continuous deployment** (or **Edit continuous deployment**).
3. Connect GitHub and select `<AccountA>/kgoc-marine-fleet-starter`.
4. Set Branch regex to `^main$` and Build Type to **Dockerfile** (`/Dockerfile`), then save.

### 2. `[AUTO]` Open Verification PR #1 (Testing Guardrailed PRs + Auto-Deploy)
1. Ensure we are up to date on `main` and create a feature branch:
   ```sh
   git fetch origin && git checkout -b feat/docs-live-url origin/main
   ```
2. Replace `<ADD_CLOUD_RUN_URL_BEFORE_SUBMISSION>` in `README.md` with the verified `$SERVICE_URL`.
3. Run the mandatory pre-push gate:
   ```sh
   .venv/bin/python manage.py check && .venv/bin/python manage.py makemigrations --check --dry-run && .venv/bin/python manage.py test
   ```
4. Commit, push `feat/docs-live-url`, and open PR #1 via `github-mcp-server` or `gh pr create`. **Do NOT auto-merge.**

### 3. `[PAUSE FOR HUMAN + AUTO VERIFY]` Human Merges PR #1 -> Verify Cloud Build
1. Give the user the PR #1 link and ask them to click **Merge pull request** on GitHub.
2. Once the user confirms merged, check `gcloud builds list --limit=3` (Wait until the triggered build finishes `SUCCESS`) and re-verify `curl -sf "$SERVICE_URL/health/"`.

---

## Final Status Summary (Agent Must Output at End)
Print a table with `PASS` / `FAIL` / `MANUAL` for:
- Laptop Role (`A` or `B`)
- Antigravity Harness + Required Plugins (`egm` + `invoke_subagent`, `github-mcp-server`, `google-cloud-developer`, `gemini-api`, `context7`)
- `gh` CLI + Correct Team Repo `origin`
- Local `.venv`, `.env` (`GEMINI_API_KEY`), `manage.py check`, `makemigrations --check`, `manage.py test`
- *(Laptop A only)* Cloud SQL Postgres (`kgoc-pg`), Cloud Run (`$SERVICE_URL/health/` -> `postgresql`), and GitHub Continuous Deployment (`^main$`)
