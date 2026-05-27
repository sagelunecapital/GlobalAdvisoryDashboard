---
type: memory
category: project
id: PROJECT-002
tags:
  - data-sources
  - market-data
  - spx
  - mmth
  - market-regimes
  - screener
  - cot
  - stir
  - sector-rotation
created_at: 2026-04-18
updated_at: 2026-05-22
---

# Confirmed Market Data Sources

---

## Market Regime

### SPX (S&P 500) OHLC Historical Data
- **Source:** yfinance `^GSPC`
- **Price used:** Daily HIGH (not close) — DEC-2026-04-18-01
- **Verified:** April 15, 2026 High = 7,026.24

### MMTH (% Stocks Above 200-Day MA)
- **Primary source:** EODData — `INDEX/MMTH` via `EODDATA_API_KEY` env var — DEC-2026-04-22-02
- **Secondary source:** Barchart `$MMTH` (current value / recent range; full history requires login)
- **Verified:** Apr 15 = 54.99, Apr 16 = 55.45, Apr 17 = 58.54

---

## Macro Indicators (32 series via src/macro/)

### FRED API
- **Endpoint:** `https://api.fredblog.org/fred/series/observations`
- **Auth:** `FRED_KEY` env var (currently hardcoded in update_dashboard.py — security debt)
- **Key series:** DGS2, DGS10, T5YIE, T2YIE, SOFR, IORB, WALCL, WDTGAL, WLRRAL, WRESBAL, BOPGSTB, CPIAUCSL, CPILFESL, PCEPI, PCEPILFE, DFFR, A191RL1Q225SBEA (real GDP compounded annual rate)
- **Note:** WebFetch returns 403 for FRED; use Python `requests` directly or the `mcp__fred__*` MCP tools

### Atlanta Fed GDPNow
- **Source:** Official Atlanta Fed Excel endpoint (not FRED — separate institution)
- **Script:** `scripts/fetch_gdpnow.py`
- **Output:** `prototypes/gdpnow.json` — subcomponent contributions (PCE, BFI, Inventories, Net Exports, Govt)
- **GDP series rule:** Use `A191RL1Q225SBEA` for real GDP compounded annual rate — do NOT compute YoY/QoQ from nominal series

### yfinance (macro tickers)
- Futures: `GC=F` (Gold), `CL=F` (Crude WTI), `HG=F` (Copper), `NG=F` (Natural Gas), `ZC=F` (Corn)
- FX: `EURUSD=X`, `GBPUSD=X`, `JPY=X`, `AUDUSD=X`, `CNH=X`, `CHF=X`, `DX-Y.NYB` (DXY)
- Bonds: `^TNX` (10Y), `^FVX` (5Y), `^IRX` (3M)
- BTC: `BTC-USD` (weekly W-FRI, monthly ME resampling)

---

## Liquidity (src/liquidity/)

### FRED Liquidity Series
- WALCL — Fed Total Assets
- WDTGAL — Treasury General Account
- WLRRAL — Reverse Repo
- WRESBAL — Reserve Balances
- BOPGSTB — Trade Balance
- **Net Liquidity formula:** `WALCL - WDTGAL - WLRRAL`

### Bitcoin
- **Source:** yfinance `BTC-USD`
- **Frequency:** Weekly (W-FRI) and Monthly (ME) resampled

---

## STIR / Yields Tab

### CME Fed Funds Futures (ZQ)
- **Source:** yfinance — `ZQM25`, `ZQN25`, `ZQU25`, `ZQZ25`, etc.
- **Script:** `scripts/stir_pipeline.py`
- **Output:** `prototypes/stir.json`

### SOFR Futures (SR3)
- **Source:** yfinance — `SR3H25`, `SR3M25`, etc.

### EFFR / SOFR
- **Source:** FRED API — `DFF` (Effective Fed Funds Rate), `SOFR`

---

## COT Positioning

### CFTC Legacy Futures
- **Source:** CFTC Socrata API via `sodapy`
- **Script:** `scripts/cot_report_pull.py` → `data/cftc_cot.db`
- **Export:** `scripts/export_cot_json.py` → `prototypes/cot_data.json`
- **Contracts (14):** Crude Oil, Natural Gas, Gold, Silver, Copper, Wheat, Corn, Soybeans, Coffee, Cocoa, Cotton, S&P 500 E-mini, Nasdaq E-mini, Euro FX
- **Price data:** `scripts/export_price_json.py` → `prototypes/price_data.json` (3yr daily OHLC via yfinance)

---

## Sector Rotation

- **Source:** yfinance (sector ETFs and indices)
- **Script:** `scripts/sector_data_collector.py` → `data/sector_rotation.db` (SQLite)
- **Export:** `scripts/export_sector_json.py` → `prototypes/sector_rotation.json`
- **Countries:** United States, China, Korea

---

## Screener (US Movers + IPOs)

### US Movers
- **Source:** TradingView screener via Playwright (headless browser)
- **Script:** `scripts/screener_fetch.py`
- **Output:** `prototypes/screener_movers.json`
- **Enrichment:** Claude patches catalyst/source/catalyst_type/group_id directly into JSON

### China/HK Movers
- **Source:** TradingView screener (China filter) via Playwright
- **Script:** `scripts/screener_fetch_cn.py`
- **Output:** `prototypes/screener_movers_cn.json`

### IPOs (US + HK)
- **Source:** TradingView IPO screener + yfinance for ipo_close prices
- **Script:** `scripts/screener_fetch.py`
- **Output:** `prototypes/screener_ipos.json` — keys: `us` (US IPOs), `hk` (HK IPOs)
- **HK ticker format:** `NNNN.HK` (4-digit zero-padded) for yfinance
- **HK currency:** Storage in USD; display multiplies by HKD=7.78

---

## MCP Tools (claude.ai / Claude Code)

- `mcp__fred__fetch_fred_series` — fetch any FRED series by ID
- `mcp__fred__fetch_gdpnow` — fetch GDPNow latest estimate
- `mcp__fred__fetch_monthly_indicators` — fetch batch monthly macro series
- `mcp__fred__fetch_series_latest` — fetch latest value for a FRED series
- **Server:** `scripts/fred_mcp_server.py` (FastMCP wrapper around src/macro/fetch/)
