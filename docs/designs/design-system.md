# Maritime Control Tower Design System

> **Mandatory UI Contract for Both Teams & AI Agents:**
> Follow this specification across `/`, `/trips/`, `/optimizer/`, and `/safety/` on our zero-build CDN stack (**Tailwind CSS Play CDN + DaisyUI 4.12 + HTMX 2 + Alpine.js 3 + Chart.js 4**). Foundational tokens and fonts are already loaded in `templates/base.html`.

---

## 1. Aesthetic Direction — "Offshore Precision · Maritime Industrial Light"
- **Tone:** Crisp, high-contrast offshore dispatch control tower built for marine operations supervisors—calm neutral surfaces with sharp semantic telemetry, never consumer-SaaS fluff.
- **Surfaces:**
  - Page canvas: `bg-slate-50` (`#F8FAFC`)
  - Primary card/panel: `bg-white rounded-xl border border-slate-200/90 shadow-xs`
  - Subtle nested inset / well: `bg-slate-50/80 rounded-lg border border-slate-200/70`
  - Top command navbar: Deep Maritime Navy `#0B192C` (`bg-[#0B192C]`)
- **Rule:** Operational light mode only. Never add dark-mode toggles, neon/rainbow gradients, or decorative shadows.

---

## 2. Strict Semantic Color Tokens (Never Decorative)

| Role | Token / Hex | Tailwind / Utility Classes | Use Strictly For |
|---|---|---|---|
| **Command Chrome** | `#0B192C` | `bg-[#0B192C] text-slate-100` | Top navbar shell |
| **Primary Action** | Offshore Teal `#0F766E` | `btn btn-primary` or `bg-teal-700 hover:bg-teal-800 text-white` | Primary CTAs (`Submit`, `Run Solver`, `Approve & Save`) |
| **Healthy / Savings / AI `approve`** | Emerald `#059669` | `bg-emerald-50 text-emerald-800 border border-emerald-200` | KWD/fuel/CO₂ savings, optimal utilization, approved merges |
| **Warning / Half-Empty / AI `review`** | Amber `#D97706` | `bg-amber-50 text-amber-900 border border-amber-200` | Under-utilized runs (`< 50%`), `review` merges, pending states |
| **Critical / HSE Hold / Anomaly / AI `hold`** | Rose `#E11D48` | `bg-rose-50 text-rose-800 border border-rose-200` | Fuel outliers, active HSE holds, `hold` merges, validation errors |
| **Embedded Bonus AI ONLY** | Deep Indigo `#4338CA` | `bg-indigo-50/70 border border-indigo-200 text-indigo-950` | Gemini 4 Dispatch Co-Pilot card & AI badges (separates AI from Python math) |
| **Neutral Ink** | Slate 900 / 600 / 500 | `text-slate-900`, `text-slate-600`, `text-slate-500` | Headings/numbers, body copy, eyebrows/timestamps |

> **DaisyUI Override Note:** `templates/base.html` overrides `[data-theme="corporate"]` CSS variables (`--p`, `--su`, `--wa`, `--er`) so `btn-primary`, `badge-success`, `badge-warning`, and `badge-error` align with these hex tokens. Avoid unstyled DaisyUI `btn-secondary` (default pink).

---

## 3. Typography & Tabular Telemetry
- **Fonts:** `Inter` (`font-sans`) for UI labels/prose; `JetBrains Mono` (`font-mono`) for IDs, vessel codes, timestamps, and KPI figures.
- **Mandatory `tabular-nums` Rule:** Every KPI figure, KWD cost, fuel liter count, kg CO₂, passenger/tonnage ratio, percentage, and numeric table cell MUST include `font-mono tabular-nums` (and `text-right` in tables).
- **Scale:**
  - Slice Eyebrow: `text-xs font-semibold uppercase tracking-wider text-teal-700`
  - Page `h1`: `text-2xl font-bold tracking-tight text-slate-900`
  - Subtitle: `text-sm text-slate-600 mt-1`
  - Card Title `h2`: `text-base font-semibold text-slate-900`
  - KPI Label: `text-xs font-medium uppercase tracking-wide text-slate-500`
  - KPI Value: `text-2xl sm:text-3xl font-bold font-mono tabular-nums text-slate-900`
  - Explicit Units: Always pair numbers with explicit units (`KWD`, `L`, `kg CO₂`, `pax`, `t`, `%`, `hrs`).

