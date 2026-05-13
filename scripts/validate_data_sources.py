#!/usr/bin/env python3
"""
validate_data_sources.py — parallel data-source validator for macro dashboards.

Validates every external series referenced by update_dashboard.py and
src/macro/fetch/ against FRED metadata, value-range plausibility, and
hardcoded transformation consistency checks.

Exit codes:
    0  no HIGH-risk findings
    1  one or more HIGH-risk findings  (CI merge gate)

Environment:
    FRED_API_KEY  required for FRED API calls

Output:
    data_audit.md  (repo root, overwritten each run)
"""

import os
import sys
import json
import textwrap
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import requests

FRED_BASE = "https://api.stlouisfed.org/fred"
REPO_ROOT = Path(__file__).resolve().parent.parent
REPORT_PATH = REPO_ROOT / "data_audit.md"
STIR_PATH = REPO_ROOT / "prototypes" / "stir.json"
COT_PATH = REPO_ROOT / "prototypes" / "cot_data.json"
RISK_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2, "OK": 3}
STIR_MAX_STALENESS_DAYS = 3
COT_MAX_STALENESS_DAYS = 10


# ---------------------------------------------------------------------------
# Finding
# ---------------------------------------------------------------------------

@dataclass
class Finding:
    risk: str           # HIGH | MEDIUM | LOW | OK
    series_id: str
    category: str
    title: str
    detail: str
    file_refs: list = field(default_factory=list)
    fix: str = ""

    def sort_key(self):
        return (RISK_ORDER.get(self.risk, 9), self.category, self.series_id)


# ---------------------------------------------------------------------------
# FRED series manifest
# Each dict: id, units_substr, freq, sadj (None = skip check),
#            value_range (lo, hi), known_dead, file_refs, fix_suggestion
# ---------------------------------------------------------------------------

