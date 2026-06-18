#!/usr/bin/env python3
"""fetch_warsh.py - build prototypes/warsh.json for the Warsh Playbook tab.

Sources every chart on the tab from live data so it never goes stale:
  - FRED (daily): DGS2, DGS10, T10Y2Y, DFII10, MORTGAGE30US (weekly), DEXUSEU
  - yfinance:     ^MOVE (rate vol), DX-Y.NYB (dollar index)
  - stir.json:    live SOFR-implied policy path (meeting_path) + Dec-26 strip level

Gaps handled honestly:
  - SOFR Dec-2026 implied-rate HISTORY has no free source -> we plot the live
    SOFR-implied policy path by FOMC meeting instead (real, on-message).
  - German 2Y has no clean free daily series -> the FX chart plots EURUSD vs the
    US 2Y level rather than the US-DE differential.

Robust by design: if a source fails, that chart's key is written as null and the
dashboard falls back to its built-in illustrative curve for that one chart only.
Run via scripts/update_and_deploy.ps1 (after stir_pipeline.py).
"""
import os, sys, json, bisect, datetime, warnings
import requests

warnings.filterwarnings("ignore")

FRED_KEY  = "2e8783a45bc0ff35dda158225a6b2b02"
FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"

HERE      = os.path.dirname(os.path.abspath(__file__))
PROTO     = os.path.normpath(os.path.join(HERE, "..", "prototypes"))
STIR_PATH = os.path.join(PROTO, "stir.json")
OUT_PATH  = os.path.join(PROTO, "warsh.json")

TODAY = datetime.date.today()


def fred(series_id, days=400):
    """Return {YYYY-MM-DD: float} for a FRED series over the trailing window."""
    start = (TODAY - datetime.timedelta(days=days)).isoformat()
    params = {"series_id": series_id, "api_key": FRED_KEY,
              "file_type": "json", "observation_start": start}
    r = requests.get(FRED_BASE, params=params, timeout=30)
    r.raise_for_status()
    out = {}
    for o in r.json().get("observations", []):
        if o["value"] != ".":
            out[o["date"]] = float(o["value"])
    if not out:
        raise RuntimeError("empty series " + series_id)
    return out


def yf_close(ticker, days=400):
    """Return {YYYY-MM-DD: float} of daily closes via yfinance.

    Tries progressively shorter periods - futures contracts (e.g. ZQZ26) often
    return empty for a 1y/2y window but populate for 6mo.
    """
    import yfinance as yf
    periods = ["2y", "1y", "6mo", "3mo"] if days > 365 else ["1y", "6mo", "3mo"]
    c = None
    for period in periods:
        df = yf.download(ticker, period=period, interval="1d",
                         progress=False, auto_adjust=True)
        if df is not None and len(df) > 0:
            c = df["Close"]
            if hasattr(c, "columns"):
                c = c.iloc[:, 0]
            c = c.dropna()
            if len(c) > 0:
                break
    if c is None or len(c) == 0:
        raise RuntimeError("empty yf " + ticker)
    out = {}
    cutoff = TODAY - datetime.timedelta(days=days)
    for idx, val in c.items():
        d = idx.date() if hasattr(idx, "date") else idx
        if d >= cutoff:
            out[d.isoformat()] = round(float(val), 4)
    return out


def ecb_2y(days=400):
    """Euro-area AAA 2Y spot yield (ECB Data Portal) -> {YYYY-MM-DD: float}.

    The AAA curve is the German/Bund benchmark, so this stands in for the German
    2Y (no free daily DE 2Y series exists on FRED/yfinance).
    """
    url = ("https://data-api.ecb.europa.eu/service/data/YC/"
           "B.U2.EUR.4F.G_N_A.SV_C_YM.SR_2Y?format=jsondata&lastNObservations=340")
    r = requests.get(url, timeout=30, headers={"Accept": "application/json"})
    r.raise_for_status()
    j = r.json()
    series = j["dataSets"][0]["series"]
    key = list(series.keys())[0]
    obs = series[key]["observations"]
    dim = j["structure"]["dimensions"]["observation"][0]["values"]
    out = {}
    cutoff = (TODAY - datetime.timedelta(days=days)).isoformat()
    for k, v in obs.items():
        d = dim[int(k)]["id"]
        if v and v[0] is not None and d >= cutoff:
            out[d] = float(v[0])
    if not out:
        raise RuntimeError("empty ECB 2Y")
    return out