---

## 4. Standard 3-Band Page Anatomy
Every page (`/`, `/trips/`, `/optimizer/`, `/safety/`) follows this layout inside `<main>`:

1. **Band 1 — Header Band:** Eyebrow + `h1` + 1-line operational subtitle on the left; primary CTA or live status summary on the right (`flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4`).
2. **Band 2 — KPI Strip (4 Cards):** `grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4`.
3. **Band 3 — Workspace Grid:** `grid grid-cols-1 lg:grid-cols-12 gap-6` (typically `lg:col-span-8` primary ledger/solver table + `lg:col-span-4` action form / Gemini Co-Pilot sidebar).

---

## 5. Copy-Paste Component Recipes

### A. KPI Stat Card
```html
<div class="bg-white rounded-xl border border-slate-200/90 shadow-xs p-4">
  <div class="text-xs font-medium uppercase tracking-wide text-slate-500">Est. Shift Savings</div>
  <div class="mt-1.5 flex items-baseline gap-1.5">
    <span class="text-2xl font-bold font-mono tabular-nums text-emerald-700">1,420</span>
    <span class="text-xs font-semibold text-slate-500">KWD</span>
  </div>
  <p class="mt-1 text-xs text-slate-500">4 half-empty runs consolidated</p>
</div>
```

### B. Operational Panel Card
```html
<section class="bg-white rounded-xl border border-slate-200/90 shadow-xs">
  <div class="px-5 py-4 border-b border-slate-100 flex items-center justify-between gap-3">
    <div>
      <h2 class="text-base font-semibold text-slate-900">Pending Shift Queue</h2>
      <p class="text-xs text-slate-500">Requests eligible for consolidation</p>
    </div>
    <!-- Optional right action/pill -->
  </div>
  <div class="p-5">
    <!-- Body -->
  </div>
</section>
```

### C. Responsive Data Table
```html
<div class="overflow-x-auto">
  <table class="table table-sm w-full">
    <thead>
      <tr class="bg-slate-50 text-slate-500 text-xs uppercase tracking-wider border-b border-slate-200">
        <th>Trip ID</th>
        <th>Route &amp; Vessel</th>
        <th class="text-right">Pax</th>
        <th class="text-right">Fuel (L)</th>
        <th>Status</th>
      </tr>
    </thead>
    <tbody class="divide-y divide-slate-100 text-sm">
      <tr class="hover:bg-slate-50/70">
        <td class="font-mono tabular-nums text-xs text-slate-600">#TR-0981</td>
        <td>
          <div class="font-medium text-slate-900">Mina → Khafji Platform A</div>
          <div class="text-xs text-slate-500">Al-Khafji · Crew Boat</div>
        </td>
        <td class="text-right font-mono tabular-nums">6 / 20</td>
        <td class="text-right font-mono tabular-nums">420</td>
        <td><!-- Semantic Pill --></td>
      </tr>
    </tbody>
  </table>
</div>
```

### D. Semantic Status Pills
```html
<!-- Healthy / Approved / Optimal -->
<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-emerald-50 text-emerald-800 border border-emerald-200">Approve</span>

<!-- Half-Empty (<50%) / Review / Pending -->
<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-amber-50 text-amber-900 border border-amber-200">Half-Empty (30%)</span>

<!-- HSE Hold / Fuel Outlier / AI Hold -->
<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-rose-50 text-rose-800 border border-rose-200">HSE Hold</span>

<!-- Neutral / Completed -->
<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-slate-100 text-slate-700 border border-slate-200">Completed</span>
```