FRED_MANIFEST = [
    # --- Inflation ---
    dict(id="CPIAUCSL",  units_substr="Index",    freq="Monthly",   sadj="Seasonally Adjusted",
         value_range=(200, 420), file_refs=["update_dashboard.py:362", "src/macro/fetch/monthly_indicators.py:27"]),
    dict(id="CPILFESL",  units_substr="Index",    freq="Monthly",   sadj="Seasonally Adjusted",
         value_range=(200, 420), file_refs=["update_dashboard.py:363", "src/macro/fetch/monthly_indicators.py:28"]),
    dict(id="PCEPI",     units_substr="Index",    freq="Monthly",   sadj="Seasonally Adjusted",
         value_range=(70, 180),  file_refs=["update_dashboard.py:364", "src/macro/fetch/monthly_indicators.py:29"]),
    dict(id="PCEPILFE",  units_substr="Index",    freq="Monthly",   sadj="Seasonally Adjusted",
         value_range=(70, 180),  file_refs=["update_dashboard.py:365", "src/macro/fetch/monthly_indicators.py:30"]),
    dict(id="PPIACO",    units_substr="Index",    freq="Monthly",   sadj="Not Seasonally Adjusted",
         value_range=(100, 450), file_refs=["update_dashboard.py:366", "src/macro/fetch/monthly_indicators.py:31"]),
    dict(id="PPICOR",    units_substr="Index",    freq="Monthly",   sadj="Not Seasonally Adjusted",
         value_range=(80, 250),  file_refs=["update_dashboard.py:367"]),
    # --- ISM (expected dead) ---
    dict(id="NAPM",   units_substr="Index", freq="Monthly", sadj=None, value_range=(30, 70),
         known_dead=True,
         file_refs=["src/macro/fetch/monthly_indicators.py:42"],
         fix_suggestion="ISM Manufacturing PMI is no longer on public FRED. Use Nasdaq Data Link ISM dataset or S&P Global Markit US Manufacturing PMI (paid). Alternatively remove from fetch list and substitute a regional Fed index (e.g., Chicago PMI CPMI)."),
    dict(id="NMFCI",  units_substr="Index", freq="Monthly", sadj=None, value_range=(30, 70),
         known_dead=True,
         file_refs=["src/macro/fetch/monthly_indicators.py:53-54"],
         fix_suggestion="ISM Services PMI is not available on public FRED under any active series ID. NMFCI does not exist. Use Nasdaq Data Link ISM data or S&P Global Markit US Services PMI. The existing fetch_ism_services() error guard is correct in structure but needs a valid series ID."),
    # --- Breakeven (T2YIE expected dead) ---
    dict(id="T5YIE",  units_substr="Percent", freq="Daily", sadj="Not Seasonally Adjusted",
         value_range=(0, 6), file_refs=["update_dashboard.py:426", "src/macro/fetch/monthly_indicators.py:35"]),
    dict(id="T2YIE",  units_substr="Percent", freq="Daily", sadj="Not Seasonally Adjusted",
         value_range=(0, 6), known_dead=True,
         file_refs=["src/macro/fetch/monthly_indicators.py:37"],
         fix_suggestion="No TIPS-derived 2Y breakeven exists on FRED (shortest TIPS maturity tracked is 5Y). Replace T2YIE with T5YIE (already fetched) or EXPINF2YR (2Y survey-based, Monthly). If 2Y breakeven is not essential, remove the series."),
    # --- Labor ---
    dict(id="PAYEMS", units_substr="Thousands", freq="Monthly", sadj="Seasonally Adjusted",
         value_range=(100000, 175000), file_refs=["src/macro/fetch/monthly_indicators.py:43"]),
    dict(id="UNRATE", units_substr="Percent",  freq="Monthly", sadj="Seasonally Adjusted",
         value_range=(1, 20), file_refs=["src/macro/fetch/monthly_indicators.py:44"]),
    dict(id="RSAFS",  units_substr="Millions", freq="Monthly", sadj="Seasonally Adjusted",
         value_range=(300000, 1100000), file_refs=["src/macro/fetch/monthly_indicators.py:49"]),
    # --- Yields ---
    dict(id="DGS1",   units_substr="Percent", freq="Daily", sadj="Not Seasonally Adjusted",
         value_range=(0, 12), file_refs=["update_dashboard.py:369"]),
    dict(id="DGS2",   units_substr="Percent", freq="Daily", sadj="Not Seasonally Adjusted",
         value_range=(0, 12), file_refs=["update_dashboard.py:370", "src/macro/fetch/yfinance_macro.py:186"]),
    dict(id="DGS5",   units_substr="Percent", freq="Daily", sadj="Not Seasonally Adjusted",
         value_range=(0, 12), file_refs=["update_dashboard.py:371"]),
    dict(id="DFII5",  units_substr="Percent", freq="Daily", sadj="Not Seasonally Adjusted",
         value_range=(-3, 5),  file_refs=["update_dashboard.py:374"]),
    dict(id="DFII10", units_substr="Percent", freq="Daily", sadj="Not Seasonally Adjusted",
         value_range=(-3, 5),  file_refs=["update_dashboard.py:375"]),
    dict(id="DFII30", units_substr="Percent", freq="Daily", sadj="Not Seasonally Adjusted",
         value_range=(-3, 5),  file_refs=["update_dashboard.py:376"]),
    dict(id="DGS3MO", units_substr="Percent", freq="Daily", sadj="Not Seasonally Adjusted",
         value_range=(0, 12),  file_refs=["src/macro/fetch/yfinance_macro.py:143"]),
    # --- Policy rates ---
    dict(id="SOFR",   units_substr="Percent", freq="Daily", sadj="Not Seasonally Adjusted",
         value_range=(0, 12), file_refs=["update_dashboard.py:403"]),
    dict(id="IORB",   units_substr="Percent", freq="Daily", sadj="Not Seasonally Adjusted",
         value_range=(0, 12), file_refs=["update_dashboard.py:404"]),
    # --- Liquidity (H.4.1 — all in Millions of U.S. Dollars) ---
    dict(id="WRESBAL", units_substr="Millions", freq="Weekly", sadj="Not Seasonally Adjusted",
         value_range=(500_000, 6_000_000), file_refs=["update_dashboard.py:379,538"]),
    dict(id="WALCL",   units_substr="Millions", freq="Weekly", sadj="Not Seasonally Adjusted",
         value_range=(3_000_000, 12_000_000), file_refs=["update_dashboard.py:380,542"]),
    dict(id="WDTGAL",  units_substr="Millions", freq="Weekly", sadj="Not Seasonally Adjusted",
         value_range=(50_000, 3_000_000), file_refs=["update_dashboard.py:381,542"]),
    dict(id="WLRRAL",  units_substr="Millions", freq="Weekly", sadj="Not Seasonally Adjusted",
         value_range=(0, 3_000_000), file_refs=["update_dashboard.py:382,542"]),
    dict(id="BOPGSTB", units_substr="Millions", freq="Monthly", sadj="Seasonally Adjusted",
         value_range=(-150_000, 0), file_refs=["update_dashboard.py:383,547"]),
    # --- GDP ---
    dict(id="A191RL1Q225SBEA", units_substr="Percent", freq="Quarterly", sadj="Seasonally Adjusted",
         value_range=(-15, 15), file_refs=["update_dashboard.py:409"]),
]


