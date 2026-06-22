# Global Advisory Dashboard — Specification Sheet

> Single-page, install-as-app market-intelligence dashboard.
> **Entry point:** `prototypes/index.html` (~6,060 lines, ~565 KB, self-contained HTML + inline CSS + inline JS).
> **Spec generated:** 2026-06-22.

---

## 1. Overview

| Field | Value |
|---|---|
| Product name | **Global Advisory Dashboard** (PWA short name: *Advisory*) |
| Purpose | A macro-to-micro market intelligence console: regime read at the top, drilling down through growth/inflation/rates/liquidity, technicals, positioning, research and a daily journal. |
| Audience | Internal advisory / trading desk. |
| Form factor | Single-file SPA, installable as a standalone PWA (mobile + desktop). |
| Theme | Dark surface (`#000000`) with an **amber** primary accent (`#ffb800`); secondary amber `#ffce5c`. |
| Typography | **JetBrains Mono** (400–800) for all text; **Material Symbols Outlined** for icons (both via Google Fonts CDN). |
| Charting | **Plotly.js 2.35.2** (CDN) — every chart on the site (~50+ instances: line, bar, candlestick, scatter, dual-axis). |
| Framework | None. 100% vanilla JS + CSS. No build step. |

> **Design note:** `.gaai/.../prd/PS_Design.md` documents a PlayStation-blue design system. The shipped dashboard reuses that system's CSS variable *names* (`--ps-blue`, `--ps-cyan`) but overrides the values to amber. The spec below reflects the **live** dashboard, not the template.

---

## 1a. Getting Started — A Guide for New Users

**Where to look first.** The dashboard is laid out top-to-bottom on the left sidebar in the order you should read it: start at **Macro** (the regime read), then work down through the detail tabs. The fastest orientation is the **Macro** tab — it tells you the overall growth/inflation/rates/liquidity regime in one screen. Everything below it explains *why*.

**The 60-second walkthrough**
1. **Open Macro.** Read the 4-criterion regime grid (Growth, Inflation, Yield-Curve Regime, Global Credit Creation). The amber values are the current read.
2. **Click the expandable criteria.** *Yield-Curve Regime* and *Global Credit Creation* (and the *Market Narrative* / *Long Bias* boxes) open a decision table showing the logic behind the call. Click again to collapse.
3. **Drill into a driver.** Use the indented Macro sub-tabs — **Growth → Inflation → Yields → Liquidity → Yen Carry Trade** — to see the data behind each regime criterion.
4. **Check the tape.** Jump to **Technicals** for the market-regime signals (trend, breadth, buying pressure), then **Breadth / Leadership / Positioning** for what's leading and how traders are positioned.
5. **Go bottom-up.** **Research** (your sector theses) and **Screener** (daily movers + IPOs) cover single names. **Journal** is your dated tactical note.

**Reading the navigation**
- **Bold sidebar items** are top-level tabs; **indented items** are sub-tabs of the section above them.
- The **active tab** is highlighted amber with a left border.
- Click any nav item to swap the main panel — the page never reloads.

**Two long-form briefings.** **Warsh Playbook** and **Yen Carry Trade** are full research write-ups (hero + multi-section narrative with inline charts), not data tables — read them like an article, scrolling top to bottom.

**Controls you'll use everywhere**
| Control | Where | What it does |
|---|---|---|
| Inner tabs / toggles | Inflation (CPI/PCE/PPI), Yields (SOFR/Fed-Funds, Meetings/Strip/Spreads), Liquidity, Breadth (country), Screener (US/China) | Switch the series or view shown in that panel |
| Period buttons | Yields (1Y/3Y/5Y/All), Positioning lookback slider | Change the time window |
| Axis selectors | Breadth → Quadrant Rotation | Re-plot the scatter on different horizons |
| ← / → date steppers | Journal, Screener | Move between dates |
| Chart hover / legend | Every Plotly chart | Hover for values; click a legend entry to hide/show a series; drag to zoom; PNG export top-right |

