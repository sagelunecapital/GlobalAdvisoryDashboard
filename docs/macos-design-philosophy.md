# macOS 27 "Liquid Glass" Design Philosophy

> The design language now shipping as the production homepage **`prototypes/index.html`**
> (Vercel serves `prototypes/` from `main`) — a first-party macOS-feeling reskin of the
> Global Advisory Dashboard. This is a **visual-language layer only**: it reskins the
> original dashboard's markup/JS/Plotly without changing a single ID, class, data source,
> or line of application logic. Everything here is CSS + minimal HTML, applied as
> **appended override layers** in `<head>` (later rules win; `!important` where a base
> rule must be beaten). The pre-reskin terminal dashboard is preserved in git history.

---

## 0. Prime directive

**Reskin, never redesign.** Preserve every feature, ID, class, data fetch, JS behavior,
Plotly chart, and layout. Improve only visual language: material, spacing, hierarchy,
motion, color, typography. If a change requires touching JS or restructuring the DOM,
it's out of scope — find a CSS-only path instead.

Variants (all CSS reskins of the same dashboard app):
- **`prototypes/index.html`** — light "Music-app" pane layout. **SHIPPED — the production
  homepage.** (Was developed as `dashboard-macos-light.html`, then promoted to `index.html`.)
- **`prototypes/dashboard-macos.html`** — dark "desktop metaphor" (window manager + dock +
  widgets). Local/experimental; gitignored, not deployed.

---

## 1. Core principles

1. **Reskin over redesign** — visual language only; functionality is sacred.
2. **Depth over borders** — separate surfaces with elevation, translucency, and shade,
   not lines. Remove harsh borders wherever a shadow or a level change can do the job.
3. **Glass is for the floating layer only** — sidebar, toolbar, popovers, tooltips,
   menus get vibrancy/blur. **Content stays opaque.** Never frost a data card.
4. **Differentiate by opacity, not outlines** — the macOS "grouped-inset" move: the
   outer container is more translucent/recessed; the inner tiles are ~100% opaque and
   sit on top. The gap in luminance *is* the border.
5. **Optical hierarchy, not weight** — lean on size, color, and spacing before font
   weight. Apple text tops out around semibold (600); labels are gray, not bold.
6. **Elevation by soft, diffuse shadows** — low opacity, large blur, minimal spread.
   No "card-UI" drop shadows.
7. **Every surface responds** — no dead UI. Hover gently illuminates; press gives
   spring feedback. Motion runs on `transform`/`opacity` (GPU) with natural easing.
8. **One radius system** — a small, intentional, concentric scale. No random 8 vs 9.
9. **Semantic color is data, not decoration** — red/green up-down and category colors
   are meaning; never override them for aesthetics. Blue is reserved for selection and
   interaction, not everywhere.
10. **Believable, not "inspired"** — the bar is "Apple designed this," judged at a glance.

---

## 2. Design tokens (the current system)

