#!/usr/bin/env python3
"""cross_asset_fetch.py - build prototypes/cross_asset.json for the
Cross-Asset Regimes tab (SPX + UST 10Y + DXY joint regime model).

The tab classifies every trading day into one of 8 regimes from the signs of
three vol-normalized momentum signals (stocks / rates / dollar). The method,
lookback and vol windows are user-selectable on the page, so the regime model,
frequency table, transition matrix and linkage are ALL computed client-side
from the raw daily series shipped here. This script's job is therefore:

  1. Fetch the raw daily history and INNER-JOIN it (Pine alignData(); an
     observation exists only where every leg printed - no forward-fill):
       - EQUITY: yfinance ES=F       (E-mini S&P front-month continuous)
       - UST10Y: FRED   DGS10        (constant-maturity yield %)
       - DXY   : yfinance DX-Y.NYB   (ICE dollar index, matches the readouts)
  2. Compute the latest-day ticker readouts (level + 1d change).
  3. Pre-compute the SYNTHESIS tab's Cramer's V association ranking over the
     full history (needs extra curve / real-rate series: DGS2, DFII10, T10YIE).
     This is a structural, method-independent stat so it is computed once here.

Robust by design: any source that fails is skipped with a warning. If the core
three are unavailable the run aborts; if only the synthesis extras fail, the V
table falls back to the documented seed values so the tab still renders.

Run via scripts/update_and_deploy.ps1 alongside the other fetchers.
"""
import os, sys, json, datetime, warnings
import requests

warnings.filterwarnings("ignore")

FRED_KEY  = os.environ.get("FRED_API_KEY", "2e8783a45bc0ff35dda158225a6b2b02")
FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"

HERE     = os.path.dirname(os.path.abspath(__file__))
PROTO    = os.path.normpath(os.path.join(HERE, "..", "prototypes"))
OUT_PATH = os.path.join(PROTO, "cross_asset.json")

TODAY = datetime.date.today()
START = "1985-01-01"   # request deep; the inner join binds the real axis (ES=F starts 2000-09)

# Equity leg. The Pine model prices the equity leg off the E-mini front month, so
# the joined series is a ~23h futures session rather than the 09:30-16:00 cash index.
EQUITY_TICKER = "ES=F"

# Default regime settings used ONLY for the structural Cramer's V computation
# (the live tab recomputes regimes client-side under the user's controls).
DEF_LOOKBACK = 20


def fred(series_id, start=START):
    params = {"series_id": series_id, "api_key": FRED_KEY,
              "file_type": "json", "observation_start": start}
    r = requests.get(FRED_BASE, params=params, timeout=40)
    r.raise_for_status()
    out = {}
    for o in r.json().get("observations", []):
        if o["value"] != ".":
            out[o["date"]] = float(o["value"])
    if not out:
        raise RuntimeError("empty FRED series " + series_id)
    return out


def yf_close(ticker, start=START):
    import yfinance as yf
    df = yf.download(ticker, start=start, interval="1d",
                     progress=False, auto_adjust=True)
    if df is None or len(df) == 0:
        raise RuntimeError("empty yf " + ticker)
    c = df["Close"]
    if hasattr(c, "columns"):
        c = c.iloc[:, 0]
    c = c.dropna()
    out = {}
    for idx, val in c.items():
        d = idx.date() if hasattr(idx, "date") else idx
        out[d.isoformat()] = float(val)
    if not out:
        raise RuntimeError("empty yf window " + ticker)
    return out


def ffill_on(series, axis):
    """Forward-fill `series` (a {date:val} map) onto a sorted `axis` of dates."""
    import bisect
    keys = sorted(series)
    out = []
    for d in axis:
        i = bisect.bisect_right(keys, d) - 1
        out.append(series[keys[i]] if i >= 0 else None)
    return out


def cramers_v(cat_a, cat_b):
    """Cramer's V for two equal-length lists of categorical labels (None-safe)."""
    pairs = [(a, b) for a, b in zip(cat_a, cat_b) if a is not None and b is not None]
    n = len(pairs)
    if n < 30:
        return None
    rows = sorted(set(a for a, _ in pairs))
    cols = sorted(set(b for _, b in pairs))
    if len(rows) < 2 or len(cols) < 2:
        return None
    ri = {r: i for i, r in enumerate(rows)}
    ci = {c: j for j, c in enumerate(cols)}
    obs = [[0] * len(cols) for _ in rows]
    for a, b in pairs:
        obs[ri[a]][ci[b]] += 1
    rtot = [sum(r) for r in obs]
    ctot = [sum(obs[i][j] for i in range(len(rows))) for j in range(len(cols))]
    chi2 = 0.0
    for i in range(len(rows)):
        for j in range(len(cols)):
            e = rtot[i] * ctot[j] / n
            if e > 0:
                chi2 += (obs[i][j] - e) ** 2 / e
    k = min(len(rows), len(cols)) - 1
    if k <= 0:
        return None
    v = (chi2 / (n * k)) ** 0.5
    return round(min(v, 1.0), 3)


