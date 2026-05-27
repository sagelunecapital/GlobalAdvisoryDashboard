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
  - screener
  - positioning
  - breadth
  - vercel
  - api
created_at: 2026-04-17
updated_at: 2026-05-22
depends_on:
  code_paths:
    - src/db/schema.py
    - src/macro/db/macro_schema.py
    - src/analysis/regime.py
    - src/liquidity/db/liquidity_schema.py
    - update_dashboard.py
    - gaai_deliver.py
    - vercel.json
    - .github/workflows/regime-update.yml
    - .github/workflows/dashboard-update.yml
    - .github/workflows/data-audit.yml
  decisions:
    - DEC-2026-04-22-01
    - DEC-2026-04-22-02
    - DEC-2026-04-27-01
    - DEC-2026-04-27-02
    - DEC-2026-04-27-03
    - DEC-2026-04-27-04
    - DEC-2026-05-12-01
    - DEC-2026-05-12-02
  epics:
    - E01
    - E02
    - E03
    - E04
    - E05
    - E06
    - E07
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

## Tech Stack & Conventions

- **Language(s):** Python 3.x (DEC-2026-04-22-01)
- **Frameworks:** None — data pipeline only; dashboard is plain HTML/JS
- **Data sources:**
  - yfinance `^GSPC` for SPX daily OHLC
  - EODData (`EODDATA_API_KEY`) for MMTH (DEC-2026-04-22-02)
  - FRED API (`FRED_KEY`) for liquidity (WALCL, WDTGAL, WLRRAL, WRESBAL, BOPGSTB), macro indicators, SOFR, IORB, T5YIE, T2YIE, GDP YoY%
  - Atlanta Fed GDPNow Excel API for GDP nowcast
  - yfinance / Barchart for macro tickers, futures, FX
  - yfinance `BTC-USD` for Bitcoin price
  - CFTC Socrata API (`sodapy`) for COT legacy futures data (14 contracts)
  - CME ZQ/SR3 futures via yfinance for STIR pipeline
  - TradingView screener via Playwright (headless) for movers
  - MCP server (`scripts/fred_mcp_server.py`) — wraps FRED fetchers as Claude tools
- **Database:** SQLite (WAL mode, `data/` directory) — local development only; `data/gaai-jobs.db` for GAAI daemon job state (DEC-2026-05-12-01)
- **Dependencies:** `requirements.txt` (yfinance, pandas, requests, pytest, pytest-cov, openpyxl, pyyaml); additional: sodapy, playwright, plotly, numpy, mcp (not in requirements.txt)
- **Deployment:** Vercel static hosting (`outputDirectory: prototypes`)
- **CI/CD:** GitHub Actions — weekday auto-commits of `regime.json` (22:00 UTC), `gdpnow.json` (21:00 UTC); dashboard HTML injection at 23:00 UTC; data audit on PR merge
- **Windows deploy script:** `scripts/update_and_deploy.ps1` — runs all Python pipeline scripts, commits data files to main, pushes to Vercel
- **Key conventions:**
  - `spx_daily_high` column name (DEC-2026-04-18-01); SPX price = daily HIGH always
  - EMA via `pandas.ewm(span=N, adjust=False).mean()`
  - 2yr SPX fetch for EMA warm-up, trim to 1yr post-computation
  - External API calls are always mocked in tests (no live calls in test suite)
  - SQLite connections always enable WAL mode + foreign keys
  - All Python print/stderr output is ASCII-only (Windows console cp1252)
  - Use `pathlib.Path` for all path construction in scripts — no `os.path.join` or string concatenation

---

## Dashboard Tab Inventory (production — main branch)

