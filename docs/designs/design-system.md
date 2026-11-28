# Hybrid Maritime Command Design System

> **Mandatory UI Contract for Both Teams & AI Agents:**
> Follow this specification across `/`, `/trips/`, `/optimizer/`, `/safety/`, and `/copilot/` on our zero-build CDN stack (**Tailwind CSS Play CDN + DaisyUI 4.12 + HTMX 2 + Alpine.js 3 + Chart.js 4**). All fonts, color tokens, sidebar shell, and surface helpers are preloaded in `templates/base.html`.

---

## 1. Aesthetic Direction — "Hybrid Maritime Command"
- **Shell:** Slim `48px` (`h-12`) Deep Maritime Navy (`#0A1628`) sticky top navigation bar containing ONLY the brand link, direct links to all 5 operational pages (`Control Tower`, `Trips`, `Optimizer`, `Safety`, `AI Co-Pilot` — zero burger menu), and an optional single `topbar_actions` CTA (never `/health/` or `Mock Data` pills in the navbar; keep `/health/` live silently and keep the mock-data disclaimer in the quiet footer), paired with a light operational workspace (`#F6F8FB`).
- **Cards & Depth:** Crisp white elevated surfaces (`.surface-card`: `#FFFFFF`, hairline `rgba(226,232,240,0.92)` border, subtle two-step elevation shadow, `14px` radius).
- **Template Blocks Available in `templates/base.html`:**
  - `{% block title %}` — `<title>` tag (`Page · CrudeInference · KGOC Marine Fleet`)
  - `{% block topbar_title %}` — Sticky topbar breadcrumb/title
  - `{% block topbar_actions %}` — Optional right-aligned topbar action button or shift pill
  - `{% block content %}` — Main 3-band workspace
  - `{% block extra_scripts %}` — Page-specific Chart.js / Alpine scripts
- **Preloaded Utility Classes in `templates/base.html`:**
  - `.surface-card`, `.surface-card-hover`, `.scroll-reveal` (progressive-enhancement entry motion via `animation-timeline: view()`), `[data-scroll-section]` (`scroll-margin-top` + automatic topbar section-spy + scroll progress hairline)
  - `.kpi-accent-teal`, `.kpi-accent-emerald`, `.kpi-accent-amber`, `.kpi-accent-rose`, `.kpi-accent-indigo`
  - `.ai-copilot-surface` (gradient surface reserved strictly for Gemini 4 Co-Pilot panels)
  - `.field-control`, `.field-error-msg`, `.visually-hidden` (calm `:user-invalid` post-interaction form validation + ARIA sync)
  - `.tabular-nums`, `.htmx-indicator`, `.htmx-hide-on-request`, `.htmx-fade-in`

---

## 2. Strict Semantic Color Tokens (Never Decorative)

| Role | Token / Hex | Classes / Surface | Use Strictly For |
|---|---|---|---|
| **Command Chrome** | `#0A1628` | `bg-[#0A1628] text-slate-100` | Left app sidebar (`base.html`) |
| **Workspace Canvas** | `#F6F8FB` | `bg-[#F6F8FB]` | Page canvas behind cards |
| **Primary Action** | Offshore Teal `#0D9488` | `btn btn-primary` / `bg-teal-600 hover:bg-teal-700 text-white` | Primary CTAs (`Log Trip`, `Run Solver`, `Approve & Save`) |
| **Savings / Optimal / AI `approve`** | Emerald `#059669` | `bg-emerald-50 text-emerald-800 border border-emerald-200` | KWD/fuel/CO₂ savings, optimal load (`70–95%`), AI `Approve` |
| **Warning / Half-Empty / AI `review`** | Amber `#D97706` | `bg-amber-50 text-amber-900 border border-amber-200` | Half-empty trips (`< 50%`), `Pending` status, AI `Review` |
| **Critical / HSE Hold / Outlier / AI `hold`** | Rose `#E11D48` | `bg-rose-50 text-rose-800 border border-rose-200` | Fuel anomalies, active HSE holds, AI `Hold`, errors |
| **Embedded Bonus AI ONLY** | Electric Indigo `#4F46E5` | `.ai-copilot-surface` / `bg-indigo-600 text-white` | Gemini 4 Co-Pilot cards, badges, and AI rationale |
| **Neutral Ink** | Slate 900 / 600 / 500 | `text-slate-900`, `text-slate-600`, `text-slate-500` | Primary numbers/titles, body copy, labels/timestamps |