```css
/* Radius — concentric, intentional */
--r-control: 8px;   /* buttons, inputs, nav rows            */
--r-tile:    10px;  /* inner tiles (rcrit, kpi, cot, cols)  */
--r-card:    12px;  /* standalone content cards             */
--r-group:   16px;  /* outer containers that wrap tiles     */
--r-pop:     13px;  /* popovers, menus, tooltips            */
--r-pill:    980px; /* segmented toggles, chips, change-pills */

/* Surfaces — low contrast, layered (window → content → card → tile) */
window/canvas: linear-gradient(177deg, #f2f3f6 0%, #eaecf0 62%, #e8eaee 100%)
--card-bg:   #fcfcfe;                 /* off-white, NOT pure #fff */
--tile-bg:   #fdfdff;
grouped outer: rgba(255,255,255,0.40) /* recessed, translucent   */
--sidebar-bg: rgba(247,248,250,0.55)  /* vibrant glass           */

/* Labels (Apple semantic) — softened, still readable */
--ink:   #212126;                 /* label      */
--ink-2: rgba(60,60,67,0.56);     /* secondary  */
--ink-3: rgba(60,60,67,0.30);     /* tertiary   */
--sep:   rgba(60,60,67,0.07);     /* separators — barely there */
--hair:  rgba(60,60,67,0.09);

/* Accent — blue only for interaction */
--accent:      #007aff;
--accent-weak: rgba(0,122,255,0.10);  /* selected nav row fill  */

/* Shadows — diffuse, low opacity */
--shadow-1:    0 1px 2px rgba(16,24,40,0.03);
--shadow-2:    0 1px 3px rgba(16,24,40,0.03), 0 6px 20px rgba(16,24,40,0.045);
--shadow-tile: 0 1px 2px rgba(16,24,40,0.035);
--shadow-pop:  0 14px 44px rgba(16,24,40,0.12), 0 2px 8px rgba(16,24,40,0.045);

/* Motion */
--ease:   cubic-bezier(.32,.72,0,1);    /* standard glide       */
--spring: cubic-bezier(.34,1.30,.52,1); /* press/hover overshoot */
```

**Data / semantic colors (never restyled):** green `#12a150`, red `#e5484d`, plus the
theme categories (blue/purple/etc.) used by the screener and leadership panels.

---

## 3. Typography — the single most important detail

**The font IS the macOS feel.** On Windows, `-apple-system`/`SF Pro` are not installed,
so a plain system stack silently falls back to **Segoe UI** and the whole thing reads as
"web dashboard." The fix — and what the macOS reference site itself does — is to **load
Inter** (an open SF-Pro stand-in) and put it in the stack:

```html
<link href="https://fonts.googleapis.com/css2?family=Inter:opsz,wght@14..32,100..900&display=swap" rel="stylesheet">
```
```css
--sf: -apple-system, BlinkMacSystemFont, 'SF Pro Text', 'SF Pro Display', Inter, 'Segoe UI', system-ui, sans-serif;
body { font-family: var(--sf); font-variant-numeric: tabular-nums;
       font-optical-sizing: auto;
       font-feature-settings: "cv02","cv03","cv04","cv11","ss01"; /* SF-like glyphs */
       letter-spacing: -0.006em;
       -webkit-font-smoothing: antialiased; text-rendering: optimizeLegibility; }
```
macOS users get real SF; everyone else gets Inter, which is visually ~identical.
**Also set the same family on every Plotly `font.family`** so chart axes match.

Hierarchy: large title ~25px/600 with `-0.021em` tracking; toolbar title ~14.5px/600;
section labels ~560 weight, gray, `+0.02em`. Numbers stay aligned via `tabular-nums`
(not a monospace font).

---

## 4. Signature techniques

### Grouped-inset material (principle 4)
The Macro Regime card = an outer `.card` wrapping tiles (`.rcrit`, `.rsum-combined`).
- Outer → `rgba(255,255,255,0.40)`, hairline `--sep`, no shadow, `--r-group`.
- Inner tiles → opaque `--tile-bg`, **no border**, `--r-tile`, `--shadow-tile`.
- Target outer containers automatically with `:has()`:
  `.card:has(.rcrit), .card:has(.stir-kpi), .card:has(> .card){ …recessed… }`
  (Degrades gracefully to opaque-white if `:has()` is unsupported.)

### Vibrant glass chrome (principle 3)
```css
.layout-header, .sidebar {
  background: rgba(255,255,255,0.66);              /* sidebar: 0.55 */
  backdrop-filter: saturate(200%) blur(40px);
  border: 1px solid var(--sep);
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.55); /* soft top highlight = "material" */
}
```

### Stocks-app change pills
The screener movers use solid rounded green/red (theme-colored) pills for `%` change —
the signature macOS **Stocks** move: `.scr-change{ padding:2px 9px; border-radius:8px;
color:#fff; font-weight:700 }` with `.pos→green`, `.neg→red`, theme classes → their color.