| Tab | Type | Sub-tabs | Data Source |
|---|---|---|---|
| Macro | top-level | — | update_dashboard.py HTML injection |
| Yields | sub (under Macro) | Meetings / Strip / Spreads | stir.json (stir_pipeline.py) |
| Liquidity | sub (under Macro) | Reserve Balance / Fed Liq / Trade Balance / Bitcoin | update_dashboard.py HTML injection |
| Technicals | top-level | Breadth, Positioning | — |
| Breadth | sub (under Technicals) | — | regime.json (fetch_regime.py) |
| Positioning | sub (under Technicals) | COT / Sector Rotation | cot_data.json, sector_rotation.json |
| Research | top-level | Screener | ticker_perf.json |
| Screener | sub (under Research) | United States / China toggle; Movers / IPOs | screener_movers.json, screener_movers_cn.json, screener_ipos.json |
| Journal | top-level | Daily / Weekly toggle | client-side only (no server data) |

---

## Static Data Files in prototypes/

| File | Updated By | Content |
|---|---|---|
| `index.html` | update_dashboard.py + GH Action | Main dashboard with injected JS data block |
| `regime.json` | fetch_regime.py (GH Action 22:00 UTC) | SPX regime, EMA12/25, MMTH, divergence |
| `gdpnow.json` | fetch_gdpnow.py (GH Action 21:00 UTC) | Atlanta Fed GDPNow subcomponent contributions |
| `stir.json` | stir_pipeline.py (Windows Task Scheduler) | Fed Funds futures, EFFR/SOFR, FOMC schedule, probability matrix |
| `cot_data.json` | export_cot_json.py | CFTC COT positioning for 14 futures contracts |
| `price_data.json` | export_price_json.py | 3yr daily OHLC for COT contract tickers |
| `sector_rotation.json` | export_sector_json.py | Sector RS rankings, EMA21 signals, US/China/Korea |
| `ticker_perf.json` | export_ticker_perf.py | Per-ticker performance and market cap for Research tab |
| `screener_movers.json` | screener_fetch.py (manual) | US daily movers with Claude-enriched catalysts |
| `screener_movers_cn.json` | screener_fetch_cn.py (manual) | China/HK movers with Claude-enriched catalysts |
| `screener_ipos.json` | screener_fetch.py (manual) | US IPOs (key: `us`) and HK IPOs (key: `hk`) |

---

## Screener Workflow (canonical)

1. Run `python scripts/screener_fetch.py` — fetches raw US movers and IPOs
2. Ask Claude to enrich — Claude patches JSON files directly (catalyst, source, catalyst_type, group_id)
3. Ask Claude to push — `git add` + commit + push to main
4. Run `! powershell -Command "schtasks /run /tn 'GAAI Dashboard Update'"` — updates all other data

**Key rules:**
- Enrichment patches files in-place; never overwrites previously enriched committed data
- HK IPO prices and market caps are stored in USD; display multiplies by HKD=7.78
- yfinance HK tickers require `NNNN.HK` format (4-digit zero-padded)
- Hot IPO threshold: first-day return >= 30% (`ipo_close / price_usd - 1 >= 0.30`)
- Movers schema: `{updated_at, by_date: {date: [rows]}}` with fields: ticker, company, sector, industry, country, mkt_cap (USD), pe, price, change_pct, volume, catalyst, source, source_url, catalyst_type, group_id, group_summary

---

## Architectural Boundaries

### Three Parallel Delivery Patterns (coexist until E06)

