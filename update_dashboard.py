#!/usr/bin/env python3
"""
update_dashboard.py
Fetches real market data from FRED and CoinGecko, then injects it into
prototypes/dashboard-prototype.html between the DATA BLOCK markers.

Run once daily at market close (registered via Windows Task Scheduler).
"""

import os, sys, math, re, json
from datetime import datetime, date, timedelta

import requests
import yfinance as yf
import pandas as pd

# ── Config ────────────────────────────────────────────────────────
FRED_KEY  = "2e8783a45bc0ff35dda158225a6b2b02"
FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"
HTML_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "prototypes", "index.html")
BLOCK_START = "// ─── DATA BLOCK START ───"
BLOCK_END   = "// ─── DATA BLOCK END ───"
DATA_ORIGIN = date(2020, 1, 1)


# ── FRED ──────────────────────────────────────────────────────────
def fetch_fred(series_id, start=DATA_ORIGIN, freq=None, aggr=None, units=None):
    """Return {date_str: float} for a FRED series (dots dropped)."""
    params = {
        "series_id":        series_id,
        "api_key":          FRED_KEY,
        "file_type":        "json",
        "observation_start": str(start),
    }
    if freq:  params["frequency"] = freq
    if aggr:  params["aggregation_method"] = aggr
    if units: params["units"] = units
    r = requests.get(FRED_BASE, params=params, timeout=30)
    r.raise_for_status()
    out = {}
    for obs in r.json().get("observations", []):
        if obs["value"] != ".":
            out[obs["date"]] = float(obs["value"])
    return out


def fetch_yf_yield(ticker, start=DATA_ORIGIN):
    """Return {date_str: float} for a yfinance yield ticker (Close prices)."""
    df = yf.download(ticker, start=str(start), interval="1d", auto_adjust=True, progress=False)
    if df is None or len(df) == 0:
        raise RuntimeError(f"yfinance returned no data for {ticker}")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    out = {}
    for ts, row in df.iterrows():
        d = ts.date() if hasattr(ts, "date") else datetime.utcfromtimestamp(ts.timestamp()).date()
        v = float(row["Close"])
        if v == v:  # skip NaN
            out[str(d)] = v
    return out


def fetch_yf_5d_pct(ticker):
    """Return 5-trading-day % change (latest close vs 6th-to-last close)."""
    try:
        df = yf.download(ticker, period="30d", interval="1d", auto_adjust=True, progress=False)
        if df is None or len(df) == 0:
            return 0.0
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        closes = df["Close"].dropna()
        if len(closes) < 6:
            return 0.0
        return float((closes.iloc[-1] / closes.iloc[-6] - 1) * 100)
    except Exception:
        return 0.0


# ── Date helpers ──────────────────────────────────────────────────
def month_keys(start: date, end: date):
    """['2020-01', '2020-02', ...] inclusive."""
    keys, d = [], date(start.year, start.month, 1)
    while d <= date(end.year, end.month, 1):
        keys.append(f"{d.year}-{d.month:02d}")
        m = d.month + 1
        d = date(d.year + (m > 12), (m - 1) % 12 + 1, 1)
    return keys


def resample_monthly(day_dict):
    """Daily/weekly {date_str: float} → last value per month {YYYY-MM: float}."""
    by_month: dict = {}
    for d_str, v in day_dict.items():
        key = d_str[:7]
        if key not in by_month or d_str > by_month[key][0]:
            by_month[key] = (d_str, v)
    return {k: v[1] for k, v in by_month.items()}


def to_month_key(fred_monthly):
    """FRED monthly {YYYY-MM-DD: v} → {YYYY-MM: v}."""
    return {d[:7]: v for d, v in fred_monthly.items()}


# ── Array helpers ─────────────────────────────────────────────────
def align(keys, d: dict, default=None):
    return [d.get(k, default) for k in keys]


def forward_fill(arr):
    out, last = [], None
    for v in arr:
        if v is not None:
            last = v
        out.append(last)
    return out