# ---------------------------------------------------------------------------
# Hardcoded static findings (code-analysis, no API call required)
# ---------------------------------------------------------------------------

def _static_findings() -> list[Finding]:
    findings = []

    # HIGH: SPX High vs Close EMA discrepancy
    findings.append(Finding(
        risk="HIGH",
        series_id="^GSPC",
        category="Transformation",
        title="^GSPC: EMA computed from High price in update_dashboard.py vs Close price in fetch_regime.py",
        detail=(
            "update_dashboard.py:252 fetches raw['High'] for EMA12/EMA25 computation. "
            "scripts/fetch_regime.py:52 uses hist['Close'] for the same EMAs. "
            "EMA-of-Highs is structurally ~18 pts above EMA-of-Closes (quantified 2026-05-11). "
            "At EMA crossover points the two scripts can produce different GREEN/YELLOW/RED "
            "classifications for the same market state. Both scripts write regime data that "
            "the dashboard reads — whichever runs last wins, with no warning of the conflict."
        ),
        file_refs=["update_dashboard.py:248-256", "scripts/fetch_regime.py:46-56"],
        fix=(
            "Standardize both scripts to the same price type. "
            "Per project spec comment ('daily HIGH per project spec'), "
            "update fetch_regime.py:52 to use hist['High'] and extend period from '90d' to '2y' "
            "for consistent EMA warm-up."
        ),
    ))

    # HIGH: t5yie_wow in basis points, us2y/10y_wow in percentage points
    findings.append(Finding(
        risk="HIGH",
        series_id="T5YIE/DGS2/^TNX",
        category="Transformation",
        title="macroRegime WoW unit mismatch: t5yie_wow is basis points; us2y_wow/us10y_wow are percentage points",
        detail=(
            "update_dashboard.py:432: t5yie_wow = (t5yie_now - t5yie_prev) * 100 "
            "(T5YIE in %, diff * 100 = basis points). "
            "update_dashboard.py:437-455: us2y_wow and us10y_wow are raw yield differences "
            "from investing.com or FRED (both in %, no * 100 applied) = percentage points. "
            "All three land in macroRegime JS object at the same level. "
            "A 5 bp T5YIE move shows as 5; the same 5 bp US 2Y move shows as 0.05."
        ),
        file_refs=["update_dashboard.py:432", "update_dashboard.py:437-455", "update_dashboard.py:335-354"],
        fix=(
            "Apply consistent units. Either: (a) remove the * 100 on line 432 so all three "
            "are in percentage points, OR (b) multiply us2y_wow and us10y_wow by 100 so all "
            "three are in basis points. Update the JS display code and axis labels to match."
        ),
    ))

    # MEDIUM: gdp_yoy naming confusion
    findings.append(Finding(
        risk="MEDIUM",
        series_id="A191RL1Q225SBEA",
        category="Transformation",
        title="gdp_yoy_data variable name is misleading — series is QoQ CAAR, not YoY",
        detail=(
            "update_dashboard.py:409 assigns A191RL1Q225SBEA (real GDP QoQ compounded annual rate) "
            "to the variable gdp_yoy_data. Line 341 outputs it as macroRegime.gdp_yoy in JS. "
            "Dashboard consumers reading macroRegime.gdp_yoy will likely misinterpret the "
            "value as year-over-year growth. The print() at line 411 correctly says 'GDP QoQ' "
            "but the variable and JS key perpetuate the YoY label."
        ),
        file_refs=["update_dashboard.py:409", "update_dashboard.py:341"],
        fix="Rename gdp_yoy_data -> gdp_qoq_data and macroRegime.gdp_yoy -> macroRegime.gdp_qoq throughout.",
    ))

    # MEDIUM: ^FVX in yfinance_macro.py without DGS5 fallback
    findings.append(Finding(
        risk="MEDIUM",
        series_id="^FVX",
        category="yfinance",
        title="^FVX fetched in yfinance_macro.py with no DGS5 fallback (known unreliable ticker)",
        detail=(
            "src/macro/fetch/yfinance_macro.py:120 includes '^FVX' in yield_tickers with no fallback. "
            "update_dashboard.py:371 documents the same ticker as unreliable and substitutes FRED DGS5. "
            "When ^FVX returns sparse data (historically documented), yfinance_macro.py silently "
            "produces a degraded US_5Y_YIELD series with no warning."
        ),
        file_refs=["src/macro/fetch/yfinance_macro.py:120", "update_dashboard.py:371"],
        fix=(
            "In yfinance_macro.py, add a DGS5 fallback for ^FVX matching the pattern used in "
            "update_dashboard.py: if len(raw_series.get('^FVX', [])) < 52, fetch FRED DGS5 and "
            "use it as US_5Y_YIELD."
        ),
    ))

    # MEDIUM: YoY formula abs() inconsistency
    findings.append(Finding(
        risk="MEDIUM",
        series_id="*",
        category="Transformation",
        title="YoY% formula uses abs() denominator in update_dashboard.py but ratio in monthly_indicators.py",
        detail=(
            "update_dashboard.py:179: ((arr[i] - arr[i-lag]) / abs(arr[i-lag])) * 100. "
            "monthly_indicators.py:89: ((raw / raw.shift(12)) - 1) * 100. "
            "For positive price indices (CPI, PCE, PPI) the outputs are identical. "
            "If any series with a negative base value is added (e.g., trade balance spread), "
            "abs() suppresses sign inversion and the two implementations diverge silently. "
            "Two separate implementations of the same metric with no shared function is a "
            "maintenance liability."
        ),
        file_refs=["update_dashboard.py:179", "src/macro/fetch/monthly_indicators.py:89"],
        fix=(
            "Extract a shared yoy_pct() utility into src/macro/utils.py and import it in both files. "
            "Use the ratio formula without abs(): ((base_now / base_prev) - 1) * 100."
        ),
    ))

    # MEDIUM: MMTH dual-source divergence
    findings.append(Finding(
        risk="MEDIUM",
        series_id="$MMTH",
        category="Scraper",
        title="MMTH sourced from Barchart in fetch_regime.py but EODData in update_dashboard.py — dual-source divergence",
        detail=(
            "scripts/fetch_regime.py:59-67 scrapes Barchart for $MMTH with no fallback. "
            "update_dashboard.py:259-281 uses EODData API (EODDATA_API_KEY env var, falls back to None). "
            "Both write MMTH to different outputs (regime.json vs index.html data block). "
            "MMTH drives the GREEN/YELLOW/RED boundary (threshold=60%). If the two sources "
            "report different values on the same day, the regime tab and the main dashboard "
            "data block will show different regime colors."
        ),
        file_refs=["scripts/fetch_regime.py:59-67", "update_dashboard.py:259-281"],
        fix=(
            "Centralize MMTH fetch in one place (e.g., scripts/fetch_mmth.py) and have both "
            "scripts read from mmth.json. Use EODData as primary (more stable API) with "
            "Barchart as fallback rather than the current arrangement."
        ),
    ))

    # MEDIUM: investing.com vs FRED fallback WoW cutoff inconsistency
    findings.append(Finding(
        risk="MEDIUM",
        series_id="DGS2/^TNX",
        category="Transformation",
        title="WoW yield change: 7-calendar-day cutoff on investing.com path vs 5-calendar-day on FRED fallback",
        detail=(
            "update_dashboard.py:74: cutoff = latest_d - timedelta(days=7) (investing.com path). "
            "update_dashboard.py:444: timedelta(days=5) (FRED fallback path). "
            "Same display field (us2y_wow, us10y_wow) uses different lookback lengths depending "
            "on which data source succeeded. A 7-day change and a 5-day change are "
            "numerically different figures labelled identically as 'WoW'."
        ),
        file_refs=["update_dashboard.py:74", "update_dashboard.py:444", "update_dashboard.py:452"],
        fix="Align both paths to the same lookback: use timedelta(days=7) in the FRED fallback too (lines 444, 452).",
    ))

    # LOW: WRESBAL comment wrong (code is correct — FRED confirmed Millions)
    findings.append(Finding(
        risk="LOW",
        series_id="WRESBAL",
        category="FRED series",
        title="WRESBAL: inline comment says 'billions USD' but FRED units are 'Millions of U.S. Dollars'",
        detail=(
            "update_dashboard.py:379: comment says '# Reserve Balances (weekly, billions USD)'. "
            "FRED confirms WRESBAL units = 'Millions of U.S. Dollars'. "
            "The /1000 scaling at line 538 is therefore CORRECT (millions -> billions). "
            "The comment is misleading and contradicts the scaling operation below it, "
            "which could cause a future developer to remove the /1000 as apparently redundant."
        ),
        file_refs=["update_dashboard.py:379", "update_dashboard.py:538"],
        fix="Update comment on line 379 to: '# Reserve Balances (weekly, millions USD → divide by 1000 for billions)'.",
    ))

    # LOW: T5YIE WoW calendar vs trading day
    findings.append(Finding(
        risk="LOW",
        series_id="T5YIE",
        category="Transformation",
        title="T5YIE WoW lookback uses calendar days — on Thursday/Friday the gap spans 6-7 calendar days",
        detail=(
            "update_dashboard.py:429-431: cutoff = latest_date - timedelta(days=5). "
            "T5YIE has no weekend observations. On a Thursday, subtracting 5 calendar days "
            "produces a Saturday cutoff; the prior observation used is the Friday before "
            "(6 calendar days prior). Direction signal unaffected; magnitude slightly compressed."
        ),
        file_refs=["update_dashboard.py:429-431"],
        fix="Use the 5th-prior observation by index rather than timedelta: t5yie_prev = t5yie_data[t5yie_dates[-6]] if len(t5yie_dates) >= 6 else t5yie_now.",
    ))

    # LOW: WLRRAL includes term RRP
    findings.append(Finding(
        risk="LOW",
        series_id="WLRRAL",
        category="FRED series",
        title="WLRRAL captures all reverse repos (ON RRP + term RRP), not ON RRP only",
        detail=(
            "The standard Fed Net Liquidity formula (WALCL - WDTGAL - WLRRAL) uses WLRRAL "
            "which includes all reverse repurchase agreements. RRPONTSYD isolates overnight "
            "ON RRP only. Currently term RRP is near zero, so the two are nearly identical. "
            "If the Fed reactivates term RRP in a stress episode, WLRRAL will overstate the "
            "liquidity drain vs the ON RRP-only definition used by most macro practitioners."
        ),
        file_refs=["update_dashboard.py:382", "update_dashboard.py:542"],
        fix="Note in code comment that WLRRAL is used intentionally (H.4.1 convention); add RRPONTSYD as a cross-check if precision is needed.",
    ))

    # LOW: GDPNow hardcoded column positions
    findings.append(Finding(
        risk="LOW",
        series_id="GDPNow",
        category="Scraper",
        title="GDPNow Excel parser uses hardcoded column position (GDP_COL=9) — fragile to Atlanta Fed format changes",
        detail=(
            "scripts/fetch_gdpnow.py: GDP_COL = 9 and COMPONENT_MAP use hardcoded column indices. "
            "If the Atlanta Fed adds or removes a column from the GDPNow model output XLSX, "
            "the parser silently returns wrong values or raises ValueError. "
            "update_dashboard.py:421 falls back to gdpnow_latest=0.0 on parse failure, "
            "which would display 0.0% GDPNow without signaling an error to the user."
        ),
        file_refs=["scripts/fetch_gdpnow.py", "update_dashboard.py:413-423"],
        fix="Use column name detection instead of hardcoded indices. Also change the 0.0 fallback in update_dashboard.py:421 to emit a visible error marker (e.g., None -> 'N/A' display) rather than a plausible-looking 0.0.",
    ))

    return findings