**Editing (optional, for editors).** Most of the dashboard is read-only. To edit **Journal**, **Research**, or **Leadership**, click the **person icon** in the top-right header and log in. Edit buttons then unlock; your changes are saved server-side. Without logging in you can view everything but not change it.

**On mobile / small screens.** The sidebar collapses to a **hamburger menu** (top-left); tap it to open the nav drawer. The dashboard is installable as an app (PWA) — use your browser's "Add to Home Screen" / "Install" option.

**Tip:** the **fullscreen toggle** in the header gives you an edge-to-edge view for presenting, and the **refresh** control re-pulls the latest data.

---

## 2. Architecture

```
Browser (index.html, single file)
  ├─ inline CSS  (theme tokens, layout, components)
  ├─ inline JS   (tab routing, fetch loaders, Plotly render, edit/auth)
  ├─ Plotly.js   (CDN)
  └─ fetch() →  *.json  (static data, cache-busted with ?_=Date.now())
                /api/*  (Python persistence endpoints — edits only)

Data pipeline (Python, scripts/ + src/)
  fetch/compute  →  export  →  prototypes/*.json  →  dashboard reads
```

- **Read path:** the dashboard `fetch()`es static JSON files sitting next to `index.html`. No server required to *view*.
- **Write path:** edit features POST to a small Python API (`api/*.py`) that persists user content to `_api_*.json`.
- **Layout shell:** fixed left **sidebar** (nav) + top **header** (title, session date, auth, fullscreen) + scrolling **main panel** that swaps content per tab via `showMain(id, btn)`.

---

## 3. Navigation Map

Sidebar nav (in display order). Parent tabs in **bold**, indented entries are sub-tabs.

| # | Label | id | Icon | Notes |
|---|---|---|---|---|
| 1 | **Macro** | `macro` | insights | Default active tab |
| 1a | Growth | `growth` | trending_up | |
| 1b | Inflation | `inflation` | thermostat | |
| 1c | Yields | `stir` | show_chart | |
| 1d | Liquidity | `liquidity` | water_drop | |
| 1e | Yen Carry Trade | `yen` | currency_yen | |
| 2 | **Warsh Playbook** | `warsh` | menu_book | Long-form research page |
| 3 | **Technicals** | `execution` | candlestick_chart | |
| 3a | Breadth | `breadth` | bar_chart | |
| 3b | Leadership | `leadership` | leaderboard | |
| 3c | Positioning | `positioning` | swap_horiz | |
| 4 | **Research** | `research` | science | |
| 4a | Screener | `screener` | filter_alt | |
| 5 | **Journal** | `journal` | edit_note | |
| — | Collapse | — | left_panel_close | Sidebar collapse control (desktop) |

**Header controls:** title `Global Advisory Dashboard`; session-date readout; auth/login icon (`person`) → edit-unlock modal; fullscreen toggle. Mobile (<900px): sidebar becomes a hamburger drawer; collapse control hidden.

---

## 4. Tab Specifications

### 4.1 Macro (`macro`) — default
- **Macro Regime** — 4-criterion grid: **Growth** (GDPNow vs GDP), **Inflation** (expectations rising/falling), **Yield Curve Regime** (expandable: 7 condition→outcome rows, e.g. Bear Steepener / Bull Flattener), **Global Credit Creation** (expandable: 6 scored conditions, e.g. SOFR vs IORB).
- **Market Narrative & Long Bias** — two expandable decision tables: **Market Narrative** (Reflation / Goldilocks / Stagflation / Deflation from growth×inflation) and **Long Bias** (High Beta / Secular / Cyclicals / Defensives from regime×GCC).
- **Framework narrative** — explanatory text block (amber left-border) on the macro chain (growth → inflation → yields → FX → liquidity).
- **Start here:** read the 4 amber regime values, then expand any criterion for the logic behind it.
- **Data:** `regime.json`, `gdpnow.json`.

### 4.2 Growth (`growth`)
- Single line chart, GDPNow YoY %. Source label: *Atlanta Fed GDPNow*.
- **Start here:** is the GDPNow line rising or falling? That's the growth read feeding Macro.
- **Data:** `gdpnow.json`.

