# Cross-Asset Regimes — Spec Sheet

**Tab:** `Cross Asset` (sidebar) · **Panel id:** `main-cross-asset` · **Access:** login-gated
(same guard as Warsh / Yen / Journal / Resources)
**Live:** https://global-advisory-dashboard.vercel.app · **Deploys from:** `main`
**Last built:** 2026-07-01 · asof data 2026-06-30

Analyzes the **joint regime of SPX + UST 10Y + DXY** — classifying every trading day
into one of 8 regimes from the signs of three vol-normalized momentum signals, then
slicing that history four ways (Regimes / Attribution / Transitions / Synthesis).

---

## 1. Data pipeline

**Script:** `scripts/cross_asset_fetch.py` → **output:** `prototypes/cross_asset.json`

| Series | Source | Notes |
|---|---|---|
| SPX | yfinance `^GSPC` (close, auto-adjusted) | deep history |
| UST 10Y | FRED `DGS10` | constant-maturity yield, % |
| DXY | yfinance `DX-Y.NYB` | ICE dollar index (matches readouts) |
| 2Y | FRED `DGS2` | synthesis only (curve regime) |
| Real 10Y | FRED `DFII10` | synthesis only (rate driver) |
| 10Y breakeven | FRED `T10YIE` | synthesis only (rate driver) |

- Aligned to a common daily axis, forward-filled, trimmed to where all three core
  series are real: **10,610 days, 1985-01-02 → present.**
- Robust by design: any failed source is skipped with a warning; if a core series is
  missing the run aborts; if only the synthesis extras fail, the Cramér's V table
  falls back to documented seed values.

**JSON shape:**
```
{ updated, asof, n,
  dates[], spx[], y10[], dxy[],          // raw aligned daily series
  readout: { asof, spx, spx_chg_pct, y10, y10_chg_bp, dxy, dxy_chg_pct },
  synthesis: [ { rank, rel, v, cat, interp, real }, ... ] }
```

Everything else (normalized signals, regime classification, frequency/duration,
transition matrix, linkage) is computed **client-side** from the raw series, so every
control button recomputes the whole page from source.

---

## 2. Regime model (the math)

Computed in the browser; depends only on **Method + Lookback + Vol**.

**Daily returns** — SPX & DXY: percent change. 10Y: daily yield change in **bp**.

**Lookback (L) return** — SPX/DXY: `level[t]/level[t−L] − 1`. 10Y: `(y[t]−y[t−L]) × 100` bp.

**Volatility (V)** — sample standard deviation of daily returns over the trailing V days.

**Normalized signal** (per asset):
- **VOL-SCALED:** `signal = L-day return / (dailyVol × √L)` → in **sigma units**
  (a value of +2.0 means the asset moved up by ~2× its normal volatility).
- **Z-SCORE:** `signal = (L-day return − rolling mean over V) / rolling std over V`.

**Regime** = signs of the three signals:
- Stocks **Up** if SPX signal > 0 · Rates **Up** if 10Y signal > 0 (yields rising) ·
  Dollar **Up** if DXY signal > 0.
- Code index: `idx = (stocksUp?0:4) + (ratesUp?0:2) + (dollarUp?0:1)` → **R1…R8**.

### Regime codes & palette
Cool = stocks up (good), warm = stocks down (bad).

| Code | State | Color |
|---|---|---|
| R1 | Stocks Up / Rates Up / Dollar Up | `#3fb950` green |
| R2 | Stocks Up / Rates Up / Dollar Down | `#26c281` emerald |
| R3 | Stocks Up / Rates Down / Dollar Up | `#4a9eff` blue |
| R4 | Stocks Up / Rates Down / Dollar Down | `#2dd4bf` teal |
| R5 | Stocks Down / Rates Up / Dollar Up | `#f85149` red |
| R6 | Stocks Down / Rates Up / Dollar Down | `#ff9f1c` orange |
| R7 | Stocks Down / Rates Down / Dollar Up | `#a371f7` purple |
| R8 | Stocks Down / Rates Down / Dollar Down | `#d857c9` magenta |

### Window aggregations (over the visible range)
- **FREQ** = days in regime / total days.
- **AVG DUR** = days in regime / number of consecutive runs of that regime.
- **Median return** per asset per regime (SPX %, 10Y bp, DXY %).
- **Transition matrix** = day-to-day regime→regime counts, row-normalized to %.
- **Rolling linkage** = mean of the three |pairwise correlations| among daily returns
  (SPX/10Y/DXY) over a `max(V, 20)`-day window, ×100. High = macro-driven, low =
  idiosyncratic.
- **Cumulative move since regime start** = move from the day before the current run
  began through the latest day (SPX %, 10Y bp, DXY %).

