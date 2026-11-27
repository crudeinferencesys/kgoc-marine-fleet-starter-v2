# Tonight & Kickoff Setup Runbook

Follow this checklist in order tonight so both laptops, GitHub, Antigravity, and 100% GCP hosting are verified before tomorrow morning.

> **Shortcut for Steps 3 & 4:** Once you have created the team GitHub repo and cloned it on each laptop, you can let Antigravity automate local setup, tests, and GCP provisioning using [SETUP_AGENT.md](SETUP_AGENT.md):
> - **Laptop A:** `"Follow SETUP_AGENT.md for Laptop A"`
> - **Laptop B:** `"Follow SETUP_AGENT.md for Laptop B"`

---

## 0. URGENT (Before 11:00 PM Tonight) — CODED Portal Registration
- [ ] Both teammates sign in to the **CODED Hackathon Portal** (email + OTP), create/join your team, and confirm both members appear on the same team before **11:00 PM (Friday, Nov 27)**.

---

## 1. Google Accounts + Family Sharing + AI Ultra + GCP Credits
1. Create the two new Google accounts under the **exact same billing country** (required for Google Family Sharing).
2. **Account A (Family Manager):**
   - Subscribe to **Google AI Ultra** (\$200).
   - Create a **Google Family Group** and invite **Account B**.
   - Keep your existing Antigravity account signed in on a separate browser/profile as a **hot fallback** in case a brand-new account hits a card/risk verification hold overnight.