### 4.3 Inflation (`inflation`)
- Measure tabs **CPI / PCE / PPI** × **Headline / Core** (6 combinations).
- Each combo: dual-axis line (YoY % vs breakeven inflation) + MoM % line. Source: *BLS / BEA*.
- **Start here:** default view is CPI · Headline; compare the YoY line against the breakeven on the right axis.

### 4.4 Yields (`stir`)
- **Yield Curve:** 2s10s spread line + yield-level bar chart (2Y/5Y/10Y/30Y); period selector **1Y / 3Y / 5Y / All**. Source: *US Treasury / FRED*.
- **US STIR:** 4 KPI boxes (Terminal Rate, Terminal−EFFR, Terminal−+6M, Terminal−+12M). Product tabs **SOFR Futures / Fed Funds Futures**; view tabs **Meetings / Strip / Spreads**:
  - *Meetings* — implied policy-path line + meeting table.
  - *Strip* — contract table (Last PX, Implied Rate, ±OCR, PX 1D/5D/1M, Volume, OI, OI Chg).
  - *Spreads* — calendar-spread matrix (+3/+6/+9/+12M).
- **Start here:** glance at the 4 STIR KPIs (Terminal Rate & spreads), then the 2s10s spread chart.
- **Data:** `price_data.json`, `stir.json`.

### 4.5 Liquidity (`liquidity`)
- Left: inner tabs **Reserve Balance / Fed Liquidity / Trade Balance / Carry Trade / Real Yields**, each a chart with its own FRED source label.
- Right: **Combined YoY overlay** — Reserve Balance, Fed Liquidity, Trade Balance, Carry Trade on multi-axis.
- **Start here:** the right-hand combined YoY overlay shows all four liquidity series at once.
- **Data:** `carry.json` (+ liquidity series in price/FRED feeds).

### 4.6 Yen Carry Trade (`yen`)
- Long-form research page (hero + 9 sections), each with 2–3 columns and inline charts (~200px): decoupling/fair-value, USDJPY vs DXY decomposition, Japan 1Y real rate, 10s30s JGB vs core CPI, TOPIX Banks risk gauge, reflexive loop & Aug-2024 unwind, structural chain diagram (8 steps), three academic papers, carry mechanics, and the playbook summary.
- **Start here:** read top-to-bottom like an article; the closing Playbook is the takeaway.
- **Data:** `yen.json`, `price_data.json`.

### 4.7 Warsh Playbook (`warsh`)
- Long-form research page (hero + 6 sections): information architecture (2Y release impulses, MOVE), the curve as verdict (2s10s, 1M change), pricing hikes (SOFR Z6), uneven transmission (30Y mortgage vs 10Y, EURUSD vs 2Y diff), real rates & the dollar (10Y real vs DXY, daisy-chain diagram), and the playbook.
- **Start here:** read top-to-bottom like an article; the closing Playbook is the takeaway.
- **Data:** `warsh.json`, `price_data.json`.

### 4.8 Technicals (`execution`)
- **Market Regime** two-column: left = Market Signal (SPX vs 12D/25D EMA), Breadth Signal (MMTH), Buying Signal (NCFD Hot/Warm/Lukewarm/Cold + NHNL), plus a regime-summary text block; right = "What is this?" explainer (signal thresholds 25/75, conjunction logic). Source: *Bloomberg*.
- **Start here:** read the three signal boxes (left), then the regime summary; the right column explains each.

### 4.9 Breadth (`breadth`)
- Country toggle **United States / China / Korea**.
- **Module 1 — Industry Relative to SPX:** table (Current RS, 21D RS EMA, Gap).
- **Module 2 — Industry Relative to Each Other:** Daily/Weekly/Monthly ranks + "See Return Attribution" toggle.
- **Module 3 — Quadrant Rotation:** scatter with X-axis (1D/5D/10D) and Y-axis (1M/2M/3M) controls.
- **Start here:** top of Module 1's table = biggest positive RS gap (strongest industries).
- **Data:** `sector_rotation.json`, `mfra_group.json`.

