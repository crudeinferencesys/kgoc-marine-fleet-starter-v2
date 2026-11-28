# Hybrid Maritime Command Design System

> **Mandatory UI Contract for Both Teams & AI Agents:**
> Follow this specification across `/`, `/trips/`, `/optimizer/`, `/safety/`, and `/copilot/` on our zero-build CDN stack (**Tailwind CSS Play CDN + DaisyUI 4.12 + HTMX 2 + Alpine.js 3 + Chart.js 4**). All fonts, color tokens, sidebar shell, and surface helpers are preloaded in `templates/base.html`.

---

## 1. Aesthetic Direction — "Hybrid Maritime Command"
- **Shell:** Deep Maritime Navy pop-out left sidebar drawer (`#0A1628`, toggled via topbar hamburger menu on desktop and mobile) paired with an airy, high-readability light operational workspace (`#F6F8FB`) and frosted sticky topbar (`bg-white/85 backdrop-blur-md`).
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

## 4. Zero-Scroll Cockpit & 3-Band Page Anatomy
Every slice (`/`, `/trips/`, `/optimizer/`, `/safety/`, `/copilot/`) fits inside a single desktop viewport without page scrolling by organizing the 3 bands with tabs and slide-over drawers:
1. **Band 1 — Compact Header + Tab Switcher:** Single-row `h1` (`text-xl font-bold`), live count pill, segmented view tabs (`Live Map | Fleet Analytics | Operations Hub` or `Ledger | Analytics`), and primary CTA / `Export CSV` action (`mb-3`).
2. **Band 2 — Compact KPI Ribbon (4 Cards):** `grid grid-cols-2 lg:grid-cols-4 gap-3 mb-3` (`p-3`, `text-xl sm:text-2xl`) showing headline figure + inline unit + right-aligned mono context.
3. **Band 3 — Tabbed Workspace + Slide-Over Drawers:** Only one primary workspace band is shown per tab, tables default to **8 rows per page** (`8 / 15 / 25` switcher) with filtered **CSV export** for deep dives, and secondary forms/inspectors open in right-side Alpine slide-over drawers (`z-50`).

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

## 6. Cutting-Edge Interaction Patterns (Scroll, Smart Forms, Discovery, Tactical Map, Quiet Cockpit)

### 1. Scroll-Aware Sections (`base.html` Topbar Progress + Section-Spy)
`templates/base.html` automatically renders a `2.5px` topbar scroll progress hairline (`animation-timeline: scroll()`), a dynamic depth + section pill (`#topbar-scroll-context`), and a back-to-top button. Tag major page bands with `data-scroll-section` and `data-scroll-label`, and apply `.scroll-reveal` on secondary cards below the fold:
```html
<section id="fleet-map" data-scroll-section data-scroll-label="Offshore Map" class="surface-card p-5 scroll-reveal">
  ...
</section>
```

### 2. One-Page Progressive Input Forms (Smart Defaults + Remaining Counter + Skip Optional)
Keep user input on a single screen: pre-fill probable operational defaults (`Flexible Window: Yes`, `Weather: Calm`, `Priority: Routine`), show a live Alpine counter of remaining required inputs + load preview, place optional details inside `<details>` with an explicit **Use defaults & submit** / **Skip optional** exit hatch, and use `.field-control` for calm `:user-invalid` validation:
```html
<form x-data="{ dest: '', pax: 6, cap: 20, showOptional: false, get remaining() { return (this.dest ? 0 : 1) + (this.pax >= 0 ? 0 : 1); } }">
  <div class="flex items-center justify-between text-xs mb-3">
    <span class="font-medium text-slate-600"
          x-text="remaining === 0 ? 'Ready · Est. ' + Math.round((pax / cap) * 100) + '% load' : remaining + ' decision remaining'"></span>
    <span class="font-mono tabular-nums text-amber-700" x-show="pax / cap < 0.5">Half-empty (&lt;50%)</span>
  </div>
  <!-- Place format hints above the input; never flash red while typing -->
  <label for="id_dest" class="block text-xs font-semibold text-slate-700">Destination *</label>
  <span id="dest-hint" class="block text-[11px] text-slate-500 mb-1">Select offshore platform or terminal</span>
  <select id="id_dest" name="destination" x-model="dest" required aria-describedby="dest-hint" data-error="dest-error"
          class="select select-bordered select-sm w-full field-control">...</select>
  <p id="dest-error" class="field-error-msg">Choose a destination before logging the trip.</p>

  <details class="mt-3 rounded-lg bg-slate-50 border border-slate-200/80 p-3" :open="showOptional">
    <summary class="cursor-pointer text-xs font-medium text-slate-600 select-none">+ Optional timing window &amp; dispatcher notes (defaults applied)</summary>
    <div class="mt-3 space-y-2"><!-- Optional fields --></div>
  </details>
  <div class="mt-4 flex items-center justify-between gap-2">
    <button type="submit" class="btn btn-ghost btn-xs text-slate-500">Skip optional &amp; submit</button>
    <button type="submit" class="btn btn-primary btn-sm">Log Trip Request</button>
  </div>
</form>
```