### E. HTMX Action Button with Loading State (Solver & Gemini Co-Pilot)
Always use `hx-indicator` + `hx-disabled-elt="this"` so multi-second requests (like Gemini 4 calls) give immediate visual feedback and prevent double-submits:
```html
<button
  type="button"
  class="btn btn-primary btn-sm gap-2"
  hx-post="{% url 'optimizer:ai_briefing' %}"
  hx-target="#ai-copilot-panel"
  hx-swap="innerHTML"
  hx-indicator="#ai-spinner"
  hx-disabled-elt="this">
  <span class="htmx-hide-on-request">Generate AI Dispatch Briefing</span>
  <span id="ai-spinner" class="htmx-indicator items-center gap-2">
    <span class="loading loading-spinner loading-xs"></span>
    Analyzing merges…
  </span>
</button>
```

### F. Actionable Gemini AI Co-Pilot Panel (Deep Indigo Accent)
```html
<section class="bg-indigo-50/60 rounded-xl border border-indigo-200 p-5 space-y-3">
  <div class="flex items-center justify-between gap-2">
    <div class="flex items-center gap-2">
      <span class="inline-flex items-center px-2 py-0.5 rounded-md text-xs font-semibold bg-indigo-700 text-white">Gemini 4 Co-Pilot</span>
      <h2 class="text-sm font-semibold text-indigo-950">Dispatch Risk &amp; Handover Review</h2>
    </div>
    {% if ai_fallback_used %}
    <span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-amber-50 text-amber-900 border border-amber-200">Deterministic Fallback</span>
    {% endif %}
  </div>
  <p class="text-sm text-slate-700 leading-relaxed">{{ briefing.executive_summary }}</p>
  <!-- Per-merge decision cards with Approve/Review/Hold pills -->
</section>
```

### G. Form Controls (Accessible & Compact)
```html
<div class="space-y-3">
  <div>
    <label for="id_pax_count" class="block text-xs font-semibold text-slate-700 mb-1">
      Passengers (pax)
    </label>
    <input id="id_pax_count" name="pax_count" type="number" min="0"
           class="input input-bordered input-sm w-full bg-white font-mono tabular-nums" required />
  </div>
  <div>
    <label for="id_vessel" class="block text-xs font-semibold text-slate-700 mb-1">
      Assigned Vessel
    </label>
    <select id="id_vessel" name="vessel" class="select select-bordered select-sm w-full bg-white" required>
      <!-- options -->
    </select>
  </div>
</div>
```

### H. Chart.js 4 Standard Configuration
Always place `<canvas>` inside a fixed-height container (`relative h-64`) to prevent layout shifts:
```html
<div class="relative h-64 w-full">
  <canvas id="fleetUtilizationChart"></canvas>
</div>
<script>
  const CHART_PALETTE = {
    teal: '#0F766E',
    amber: '#D97706',
    rose: '#E11D48',
    indigo: '#4338CA',
    slate: '#64748B',
    grid: '#E2E8F0',
  };
  // Use responsive: true, maintainAspectRatio: false,
  // font: { family: "'Inter', sans-serif" }, and clean borderRadius: 6 on bars.
</script>
```

---

## 6. Anti-Patterns Checklist (Do Not Ship)
- Do **not** leave starter/developer copy (`Teammate A`, `apps/trips/`, `Ready for Feature 1...`) in finished slice templates.
- Do **not** add dark mode toggles, unrequested login screens, or standalone static pages.
- Do **not** render raw floats without rounding/units (format KWD to 2 decimals or integer, liters/kg cleanly, percentages with `%`).
- Do **not** place charts without a fixed-height wrapper (`h-64` / `h-72`).
- Do **not** omit `hx-indicator` / `hx-disabled-elt="this"` on async HTMX actions.