### 4.10 Leadership (`leadership`)
- Snapshot date picker + "Add Day"; **Leadership Breadth** bar chart (clickable bars) + **Net Rotation** column chart; 4-column category grid (Leading / Bounced Off / Uptrending / Downtrending) populated per selected snapshot.
- **Start here:** click a bar in Leadership Breadth to load that day's category grid below.
- **Persisted via** `/api/save-leadership` (auth required).

### 4.11 Positioning (`positioning`)
- COT contract grid → on click, detail view: asset-class dropdown (Agriculture/Energy/Metals/Currencies/Bonds/Indices), contract dropdown, price candlestick, net-positions chart, and a lookback slider (52–500 weeks).
- **Start here:** click any contract tile to open its positions detail; use the slider to widen history.
- **Data:** `cot_data.json` (1.4 MB).

### 4.12 Research (`research`)
- Grid of sector cards (sort by Name/Date/Performance) + "+ New".
- **Research page modal:** editable title; Thesis + Constituents (view/edit toggle, textarea editing); missing-ticker detector; YTD-performance bar chart; market-cap vs YTD-return bubble chart; sortable constituents table (1D/1W/1M/6M/1Y/YTD/Mkt Cap).
- **Start here:** click a sector card to open its thesis + performance; log in to edit or add one.
- **Data:** `ticker_perf.json`; **persisted via** `/api/save-research`.

### 4.13 Screener (`screener`)
- Date stepper + Daily/Weekly toggle + market toggle **United States / China**.
- **Movers** cards with catalyst legend (Continuation / Earnings·Guidance / Analyst Action / Other) + **IPOs** cards (offer price, 1st-day return, YTD).
- **Start here:** scan Movers by catalyst color; use ← / → to change date, toggle for China.
- **Data:** `screener_movers.json`, `screener_movers_cn.json`, `screener_ipos.json`.

### 4.14 Journal (`journal`)
- Date stepper + Daily/Weekly; view/edit toggle on a tactical note (defensive posture, exposure calls, etc.).
- **Start here:** read the latest note; log in and hit Edit to write the day's tactical call.
- **Persisted via** `/api/save-journal`.

---

## 5. Data Sources

All `*.json` live alongside `index.html` in `prototypes/` and are fetched cache-busted (`?_=Date.now()`).

| File | Size | Feeds | Producer script |
|---|---|---|---|
| `regime.json` | 481 B | Macro Regime states + narratives | `fetch_regime.py` |
| `gdpnow.json` | 128 KB | Macro / Growth | `fetch_gdpnow.py` |
| `carry.json` | 114 KB | Liquidity (Carry Trade) | `carry_export.py` |
| `stir.json` | 22 KB | Yields / US STIR | `stir_pipeline.py`, `barchart_fetch.py` |
| `cot_data.json` | 1.4 MB | Positioning (COT) | `export_cot_json.py`, `cot_report_pull.py` |
| `sector_rotation.json` | 145 KB | Breadth (Modules 1–3) | `export_sector_json.py`, `sector_data_collector.py` |
| `mfra_group.json` | 120 KB | Breadth (return attribution) | `mfra_export.py`, `mfra_compute.py` |
| `price_data.json` | 4.3 MB | Yields / Warsh / Yen / Research charts | `export_price_json.py` |
| `ticker_perf.json` | 420 KB | Research / Screener | `export_ticker_perf.py` |
| `screener_movers.json` | 306 KB | Screener (US movers) | `screener_fetch.py` |
| `screener_movers_cn.json` | 74 KB | Screener (China movers) | `screener_fetch.py` |
| `screener_ipos.json` | 7.2 KB | Screener (IPOs) | `screener_fetch.py` |
| `warsh.json` | 8.8 KB | Warsh Playbook | `fetch_warsh.py` |
| `yen.json` | 12.6 KB | Yen Carry Trade | `fetch_yen.py` |

