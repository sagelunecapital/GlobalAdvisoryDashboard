# Data Audit Report

**Generated:** 2026-05-12 (initial baseline — committed from manual agent research)
**Script:** `scripts/validate_data_sources.py`
**Scope:** All external series referenced by `update_dashboard.py` and `src/macro/fetch/`

> This file is regenerated on every run of the validator. The version committed here
> is the initial baseline established during Discovery. Re-run the script to refresh.

---

## Summary

| Risk | Count |
|------|-------|
| HIGH | 7 |
| MEDIUM | 8 |
| LOW | 4 |

---

## HIGH Risk

### [HIGH] NAPM — Dead FRED series: ISM Manufacturing PMI

**Category:** dead_series
**File refs:** `src/macro/fetch/monthly_indicators.py:42`

FRED series `NAPM` returns HTTP 400 (series does not exist). ISM Manufacturing PMI data is
proprietary and not available on public FRED. Any call to `fetch_direct_monthly("ISM_MFG_PMI", "NAPM")`
raises `RuntimeError` in production — this indicator is silently dropped from the macro table.

**Fix:** Replace with `MANEMP` (Manufacturing Employment, a proxy) or `INDPRO` (Industrial Production
Index). Alternatively, source ISM data from a licensed provider and add a `known_dead` bypass.
Remove or stub out the `NAPM` fetch call to prevent uncaught exceptions.

---

### [HIGH] NMFCI — Dead FRED series: ISM Services PMI

**Category:** dead_series
**File refs:** `src/macro/fetch/monthly_indicators.py:53`

FRED series `NMFCI` returns HTTP 400 (series does not exist). ISM Services (Non-Manufacturing)
PMI data is proprietary. `fetch_ism_services()` raises `RuntimeError` in production.

**Fix:** Replace with `PAYEMS` (Total Nonfarm Payrolls) or `SRVPRD` (Service-Providing Employment)
as a proxy for services sector activity, or source from a licensed provider.

---

### [HIGH] T2YIE — Dead FRED series: 2-Year Breakeven Inflation

**Category:** dead_series
**File refs:** `src/macro/fetch/monthly_indicators.py:37`

FRED series `T2YIE` returns HTTP 400 (series does not exist). No TIPS-derived 2-year breakeven
inflation rate exists on public FRED — the shortest TIPS maturity tracked is 5 years (`T5YIE`).
`BREAKEVEN_SERIES = [("BREAKEVEN_5Y", "T5YIE"), ("BREAKEVEN_2Y", "T2YIE")]` — the 2Y entry
always fails.

**Fix:** Replace `T2YIE` with `EXPINF2YR` (University of Michigan 2-Year Ahead Expected Inflation,
monthly) or drop the 2Y breakeven from the display and use only `T5YIE`.

---

### [HIGH] ^GSPC — SPX EMA source conflict: High vs Close

**Category:** transformation_logic
**File refs:** `update_dashboard.py:252`, `scripts/fetch_regime.py:52`

`update_dashboard.py` computes the 200-day EMA from `raw["High"]` (line 252). `fetch_regime.py`
computes the same EMA from `hist["Close"]` (line 52). These diverge by approximately 18 points
for EMA12 — enough to flip the EMA crossover signal direction during sideways markets. The regime
classification depends on which EMA is above the other, so this discrepancy produces contradictory
signals in the two modules.

**Fix:** Standardize on `Close` (industry convention for moving averages). Update
`update_dashboard.py:252` to use `raw["Close"]` instead of `raw["High"]`.

---

### [HIGH] T5YIE — WoW unit mismatch in macroRegime object

**Category:** transformation_logic
**File refs:** `update_dashboard.py:432`, `update_dashboard.py:418`, `update_dashboard.py:422`

`t5yie_wow` is computed as `(diff) * 100` (line 432), making it basis points (bps). `us2y_wow`
and `us10y_wow` are raw percentage-point differences without ×100 (lines 418, 422). All three
fields are serialized into the same `macroRegime` JSON object and displayed in the same table
column, implying they share units. A 10bp move appears as "0.10" for yields but "10.00" for
breakeven — the same JS cell renderer applies to both.