def sign_state(seq, lb, up_lbl, dn_lbl):
    """Per-day Up/Down label from the sign of the trailing lb-day change."""
    out = []
    for i in range(len(seq)):
        if i < lb or seq[i] is None or seq[i - lb] is None:
            out.append(None)
        else:
            out.append(up_lbl if seq[i] - seq[i - lb] > 0 else dn_lbl)
    return out


def pct_state(seq, lb, up_lbl, dn_lbl):
    out = []
    for i in range(len(seq)):
        if i < lb or seq[i] is None or seq[i - lb] in (None, 0):
            out.append(None)
        else:
            out.append(up_lbl if seq[i] / seq[i - lb] - 1 > 0 else dn_lbl)
    return out


# Relationship label + fixed interpretation gloss (copy is product-spec, kept
# verbatim). seed = documented fallback V if a series is unavailable.
SYNTH_RELS = [
    ("Cross-Asset Regime <-> Dollar Direction",  "xar", "dd",
     "Whether dollar direction differentiates cross-asset regimes", 1.000),
    ("Stock-Bond Quadrant <-> Curve Regime",     "sbq", "cr",
     "How stock-bond correlation regime maps to curve dynamics", 0.505),
    ("Spread Direction <-> Curve Regime",        "sd", "cr",
     "How relative stock-bond performance connects to curve shape", 0.453),
    ("Cross-Asset Regime <-> Curve Regime",      "xar", "cr",
     "How strongly curve shape (steepening/flattening) links to stock-bond-FX regime", 0.371),
    ("Curve Regime <-> Dollar Direction",        "cr", "dd",
     "How the dollar relates to yield curve dynamics", 0.196),
    ("Cross-Asset Regime <-> 10Y Rate Driver",   "xar", "rd",
     "Whether real rates or inflation expectations drive different macro regimes", 0.164),
    ("Spread Direction <-> Dollar Direction",    "sd", "dd",
     "Whether dollar confirms or contradicts relative stock-bond performance", 0.146),
    ("Curve Regime <-> 10Y Rate Driver",         "cr", "rd",
     "Whether real or inflation drives curve shape changes", 0.125),
    ("Stock-Bond Quadrant <-> 10Y Driver",       "sbq", "rd",
     "Which rate component matters most in each stock-bond state", 0.088),
    ("Dollar Direction <-> 10Y Rate Driver",     "dd", "rd",
     "Whether the dollar is more connected to real rates or inflation expectations", 0.019),
]


def category_for(v):
    if v >= 0.35:
        return "PRIMARY"
    if v >= 0.15:
        return "SECONDARY"
    return "CONFIRMING"