> **DaisyUI Rule:** `[data-theme="corporate"]` variables are tuned in `base.html` (`--p: 56% 0.11 180`, `--su`, `--wa`, `--er`). Use `btn-primary`, `btn-outline`, or explicit Tailwind semantic classes—never use unstyled DaisyUI `btn-secondary` (default pink).

---

## 3. Typography, Telemetry & No-Emoji Policy
- **Fonts:** `Plus Jakarta Sans` (`font-sans`) for headings, labels, and copy; `JetBrains Mono` (`font-mono`) for trip/vessel IDs, timestamps, capacities, and metrics.
- **Mandatory `tabular-nums` Rule:** Every KPI figure, KWD amount, fuel liter count, kg CO₂, passenger/tonnage ratio, percentage, and numeric table column MUST use `font-mono tabular-nums` (right-aligned in tables).
- **Explicit Units:** Always pair values with explicit units (`KWD`, `L`, `kg CO₂`, `pax`, `t`, `%`, `hrs`).
- **No-Emoji Policy:** Never use emojis in nav items, KPI headers, badges, or alerts. Use clean `16px–20px` inline stroke SVG icons (`stroke-width="1.75"`).

---

## 4. Standard Page Anatomy & Zero-Scroll Desktop Contract
- **Control Tower (`/`) — Zero Band-1 Header Clutter:** Opens straight into **4 clickable KPI drill-down cards** (`Trips`, `Half-Empty`, `Optimizer`, `Safety`) and a **2×2 clickable executive Chart.js grid** (paired with a single `AI Co-Pilot →` CTA in `topbar_actions`), avoiding redundant page-launch card grids or visible `h1` hero headers.
- **Feature Workspaces (`/trips/`, `/optimizer/`, `/safety/`, `/copilot/`):** Follow the compact 3-band layout inside `{% block content %}`:
  1. **Band 1 — Slim Toolbar Header (`~36px`):** Concise `h1` + count badge, optional 2-tab switcher (`Trip Ledger` / `Log New Trip`), and at most one contextual primary action (never duplicate cross-page links already present in `#primary-top-nav`).
  2. **Band 2 — KPI Strip (4 Cards):** `grid grid-cols-2 lg:grid-cols-4 gap-3 mb-3` with compact `p-3` KPI cards.
  3. **Band 3 — Workspace Grid / Table:** Focused 12-col split or full-width paginated table.

> **Zero-Scroll Single-Viewport Desktop Contract (`>= 1280×760`):**
> Every operational page — and **especially the Command Center (`/`)** — MUST fit cleanly within a single desktop viewport (`document.documentElement.scrollHeight <= window.innerHeight` at `1280×800` and `1440×900`) with **zero page-level vertical scrolling**. Keep total workspace height within `~620px`–`660px` using the `48px` (`h-12`) topbar, zero Band-1 bloat, `p-3` KPI strips (`~94px`), `h-44 xl:h-[205px]` Chart.js wrappers in a 2×2 grid, Alpine tabs for secondary workflows, and bounded internal scroll (`max-h-[...] overflow-y-auto`) ONLY inside dense tables/lists when needed.

---

## 5. Signature Component Recipes (Copy-Paste Ready)