**Fix:** Align all three to the same unit. The simplest fix is to remove the `* 100` from
`t5yie_wow` (line 432) to keep everything in percentage-points. Update any display formatting
that relies on bps scale.

---

### [HIGH] stir.json — Stale STIR data (>3 days)

**Category:** staleness
**File refs:** `prototypes/stir.json` (updated field)

`prototypes/stir.json` is a static snapshot of SOFR/Fed Funds futures cut/hike probabilities
with no `fetch_stir.py` script in `scripts/`. The file is updated manually and has no automated
refresh pipeline. A snapshot older than 3 days contains materially incorrect market-implied
rate paths, especially around FOMC meeting windows.

**Fix:** Write `scripts/fetch_stir.py` that pulls from CME FedWatch API or FRED `SOFR` daily
series and writes `prototypes/stir.json` with an `"updated"` ISO timestamp. Add to the nightly
`dashboard-update.yml` workflow.

---

### [HIGH] $MMTH — Barchart scraper with no fallback

**Category:** source_reliability
**File refs:** `scripts/fetch_regime.py:62`

`fetch_regime.py` scrapes Barchart for `$MMTH` (NYSE stocks above 200-day MA) with no fallback
source. Barchart frequently blocks bot traffic and has changed its HTML structure multiple times.
A scraper failure silently drops the breadth signal from the regime calculation.

**Fix:** Add a fallback to the StockCharts or TradingView data endpoint, or store the last-known
value with a `stale_flag` that triggers a MEDIUM warning in the dashboard rather than silently
using `NaN`. At minimum, add error handling that raises a named exception on fetch failure rather
than returning `None`.

---

## MEDIUM Risk

### [MEDIUM] gdp_yoy — Misleading variable name

**Category:** transformation_logic
**File refs:** `update_dashboard.py:409`

Variable `gdp_yoy_data` at line 409 actually holds the FRED series `A191RL1Q225SBEA`, which is
the compounded annual rate of change (not YoY%). The name implies a year-over-year transformation
was applied, which could lead future maintainers to double-apply a YoY transform or compare it
incorrectly against other YoY series.

**Fix:** Rename to `gdp_annualized_data` or `gdp_car_data` to reflect the actual FRED series
semantics.

---

### [MEDIUM] ^FVX — Yahoo Finance ticker with no fallback

**Category:** source_reliability
**File refs:** `update_dashboard.py` (5Y Treasury yield via yfinance)

`^FVX` (5-Year Treasury yield) is fetched via yfinance with no FRED fallback. Yahoo Finance
tickers have higher outage rates than FRED. `DGS5` on FRED is the canonical daily 5Y yield
and is updated with a 1-business-day lag (acceptable for dashboard use).

**Fix:** Add `DGS5` from FRED as a fallback when `^FVX` returns empty or NaN.

---

### [MEDIUM] YoY abs() — Absolute value collapses contraction signal

**Category:** transformation_logic
**File refs:** `update_dashboard.py` (YoY% computation)

The YoY% formula wraps the denominator in `abs()`, preventing negative-to-positive sign flips
from producing the correct directional signal. This matters when an indicator crosses zero
(e.g., trade balance moving from deficit to surplus).

**Fix:** Remove `abs()` from the denominator. Accept that the sign can flip when crossing zero
and handle the display formatting separately if needed.

---

### [MEDIUM] $MMTH — Dual-source inconsistency

**Category:** source_reliability
**File refs:** `update_dashboard.py`, `scripts/fetch_regime.py:62`

`$MMTH` is sourced from two different places (Barchart scraper in `fetch_regime.py` and a
separate path in `update_dashboard.py`). If the two sources diverge — which is possible given
different scrape timing and data normalization — the breadth signal will be inconsistent between
the regime module and the main dashboard.

**Fix:** Centralize `$MMTH` fetch into one function and import it in both callers.

---

### [MEDIUM] investing.com — 7-day vs FRED 5-day week mismatch

**Category:** transformation_logic
**File refs:** `update_dashboard.py` (investing.com scraper section)

