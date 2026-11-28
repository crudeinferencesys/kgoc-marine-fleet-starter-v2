# Design Sitemap (EGM Lite)

Index of active specifications, frozen boundaries, and team ownership.

## Documents
| Document | Purpose | Status |
|---|---|---|
| [hackathon_brief.md](../hackathon_brief.md) | Official KGOC + CODED workshop rules & Theme 4 summary | Reference |
| [architecture.md](architecture.md) | Stack, GCP Cloud Run + Cloud SQL, HTMX, Gemini AI wrapper | Locked |
| [design-system.md](design-system.md) | Maritime Control Tower palette, typography, KPI/table/HTMX/AI/Chart.js recipes | Locked — follow for all UI & charts |
| [mvp-spec.md](mvp-spec.md) | Theme 4 dataset schema, Control Tower, 3 core features, Actionable AI, KWD math | Pre-Kickoff Blueprint Locked — confirm columns at 11:00 AM |

## Vertical Slice Ownership
| Slice | Paths | Owner |
|---|---|---|
| Core Shell & Frozen Schema | `apps/core/`, `templates/base.html`, `config/` | Shared (Salman freezes schema PR at 11:15–11:40 AM) |
| Control Tower + Feature 1: Trips & Utilization | `apps/trips/`, `templates/trips/`, `templates/core/home.html` | **Salman** (Laptop A) |
| Feature 2: Dispatch Optimizer | `apps/optimizer/views.py`, `urls.py`, `templates/optimizer/index.html` | **Saleh** (Laptop B) |
| Feature 3: Safety & Fuel Anomaly Guard | `apps/safety/`, `templates/safety/` | **First Finisher** (Coordinate) |
| Feature 4 (Bonus AI): AI Dispatch Co-Pilot (`/copilot/`) | `apps/optimizer/copilot_urls.py`, `copilot_views.py`, `templates/optimizer/copilot.html` | **Saleh** (Laptop B, after Feature 2) |