def yoy_pct(arr, lag=12):
    out = [None] * len(arr)
    for i in range(lag, len(arr)):
        if arr[i] is not None and arr[i - lag] is not None and arr[i - lag] != 0:
            out[i] = ((arr[i] - arr[i - lag]) / abs(arr[i - lag])) * 100
    return out


def mom_pct(arr):
    out = [None] * len(arr)
    for i in range(1, len(arr)):
        if arr[i] is not None and arr[i - 1] is not None and arr[i - 1] != 0:
            out[i] = ((arr[i] - arr[i - 1]) / abs(arr[i - 1])) * 100
    return out


def moving_avg(arr, w):
    out = [None] * len(arr)
    for i in range(w - 1, len(arr)):
        win = arr[i - w + 1: i + 1]
        if all(v is not None for v in win):
            out[i] = sum(win) / w
    return out


def sub(a, b):
    return [av - bv if av is not None and bv is not None else None
            for av, bv in zip(a, b)]


# ── JS serialization ──────────────────────────────────────────────
def _fmt(v, dec):
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return "null"
    return f"{v:.{dec}f}"


def js_arr(arr, dec=4):
    return "[" + ",".join(_fmt(v, dec) for v in arr) + "]"


def js_daily_dates(date_strings):
    """['2020-01-02', ...] → compact JS that builds local Date objects."""
    joined = ",".join(f"'{d}'" for d in date_strings)
    return (f"[{joined}]"
            ".map(s=>{const p=s.split('-');"
            "return new Date(+p[0],+p[1]-1,+p[2])})")


def js_month_dates(month_keys_list):
    """['2020-01', ...] → compact JS that builds local Date objects."""
    joined = ",".join(f"'{k}'" for k in month_keys_list)
    return (f"[{joined}]"
            ".map(s=>{const p=s.split('-');"
            "return new Date(+p[0],+p[1]-1,1)})")


# ── Bitcoin ───────────────────────────────────────────────────────
def fetch_bitcoin():
    """Return {date_str: usd_close_price} daily from yfinance (BTC-USD)."""
    ticker = yf.Ticker("BTC-USD")
    df = ticker.history(start=str(DATA_ORIGIN), interval="1d")
    out = {}
    for ts, row in df.iterrows():
        d = ts.date() if hasattr(ts, "date") else datetime.utcfromtimestamp(ts.timestamp()).date()
        out[str(d)] = float(row["Close"])
    return out


# ── SPX + MMTH ────────────────────────────────────────────────────
def fetch_spx():
    """Return latest (date, spx_high, ema12, ema25) using daily HIGH per project spec."""
    raw = yf.download("^GSPC", period="2y", interval="1d", auto_adjust=True, progress=False)
    if raw is None or len(raw) == 0:
        raise RuntimeError("yfinance returned no data for ^GSPC")
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    highs = raw["High"].astype(float)
    ema12 = highs.ewm(span=12, adjust=False).mean()
    ema25 = highs.ewm(span=25, adjust=False).mean()
    last_date = highs.index[-1].strftime("%Y-%m-%d")
    return last_date, float(highs.iloc[-1]), float(ema12.iloc[-1]), float(ema25.iloc[-1])