### 1. KPI Telemetry Card
```html
<div class="surface-card kpi-accent-emerald p-4">
  <div class="flex items-center justify-between gap-2">
    <span class="text-[11px] font-semibold uppercase tracking-wider text-slate-500">Est. 90-Day Savings</span>
    <span class="flex h-7 w-7 items-center justify-center rounded-lg bg-emerald-50 text-emerald-700">
      <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>
    </span>
  </div>
  <div class="mt-2 flex items-baseline gap-1.5">
    <span class="text-2xl sm:text-3xl font-bold font-mono tabular-nums text-emerald-700">14,820</span>
    <span class="text-xs font-semibold text-slate-500">KWD</span>
  </div>
  <p class="mt-1 text-xs text-slate-500 font-mono tabular-nums">98,800 L diesel · 264.8 t CO₂ avoided</p>
</div>
```

### 2. Visual Vessel Capacity Bar (Utilization Telemetry)
Color mapping: `< 50%` Amber (`bg-amber-500`), `50–69%` Teal (`bg-teal-600`), `70–95%` Emerald (`bg-emerald-600`), `> 95%` Rose (`bg-rose-600`).
```html
<div class="flex items-center justify-end gap-2.5">
  <div class="w-20 h-1.5 rounded-full bg-slate-100 overflow-hidden">
    <div class="h-full rounded-full bg-amber-500" style="width: 30%"></div>
  </div>
  <span class="font-mono tabular-nums text-xs text-slate-700 w-16 text-right">6/20 · 30%</span>
</div>
```

### 3. Before → After Consolidation Diff Card (`/optimizer/`)
```html
<div class="surface-card p-4 space-y-3 htmx-fade-in">
  <div class="flex flex-wrap items-center justify-between gap-2">
    <label class="flex items-center gap-2.5 cursor-pointer">
      <input type="checkbox" name="selected_merges" value="{{ merge.id }}"
             class="checkbox checkbox-primary checkbox-sm" {% if merge.checked %}checked{% endif %} />
      <span class="text-sm font-semibold text-slate-900">Mina → Khafji Platform A · 08:00 Window</span>
    </label>
    <div class="flex items-center gap-1.5">
      <span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-emerald-50 text-emerald-800 border border-emerald-200 font-mono tabular-nums">-1 Trip · +185 KWD</span>
      <span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-emerald-50 text-emerald-800 border border-emerald-200">AI: Approve</span>
    </div>
  </div>
  <div class="grid grid-cols-1 md:grid-cols-11 gap-3 items-center text-xs">
    <div class="md:col-span-5 rounded-lg bg-amber-50/70 border border-amber-200/80 p-3 space-y-1">
      <div class="font-semibold uppercase tracking-wider text-[10px] text-amber-800">Before (2 Half-Empty Runs)</div>
      <div class="font-mono tabular-nums text-slate-700">#TR-104 (5/20 pax) + #TR-109 (4/20 pax)</div>
    </div>
    <div class="md:col-span-1 flex justify-center text-teal-700 font-bold">→</div>
    <div class="md:col-span-5 rounded-lg bg-emerald-50/70 border border-emerald-200/80 p-3 space-y-1">
      <div class="font-semibold uppercase tracking-wider text-[10px] text-emerald-800">After (1 Consolidated Sailing)</div>
      <div class="font-mono tabular-nums text-slate-900 font-medium">Al-Khafji · 9/20 pax (45%) · 410 L saved</div>
    </div>
  </div>
</div>
```

### 4. Actionable Gemini 4 AI Co-Pilot Card (`.ai-copilot-surface`)
```html
<section class="ai-copilot-surface p-5 space-y-4 htmx-fade-in">
  <div class="flex flex-wrap items-center justify-between gap-2">
    <div class="flex items-center gap-2">
      <span class="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-md text-xs font-semibold bg-indigo-600 text-white">
        Gemini 4 Co-Pilot
      </span>
      <h2 class="text-sm font-semibold text-indigo-950">Dispatch Risk &amp; Handover Review</h2>
    </div>
    {% if ai_fallback_used %}
    <span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-amber-50 text-amber-900 border border-amber-200">Deterministic Fallback</span>
    {% else %}
    <span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-indigo-100 text-indigo-800 border border-indigo-200 font-mono">gemini-4-hydrogen</span>
    {% endif %}
  </div>
  <p class="text-sm text-slate-700 leading-relaxed">{{ briefing.executive_summary }}</p>
</section>
```