### macOS tooltips
Custom SVG-chart tooltip `.chart-tt` → vibrant glass bubble (blur, `--r-pop`, `--shadow-pop`).
Plotly hoverlabels → white bubble `rgba(255,255,255,0.98)` + hairline (SVG can't round, so
match via color/border/font).

### Motion
`@keyframes mp-in{ from{opacity:0;transform:translateY(8px)} to{opacity:1;transform:none} }`
on `.main-panel.active` → every tab switch fades up. Hover = `translateY(-1px/-2px)` +
soft shadow; press = `scale(.975)` on `--spring`. Respect `prefers-reduced-motion`.

### Native app frame
Fill the window edge-to-edge: `.app{ padding:0; max-width:none }` (macOS apps have no
outer inset). The sidebar meets the top/left edges; the toolbar meets the top/right.

### Source-list sidebar hierarchy
Parent tabs + indented children (Finder/System Settings):
`.nav-tab.nav-sub{ padding-left:32px; font-size:12.5px }` and
`.nav-tab:not(.nav-sub){ margin-top:15px }` for group spacing. Selected row = rounded
`--accent-weak` fill with `--accent` text + icon.

---

## 5. Hard-won gotchas (read before editing)

- **Inter must be webfont-loaded.** Naming `-apple-system` alone → Segoe UI on Windows.
  This was the difference between "rough web app" and "premium." (§3)
- **Never force `color` on data elements.** `.rcrit-value` / `table td` / value cells
  carry `.pos/.neg/.amb` semantic colors — setting `color:… !important` there flattens
  red/green to black. On those selectors set **font-weight only**.
- **`.gitignore` blocks new dashboards.** The repo has `*.html` + `!prototypes/index.html`.
  Any new prototype HTML needs its own `!prototypes/<file>.html` exception or it silently
  won't commit/deploy.
- **Charts need a visible container to size.** Plotly/custom charts are drawn via
  `window._redraw[id]` on tab switch; keep `paper/plot_bgcolor:'transparent'` so the
  opaque card shows through, and don't break the panel `display:none/active` toggling.
- **Re-theming Plotly = remap literals, not call sites.** The base charts hardcode dark
  grid/zeroline/font colors in ~40 places; recolor by string-replacing the literals
  (and rewriting `STIR.PALETTE`, which was white-on-dark), not by editing each chart.
- **Keep intentional whites.** `.tableau-wrap{background:#fff}` and the `,0.75);color:#fff`
  heatmap cells are deliberate — don't sweep them in a global recolor.
- **`:has()` for outer/inner targeting** is clean but Chrome/Safari-era only; ensure the
  fallback still looks acceptable.
- **Patch large files programmatically.** These reskins were applied via small Python
  string-replace scripts with `assert`s (never hand-editing the 600 KB+ file), then the
  script is deleted. Verify visually in a browser after every pass.

---

## 6. Build & verify workflow

1. Copy `index.html` → new variant; apply CSS as an appended layer before `</style>`.
2. Serve locally: `python -m http.server 8899 --bind 127.0.0.1` (JSON `fetch()` fails on
   `file://`), open the page, screenshot at device scale, eyeball each tab.
3. Confirm: semantic red/green intact, charts render at correct width, no console errors
   beyond the harmless `/api/save-*` 404s (backend-only on a static host).
4. Deploy: Vercel serves `prototypes/` (`outputDirectory:"prototypes"`) from `main`;
   the page lives at `/<filename>.html`.

---

*Iterated across sessions 2026-07-17 → 07-18. Order of passes: dark desktop → light pane
reskin → blue accent + whitish-gray canvas + Inter → six shell principles + Stocks pills →
grouped-inset material + macOS tooltips → first-party HIG polish (semantic tokens, lighter
type, spring motion) → edge-to-edge + restored sidebar hierarchy → final HIG polish
(unified radii, −12% contrast, diffuse shadows, richer layered background, vibrant glass).*