def fetch_mmth_latest():
    """Return latest MMTH value via EODData if EODDATA_API_KEY is set, else None."""
    api_key = os.environ.get("EODDATA_API_KEY")
    if not api_key:
        return None
    try:
        from_date = (date.today() - timedelta(days=10)).isoformat()
        to_date   = date.today().isoformat()
        r = requests.get(
            "https://eodhistoricaldata.com/api/eod/MMTH.INDX",
            params={"api_token": api_key, "from": from_date, "to": to_date,
                    "fmt": "json", "period": "d"},
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        if not data:
            raise RuntimeError("EODData returned empty response for MMTH.INDX")
        latest = sorted(data, key=lambda x: x["date"])[-1]
        return float(latest["close"])
    except Exception as e:
        print(f"  MMTH fetch failed: {e}")
        return None


def classify_regime(spx_high, ema12, ema25, mmth):
    """8-condition regime classification per project memory."""
    above_12 = spx_high > ema12
    above_25 = spx_high > ema25
    below_25  = not above_25
    between   = above_25 and not above_12

    bearish_div = mmth is not None and above_12 and mmth < 60
    bullish_div = mmth is not None and below_25  and mmth > 40
    m = f"{mmth:.1f}%" if mmth is not None else "—"

    if above_12 and not bearish_div:
        return "green",  "none",     "SPX above 12d EMA with broad market participation. Bull market confirmed."
    elif above_12 and bearish_div:
        return "yellow", "bearish",  f"SPX above 12d EMA but MMTH at {m} — breadth divergence active. Downgrade to Yellow."
    elif between and bearish_div:
        return "red",    "bearish",  f"SPX between EMAs with weak breadth ({m}). Risk-off."
    elif between and bullish_div:
        return "yellow", "bullish",  f"SPX between EMAs with MMTH holding at {m}. Possible base forming."
    elif between:
        return "yellow", "none",     "SPX between 12d and 25d EMA. Neutral — monitor for directional break."
    elif below_25 and bullish_div:
        return "yellow", "bullish",  f"SPX below 25d EMA but MMTH holding at {m}. Potential base — upgrade to Yellow."
    elif below_25 and bearish_div:
        return "red",    "bearish",  f"SPX below 25d EMA with weak breadth ({m}). Risk-off."
    else:
        return "red",    "none",     "SPX below 25d EMA. Bear market conditions — reduce equity risk."


def _regime_block(spx_date, spx_high, ema12, ema25, mmth):
    rc, rd, cond = classify_regime(spx_high, ema12, ema25, mmth)
    mmth_js = "null" if mmth is None else f"{mmth:.2f}"
    # Format date as "Tue 22 Apr 2026"
    try:
        d = datetime.strptime(spx_date, "%Y-%m-%d")
        as_of = d.strftime("%a %d %b %Y")
    except Exception:
        as_of = spx_date
    cond_escaped = cond.replace("'", "\\'")
    return (
        f"const regimeSpx={spx_high:.2f};\n"
        f"const regimeEma12={ema12:.2f};\n"
        f"const regimeEma25={ema25:.2f};\n"
        f"const regimeMmth={mmth_js};\n"
        f"const regimeClass='{rc}';\n"
        f"const regimeDiv='{rd}';\n"
        f"const regimeCond='{cond_escaped}';\n"
        f"const regimeAsOf='{as_of}';"
    )


def _regime_macro_block(gdpnow, gdp_yoy, t5yie_wow, us2y_wow, us10y_wow,
                         sofr, iorb, net_liq_wow, usdjpy_5d, usdcnh_5d,
                         eurchf_5d, dxy_5d, updated):
    return (
        "const macroRegime={"
        f"gdpnow:{gdpnow:.4f},"
        f"gdp_yoy:{gdp_yoy:.4f},"
        f"t5yie_wow:{t5yie_wow:.4f},"
        f"us2y_wow:{us2y_wow:.4f},"
        f"us10y_wow:{us10y_wow:.4f},"
        f"sofr:{sofr:.4f},"
        f"iorb:{iorb:.4f},"
        f"net_liq_wow:{net_liq_wow:.4f},"
        f"usdjpy_5d:{usdjpy_5d:.4f},"
        f"usdcnh_5d:{usdcnh_5d:.4f},"
        f"eurchf_5d:{eurchf_5d:.4f},"
        f"dxy_5d:{dxy_5d:.4f},"
        f"updated:'{updated}'"
        "};"
    )


# ── Main ──────────────────────────────────────────────────────────
def main():
    # ── Fetch ─────────────────────────────────────────────────────
    print("Fetching inflation data from FRED...")
    cpi_h  = fetch_fred("CPIAUCSL")   # CPI Headline index
    cpi_c  = fetch_fred("CPILFESL")   # CPI Core index
    pce_h  = fetch_fred("PCEPI")      # PCE Headline index
    pce_c  = fetch_fred("PCEPILFE")   # PCE Core index
    ppi_h  = fetch_fred("PPIACO")     # PPI All Commodities index
    ppi_c  = fetch_fred("PPICOR")     # PPI Final Demand Less Food & Energy

    print("Fetching treasury yields (1Y/2Y: FRED, 5Y/10Y/30Y: yfinance)...")
    dgs1   = fetch_fred("DGS1")       # 1Y nominal — no yfinance equivalent
    dgs2   = fetch_fred("DGS2")       # 2Y nominal — no yfinance equivalent
    dgs5   = fetch_yf_yield("^FVX")   # 5Y nominal
    dgs10  = fetch_yf_yield("^TNX")   # 10Y nominal
    dgs30  = fetch_yf_yield("^TYX")   # 30Y nominal
    dfii5  = fetch_fred("DFII5")      # 5Y TIPS real yield — FRED only
    dfii10 = fetch_fred("DFII10")
    dfii30 = fetch_fred("DFII30")

    print("Fetching liquidity data from FRED...")
    resbal = fetch_fred("WRESBAL")    # Reserve Balances (weekly, billions USD) — chart use only
    walcl  = fetch_fred("WALCL")      # Fed Total Assets (weekly, millions USD) — H.4.1
    wdtgal = fetch_fred("WDTGAL")     # Treasury General Account (weekly, millions USD) — H.4.1
    wlrral = fetch_fred("WLRRAL")     # Reverse Repo Agreements (weekly, millions USD) — H.4.1
    trade  = fetch_fred("BOPGSTB")    # Trade Balance (monthly, millions USD)

    print("Fetching Bitcoin price from CoinGecko...")
    btc = fetch_bitcoin()

    print("Fetching SPX data...")
    spx_date, spx_high, spx_ema12, spx_ema25 = fetch_spx()
    print(f"  SPX {spx_high:.2f}  12d EMA {spx_ema12:.2f}  25d EMA {spx_ema25:.2f}")

    print("Fetching MMTH (requires EODDATA_API_KEY)...")
    mmth_val = fetch_mmth_latest()
    if mmth_val is None:
        print("  MMTH unavailable — set EODDATA_API_KEY env var for live data")
    else:
        print(f"  MMTH {mmth_val:.1f}%")

    print("Fetching regime inputs...")

    # SOFR and IORB — weekly ending Friday, average
    sofr_wk = fetch_fred("SOFR", freq="wef", aggr="avg")
    iorb_wk = fetch_fred("IORB", freq="wef", aggr="avg")
    sofr_latest = sofr_wk[sorted(sofr_wk)[-1]] if sofr_wk else 0.0
    iorb_latest = iorb_wk[sorted(iorb_wk)[-1]] if iorb_wk else 0.0
    print(f"  SOFR {sofr_latest:.2f}%  IORB {iorb_latest:.2f}%")

    # GDP YoY % change (latest quarter)
    gdp_yoy_data = fetch_fred("GDP", units="pc1")
    gdp_yoy_latest = gdp_yoy_data[sorted(gdp_yoy_data)[-1]] if gdp_yoy_data else 0.0
    print(f"  GDP YoY {gdp_yoy_latest:.2f}%")

    # GDPNow — read from gdpnow.json (refreshed by fetch_gdpnow.py)
    _gn_path = os.path.join(os.path.dirname(os.path.abspath(HTML_PATH)), "gdpnow.json")
    try:
        with open(_gn_path) as _f:
            _gn = json.load(_f)
        _lq = _gn["latest_quarter"]
        gdpnow_latest = _gn["quarters"][_lq]["gdp"][-1]
    except Exception as _e:
        print(f"  GDPNow read failed: {_e}")
        gdpnow_latest = 0.0
    print(f"  GDPNow {gdpnow_latest:.2f}%")

    # T5YIE WoW change in basis points (sign = inflation direction; bp scale consistent with yields)
    t5yie_data = fetch_fred("T5YIE")
    t5yie_dates = sorted(t5yie_data)
    t5yie_now  = t5yie_data[t5yie_dates[-1]] if t5yie_dates else 0.0
    _cutoff    = str((date.fromisoformat(t5yie_dates[-1]) - timedelta(days=5)).isoformat()) if t5yie_dates else ""
    _prev_d    = [d for d in t5yie_dates if d <= _cutoff]
    t5yie_prev = t5yie_data[_prev_d[-1]] if _prev_d else t5yie_now
    t5yie_wow  = (t5yie_now - t5yie_prev) * 100  # basis points (e.g. +0.08pp → +8bp)

    # MPS: absolute basis-point change (not % of yield) so 2Y/10Y ordering reflects curve shape
    dgs2_dates = sorted(dgs2)
    dgs2_now   = dgs2[dgs2_dates[-1]] if dgs2_dates else 0.0
    _cutoff2   = str((date.fromisoformat(dgs2_dates[-1]) - timedelta(days=5)).isoformat()) if dgs2_dates else ""
    _prev2     = [d for d in dgs2_dates if d <= _cutoff2]
    dgs2_prev  = dgs2[_prev2[-1]] if _prev2 else dgs2_now
    us2y_wow   = (dgs2_now - dgs2_prev) * 100  # basis points

    dgs10_dates = sorted(dgs10)
    dgs10_now   = dgs10[dgs10_dates[-1]] if dgs10_dates else 0.0
    _cutoff10   = str((date.fromisoformat(dgs10_dates[-1]) - timedelta(days=5)).isoformat()) if dgs10_dates else ""
    _prev10     = [d for d in dgs10_dates if d <= _cutoff10]
    dgs10_prev  = dgs10[_prev10[-1]] if _prev10 else dgs10_now
    us10y_wow   = (dgs10_now - dgs10_prev) * 100  # basis points
    print(f"  T5YIE WoW {t5yie_wow:+.1f}bp  US2Y WoW {us2y_wow:+.1f}bp  US10Y WoW {us10y_wow:+.1f}bp")

    # Net Liquidity WoW % change — WALCL - WDTGAL - WLRRAL (same formula as liqFedliq chart)
    def _latest(d): return d[sorted(d)[-1]] if d else 0.0
    def _prev_val(d, days=8):
        dates = sorted(d)
        cutoff = str((date.fromisoformat(dates[-1]) - timedelta(days=days)).isoformat()) if dates else ""
        prev = [x for x in dates if x <= cutoff]
        return d[prev[-1]] if prev else _latest(d)

    def _net_liq_b(w, tga, rra):
        return (w - tga - rra) / 1000  # millions → billions

    net_liq_now  = _net_liq_b(_latest(walcl),    _latest(wdtgal),    _latest(wlrral))
    net_liq_prev = _net_liq_b(_prev_val(walcl),  _prev_val(wdtgal),  _prev_val(wlrral))

    net_liq_wow  = (net_liq_now - net_liq_prev) / abs(net_liq_prev) * 100 if net_liq_prev else 0.0
    print(f"  Net Liq {net_liq_now:.0f}B  WoW {net_liq_wow:+.2f}%  "
          f"(WALCL {_latest(walcl)/1000:.0f}B - WDTGAL {_latest(wdtgal)/1000:.0f}B - WLRRAL {_latest(wlrral)/1000:.0f}B)")

    # FX 5-day % change from yfinance
    print("Fetching regime FX (yfinance)...")
    usdjpy_5d = fetch_yf_5d_pct("JPY=X")     # USDJPY: falling < 0 = negative impulse
    usdcnh_5d = fetch_yf_5d_pct("CNH=X")     # USDCNH: rising  > 0 = negative impulse
    if abs(usdcnh_5d) < 1e-4:
        usdcnh_5d = fetch_yf_5d_pct("CNY=X")
    eurchf_5d = fetch_yf_5d_pct("EURCHF=X")  # EURCHF: falling < 0 = negative impulse
    dxy_5d    = fetch_yf_5d_pct("DX-Y.NYB")  # DXY:    rising  > 0 = negative impulse
    print(f"  USDJPY {usdjpy_5d:+.2f}%  USDCNH {usdcnh_5d:+.2f}%  EURCHF {eurchf_5d:+.2f}%  DXY {dxy_5d:+.2f}%")

    # ── Monthly date axis ─────────────────────────────────────────
    today = date.today()
    last_mo_end = date(today.year, today.month, 1) - timedelta(days=1)
    last_mo = date(last_mo_end.year, last_mo_end.month, 1)
    mkeys = month_keys(DATA_ORIGIN, last_mo)
    N = len(mkeys)

    # ── Inflation ─────────────────────────────────────────────────
    def monthly_aligned(fred_dict):
        return align(mkeys, to_month_key(fred_dict))

    cpi_h_a  = monthly_aligned(cpi_h)
    cpi_c_a  = monthly_aligned(cpi_c)
    pce_h_a  = monthly_aligned(pce_h)
    pce_c_a  = monthly_aligned(pce_c)
    ppi_h_a  = monthly_aligned(ppi_h)
    ppi_c_a  = monthly_aligned(ppi_c)

    infl_pairs = [
        ("cpi-head", cpi_h_a), ("cpi-core", cpi_c_a),
        ("pce-head", pce_h_a), ("pce-core", pce_c_a),
        ("ppi-head", ppi_h_a), ("ppi-core", ppi_c_a),
    ]

    # ── Daily yields ──────────────────────────────────────────────
    # Use DGS10 dates as the canonical trading-day axis (all DGS share the calendar)
    daily_dates = sorted(dgs10.keys())
    ND = len(daily_dates)

    def daily_aligned(fred_dict):
        raw = [fred_dict.get(d) for d in daily_dates]
        return forward_fill(raw)

    nom1  = daily_aligned(dgs1)
    nom2  = daily_aligned(dgs2)
    nom5  = daily_aligned(dgs5)
    nom10 = daily_aligned(dgs10)
    nom30 = daily_aligned(dgs30)
    real5  = daily_aligned(dfii5)
    real10 = daily_aligned(dfii10)
    real30 = daily_aligned(dfii30)

    be5  = sub(nom5,  real5)
    be10 = sub(nom10, real10)
    be30 = sub(nom30, real30)

    spr_nom  = sub(nom10, nom2)
    spr_real = sub(real10, real5)
    spr_be   = sub(be10, be5)

    # ── Liquidity (monthly) ───────────────────────────────────────
    liq_resbal = forward_fill(align(mkeys, resample_monthly(
        {k: v / 1000 for k, v in resbal.items()})))  # millions → billions
    # Net Liquidity = WALCL - WDTGAL - WLRRAL (all millions USD → billions)
    _all_liq_dates = sorted(set(walcl) | set(wdtgal) | set(wlrral))
    _net_liq_daily = {
        d: (walcl.get(d, 0) - wdtgal.get(d, 0) - wlrral.get(d, 0)) / 1000
        for d in _all_liq_dates if walcl.get(d) is not None
    }
    liq_fedliq = forward_fill(align(mkeys, resample_monthly(_net_liq_daily)))
    liq_trade  = forward_fill(align(mkeys, to_month_key(
        {k: v / 1000 for k, v in trade.items()})))   # millions → billions
    liq_btc    = forward_fill(align(mkeys, resample_monthly(btc)))

    yoy_rb = moving_avg(yoy_pct(liq_resbal), 3)
    yoy_fl = moving_avg(yoy_pct(liq_fedliq), 3)
    yoy_tr = moving_avg(yoy_pct(liq_trade),  3)
    yoy_bt = moving_avg(yoy_pct(liq_btc),    3)

    print(f"  Monthly obs: {N}  |  Trading days: {ND}")

    # ── Build JS data block ───────────────────────────────────────
    updated = datetime.now().strftime("%Y-%m-%d %H:%M")

    infl_js_parts = []
    for key, arr in infl_pairs:
        infl_js_parts.append(
            f"  '{key}':{{yoy:{js_arr(yoy_pct(arr),2)},mom:{js_arr(mom_pct(arr),2)}}}"
        )
    infl_sets_js = "{\n" + ",\n".join(infl_js_parts) + "\n}"

    nom_daily_js = (
        "{\n"
        f"  '1Y':{js_arr(nom1,4)},\n"
        f"  '2Y':{js_arr(nom2,4)},\n"
        f"  '5Y':{js_arr(nom5,4)},\n"
        f"  '10Y':{js_arr(nom10,4)},\n"
        f"  '30Y':{js_arr(nom30,4)}\n"
        "}"
    )
    real_daily_js = (
        "{\n"
        f"  '5Y':{js_arr(real5,4)},\n"
        f"  '10Y':{js_arr(real10,4)},\n"
        f"  '30Y':{js_arr(real30,4)}\n"
        "}"
    )
    be_daily_js = (
        "{\n"
        f"  '5Y':{js_arr(be5,4)},\n"
        f"  '10Y':{js_arr(be10,4)},\n"
        f"  '30Y':{js_arr(be30,4)}\n"
        "}"
    )

    block = (
        f"const N={N}; // monthly obs Jan 2020 — updated {updated}\n"
        f"const dates={js_month_dates(mkeys)};\n"
        f"const inflSets={infl_sets_js};\n"
        "\n"
        "// --- Yields: daily ---\n"
        f"const ND={ND};\n"
        f"const dDatesArr={js_daily_dates(daily_dates)};\n"
        f"const nomDaily={nom_daily_js};\n"
        f"const realDaily={real_daily_js};\n"
        f"const beDaily={be_daily_js};\n"
        f"const sprNom={js_arr(spr_nom,4)};\n"
        f"const sprReal={js_arr(spr_real,4)};\n"
        f"const sprBE={js_arr(spr_be,4)};\n"
        "\n"
        "// --- Liquidity ---\n"
        f"const liqResbal={js_arr(liq_resbal,2)};\n"
        f"const liqFedliq={js_arr(liq_fedliq,2)};\n"
        f"const liqTrade={js_arr(liq_trade,3)};\n"
        f"const liqBtc={js_arr(liq_btc,2)};\n"
        f"const yoyRB={js_arr(yoy_rb,4)};\n"
        f"const yoyFL={js_arr(yoy_fl,4)};\n"
        f"const yoyTR={js_arr(yoy_tr,4)};\n"
        f"const yoyBT={js_arr(yoy_bt,4)};\n"
        "\n"
        "// --- Market Regime ---\n"
        + _regime_block(spx_date, spx_high, spx_ema12, spx_ema25, mmth_val)
        + "\n"
        "\n// --- Macro Regime ---\n"
        + _regime_macro_block(
            gdpnow_latest, gdp_yoy_latest, t5yie_wow, us2y_wow, us10y_wow,
            sofr_latest, iorb_latest, net_liq_wow,
            usdjpy_5d, usdcnh_5d, eurchf_5d, dxy_5d,
            datetime.now().strftime("%Y-%m-%d")
        )
    )

    # ── Inject into HTML ──────────────────────────────────────────
    html = open(HTML_PATH, encoding="utf-8").read()
    si = html.find(BLOCK_START)
    ei = html.find(BLOCK_END)
    if si == -1 or ei == -1 or si >= ei:
        sys.exit("ERROR: DATA BLOCK markers missing or out of order in HTML.")

    new_html = (
        html[: si + len(BLOCK_START)]
        + "\n"
        + block
        + "\n"
        + html[ei:]
    )
    open(HTML_PATH, "w", encoding="utf-8").write(new_html)
    print(f"Dashboard updated: {HTML_PATH}")


if __name__ == "__main__":
    main()