# ---------------------------------------------------------------------------
# FRED validator (one series)
# ---------------------------------------------------------------------------

def _validate_fred_series(entry: dict, api_key: str) -> list[Finding]:
    sid = entry["id"]
    findings: list[Finding] = []
    file_refs = entry.get("file_refs", [])
    known_dead = entry.get("known_dead", False)

    # --- Metadata fetch ---
    try:
        r = requests.get(
            f"{FRED_BASE}/series",
            params={"series_id": sid, "api_key": api_key, "file_type": "json"},
            timeout=20,
        )
        if r.status_code == 400:
            findings.append(Finding(
                risk="HIGH",
                series_id=sid,
                category="FRED series",
                title=f"{sid}: Series does not exist on FRED (HTTP 400) — fetch will fail at runtime",
                detail=(
                    f"FRED returns HTTP 400 Bad Request for series_id={sid!r}. "
                    f"Any code path that fetches this series will raise RuntimeError "
                    f"and abort the containing fetch routine."
                    + (f" Series was expected to exist but has been discontinued." if not known_dead else "")
                ),
                file_refs=file_refs,
                fix=entry.get("fix_suggestion", f"Replace '{sid}' with a valid active FRED series ID."),
            ))
            return findings
        r.raise_for_status()
    except requests.RequestException as exc:
        findings.append(Finding(
            risk="LOW",
            series_id=sid,
            category="FRED series",
            title=f"{sid}: FRED metadata fetch failed — could not validate",
            detail=f"Network error: {exc}",
            fix="Retry validation; if persistent, check FRED API status.",
        ))
        return findings

    seriess = r.json().get("seriess", [])
    if not seriess:
        findings.append(Finding(
            risk="MEDIUM",
            series_id=sid,
            category="FRED series",
            title=f"{sid}: Unexpected empty response from FRED metadata endpoint",
            detail="FRED returned HTTP 200 but 'seriess' array is empty.",
            file_refs=file_refs,
        ))
        return findings

    meta = seriess[0]
    actual_units = meta.get("units", "")
    actual_freq  = meta.get("frequency", "")
    actual_sadj  = meta.get("seasonal_adjustment", "")
    obs_end_str  = meta.get("observation_end", "")

    # Units check
    expected_units_substr = entry.get("units_substr")
    if expected_units_substr and expected_units_substr.lower() not in actual_units.lower():
        findings.append(Finding(
            risk="HIGH",
            series_id=sid,
            category="FRED series",
            title=f"{sid}: Units mismatch — code assumes '{expected_units_substr}', FRED reports '{actual_units}'",
            detail=(
                f"Expected units containing '{expected_units_substr}'; "
                f"FRED title: '{meta.get('title', '')}', actual units: '{actual_units}'. "
                f"Any scaling or transformation based on wrong units will produce incorrect values."
            ),
            file_refs=file_refs,
            fix=f"Verify the correct units for {sid} and update all scaling code accordingly.",
        ))

    # Frequency check
    expected_freq = entry.get("freq")
    if expected_freq:
        if not (expected_freq.lower() in actual_freq.lower() or actual_freq.lower() in expected_freq.lower()):
            findings.append(Finding(
                risk="MEDIUM",
                series_id=sid,
                category="FRED series",
                title=f"{sid}: Frequency mismatch — expected '{expected_freq}', got '{actual_freq}'",
                detail=f"Code may mishandle date alignment if frequency assumption is wrong.",
                file_refs=file_refs,
            ))

    # Seasonal adjustment check
    expected_sadj = entry.get("sadj")
    if expected_sadj and expected_sadj.lower() not in actual_sadj.lower():
        findings.append(Finding(
            risk="LOW",
            series_id=sid,
            category="FRED series",
            title=f"{sid}: Seasonal adjustment differs — expected '{expected_sadj}', got '{actual_sadj}'",
            detail="Month-over-month changes may carry seasonal noise if NSA is used where SA was assumed.",
            file_refs=file_refs,
        ))

    # Freshness check
    if obs_end_str:
        try:
            obs_end_date = datetime.strptime(obs_end_str, "%Y-%m-%d").date()
            today = date.today()
            freq_lower = actual_freq.lower()
            if "daily" in freq_lower:
                max_lag = 14
            elif "week" in freq_lower:
                max_lag = 21
            elif "month" in freq_lower:
                max_lag = 90
            else:
                max_lag = 200  # quarterly
            lag = (today - obs_end_date).days
            if lag > max_lag * 2:
                findings.append(Finding(
                    risk="HIGH",
                    series_id=sid,
                    category="FRED series",
                    title=f"{sid}: Possible discontinuation — last observation {obs_end_str} is {lag} days ago",
                    detail=f"For {actual_freq} frequency, expected within {max_lag} days. Lag of {lag} days suggests the series may have ended.",
                    file_refs=file_refs,
                    fix=f"Check FRED for {sid} status and any series ID replacement.",
                ))
        except ValueError:
            pass

    # Value-range check (fetch recent observations)
    value_range = entry.get("value_range")
    if value_range:
        try:
            r2 = requests.get(
                f"{FRED_BASE}/series/observations",
                params={
                    "series_id": sid,
                    "api_key": api_key,
                    "file_type": "json",
                    "sort_order": "desc",
                    "limit": 104,
                    "observation_start": str(date.today() - timedelta(days=730)),
                },
                timeout=20,
            )
            r2.raise_for_status()
            raw_obs = [o["value"] for o in r2.json().get("observations", []) if o["value"] != "."]
            obs_vals = [float(v) for v in raw_obs]
            if obs_vals:
                lo, hi = value_range
                out_of_range = [v for v in obs_vals if v < lo or v > hi]
                if len(out_of_range) > max(1, len(obs_vals) * 0.05):
                    findings.append(Finding(
                        risk="MEDIUM",
                        series_id=sid,
                        category="FRED series",
                        title=f"{sid}: {len(out_of_range)}/{len(obs_vals)} recent values outside expected range [{lo:,.0f}, {hi:,.0f}]",
                        detail=(
                            f"Min={min(obs_vals):,.2f}, Max={max(obs_vals):,.2f}, "
                            f"Latest={obs_vals[0]:,.2f}. "
                            f"Check for unit changes or unexpected scaling."
                        ),
                        file_refs=file_refs,
                    ))
        except Exception:
            pass  # range check is best-effort

    return findings