### 5. HSE Safety Override Alert Banner & Rule Card (`/optimizer/` & `/safety/`)
```html
<div class="rounded-xl border border-rose-200 bg-rose-50/80 border-l-4 border-l-rose-600 p-4 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
  <div>
    <div class="text-xs font-semibold uppercase tracking-wider text-rose-800">Active HSE Override</div>
    <p class="text-sm font-medium text-slate-900 mt-0.5">Maintenance Hold on MV Safaniya — excluded from all automated merges.</p>
  </div>
  <a href="{% url 'safety:index' %}" class="btn btn-xs bg-white border-rose-200 text-rose-800 hover:bg-rose-100">Manage Holds</a>
</div>
```

### 6. Responsive Data Table
Paginate dense operational tables by default (`8` rows default, selectable `8 / 15 / 25`) so tables fit a single desktop viewport without inner scrolling, and pair with a 1-click filtered `Export CSV` link for deep dives.
```html
<section class="surface-card overflow-hidden">
  <div class="px-5 py-4 border-b border-slate-100 flex items-center justify-between gap-3">
    <div>
      <h2 class="text-base font-semibold text-slate-900">Fleet Trip Ledger</h2>
      <p class="text-xs text-slate-500">976 historical sailings + live pending requests</p>
    </div>
  </div>
  <div class="overflow-x-auto">
    <table class="table table-sm w-full">
      <thead>
        <tr class="bg-slate-50 text-slate-500 text-[11px] uppercase tracking-wider border-b border-slate-200">
          <th>Trip ID</th>
          <th>Route &amp; Vessel</th>
          <th class="text-right">Load</th>
          <th class="text-right">Fuel (L)</th>
          <th>Status</th>
        </tr>
      </thead>
      <tbody class="divide-y divide-slate-100 text-sm">
        <!-- rows with font-mono tabular-nums on IDs and numeric cells -->
      </tbody>
    </table>
  </div>
</section>
```

### 7. HTMX Action Button + Loading Indicator & Accessible Forms
Always pair `hx-indicator` + `hx-disabled-elt="this"` on solver/AI buttons, and use explicit `<label for="...">` tags on inputs:
```html
<button
  type="button"
  class="btn btn-primary btn-sm gap-2"
  hx-post="{% url 'optimizer:ai_briefing' %}"
  hx-target="#ai-copilot-panel"
  hx-swap="innerHTML"
  hx-indicator="#ai-spinner"
  hx-disabled-elt="this">
  <span class="htmx-hide-on-request">Run AI Risk Review</span>
  <span id="ai-spinner" class="htmx-indicator items-center gap-2">
    <span class="loading loading-spinner loading-xs"></span>
    Analyzing merges…
  </span>
</button>
```

### 8. Chart.js 4 Standard Config
Always wrap `<canvas>` in `<div class="relative h-64 w-full">` to prevent layout shifts:
```javascript
const CHART_PALETTE = {
  teal: '#0D9488',
  emerald: '#059669',
  amber: '#D97706',
  rose: '#E11D48',
  indigo: '#4F46E5',
  navy: '#0A1628',
  grid: '#E2E8F0',
};
// Standard options:
// responsive: true, maintainAspectRatio: false,
// plugins.legend.labels.font = { family: "'Plus Jakarta Sans', sans-serif", size: 12 },
// plugins.tooltip.backgroundColor = '#0A1628',
// scales.x.grid.display = false,
// scales.y.grid.color = '#E2E8F0', scales.y.border = { dash: [4, 4], display: false },
// bar datasets: borderRadius: 6, borderSkipped: false.
```

---

## 6. Cutting-Edge Interaction Patterns (Scroll, Simple-Menu Workflows, Discovery & Pagination, Quiet Cockpit)

