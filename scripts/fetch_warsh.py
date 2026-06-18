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
    """Return {YYYY-MM-DD: float} of daily closes via yfinance."""
    import yfinance as yf
    period = "2y" if days > 365 else "1y"
    df = yf.download(ticker, period=period, interval="1d",
                     progress=False, auto_adjust=True)
    if df is None or len(df) == 0:
        raise RuntimeError("empty yf " + ticker)
    c = df["Close"]
    if hasattr(c, "columns"):
        c = c.iloc[:, 0]
    c = c.dropna()
    out = {}
    cutoff = TODAY - datetime.timedelta(days=days)
    for idx, val in c.items():
        d = idx.date() if hasattr(idx, "date") else idx
        if d >= cutoff:
            out[d.isoformat()] = round(float(val), 4)
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

    # 5 - SOFR-implied policy path from the live strip (stir.json)
    z6_implied = None
    try:
        with open(STIR_PATH, "r", encoding="utf-8") as fh:
            stir = json.load(fh)
        mp = stir.get("meeting_path", [])
        if mp:
            labels = [m["meeting"] for m in mp]
            vals = [round(m.get("post_rate", m.get("contract_rate")), 3) for m in mp]
            charts["sofr"] = {"labels": labels, "vals": vals}
        for c in stir.get("sofr_strip", []):
            if "Z6" in c.get("symbol", "") or (c.get("year") == 2026 and str(c.get("symbol", "")).endswith("Z6")):
                z6_implied = c.get("implied_rate")
        effr = stir.get("effr")
        charts["sofr_kpi"] = {
            "z6": round(z6_implied, 2) if z6_implied is not None else None,
            "effr": effr,
            "hikes_bp": (round((z6_implied - effr) * 100) if (z6_implied is not None and effr is not None) else None),
        }
    except Exception as e:
        warnv.append("SOFR strip (stir.json) failed: %s" % e)

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

    # 8 - EURUSD vs US 2Y (dual axis), trailing 12m
    if eur and dgs2 and axis12:
        charts["eur"] = {
            "labels": lab12,
            "eurusd": col(eur, axis12, idx12, 1, 4),
            "us2y": col(dgs2, axis12, idx12, 1, 2),
        }

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