# ---------------------------------------------------------------------------
# Staleness checks for JSON data files
# ---------------------------------------------------------------------------

def _check_stir_staleness() -> list[Finding]:
    findings: list[Finding] = []
    if not STIR_PATH.exists():
        findings.append(Finding(
            risk="HIGH",
            series_id="stir.json",
            category="Static data file",
            title="stir.json not found — STIR tab will have no data",
            detail=f"Expected at {STIR_PATH}",
            file_refs=["prototypes/stir.json"],
            fix="Run the STIR fetch script (if it exists) or restore the file.",
        ))
        return findings

    try:
        data = json.loads(STIR_PATH.read_text(encoding="utf-8"))
        updated_str = data.get("updated") or data.get("asof_date")
        if updated_str:
            try:
                updated_dt = datetime.fromisoformat(updated_str.replace("Z", "+00:00")).date()
                lag = (date.today() - updated_dt).days
                if lag > STIR_MAX_STALENESS_DAYS:
                    findings.append(Finding(
                        risk="HIGH",
                        series_id="stir.json",
                        category="Static data file",
                        title=f"stir.json is {lag} days stale (updated {updated_str}) — no automated fetch script found",
                        detail=(
                            f"SOFR and Fed Funds futures reprice intraday on Fed communication "
                            f"and macro data. A {lag}-day-old snapshot shows stale cut/hike "
                            f"probabilities in the STIR tab. "
                            f"No fetch_stir.py or equivalent was found in scripts/."
                        ),
                        file_refs=["prototypes/stir.json"],
                        fix=(
                            "Create scripts/fetch_stir.py to pull settlement prices from CME "
                            "or IBKR API daily, or wire the existing SOFR/FF futures data source "
                            "into a scheduled GitHub Action."
                        ),
                    ))
            except (ValueError, TypeError):
                pass
    except (json.JSONDecodeError, IOError):
        pass

    return findings


