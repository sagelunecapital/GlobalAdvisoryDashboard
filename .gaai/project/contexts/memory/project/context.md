---
type: memory
category: project
id: PROJECT-001
tags:
  - product
  - vision
  - scope
  - fund-management
  - dashboard
  - market-regimes
  - liquidity
  - macro
  - cross-signal
  - vercel
  - api
created_at: 2026-04-17
updated_at: 2026-04-27
depends_on:
  code_paths:
    - src/db/schema.py
    - src/macro/db/macro_schema.py
    - update_dashboard.py
    - vercel.json
    - .github/workflows/regime-update.yml
  decisions:
    - DEC-2026-04-22-01
    - DEC-2026-04-22-02
    - DEC-2026-04-27-01
    - DEC-2026-04-27-02
    - DEC-2026-04-27-03
  epics:
    - E01
    - E02
    - E03
    - E04
    - E05
    - E06
refresh_tier: 2
---

# Project Memory

## Project Overview

**Name:** Fund Manager Daily Dashboard

**Purpose:** A consolidated decision-support dashboard for fund managers. Aggregates daily market data and signals from multiple sources into a single interface, surfaces how those signals interact, and produces an alignment read that enables cohesive investment decisions.

**Target Users:** Fund managers (internal team). Not a public product.

**Delivery URL:** Hosted on Vercel; `prototypes/` is the static output directory.

---

## Core Problems Being Solved

- Daily market data is fragmented across multiple sources — no single consolidated view
- Signal interaction and cross-indicator alignment is assessed manually, introducing inconsistency
- Decision-making requires reconciling multiple data points; the dashboard should surface the cohesive read directly

---

## Success Metrics

- All daily-check data consolidated in one interface
- Market regime correctly computed and displayed in real time
- Signal interaction and alignment visible without manual cross-referencing
- Fund managers can arrive at a cohesive decision read from the dashboard alone

---

## Tech Stack & Conventions

- **Language(s):** Python 3.x (DEC-2026-04-22-01)
- **Frameworks:** None — data pipeline only; dashboard is plain HTML/JS
- **Data sources:**
  - yfinance `^GSPC` for SPX daily OHLC
  - EODData (`EODDATA_API_KEY`) for MMTH (DEC-2026-04-22-02)
  - FRED API (`FRED_KEY`) for liquidity (WALCL, WDTGAL, WLRRAL, WRESBAL, BOPGSTB), macro indicators, SOFR, IORB, GDP YoY%
  - Atlanta Fed GDPNow Excel API for GDP nowcast
  - yfinance / Barchart for EURCHF 5-day performance and macro tickers
  - yfinance `BTC-USD` for Bitcoin price (CoinGecko-equivalent via yfinance)
- **Database:** SQLite (WAL mode, `data/` directory) — local development only; NOT used in Vercel production (E06)
- **Dependencies:** `requirements.txt` (yfinance, pandas, requests, pytest, pytest-cov, openpyxl)
- **Deployment:** Vercel static hosting (`outputDirectory: prototypes`)
- **CI/CD:** GitHub Actions — weekday auto-commits of `regime.json` (22:00 UTC) and `gdpnow.json` (21:00 UTC)
- **Key conventions:**
  - `spx_daily_high` column name (DEC-2026-04-18-01); SPX price = daily HIGH always
  - EMA via `pandas.ewm(span=N, adjust=False).mean()`
  - 2yr SPX fetch for EMA warm-up, trim to 1yr post-computation
  - External API calls are always mocked in tests (no live calls in test suite)
  - SQLite connections always enable WAL mode + foreign keys

---

## Architectural Boundaries

### Two Parallel Delivery Patterns (coexist until E06)

**Pattern A — src/ Library (E01, E02, E03 stories):**
- `src/db/` — market-regime SQLite layer (`indicators` table: spx_daily_high, EMA12, EMA25, MMTH)
- `src/fetch/` — market-regime fetchers (SPX via yfinance, MMTH via EODData)
- `src/analysis/` — divergence detection (bearish/bullish/none/data-gap enum)
- `src/macro/db/` — macro indicators SQLite layer (`macro_indicators` table, composite PK on indicator_id + date)
- `src/macro/fetch/` — macro fetchers (FRED, yfinance, GDPNow, monthly indicators)
- `src/macro/` is **self-contained** — does NOT import from `src/db/`

**Pattern B — update_dashboard.py (current live production):**
- Monolithic script: fetches all live data inline (FRED, yfinance, EODData, BTC-USD)
- Computes all signals inline (SPX regime, liquidity, macro, cross-signal regime)
- Injects JS variable blocks into `prototypes/index.html` between DATA BLOCK markers
- Run manually or via Windows Task Scheduler daily after market close
- Parallel to `src/` — no shared code (DEC-2026-04-27-04)

**Pattern C — GH Actions (pre-computed static data):**
- `scripts/fetch_regime.py` → `prototypes/regime.json` (committed to repo daily)
- `scripts/fetch_gdpnow.py` → `prototypes/gdpnow.json` (committed to repo daily)
- Vercel serves `prototypes/` as the static hosting directory

**E06 Target Architecture (Vercel Serverless):**
- Python serverless functions under `api/` directory
- Five endpoints: `/api/health`, `/api/regime`, `/api/macro`, `/api/liquidity`, `/api/regime-macro`
- Stateless — fetches live data on every request; no SQLite dependency
- Replaces Pattern B (HTML injection); Pattern C (GH Actions JSON) continues for historical charts

---

## Known Constraints

- SQLite DBs are local-only — not viable for Vercel serverless (E06 explicitly stateless)
- FRED API key is currently hardcoded in `update_dashboard.py` — must be moved to env var before any public exposure or E06 deployment
- EODData requires `EODDATA_API_KEY` env var; falls back gracefully to None
- `src/` library and `update_dashboard.py` are parallel implementations of overlapping fetch logic (accepted short-term, E06 is the consolidation point)
- Divergence detection requires ≥90 calendar days of history before results are reliable

---

## Out of Scope (Permanent)

- Authentication or authorization (internal dashboard only)
- Sub-weekly / intraday data for Macro indicators
- Alerts or push notifications
- User-configurable indicator selection
- Intraday or tick-level data for any module

---

## Module Inventory

| Module | Status | Epic(s) | Notes |
|---|---|---|---|
| Market Regime | Active — E01 (E01S03–E01S05 in backlog) | E01 | E01S01, E01S02, E01S06 done |
| Liquidity | Scoped — E02 (all stories refined) | E02 | WALCL, WDTGAL, WLRRAL, WRESBAL, BOPGSTB, BTC |
| Macro | Scoped — E03 (all stories refined) | E03 | 32 indicators, 5 categories, 2σ alerts |
| Dashboard Prototype | Scoped — E04 (refined, gated on E01S04+E02S04+E03S04) | E04 | Single-file HTML prototype |
| Cross-Signal Regime | Active — E05 (E05S02–E05S03 in backlog) | E05 | Growth, Inflation, MPS, GCC, Narrative, Long Bias |
| Live API Backend | Scoped — E06 (all stories refined) | E06 | Vercel serverless; replaces HTML injection |
| Breadth | Future | TBD | Not yet scoped |
| Execution | Future | TBD | Not yet scoped |