### 3. Simple 1-Line Filters + Power-User Advanced Menu + Paginated Export
Keep the primary control bar to one line: search input + 3–4 quick preset chips, an **`Advanced Filters` popover menu** for power users (multi-facet status, vessel, destination, weather, fuel audit), and an **`Export CSV`** link matching the active filters. Tables paginate to `8` rows by default (`8 / 15 / 25` selector), and clicking any row opens a right-side **Alpine Slide-Over Inspector** (`TR-00012`) without losing context.
```html
<div class="flex flex-wrap items-center gap-1.5 mb-3">
  <button hx-get="{% url 'trips:index' %}?preset=all" class="btn btn-xs rounded-full">All <span class="font-mono tabular-nums">988</span></button>
  <button hx-get="{% url 'trips:index' %}?preset=pending" class="btn btn-xs rounded-full bg-teal-50 text-teal-800 border-teal-200">Pending Queue <span class="font-mono tabular-nums">12</span></button>
  <button hx-get="{% url 'trips:index' %}?preset=half_empty" class="btn btn-xs rounded-full bg-amber-50 text-amber-900 border-amber-200">Half-Empty &lt;50% <span class="font-mono tabular-nums">616</span></button>
  <button hx-get="{% url 'trips:index' %}?preset=outliers" class="btn btn-xs rounded-full bg-rose-50 text-rose-800 border-rose-200">Fuel Outliers <span class="font-mono tabular-nums">22</span></button>
</div>
```

### 4. Interactive KJO Offshore Tactical Map (SVG Radar Plot + Layer Toggles)
Because the KJO dataset uses named offshore hubs (`Marine Base` → `Platform A/B/C`, `Offshore Terminal`, `Maintenance Area`) and `distance_nm` rather than live AIS GPS coordinates, build zero-latency inline SVG radar plots (`#0A1628` desaturated chart canvas, `10 / 25 / 40 nm` range rings, route arcs, vessel status halos, Windy-style `Weather / HSE Holds` toggle, and click-node-to-filter HTMX triggers) — clearly labeled as a schematic mock plot.

### 5. Quiet-by-Default ("Dark Cockpit") Dashboard Discipline
- Keep nominal operational rows (`Normal` fuel, `Calm` sea, `Available`) visually quiet in neutral slate/white so **only exceptions and savings opportunities pop** (`Amber` half-empty waste, `Rose` fuel outliers / active HSE holds, `Emerald` verified KWD/CO₂ savings, `Indigo` Gemini 4 Co-Pilot).
- Always pair semantic color with an inline stroke SVG icon + explicit label (`2.07x · Investigate Fuel`, `CB-07 Standby Lock`), and display an inline impact summary right before committing persisted actions (`Approve & Save Plan`, `Activate Hold`).

---

## 7. Anti-Patterns Checklist (Do Not Ship)
- Do **not** leave starter/developer copy (`Teammate A`, `apps/trips/`, `Ready for Feature 1...`) in final slice templates.
- Do **not** add dark mode toggles, unrequested login screens, or standalone static pages.
- Do **not** use emojis anywhere in the UI (use inline stroke SVGs).
- Do **not** render raw unformatted floats (format KWD cleanly, percentages with `%`, liters/kg with commas).
- Do **not** omit `hx-indicator` / `hx-disabled-elt="this"` on HTMX actions or fixed `h-64` / `h-72` wrappers on Chart.js canvases.