**Linkage bands:** ≥60% STRONGLY LINKED (green) · 40–60% MODERATELY LINKED (amber) ·
<40% WEAKLY LINKED (red).

**Color conventions (all tables):** SPX / DXY — green = up. 10Y — green = **yields
down** (falling yields are positive). Banner tint — green risk-on (stocks up) / red
risk-off (stocks down).

---

## 3. Controls (shared state)

| Group | Options | Default |
|---|---|---|
| METHOD | VOL-SCALED · Z-SCORE | VOL-SCALED |
| LOOKBACK | 5D · 10D · 20D · 60D | 20D |
| VOL | 10D · 21D · 42D · 63D | 21D |
| RANGE | 1M · 3M · 6M · YTD · 1Y · 2Y · 5Y · 10Y · 15Y · 20Y · ALL | 2Y |

- Method / Lookback / Vol → recompute regimes and every panel.
- Range → re-window the analysis (regime model unchanged).
- **Range brush** (under the timeline / attribution chart) → drag-scrub a sub-window
  *inside* the selected range; a zoom, not a refilter. Independent per tab.
- Sub-tab-specific rows: **Attribution** analysis window (21/42/63/126D);
  **Transitions** focus (ALL/SPX/10Y/DXY) emphasizes one asset's columns.

Header status cluster shows live **market linkage** + SPX / 10Y / DXY readouts.
Full-width **current-regime banner** below the controls shows the active regime name,
cumulative move since it started, and the linkage label.

---

## 4. Sub-tabs

### Regimes
- **Regime timeline** — colored strip (one of 8 colors per day) over the normalized
  3-line signal chart (green SPX / orange 10Y / blue DXY), zero gridline, range brush.
- **Market linkage** — amber area chart, 0–100%, rolling linkage over the range.
- **Regime frequency** — 8-row table (dot · FREQ · AVG DUR · median SPX/10Y/DXY),
  current regime highlighted + starred; frequency bar chart with R1–R8 legend;
  table-row ↔ bar cross-highlight on hover.

### Attribution
- Analysis-window control + dynamic helper text.
- Three vol-adjusted stat blocks (latest SPX/10Y/DXY signal), "extreme move" caption
  when |signal| > 2.
- Full-history 3-line signal chart with ±2σ dashed reference lines + range brush.

### Transitions
- **Current state** card — regime name bar, three signal boxes, market-linkage
  callout, historical-median-linkage line for the current regime.
- **What's Next** — transition-probability table from the current regime (sorted
  desc, "stay" row highlighted; PROB, HIST OBS, destination median returns, linkage).
- **Regime economics** — per-regime medians + linkage + a THEME stacked bar showing
  which asset drives the common move (widest segment = dominant driver).
- **Transition matrix** — 8×8 amber heatmap, P(row→col), highlighted diagonal +
  trailing STICK column restating stay-probability.

### Synthesis
- Intro explainer + **Relationship Ranking** table: pairwise associations ranked by
  **Cramér's V** across categorical variables (Cross-Asset Regime, Dollar Direction,
  Stock-Bond Quadrant, Curve Regime, Spread Direction, 10Y Rate Driver).
- **Tiers:** V ≥ 0.35 PRIMARY (green) · 0.15–0.35 SECONDARY (amber) · < 0.15
  CONFIRMING (dimmed). Computed over full history from real data.

---

## 5. Files & architecture

| File | Role |
|---|---|
| `scripts/cross_asset_fetch.py` | Fetches sources, computes Cramér's V, writes JSON |
| `prototypes/cross_asset.json` | Raw aligned series + readouts + synthesis (~330 KB) |
| `prototypes/index.html` | Nav entry, `main-cross-asset` panel, CSS, and the JS engine |

- Charts: **Plotly** (`plotly-2.35.2`, the app's existing lib) — line, area, segmented
  heatmap strip, bar, and 8×8 heatmap, themed dark with amber/green/red accents.
- Reuses existing primitives: `.card`, `.itab`, the `stirLayout`-style dark Plotly
  theme, JetBrains Mono, and the app's CSS custom-property tokens.
- Redraw is registered on `window._redraw['cross-asset']` so charts re-size correctly
  on tab-show / window resize.

**Refresh:** run `python scripts/cross_asset_fetch.py` to regenerate the JSON.
(Not yet wired into `scripts/update_and_deploy.ps1` — optional follow-up.)

---

## 6. Notes / deviations from the original mockup
- The prompt described a top-nav + global top-bar and Chart.js; the live app is a
  **sidebar-nav** dashboard on **Plotly** with CSS custom properties. The tab was
  built into the existing chrome (sidebar entry) using the real primitives.
- Data is **real**, not seeded — so the live current regime, frequency table,
  transition probabilities, and Cramér's V values differ from the illustrative
  example numbers in the original prompt.