### 1. Scroll-Aware Sections (`base.html` Mobile/Overflow Fallback)
`templates/base.html` provides a `2.5px` topbar scroll progress hairline (`animation-timeline: scroll()`), a dynamic depth + section pill (`#topbar-scroll-context`), and a back-to-top button as graceful fallbacks for mobile or narrow viewports. Desktop pages (`>= 1280×760`) should remain zero-scroll above the fold; tag major page bands with `data-scroll-section` and `data-scroll-label`, and apply `.scroll-reveal` only if a secondary band sits below the fold on narrow screens:
```html
<section id="trips-ledger-section" data-scroll-section data-scroll-label="Trip Ledger" class="surface-card p-5 scroll-reveal">
  ...
</section>
```

### 2. Dedicated Simple-Menu User-Input Workflow (Centered Tab — Not a Sidebar)
Whenever a workflow requires user data creation (e.g., logging a new trip on `/trips/`, configuring solver/hold inputs on `/optimizer/` or `/safety/`, or submitting directives on `/copilot/`), **never place the form inside a slide-over sidebar or cramped side column** (reserve slide-over drawers strictly for read-only inspection such as the Trip Telemetry Inspector):
- **Dedicated Centered Workflow Tab:** Switch cleanly into a focused `max-w-4xl mx-auto` workspace tab (`Log New Trip` / `?book=1` with `← Back to Ledger`), hiding Band-2 KPI cards while keeping KPI & table containers mounted in the DOM so HTMX `hx-swap-oob="outerHTML"` refreshes them silently in the background.
- **Simple-Menu Guided Steps:** Split inputs into calm, un-overwhelming steps (e.g., `1. Route & Mission` → `2. Vessel & Payload` → `3. Optional Details`) using tappable menu cards/pills over raw `<select>` dropdowns whenever options are bounded.
- **Progress, Smart Defaults & Skip Options:** Render a Deep Maritime Navy (`#0A1628`) step progress bar + explicit remaining-inputs label (`Step 1 of 3 · 1 core step + 1 optional step left`), clickable step pills + live selection summary pill, pre-applied smart defaults (`08:30 · Calm · Routine · Flexible Window`), and a 1-click **Skip optional & submit with defaults** exit hatch available from every step, followed by a focused post-submit confirmation screen (`Log Another`, `View in Ledger`, `Inspect`, next-slice CTA).
- **HTMX + Alpine Settle Rule:** Keep all steps mounted with `x-show` (never `x-if` so skipped submissions send every field), use `.field-control` for calm `:user-invalid` validation, and put explicit `style="display: none;"` + `:class="{ 'hidden': ... }"` on any initially hidden element with an `id` inside an `hx-swap="outerHTML"` target so HTMX settle never strips `display: none`.
```html
<section id="trip-booking-workflow" x-show="activeTab === 'book'" x-cloak class="max-w-4xl mx-auto">
  <div id="trips-booking-panel" x-data="{ showConfirmation: false }" class="surface-card overflow-hidden">
    <form method="post" action="..." hx-post="..." hx-target="#trips-booking-panel" hx-swap="outerHTML"
          x-data="{ step: 1 }">
      <!-- Deep Navy header + teal progress bar + remaining-inputs indicator -->
      <!-- Step 1..3 using x-show (plus style="display: none;" + :class on #optional-trip-details) -->
      <!-- Footer: ← Back | Skip optional & submit with defaults | Next Step → / Submit -->
    </form>
  </div>
</section>
```

