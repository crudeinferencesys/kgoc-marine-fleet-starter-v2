# Design Sitemap (EGM Lite)

Index of active specifications, frozen boundaries, and team ownership.

## Documents
| Document | Purpose | Status |
|---|---|---|
| [hackathon_brief.md](../hackathon_brief.md) | Official KGOC + CODED workshop rules & Theme 4 summary | Reference |
| [architecture.md](architecture.md) | Stack, GCP Cloud Run + Cloud SQL, HTMX, Gemini AI wrapper | Locked |
| [design-system.md](design-system.md) | Maritime Control Tower palette, `48px` chrome, zero-scroll contract, modal/workflow patterns | Locked — follow for all UI & charts |
| [mvp-spec.md](mvp-spec.md) | Theme 4 dataset schema, shipped Control Tower + Features 1–4, KWD math | Synced with Shipped Control Tower + Features 1–4 (`88` tests passing) |

## Vertical Slice Ownership & Live Status
| Slice | Paths | Owner & Status |
|---|---|---|
| Core Shell & Frozen Schema | `apps/core/models.py`, `constants.py`, `ai.py`, `templates/base.html`, `config/` | Shared (**Frozen**; slim `48px` chrome shipped) |
| Control Tower (`/`) + Feature 1 (`/trips/`) | `apps/core/services.py`, `templates/core/home.html`, `apps/trips/**`, `templates/trips/**` | **Salman** — **Shipped** |
| Feature 2: Dispatch Optimizer (`/optimizer/`) | `apps/optimizer/services.py`, `views.py`, `urls.py`, `tests.py`, `templates/optimizer/index.html`, `partials/workspace.html` | **Salman** — **Shipped** (PR #24) |
| Feature 3: Safety & Fuel Guard (`/safety/`) | `apps/safety/**`, `templates/safety/**` | **Saleh** — **Shipped** (PR #22, #23; SafetyOverrides + Fuel Anomalies + 720 `VesselAvailability` rows) |
| Feature 4 (Bonus AI): AI Dispatch Co-Pilot (`/copilot/`) | `apps/optimizer/copilot_urls.py`, `copilot_views.py`, `copilot_services.py`, `copilot_tests.py`, `templates/optimizer/copilot.html`, `partials/copilot_workspace.html` | **Shipped** (PR #25; live at `core:copilot:index` with Gemini 4 + deterministic fallback) |