**Pattern A — src/ Library (E01, E02, E03 stories):**
- `src/db/` — market-regime SQLite layer (`indicators` table: spx_daily_high, EMA12, EMA25, MMTH)
- `src/fetch/` — market-regime fetchers (SPX via yfinance, MMTH via EODData)
- `src/analysis/` — divergence detection (`DivergenceResult` enum) + regime classification (`RegimeLabel` enum: GREEN/YELLOW/RED)
- `src/macro/db/` — macro indicators SQLite layer (`macro_indicators` table, composite PK on indicator_id + date)
- `src/macro/fetch/` — macro fetchers (FRED, yfinance, GDPNow, monthly indicators)
- `src/liquidity/` — FRED liquidity series + BTC fetch/persist (delivered E02S01, on PR #4, not yet in staging)
- `src/macro/` and `src/liquidity/` are **self-contained** — do NOT import from `src/db/`

**Pattern B — update_dashboard.py (current live production):**
- Monolithic script: fetches all live data inline (FRED, yfinance, Investing.com scrape)
- Computes all signals inline (SPX regime, liquidity, macro, cross-signal regime)
- Injects JS variable blocks into `prototypes/index.html` between DATA BLOCK markers
- Run via Windows Task Scheduler daily (`scripts/update_and_deploy.ps1`) or GH Action at 23:00 UTC

**Pattern C — GH Actions (pre-computed static data):**
- `scripts/fetch_regime.py` → `prototypes/regime.json` (committed daily 22:00 UTC)
- `scripts/fetch_gdpnow.py` → `prototypes/gdpnow.json` (committed daily 21:00 UTC)
- `data-audit.yml` — data validation gate on PR merges
- Vercel serves `prototypes/` as the static hosting directory

**E06 Target Architecture (Vercel Serverless):**
- Python serverless functions under `api/` directory
- Five endpoints: `/api/health`, `/api/regime`, `/api/macro`, `/api/liquidity`, `/api/regime-macro`
- Stateless — fetches live data on every request; no SQLite dependency
- Replaces Pattern B (HTML injection); Pattern C (GH Actions JSON) continues for historical charts

---

## Known Constraints

- SQLite DBs are local-only — not viable for Vercel serverless (E06 explicitly stateless)
- FRED API key is hardcoded in `update_dashboard.py` — must be moved to env var before E06 or public exposure
- `src/` library and `update_dashboard.py` are parallel implementations of overlapping fetch logic (accepted short-term, E06 is the consolidation point — DEC-2026-04-27-04)
- Investing.com scrape in update_dashboard.py is fragile (user-agent + HTML parsing; prone to breakage)
- `sodapy`, `playwright`, `plotly`, `numpy`, `mcp` are used in scripts but NOT in `requirements.txt` — inconsistency
- `scripts/update_and_deploy.ps1` hardcodes a Python path (`C:\Users\lance\AppData\Local\Programs\Python\Python313\python.exe`)
- Divergence detection requires >=90 calendar days of history before results are reliable

---

## Out of Scope (Permanent)

- Authentication or authorization (internal dashboard only)
- Sub-weekly / intraday data for Macro indicators
- Alerts or push notifications
- User-configurable indicator selection
- Intraday or tick-level data for any module

---

## Module & Epic Inventory

| Module | Status | Epic(s) | Delivery Notes |
|---|---|---|---|
| Market Regime | Active — E01S03 done (PR #5 open), E01S04/S05 refined | E01 | E01S01/S02/S06 merged; regime.py + RegimeLabel/RegimeResult delivered |
| Liquidity | Delivered (PR #4 open to staging) | E02 | E02S01 done — src/liquidity/ package (fetch + db); E02S02–S05 refined |
| Macro | Delivered (merged to staging as PR #2) | E03 | E03S01 done — src/macro/ package with 32 indicators; E03S02–S05 refined |
| Dashboard Prototype | Scoped — E04 (gated on E01S04+E02S04+E03S04) | E04 | Not yet started |
| Cross-Signal Regime | Partial — E05S01/S04 done via manual delivery | E05 | E05S02/S03 refined; depends on E03/E02 pipeline |
| Live API Backend | Scoped — E06 (all stories refined) | E06 | Vercel serverless; replaces HTML injection |
| GAAI Daemon (Windows) | Active — E07S01 done (PR #6 open) | E07 | gaai_deliver.py delivered; E07S02–S05 refined |
| Screener | Live in production (manual workflow) | — | US + China/HK; movers + IPOs; Claude enrichment |
| STIR / Yields | Live in production | — | stir_pipeline.py → stir.json |
| COT Positioning | Live in production | — | cot_report_pull.py + export_cot_json.py |
| Sector Rotation | Live in production | — | sector_data_collector.py + export_sector_json.py |
| Journal | Live in production (client-side only) | — | Daily/Weekly toggle; no server data |