### 3. Direct 1-Line Discovery, Categorized More Filters Overlay & Pagination / CSV Export
Keep the default table control bar to **1 simple direct line** without exposing a wall of dropdowns:
- **1-Line Control Bar:** Live search input (`q`) + 3–4 quick preset chips with live counts (`All`, `Pending`, `Half-Empty`, `Fuel Outliers`) + **`More Filters`** button + **`Export CSV`** link.
- **Categorized `More Filters` Full-Screen Overlay Modal:** Group power-user filters into logical domain categories (e.g., `Route & Area`, `Fleet & Crew`, `Sea State & Fuel Audit`) navigated via `←` / `→` arrow buttons, keyboard arrow keys, and category tabs with active filter counts, plus removable active-filter chips above the table. When nested inside an HTMX `outerHTML`-swapped table panel, always render the closed modal with `style="display: none;"`, `hidden`, `x-cloak`, and `:class="{ 'flex': moreOpen, 'hidden': !moreOpen }"`.
- **Default Pagination & Filtered CSV Export:** Paginate dense ledgers (`8` rows default, `8 / 15 / 25` switcher) so the workspace stays zero-scroll on desktop, paired with a filtered **`Export CSV`** download (with formula-injection escaping) and a right slide-over **Inspector** (`TR-00012`) for row deep dives:
```html
<div class="flex flex-wrap items-center justify-between gap-2 px-4 py-2.5 border-b border-slate-100">
  <div class="flex flex-wrap items-center gap-1.5">
    <input type="text" name="q" placeholder="Search Trip, Req, note…" class="input input-bordered input-xs w-44 sm:w-56" />
    <button hx-get="{% url 'trips:ledger' %}?status=all" class="btn btn-xs rounded-full">All <span class="font-mono tabular-nums">988</span></button>
    <button hx-get="{% url 'trips:ledger' %}?status=pending" class="btn btn-xs rounded-full bg-teal-50 text-teal-900 border-teal-200">Pending</button>
    <button hx-get="{% url 'trips:ledger' %}?half_empty=1" class="btn btn-xs rounded-full bg-amber-50 text-amber-900 border-amber-200">Half-Empty</button>
    <button hx-get="{% url 'trips:ledger' %}?anomaly=high" class="btn btn-xs rounded-full bg-rose-50 text-rose-800 border-rose-200">Fuel Outliers</button>
  </div>
  <div class="flex items-center gap-1.5">
    <button type="button" @click="moreOpen = true" class="btn btn-xs bg-white border-slate-200">More Filters</button>
    <a href="{% url 'trips:export_csv' %}" class="btn btn-xs bg-white border-slate-200">Export CSV</a>
  </div>
</div>
```

### 4. Quiet-by-Default ("Dark Cockpit") Dashboard Discipline
- Keep nominal operational rows (`Normal` fuel, `Calm` sea, `Available`) visually quiet in neutral slate/white so **only exceptions and savings opportunities pop** (`Amber` half-empty waste, `Rose` fuel outliers / active HSE holds, `Emerald` verified KWD/CO₂ savings, `Indigo` Gemini 4 Co-Pilot).
- Always pair semantic color with an inline stroke SVG icon + explicit label (`2.07x · Investigate Fuel`, `CB-07 Standby Lock`), and display an inline impact summary right before committing persisted actions (`Approve & Save Plan`, `Activate Hold`).

---

## 7. Anti-Patterns Checklist (Do Not Ship)
- Do **not** let desktop pages (`>= 1280×760`) overflow vertically into full-page scrolling — keep Control Tower (`/`) and core workspaces zero-scroll above the fold (use tabs, 2×2 grids, compact spacing, and bounded table scroll if needed).
- Do **not** place user data-creation forms inside slide-over sidebars or cramped side columns — use a dedicated centered simple-menu workflow tab (reserve slide-over drawers for read-only inspection).
- Do **not** add an offshore tactical map or unrequested extra visualizations outside the agreed scope.
- Do **not** render developer/infrastructure metadata (`DB: sqlite3`, `gemini-4-hydrogen` model pills, `/health/` buttons) inside the global navbar or executive page bodies.
- Do **not** add duplicate cross-page navigation buttons (`Open Optimizer`, `HSE Holds`, `Dispatch Optimizer`) inside headers when all 5 routes already live in `#primary-top-nav`.
- Do **not** leave starter/developer copy (`Teammate A`, `apps/trips/`, `Ready for Feature 1...`) in final slice templates.
- Do **not** add dark mode toggles, unrequested login screens, or standalone static pages.
- Do **not** use emojis anywhere in the UI (use inline stroke SVGs).
- Do **not** render raw unformatted floats (format KWD cleanly, percentages with `%`, liters/kg with commas).
- Do **not** omit `hx-indicator` / `hx-disabled-elt="this"` on HTMX actions or fixed height wrappers on Chart.js canvases.