3. **Claim Google Cloud / AI Studio Credits (Account A):**
   - Sign in to [Google AI Studio](https://aistudio.google.com) with **Account A**.
   - Claim the monthly Google Cloud / Gemini API credits included with AI Ultra and link a Cloud Billing account (requires the **\$5 minimum prepayment deposit**).
   - Generate **one `GEMINI_API_KEY`** in AI Studio and save it in a shared password manager / 1Password note (never commit it to Git).

---

## 2. GitHub Setup (Avoid the Double-Fork Trap!)
> **Important:** Do **NOT** both fork the starter repo into two separate forks, or you will split your PRs across two repos.

1. On **Account A's GitHub**, import or fork `Salmanisco/kgoc-marine-fleet-starter` (make it **Public** so GitHub Free enforces branch protection and secret push protection).
2. On that single team repo (`<AccountA>/kgoc-marine-fleet-starter`), go to **Settings -> Collaborators** and invite **Account B** with **Write** access.
3. Confirm visibility is **Public** (**Settings -> General -> Danger Zone -> Change visibility -> Make public**).
4. Go to **Settings -> Branches -> Add classic branch protection rule** for `main`:
   - Check **Require a pull request before merging** (`0` required approvals so either teammate can merge after a quick 30-second check).
   - Leave **Require branches to be up to date before merging** **UNCHECKED** (so parallel slice PRs merge back-to-back cleanly).
   - Check **Do not allow bypassing the above settings**.
   - Optionally block force pushes (and leave **Allow force pushes** unchecked).
5. Go to **Settings -> Code security** and enable **Secret scanning** and **Push protection**.
6. **Both laptops** clone the **exact same** team repository:
   ```sh
   git clone <TEAM_REPO_URL>
   cd kgoc-marine-fleet-starter
   ```

---

## 3. Laptop Setup & Plugin Diet (Both Laptops)
1. **Install local prerequisites:**
   - `git`, `gh` (`gh auth login` on each teammate's GitHub account), `uv` (or Python 3.12), and `gcloud` CLI (required on Account A tonight).
2. **Verify local app works:**
   ```sh
   uv venv --python 3.12 .venv
   source .venv/bin/activate
   uv pip install -r requirements.txt
   cp .env.example .env
   # Paste GEMINI_API_KEY into .env
   python manage.py migrate
   python manage.py check && python manage.py test
   python manage.py runserver
   ```
   Open `http://127.0.0.1:8000` and click **Test HTMX + CSRF** on one slice.
3. **Antigravity Harness & Plugins (Critical for EGM!):**
   - Use **Antigravity App**, **Antigravity for IDEs**, or **`agy` CLI** — do **NOT** use standalone Antigravity IDE if `invoke_subagent` is unavailable, because EGM Goldfish reviews require fresh subagents.
   - Install/verify these plugins on both accounts:
     - `egm` (`agy plugin install https://github.com/google/elephant-goldfish-model`)
     - `github-mcp-server` (signed in to each teammate's GitHub account)
     - `context7`
     - `google-cloud-developer`
     - `gemini-api`
   - **Plugin Diet:** Disable unused plugins (such as `n8n-skills`, `vercel-plugin`, `gdrive`) tomorrow to reduce MCP schema token overhead on your shared Family Antigravity quota.

---

## 4. 100% GCP Setup Tonight (Account A's Laptop)
Run these on **Account A** to provision Cloud SQL PostgreSQL + Cloud Run + GitHub auto-deploy tonight:

```sh
# 1. Authenticate & create/select your hackathon GCP project
gcloud auth login
export PROJECT_ID="kgoc-fleet-$(date +%y%m%d)"
export REGION="me-central1"   # Close to Kuwait (Dammam); or use us-central1 / europe-west1 if preferred
export DB_INSTANCE="kgoc-pg"
export DB_NAME="kgoc_fleet"
export DB_USER="kgoc_app"
export DB_PASS="CHANGE_TO_STRONG_PASSWORD"
export SERVICE_NAME="kgoc-marine-fleet"

gcloud projects create "$PROJECT_ID" --name="KGOC Marine Fleet"
gcloud config set project "$PROJECT_ID"
# Link your AI-Studio/credits billing account in Cloud Console Billing or via:
# gcloud billing accounts list
# gcloud billing projects link "$PROJECT_ID" --billing-account="YOUR_BILLING_ACCOUNT_ID"

# 2. Enable required GCP APIs
gcloud services enable \
  run.googleapis.com \
  sqladmin.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com

# 3. Provision Cloud SQL PostgreSQL 16 (takes ~5-10 min)
gcloud sql instances create "$DB_INSTANCE" \
  --database-version=POSTGRES_16 \
  --tier=db-f1-micro \
  --region="$REGION" \
  --storage-type=HDD \
  --storage-size=10GB

gcloud sql databases create "$DB_NAME" --instance="$DB_INSTANCE"
gcloud sql users create "$DB_USER" --instance="$DB_INSTANCE" --password="$DB_PASS"

export CLOUD_SQL_CONNECTION_NAME=$(gcloud sql instances describe "$DB_INSTANCE" --format="value(connectionName)")
echo "CLOUD_SQL_CONNECTION_NAME=$CLOUD_SQL_CONNECTION_NAME"

# 4. Initial Cloud Run deploy from source (verifies Dockerfile + Cloud SQL socket tonight)
gcloud run deploy "$SERVICE_NAME" \
  --source . \
  --region "$REGION" \
  --allow-unauthenticated \
  --add-cloudsql-instances "$CLOUD_SQL_CONNECTION_NAME" \
  --set-env-vars "DEBUG=False,DJANGO_SECRET_KEY=$(openssl rand -hex 32),CLOUD_SQL_CONNECTION_NAME=$CLOUD_SQL_CONNECTION_NAME,DB_NAME=$DB_NAME,DB_USER=$DB_USER,DB_PASSWORD=$DB_PASS,GEMINI_API_KEY=YOUR_GEMINI_API_KEY,GEMINI_MODEL=gemini-2.5-flash"
```

### Verify Live URL Tonight
1. Copy the printed Cloud Run URL (`https://kgoc-marine-fleet-....run.app`).
2. Visit `https://<URL>/healthz` — confirm it returns:
   `{"status": "ok", "database": "postgresql", "ai_configured": true}`
3. Visit `https://<URL>/trips/` and click **Test HTMX + CSRF** — confirm green success banner (proves HTTPS proxy headers + CSRF + Cloud Run all work!).

### Connect GitHub Auto-Deploy (Ideal for Phone Hotspots)
1. In **Google Cloud Console -> Cloud Run -> `kgoc-marine-fleet` -> Integrations / Set up Continuous Deployment**:
   - Connect your GitHub team repo (`<AccountA>/kgoc-marine-fleet-starter`).
   - Branch regex: `^main$`
   - Build type: `Dockerfile`
2. Test with one small PR merge (e.g., adding your live URL to `README.md`) tonight so tomorrow **every PR merged to `main` builds inside GCP and auto-deploys** without eating phone hotspot bandwidth.
   *(Fallback if Cloud Build ever stalls: run `gcloud run deploy "$SERVICE_NAME" --source . --region "$REGION"` manually from Account A.)*

### Saturday Night Cost Reminder (Post-Judging)
- Cloud SQL (`db-f1-micro`) bills continuously while running. After Saturday's Closing Ceremony, stop or delete `$DB_INSTANCE` (`gcloud sql instances patch "$DB_INSTANCE" --activation-policy=NEVER` or `delete`) so it doesn't burn credits idle.

---

## 5. Tomorrow's 6-Hour Sprint Plan (Saturday, 11:00 – 17:00)
- **11:00 – 11:20:** Ask organizers for the Theme 4 mock dataset (8 vessels, 976 trips). Run `python manage.py inspect_dataset <file>` and paste schema notes into `docs/designs/mvp-spec.md`.
- **11:20 – 11:45:** Run **one** focused Goldfish review (`/egm:egm-review-loop` with `design_critic` + `implementation_readiness`) on `docs/designs/mvp-spec.md`. Lock and merge `apps/core/models.py` + `seed_fleet` management command to `main`.
- **11:45 – 14:30:** Parallel `feat/*` branches:
  - **Teammate A:** `apps/trips/` (Feature 1 — dashboard, utilization KPIs, trip booking form saved to DB).
  - **Teammate B:** `apps/optimizer/` (Feature 2 — Python consolidation solver, KWD/fuel math, `apps/core/ai.py` Gemini Dispatch Co-Pilot).
  - Merge small PRs every 45–60 min.
- **14:30 – 15:30:** Feature 3 (`apps/safety/` — fuel-burn outlier detection + weather/standby overrides) + wire optimizer to respect safety overrides.
- **15:30:** **Feature freeze.** No new features after 15:30.
- **15:30 – 16:30:** End-to-end live Cloud Run smoke test (no login wall, DB persistence across page reloads, live Gemini button, fallback test, update `README.md` with exact judging test steps & mock-data disclaimer).
- **16:30 – 17:00:** Submit live URL, source code, and `README.md` on the CODED portal before **17:00**.