**Upstream feeds:** FRED, Atlanta Fed GDPNow, US Treasury, BLS/BEA, CFTC (COT), Barchart (STIR), Bloomberg (technicals), yfinance/screener feeds. Validation: `scripts/validate_data_sources.py`. Deploy: `scripts/update_and_deploy.ps1`.

---

## 6. Edit & Persistence API (Python)

| Endpoint | File | Function | Auth |
|---|---|---|---|
| `POST /api/edit-auth` | `api/edit-auth.py` | Verify username/password, return role | — |
| `POST /api/save-journal` | `api/save-journal.py` | Persist journal → `_api_journal.json` | edit headers |
| `POST /api/save-research` | `api/save-research.py` | Persist sectors/theses → `_api_research.json` | edit headers |
| `POST /api/save-notes` | `api/save-notes.py` | Persist notes → `_api_notes.json` | edit headers |
| `POST /api/save-leadership` | `api/save-leadership.py` | Persist leadership snapshots | **required** (`X-Edit-User`, `X-Edit-Password`) |

Auth flow: header `person` icon → modal → `POST /api/edit-auth` → on success, edit buttons unlock across Journal / Research / Leadership.

---

## 7. Design System (live)

**Color tokens** (CSS custom properties on `:root`):

| Token | Value | Role |
|---|---|---|
| `--ps-blue` | `#ffb800` | Primary accent (amber) |
| `--ps-cyan` | `#ffce5c` | Secondary accent / hover |
| `--surface` | `#000000` | Base background |
| `--surface-low` | `#0e0e0e` | Cards / raised surfaces |
| `--text` | `#e5e2e1` | Primary text |
| `--text-muted` | `#9e8f78` | Secondary text |

- **Type:** JetBrains Mono throughout; nav labels uppercased with letter-spacing; size scale via `--fs-*` tokens.
- **Active nav:** amber left-border + faint amber gradient wash.
- **Charts:** Plotly, dark template, amber-family series colors, custom HTML tooltip divs for special formatting.

---

## 8. Interactive Features

- **Tab routing** — `showMain(id, btn)` swaps `#main-*` panels and active nav state.
- **Inner tabs / toggles** — Inflation (measure×type), STIR (product×view), Liquidity series, Breadth country & rank mode, Screener market & timeframe.
- **Filters/controls** — Yields period (1Y/3Y/5Y/All), Quadrant axis selectors, Positioning lookback slider & dropdowns, Research sort.
- **Date navigation** — Journal & Screener date steppers; Leadership snapshot picker + Add Day.
- **Expandable logic tables** — `toggleDrop()` on Macro Regime criteria & narrative/bias.
- **Editing** — Journal / Research / Leadership with auth gating and Python persistence.
- **Chart interactivity** — Plotly hover, legend toggle, pan/zoom, PNG export; custom tooltips.
- **Shell** — sidebar collapse, mobile hamburger drawer, fullscreen toggle, data refresh.

---

## 9. PWA / Installability

- `manifest.json`: name *Global Advisory Dashboard*, short name *Advisory*, `display: standalone`, theme/background `#000000`, icons 192/512 (`any maskable`).
- `favicon.svg` (amber mask-icon), `icon-180.png` (Apple touch), `icon-192.png`, `icon-512.png`.
- Apple/mobile web-app-capable meta tags, black-translucent status bar.

---

## 10. Responsive Behavior

- **≥900px:** fixed sidebar + collapse control; multi-column panel grids.
- **<900px:** sidebar → hamburger drawer; larger tap targets; grids reflow to single column; collapse control hidden; charts hold 320–350px height.

---

## 11. At a Glance

- **5 top-level tabs · 9 sub-tabs · ~14 panel groups**
- **14 static JSON data sources** + **5 persistence endpoints**
- **~50+ Plotly charts** (line, bar, candlestick, scatter, dual-axis)
- **Single-file vanilla SPA**, **PWA-installable**, **dark + amber** theme
- **~15 Python pipeline scripts** producing the data layer