def _check_cot_staleness() -> list[Finding]:
    findings: list[Finding] = []
    if not COT_PATH.exists():
        return findings

    try:
        mtime = datetime.fromtimestamp(COT_PATH.stat().st_mtime).date()
        lag = (date.today() - mtime).days
        if lag > COT_MAX_STALENESS_DAYS:
            findings.append(Finding(
                risk="MEDIUM",
                series_id="cot_data.json",
                category="Static data file",
                title=f"cot_data.json last modified {lag} days ago — automated refresh mechanism unclear",
                detail=(
                    f"CFTC COT data is released every Friday for prior Tuesday positions. "
                    f"File mtime is {mtime}. No fetch_cot.py script found in scripts/. "
                    f"If manually refreshed, a missed week leaves stale positioning data in the COT tab."
                ),
                file_refs=["prototypes/cot_data.json"],
                fix="Confirm or create an automated weekly COT fetch (CFTC publishes machine-readable CSV at https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm). Add to GitHub Actions schedule.",
            ))
    except OSError:
        pass

    return findings


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def _render_report(findings: list[Finding]) -> str:
    today_str = date.today().isoformat()
    high = [f for f in findings if f.risk == "HIGH"]
    medium = [f for f in findings if f.risk == "MEDIUM"]
    low = [f for f in findings if f.risk == "LOW"]

    lines = [
        "# Data Source Audit Report",
        "",
        f"> Generated: {today_str}  |  "
        f"HIGH: **{len(high)}**  |  MEDIUM: **{len(medium)}**  |  LOW: **{len(low)}**",
        "",
        "Scans all external data series referenced by `update_dashboard.py`, "
        "`src/macro/fetch/`, and `scripts/` against FRED metadata, value-range "
        "plausibility, and transformation consistency. "
        "Exit code 1 (blocks CI merge) on any HIGH finding.",
        "",
        "---",
        "",
    ]

    for risk_label, group in [("HIGH", high), ("MEDIUM", medium), ("LOW", low)]:
        if not group:
            continue
        lines.append(f"## {risk_label} ({len(group)})")
        lines.append("")
        for f in group:
            refs_str = ", ".join(f"`{r}`" for r in f.file_refs) if f.file_refs else "—"
            lines.append(f"### {f.series_id} — {f.title}")
            lines.append("")
            lines.append(f"**Category:** {f.category}  ")
            lines.append(f"**Files:** {refs_str}")
            lines.append("")
            for para in textwrap.wrap(f.detail, 100):
                lines.append(para)
            lines.append("")
            if f.fix:
                lines.append(f"**Fix:** {f.fix}")
                lines.append("")
            lines.append("---")
            lines.append("")

    lines.append("## Series validated")
    lines.append("")
    lines.append("| Series | Source | Category |")
    lines.append("|--------|--------|----------|")
    seen = set()
    for entry in FRED_MANIFEST:
        sid = entry["id"]
        if sid not in seen:
            lines.append(f"| {sid} | FRED | {entry.get('freq', '')} |")
            seen.add(sid)
    for extra in ["^GSPC", "^TNX", "^TYX", "^FVX", "^IRX", "BTC-USD",
                  "DX-Y.NYB", "JPY=X", "CNH=X", "EURCHF=X", "GC=F", "CL=F"]:
        lines.append(f"| {extra} | yfinance | — |")
    lines.append("| $MMTH | Barchart/EODData | — |")
    lines.append("| GDPNow | Atlanta Fed XLSX | — |")
    lines.append("| stir.json | Manual/CME | — |")
    lines.append("| cot_data.json | CFTC | — |")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    api_key = os.environ.get("FRED_API_KEY")
    if not api_key:
        print("ERROR: FRED_API_KEY environment variable is not set.", file=sys.stderr)
        print("Run: export FRED_API_KEY=<your_key>  (or set in GitHub Actions secrets)", file=sys.stderr)
        sys.exit(2)

    print(f"Validating {len(FRED_MANIFEST)} FRED series + static checks...")

    all_findings: list[Finding] = []

    # Static hardcoded checks (no API)
    all_findings.extend(_static_findings())

    # Staleness checks
    all_findings.extend(_check_stir_staleness())
    all_findings.extend(_check_cot_staleness())

    # Parallel FRED validation
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {
            pool.submit(_validate_fred_series, entry, api_key): entry["id"]
            for entry in FRED_MANIFEST
        }
        for future in as_completed(futures):
            sid = futures[future]
            try:
                results = future.result()
                all_findings.extend(results)
                high_count = sum(1 for f in results if f.risk == "HIGH")
                med_count = sum(1 for f in results if f.risk == "MEDIUM")
                status = "HIGH " * high_count + "MEDIUM " * med_count or "ok"
                print(f"  {sid}: {status.strip()}")
            except Exception as exc:
                print(f"  {sid}: validator raised {exc}", file=sys.stderr)

    all_findings.sort(key=lambda f: f.sort_key())

    high_count  = sum(1 for f in all_findings if f.risk == "HIGH")
    med_count   = sum(1 for f in all_findings if f.risk == "MEDIUM")
    low_count   = sum(1 for f in all_findings if f.risk == "LOW")
    print(f"\nResults: HIGH={high_count}  MEDIUM={med_count}  LOW={low_count}")

    report = _render_report(all_findings)
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(f"Report written: {REPORT_PATH}")

    if high_count > 0:
        print(f"\n{high_count} HIGH-risk finding(s) — exiting 1 (CI merge blocked)", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