def build_synthesis(dates, spx, y10, dxy, warnv):
    """Compute the Cramer's V ranking over full history; fall back to seeds."""
    lb = DEF_LOOKBACK
    cats = {}
    # Cross-asset regime label (per-day 3-state code R1..R8)
    st_s = pct_state(spx, lb, "SU", "SD")
    st_r = sign_state(y10, lb, "RU", "RD")   # yields up / down
    st_d = pct_state(dxy, lb, "DU", "DD")
    order = ["SU", "SD"]  # placeholder; build full code below
    xar = []
    for s, r, d in zip(st_s, st_r, st_d):
        xar.append((s + r + d) if None not in (s, r, d) else None)
    cats["xar"] = xar
    cats["dd"] = st_d
    # Stock-bond quadrant: SPX up/down x bond up/down (bond up = yield down)
    bond = [(-y if y is not None else None) for y in y10]
    sbq_s = pct_state(spx, lb, "su", "sd")
    sbq_b = sign_state(bond, lb, "bu", "bd")
    cats["sbq"] = [(a + b) if None not in (a, b) else None for a, b in zip(sbq_s, sbq_b)]
    # Spread direction: sign of (SPX lb-return - bond lb-return)
    sd = []
    for i in range(len(dates)):
        if i < lb or None in (spx[i], spx[i - lb], y10[i], y10[i - lb]) or spx[i - lb] == 0:
            sd.append(None)
            continue
        sret = spx[i] / spx[i - lb] - 1
        bret = -(y10[i] - y10[i - lb]) / 100.0   # bond proxy return
        sd.append("Sout" if sret - bret > 0 else "Bout")
    cats["sd"] = sd

    # Curve regime + 10Y rate driver need extra FRED series
    cr = rd = None
    try:
        y2 = ffill_on(fred("DGS2"), dates)
        slope = [(a - b) if None not in (a, b) else None for a, b in zip(y10, y2)]
        cr = sign_state(slope, lb, "STEEP", "FLAT")
    except Exception as e:
        warnv.append("DGS2 (curve regime) failed: %s" % e)
    cats["cr"] = cr
    try:
        real = ffill_on(fred("DFII10"), dates)
        be = ffill_on(fred("T10YIE"), dates)
        rd = []
        for i in range(len(dates)):
            if i < lb or None in (real[i], real[i - lb], be[i], be[i - lb]):
                rd.append(None)
            else:
                dr = abs(real[i] - real[i - lb]); di = abs(be[i] - be[i - lb])
                rd.append("REAL" if dr >= di else "INFL")
    except Exception as e:
        warnv.append("DFII10/T10YIE (rate driver) failed: %s" % e)
    cats["rd"] = rd

    rows = []
    for label, ka, kb, interp, seed in SYNTH_RELS:
        v = None
        if cats.get(ka) is not None and cats.get(kb) is not None:
            v = cramers_v(cats[ka], cats[kb])
        if v is None:
            v = seed
            real_flag = False
        else:
            real_flag = True
        rows.append({"rel": label, "v": v, "interp": interp, "real": real_flag})
    rows.sort(key=lambda r: r["v"], reverse=True)
    for i, r in enumerate(rows, 1):
        r["rank"] = i
        r["cat"] = category_for(r["v"])
    return rows


def main():
    warnv = []
    spx_raw = y10_raw = dxy_raw = None
    try:
        spx_raw = yf_close(EQUITY_TICKER)
        # The Barchart $SPX backfill that used to sit here is deliberately gone: it
        # patched a missing Yahoo bar with the CASH index print, which cannot be
        # spliced onto an ES front-month series without injecting a basis-sized jump.
        # A missing newest ES bar now just drops out of the inner join instead.
    except Exception as e:
        warnv.append("equity %s failed: %s" % (EQUITY_TICKER, e))
    try:
        y10_raw = fred("DGS10")
    except Exception as e:
        warnv.append("DGS10 failed: %s" % e)
    try:
        dxy_raw = yf_close("DX-Y.NYB")
    except Exception as e:
        warnv.append("DXY DX-Y.NYB failed: %s" % e)

    if not (spx_raw and y10_raw and dxy_raw):
        print("FATAL: missing a core series; cannot build cross_asset.json")
        for w in warnv:
            print("  [warn]", w)
        return 1

    # Pine alignData(): exact k-way INNER JOIN on session dates. An observation
    # exists only on dates where EVERY leg actually printed, so a bond-market-only
    # holiday drops the day instead of fabricating a forward-filled 0bp change.
    axis = sorted(set(spx_raw) & set(y10_raw) & set(dxy_raw))
    spx = [round(spx_raw[d], 2) for d in axis]
    y10 = [round(y10_raw[d], 3) for d in axis]
    dxy = [round(dxy_raw[d], 3) for d in axis]

    # Latest-day readouts
    def chg_pct(a):
        return round((a[-1] / a[-2] - 1) * 100, 2) if len(a) > 1 and a[-2] else None
    readout = {
        "asof": axis[-1],
        "spx": spx[-1], "spx_chg_pct": chg_pct(spx),
        "y10": y10[-1], "y10_chg_bp": round((y10[-1] - y10[-2]) * 100, 1) if len(y10) > 1 else None,
        "dxy": dxy[-1], "dxy_chg_pct": chg_pct(dxy),
    }

    synthesis = build_synthesis(axis, spx, y10, dxy, warnv)

    payload = {
        "updated": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "asof": axis[-1],
        "n": len(axis),
        "dates": axis,
        "spx": spx,
        "y10": y10,
        "dxy": dxy,
        "readout": readout,
        "synthesis": synthesis,
    }
    if warnv:
        payload["warnings"] = warnv

    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, separators=(",", ":"))

    print("wrote %s  (%d days %s -> %s)" % (OUT_PATH, len(axis), axis[0], axis[-1]))
    print("  readout:", readout)
    print("  synthesis V (top 3):", [(r["rel"], r["v"], r["real"]) for r in synthesis[:3]])
    for w in warnv:
        print("  [warn]", w)
    return 0


if __name__ == "__main__":
    sys.exit(main())