def axis_for(ref, days):
    """Trading-day axis = sorted dates of a daily reference series in the window."""
    cutoff = (TODAY - datetime.timedelta(days=days)).isoformat()
    return sorted(d for d in ref if d >= cutoff)


def ffill(series, axis):
    """Forward-fill a {date:val} dict onto an explicit date axis."""
    keys = sorted(series)
    out = []
    for d in axis:
        i = bisect.bisect_right(keys, d) - 1
        out.append(series[keys[i]] if i >= 0 else None)
    return out


def sample_idx(n, target):
    """Indices that thin a length-n axis to ~target points, always keeping the last."""
    if n <= target:
        return list(range(n))
    step = n / target
    idx = sorted(set(int(i * step) for i in range(target)))
    if idx[-1] != n - 1:
        idx.append(n - 1)
    return idx


def col(series, axis, idx, scale=1.0, nd=4):
    f = ffill(series, axis)
    out = []
    for i in idx:
        v = f[i]
        out.append(round(v * scale, nd) if v is not None else None)
    return out


def main():
    charts = {}
    warnv = []

    # --- FRED daily series (required core) ---
    fred_series = {}
    for sid in ("DGS2", "DGS10", "T10Y2Y", "DFII10", "MORTGAGE30US", "DEXUSEU"):
        try:
            fred_series[sid] = fred(sid)
        except Exception as e:
            warnv.append("FRED %s failed: %s" % (sid, e))

    dgs2  = fred_series.get("DGS2")
    dgs10 = fred_series.get("DGS10")
    t10y2 = fred_series.get("T10Y2Y")
    dfii10 = fred_series.get("DFII10")
    mort = fred_series.get("MORTGAGE30US")
    eur = fred_series.get("DEXUSEU")

    # canonical trading-day axes
    axis12 = axis_for(dgs10 or dgs2 or {}, 372)
    axis6  = axis_for(dgs10 or dgs2 or {}, 188)
    idx12  = sample_idx(len(axis12), 52)
    idx6   = sample_idx(len(axis6), 28)
    lab12  = [axis12[i] for i in idx12] if axis12 else []
    lab6   = [axis6[i] for i in idx6] if axis6 else []

    # 1 - 2Y yield, trailing 12m
    if dgs2 and axis12:
        charts["y2"] = {"labels": lab12, "vals": col(dgs2, axis12, idx12, 1, 3)}

    # 2 - MOVE, trailing 12m (yfinance)
    try:
        move = yf_close("^MOVE", 372)
        if move:
            charts["move"] = {"labels": lab12, "vals": col(move, axis12, idx12, 1, 1)}
    except Exception as e:
        warnv.append("MOVE (yfinance) failed: %s" % e)

    # 3 - 2s10s spread (bp); T10Y2Y is in percentage points -> *100
    if t10y2 and axis12:
        charts["s210"] = {"labels": lab12, "vals": col(t10y2, axis12, idx12, 100, 1)}
    elif dgs2 and dgs10 and axis12:
        f2 = ffill(dgs2, axis12); f10 = ffill(dgs10, axis12)
        vals = [round((f10[i] - f2[i]) * 100, 1) if (f10[i] is not None and f2[i] is not None) else None for i in idx12]
        charts["s210"] = {"labels": lab12, "vals": vals}

    # 4 - 1-month cumulative change in 2Y / 10Y (bp), last ~22 trading days
    if dgs2 and dgs10:
        ax1 = axis_for(dgs10, 34)[-23:]
        if len(ax1) >= 5:
            f2 = ffill(dgs2, ax1); f10 = ffill(dgs10, ax1)
            base2, base10 = f2[0], f10[0]
            c2y = [round((v - base2) * 100, 1) if v is not None else None for v in f2]
            c10 = [round((v - base10) * 100, 1) if v is not None else None for v in f10]
            charts["chg"] = {"labels": ax1, "c2y": c2y, "c10y": c10}

    # 5 - SOFR Dec-2026 implied rate, trailing 6m, from the Dec-26 Fed Funds future
    #     (ZQZ26; implied = 100 - price). SOFR-FFR basis ~0, so this tracks the SOFR Z6,
    #     and ZQ has a usable daily history where the SOFR contract does not.
    effr = None
    try:
        with open(STIR_PATH, "r", encoding="utf-8") as fh:
            effr = json.load(fh).get("effr")
    except Exception as e:
        warnv.append("stir.json effr read failed: %s" % e)
    try:
        zq = yf_close("ZQZ26.CBT", 200)
        if zq:
            ax = [d for d in sorted(zq) if d >= (TODAY - datetime.timedelta(days=188)).isoformat()]
            idx = sample_idx(len(ax), 40)
            charts["sofr"] = {"labels": [ax[i] for i in idx],
                              "vals": [round(100 - zq[ax[i]], 3) for i in idx]}
            z6 = round(100 - zq[ax[-1]], 2)
            charts["sofr_kpi"] = {"z6": z6, "effr": effr,
                                  "hikes_bp": (round((z6 - effr) * 100) if effr is not None else None)}
    except Exception as e:
        warnv.append("ZQZ26 (yfinance) failed: %s" % e)
    if "sofr_kpi" not in charts:   # fallback KPI from the live SOFR strip
        try:
            with open(STIR_PATH, "r", encoding="utf-8") as fh:
                strip = json.load(fh).get("sofr_strip", [])
            z6i = next((c.get("implied_rate") for c in strip if str(c.get("symbol", "")).endswith("Z6")), None)
            if z6i is not None:
                charts["sofr_kpi"] = {"z6": round(z6i, 2), "effr": effr,
                                      "hikes_bp": (round((z6i - effr) * 100) if effr is not None else None)}
        except Exception:
            pass

    # 6 - 30Y mortgage vs 10Y (both %), trailing 12m
    if mort and dgs10 and axis12:
        charts["mort"] = {
            "labels": lab12,
            "mortgage": col(mort, axis12, idx12, 1, 2),
            "ten": col(dgs10, axis12, idx12, 1, 2),
        }

    # 7 - Mortgage - 10Y spread (bp), trailing 12m
    if mort and dgs10 and axis12:
        fm = ffill(mort, axis12); f10 = ffill(dgs10, axis12)
        vals = [round((fm[i] - f10[i]) * 100, 0) if (fm[i] is not None and f10[i] is not None) else None for i in idx12]
        charts["mspread"] = {"labels": lab12, "vals": vals}

    # 8 - EURUSD vs US-DE 2Y differential (dual axis), trailing 12m.
    #     diff(bp) = US 2Y (DGS2) - euro-area AAA 2Y (ECB, ~German Bund 2Y).
    de2y = None
    try:
        de2y = ecb_2y(400)
    except Exception as e:
        warnv.append("ECB euro-area 2Y failed: %s" % e)
    if eur and dgs2 and de2y and axis12:
        f2 = ffill(dgs2, axis12); fde = ffill(de2y, axis12)
        diff = [round((f2[i] - fde[i]) * 100, 0) if (f2[i] is not None and fde[i] is not None) else None for i in idx12]
        charts["eur"] = {"labels": lab12, "eurusd": col(eur, axis12, idx12, 1, 4), "diff": diff}
    elif eur and dgs2 and axis12:   # DE 2Y unavailable -> fall back to US 2Y level
        charts["eur"] = {"labels": lab12, "eurusd": col(eur, axis12, idx12, 1, 4),
                         "us2y": col(dgs2, axis12, idx12, 1, 2)}

    # 9 - 10Y real yield vs DXY (dual axis), trailing 6m
    dxy = None
    try:
        dxy = yf_close("DX-Y.NYB", 188)
    except Exception as e:
        warnv.append("DXY (yfinance) failed: %s" % e)
    if dfii10 and dxy and axis6:
        charts["real"] = {
            "labels": lab6,
            "real": col(dfii10, axis6, idx6, 1, 2),
            "dxy": col(dxy, axis6, idx6, 1, 1),
        }
    elif dfii10 and axis6:
        # real yield is still real even if DXY fetch failed
        charts["real"] = {"labels": lab6, "real": col(dfii10, axis6, idx6, 1, 2), "dxy": None}

    payload = {
        "updated": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "asof": (max(dgs10) if dgs10 else TODAY.isoformat()),
        "charts": charts,
    }
    if warnv:
        payload["warnings"] = warnv

    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, separators=(",", ":"))

    print("wrote %s  (%d charts, asof %s)" % (OUT_PATH, len(charts), payload["asof"]))
    for w in warnv:
        print("  [warn]", w)
    return 0


if __name__ == "__main__":
    sys.exit(main())