investing.com data uses 7-day calendar weeks in its week-over-week calculation; FRED uses
5-day business weeks. Mixing these in the same table produces week-labeling misalignment around
3-day weekends and holidays — the "WoW" column appears one period off for affected indicators.

**Fix:** Normalize all WoW calculations to use a common calendar convention. The safest approach
is to use FRED's weekly series directly (which already handle business-day alignment) rather than
computing WoW from calendar-week scraped data.

---

### [MEDIUM] T5YIE — Calendar-day staleness window

**Category:** staleness
**File refs:** `update_dashboard.py:432` (T5YIE fetch)

`T5YIE` staleness is checked against a calendar-day threshold rather than a business-day
threshold. On Mondays, the "last observation" is Friday's data — 3 calendar days old — which
may trip a 2-day staleness check incorrectly.

**Fix:** Use a business-day aware staleness check (e.g., `numpy.busday_count`) so weekends and
federal holidays don't falsely flag freshly-updated series as stale.

---

### [MEDIUM] WLRRAL — "Reverse Repo" label may include non-RRP items

**Category:** transformation_logic
**File refs:** `update_dashboard.py` (WLRRAL fetch)

`WLRRAL` (Liabilities and Capital: Liabilities: Reverse Repurchase Agreements) is labeled as
"Overnight RRP" in the dashboard, but the FRED series includes all maturities, not just
overnight. During periods of term RRP activity, this overstates the overnight RRP balance by
an unknown amount.

**Fix:** Use `RRPONTSYD` (Overnight Reverse Repurchase Agreements: Treasury Securities Sold by
the Federal Reserve) for overnight-only RRP, or update the dashboard label to "Total Reverse
Repo (all maturities)".

---

### [MEDIUM] GDPNow — Column name hardcoded to specific vintage

**Category:** transformation_logic
**File refs:** `update_dashboard.py` (GDPNow section)

The GDPNow CSV column name used to extract the nowcast is hardcoded to a specific vintage
string. The Atlanta Fed periodically renames the column header when updating methodology.
A silent KeyError would produce `NaN` for the GDP row without raising an exception.

**Fix:** Use a prefix match (`.filter(like='GDPNow')` or `str.startswith`) rather than an
exact column name, and add an explicit check that exactly one matching column is found.

---

## LOW Risk

### [LOW] WRESBAL — Inline comment says billions, units are millions

**Category:** documentation
**File refs:** `update_dashboard.py:379`

FRED confirms `WRESBAL` units are "Millions of U.S. Dollars". The inline comment at line 379
says "billions USD". The code's `/1000` scaling is correct (converts millions → billions for
display). Only the comment is wrong.

**Fix:** Change the comment from "billions USD" to "divide millions by 1000 → billions for display".

---

### [LOW] T5YIE — Pre-computed vs redundant components both fetched

**Category:** documentation
**File refs:** `update_dashboard.py` (T5YIE, DGS5, DFII5 fetches)

`T5YIE` is the FRED pre-computed breakeven (exactly `DGS5 - DFII5`). The codebase fetches all
three: `T5YIE`, `DGS5`, and `DFII5`. This is redundant but not wrong — `T5YIE` and the computed
difference from components will always agree.

**Fix:** Remove the redundant computation of `DGS5 - DFII5` if `T5YIE` is already fetched
directly, or vice versa.

---

### [LOW] WLRRAL — Term RRP undercount noted

**Category:** documentation
**File refs:** `update_dashboard.py` (WLRRAL section)

Duplicate of the MEDIUM finding above — the LOW-severity portion is the lack of a dashboard
footnote explaining that the figure includes all maturities.

**Fix:** Add a display footnote: "Includes all maturities (overnight + term)."

---

### [LOW] stir.json — No automated refresh pipeline

**Category:** staleness
**File refs:** `prototypes/stir.json`

Duplicate of HIGH finding above — the LOW-severity portion is that `data/gaai-deliver.log`
mentions no automated refresh for `stir.json` in the nightly workflow.

**Fix:** See HIGH finding — add `scripts/fetch_stir.py` and wire into `dashboard-update.yml`.

---

*End of audit report. Re-run `python scripts/validate_data_sources.py` to refresh.*
