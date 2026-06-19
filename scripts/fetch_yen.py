#!/usr/bin/env python3
"""fetch_yen.py - build prototypes/yen.json for the Yen & Carry tab.

Sources every chart it can from live data so the tab does not go stale:
  - FRED (daily):   DEXJPUS (USDJPY), DGS10 / DGS2 (US 10Y / 2Y)
  - MOF (daily):    JGB 1Y / 2Y / 10Y yields (jgbcme English CSV, full history)
  - e-Stat:         Japan core-core CPI YoY (table 0003427113, ex food & energy)
  - yfinance:       DX-Y.NYB (DXY), 1615.T (TOPIX Banks ETF),
                    JPY=X + ^N225 (Aug-2024 unwind window)

Derived, on-method:
  - fv   : USDJPY spot vs rate-differential fair value. OLS of USDJPY on the
           note's 2y+10y model (US-JP 2Y diff + US-JP 10Y diff), FIT ONLY on the
           pre-break sample (< 2025-04-01), then predicted forward. The spot-minus-
           fair residual is the decoupling argument. (Falls back to a 10Y-only fit
           if the JP 2Y leg is unavailable.)
  - corr : 120-trading-day rolling correlation of USDJPY and the US-JP 10Y diff.
  - real : JP 1Y real rate = JP 1Y JGB yield (MOF) - core-core CPI YoY (e-Stat).
  - jgb  : 10s30s JGB spread (MOF 30Y - 10Y, bp) vs core-core CPI (dual axis).

All nine panels are live. Robust by design: any source that fails is skipped
with a warning and that one chart falls back to the dashboard's built-in
illustrative curve. Run via scripts/update_and_deploy.ps1 alongside fetch_warsh.py.
"""
import os, sys, json, bisect, datetime, warnings, io, csv
import requests

warnings.filterwarnings("ignore")

FRED_KEY  = "2e8783a45bc0ff35dda158225a6b2b02"
FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"

# e-Stat (Japan official statistics). CPI table 0003427113 (2020 base):
#   cdTab=3 -> 前年同月比 (YoY %), cdArea=00000 -> 全国 (national),
#   cdCat01=0178 -> 生鮮食品及びエネルギーを除く総合 (core-core, ex food & energy).
ESTAT_KEY  = "482df469db097045af83f60b6843c841168e3789"
ESTAT_BASE = "https://api.e-stat.go.jp/rest/3.0/app/json/getStatsData"
ESTAT_CPI  = "0003427113"

# MOF (Japan Ministry of Finance) daily JGB yields, every tenor, English CSV.
# Historical file = full daily history (1986->); current = the live month.
MOF_BASE = "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/"

HERE     = os.path.dirname(os.path.abspath(__file__))
PROTO    = os.path.normpath(os.path.join(HERE, "..", "prototypes"))
OUT_PATH = os.path.join(PROTO, "yen.json")

TODAY      = datetime.date.today()
BREAK_DATE = "2025-04-01"   # pre-break OLS fit window ends here


def fred(series_id, days=900):
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


def yf_close(ticker, days=900, start=None, end=None):
    import yfinance as yf
    if start:
        df = yf.download(ticker, start=start, end=end, interval="1d",
                         progress=False, auto_adjust=True)
    else:
        periods = ["2y", "1y", "6mo"]
        df = None
        for period in periods:
            df = yf.download(ticker, period=period, interval="1d",
                             progress=False, auto_adjust=True)
            if df is not None and len(df) > 0:
                break
    if df is None or len(df) == 0:
        raise RuntimeError("empty yf " + ticker)
    c = df["Close"]
    if hasattr(c, "columns"):
        c = c.iloc[:, 0]
    c = c.dropna()
    out = {}
    cutoff = (None if start else TODAY - datetime.timedelta(days=days))
    for idx, val in c.items():
        d = idx.date() if hasattr(idx, "date") else idx
        if cutoff is None or d >= cutoff:
            out[d.isoformat()] = round(float(val), 4)
    if not out:
        raise RuntimeError("empty yf window " + ticker)
    return out


def estat_cpi_yoy(cat="0178"):
    """Japan core-core CPI YoY (%) -> {YYYY-MM-01: float}, monthly national."""
    params = {"appId": ESTAT_KEY, "statsDataId": ESTAT_CPI,
              "cdTab": "3", "cdCat01": cat, "cdArea": "00000", "limit": "400"}
    r = requests.get(ESTAT_BASE, params=params, timeout=40)
    r.raise_for_status()
    vals = r.json()["GET_STATS_DATA"]["STATISTICAL_DATA"]["DATA_INF"]["VALUE"]
    if isinstance(vals, dict):
        vals = [vals]
    out = {}
    for v in vals:
        t = str(v.get("@time", ""))           # e.g. 2026000505 -> 2026-05
        if len(t) < 10 or t[6:8] == "00":      # skip annual / fiscal-year rows
            continue
        try:
            out["%s-%s-01" % (t[:4], t[8:10])] = float(v["$"])
        except (ValueError, KeyError):
            continue
    if not out:
        raise RuntimeError("empty e-Stat CPI " + cat)
    return out


def mof_jgb():
    """Daily JGB 1Y, 2Y, 10Y & 30Y yields (%) from MOF -> (jp1, jp2, jp10, jp30).
    Merges the full historical file with the current-month file."""
    jp1, jp2, jp10, jp30 = {}, {}, {}, {}
    for fn in ("historical/jgbcme_all.csv", "jgbcme.csv"):
        r = requests.get(MOF_BASE + fn, headers={"User-Agent": "Mozilla/5.0"}, timeout=60)
        r.raise_for_status()
        r.encoding = "utf-8"
        rows = list(csv.reader(io.StringIO(r.text)))
        hi = next(i for i, row in enumerate(rows) if row and row[0].strip() == "Date")
        cols = rows[hi]
        i1, i2, i10, i30 = (cols.index("1Y"), cols.index("2Y"),
                            cols.index("10Y"), cols.index("30Y"))
        for row in rows[hi + 1:]:
            if len(row) <= i30 or not row[0].strip():
                continue
            p = row[0].strip().split("/")
            if len(p) != 3:
                continue
            d = "%04d-%02d-%02d" % (int(p[0]), int(p[1]), int(p[2]))
            for store, idx in ((jp1, i1), (jp2, i2), (jp10, i10), (jp30, i30)):
                try:
                    store[d] = float(row[idx])
                except (ValueError, IndexError):
                    pass
    if not jp10:
        raise RuntimeError("empty MOF JGB")
    return jp1, jp2, jp10, jp30


def axis_for(ref, days):
    cutoff = (TODAY - datetime.timedelta(days=days)).isoformat()
    return sorted(d for d in ref if d >= cutoff)


def ffill(series, axis):
    keys = sorted(series)
    out = []
    for d in axis:
        i = bisect.bisect_right(keys, d) - 1
        out.append(series[keys[i]] if i >= 0 else None)
    return out


def sample_idx(n, target):
    if n <= target:
        return list(range(n))
    step = n / target
    idx = sorted(set(int(i * step) for i in range(target)))
    if idx[-1] != n - 1:
        idx.append(n - 1)
    return idx


def lead_backfill(f):
    """Replace leading Nones with the first available value (avoids broken SVG
    paths when a series starts later than the axis)."""
    first = next((v for v in f if v is not None), None)
    if first is None:
        return f
    out, seen = [], False
    for v in f:
        if v is not None:
            seen = True
        out.append(v if seen else first)
    return out


def col(series, axis, idx, scale=1.0, nd=4):
    f = lead_backfill(ffill(series, axis))
    return [round(f[i] * scale, nd) if f[i] is not None else None for i in idx]


def ols(xs, ys):
    """Simple linear regression y = a + b*x over paired non-null samples."""
    pts = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    n = len(pts)
    if n < 10:
        return None
    mx = sum(p[0] for p in pts) / n
    my = sum(p[1] for p in pts) / n
    sxx = sum((p[0] - mx) ** 2 for p in pts)
    sxy = sum((p[0] - mx) * (p[1] - my) for p in pts)
    if sxx == 0:
        return None
    b = sxy / sxx
    a = my - b * mx
    return a, b


def rolling_corr(xs, ys, win=120):
    """120-pt rolling Pearson correlation; None where the window has gaps."""
    out = []
    for i in range(len(xs)):
        if i < win - 1:
            out.append(None)
            continue
        wx = xs[i - win + 1:i + 1]
        wy = ys[i - win + 1:i + 1]
        pts = [(a, b) for a, b in zip(wx, wy) if a is not None and b is not None]
        if len(pts) < win * 0.8:
            out.append(None)
            continue
        n = len(pts)
        mx = sum(p[0] for p in pts) / n
        my = sum(p[1] for p in pts) / n
        sxx = sum((p[0] - mx) ** 2 for p in pts)
        syy = sum((p[1] - my) ** 2 for p in pts)
        sxy = sum((p[0] - mx) * (p[1] - my) for p in pts)
        out.append(round(sxy / (sxx * syy) ** 0.5, 3) if sxx > 0 and syy > 0 else None)
    return out


def main():
    charts = {}
    warnv = []

    fred_series = {}
    for sid in ("DEXJPUS", "DGS10", "DGS2", "IRLTLT01JPM156N", "IR3TIB01JPM156N"):
        try:
            fred_series[sid] = fred(sid, 980)
        except Exception as e:
            warnv.append("FRED %s failed: %s" % (sid, e))

    usdjpy = fred_series.get("DEXJPUS")
    us10   = fred_series.get("DGS10")
    us2    = fred_series.get("DGS2")
    jp3m   = fred_series.get("IR3TIB01JPM156N")

    # Daily JP 1Y/2Y/10Y/30Y from MOF (FRED has only a monthly OECD 10Y, no 2Y/30Y).
    jp1 = jp2 = jp10 = jp30 = None
    try:
        jp1, jp2, jp10, jp30 = mof_jgb()
    except Exception as e:
        warnv.append("MOF JGB failed: %s" % e)
        jp10 = fred_series.get("IRLTLT01JPM156N")   # monthly 10Y fallback only

    # Japan core-core CPI YoY from e-Stat (FRED's OECD CPI series ended in 2021)
    cpi = None
    try:
        cpi = estat_cpi_yoy("0178")
    except Exception as e:
        warnv.append("e-Stat CPI failed: %s" % e)

    # Master daily axis spanning the full fetched history (~5y). The OLS fit uses
    # the whole pre-break span (the note fits multi-year, not just the display
    # window), and the 120d rolling corr is fully warmed up by the time the
    # 24-month display window starts -> no leading nulls.
    master = axis_for(usdjpy or us10 or {}, 1850)
    cut24  = (TODAY - datetime.timedelta(days=740)).isoformat()
    axis24 = [d for d in master if d >= cut24]
    idx24  = sample_idx(len(axis24), 60)
    lab24  = [axis24[i] for i in idx24] if axis24 else []

    if usdjpy and us10 and jp10 and master:
        uj_m   = lead_backfill(ffill(usdjpy, master))
        d10_m  = [(u - j) if (u is not None and j is not None) else None
                  for u, j in zip(ffill(us10, master), ffill(jp10, master))]
        d2_m   = None
        if us2 and jp2:
            d2_m = [(u - j) if (u is not None and j is not None) else None
                    for u, j in zip(ffill(us2, master), ffill(jp2, master))]
        uj_map  = {master[k]: uj_m[k]  for k in range(len(master))}
        d10_map = {master[k]: d10_m[k] for k in range(len(master))}

        # 1 - fair value. With both legs available, fit the note's 2y+10y model
        #     (USDJPY ~ US-JP 2Y diff + US-JP 10Y diff); else fall back to 10Y only.
        #     Fit on the FULL pre-break sample, predict across the display window.
        spot = [round(uj_map[axis24[i]], 1) if uj_map[axis24[i]] is not None else None for i in idx24]
        fair = None
        if d2_m is not None:
            try:
                import numpy as np
                X, Y = [], []
                for k, dt in enumerate(master):
                    if dt < BREAK_DATE and None not in (d2_m[k], d10_m[k], uj_m[k]):
                        X.append([1.0, d2_m[k], d10_m[k]]); Y.append(uj_m[k])
                if len(X) >= 20:
                    a, b2, b10 = np.linalg.lstsq(np.array(X), np.array(Y), rcond=None)[0]
                    d2_map = {master[k]: d2_m[k] for k in range(len(master))}
                    fair = []
                    for i in idx24:
                        dt = axis24[i]
                        if d2_map[dt] is not None and d10_map[dt] is not None:
                            fair.append(round(float(a + b2 * d2_map[dt] + b10 * d10_map[dt]), 1))
                        else:
                            fair.append(None)
            except Exception as e:
                warnv.append("2y+10y OLS failed: %s" % e)
        if fair is None:                       # 10Y-only fallback
            model = ols([d if master[k] < BREAK_DATE else None for k, d in enumerate(d10_m)],
                        [v if master[k] < BREAK_DATE else None for k, v in enumerate(uj_m)])
            if model:
                a, b = model
                fair = [round(a + b * d10_map[axis24[i]], 1) if d10_map[axis24[i]] is not None else None for i in idx24]
        if fair is not None:
            charts["fv"] = {"labels": lab24, "spot": spot, "fair": fair}
        else:
            warnv.append("fair-value: insufficient pre-break sample")

        # keep names used by the correlation block below
        diff_m = d10_m

        # 2 - 120d rolling correlation, computed on the master axis then displayed
        corr_m = rolling_corr(uj_m, diff_m, 120)
        corr_map = {master[k]: corr_m[k] for k in range(len(master))}
        disp = [corr_map[axis24[i]] for i in idx24]
        if any(c is not None for c in disp):
            charts["corr"] = {"labels": lab24, "vals": disp}

    # 3 - USDJPY vs DXY (dual axis)
    dxy = None
    try:
        dxy = yf_close("DX-Y.NYB", 740)
    except Exception as e:
        warnv.append("DXY (yfinance) failed: %s" % e)
    if usdjpy and dxy and axis24:
        charts["dxy"] = {
            "labels": lab24,
            "usdjpy": col(usdjpy, axis24, idx24, 1, 1),
            "dxy":    col(dxy, axis24, idx24, 1, 1),
        }

    # 4 - JP 1Y real rate = JP 1Y JGB yield (MOF, daily) - core-core CPI YoY.
    #     Falls back to the JP 3M rate if MOF's 1Y is unavailable.
    nominal_1y = jp1 if jp1 else jp3m
    real_series = None
    if nominal_1y and cpi:
        keys = sorted(set(nominal_1y) | set(cpi))
        real_series = {}
        fj = ffill(nominal_1y, keys); fc = ffill(cpi, keys)
        for k, d in enumerate(keys):
            if fj[k] is not None and fc[k] is not None:
                real_series[d] = round(fj[k] - fc[k], 2)
        if real_series and axis24:
            charts["real"] = {"labels": lab24, "vals": col(real_series, axis24, idx24, 1, 2)}

    # 5 - 10Y JGB nominal vs front-end real (dual axis)
    if jp10 and real_series and axis24:
        charts["nomreal"] = {
            "labels": lab24,
            "nominal": col(jp10, axis24, idx24, 1, 2),
            "real":    col(real_series, axis24, idx24, 1, 2),
        }

    # 5b - 10s30s JGB spread (bp) vs core-core CPI (dual axis; needs both legs)
    if jp10 and jp30 and cpi and axis24:
        keys = sorted(set(jp10) & set(jp30))
        spread = {d: round((jp30[d] - jp10[d]) * 100, 0) for d in keys}
        charts["jgb"] = {
            "labels": lab24,
            "spread": col(spread, axis24, idx24, 1, 0),
            "cpi":    col(cpi, axis24, idx24, 1, 1),
        }

    # 6 - TOPIX Banks (NEXT FUNDS TOPIX Banks ETF 1615.T tracks the index ~1:1)
    banks = None
    try:
        banks = yf_close("1615.T", 740)
    except Exception as e:
        warnv.append("TOPIX Banks 1615.T (yfinance) failed: %s" % e)
    if banks and axis24:
        charts["banks"] = {"labels": lab24, "vals": col(banks, axis24, idx24, 1, 1)}

    # 8 - TOPIX Banks vs front-end real (dual axis)
    if banks and real_series and axis24:
        charts["bankreal"] = {
            "labels": lab24,
            "banks": col(banks, axis24, idx24, 1, 1),
            "real":  col(real_series, axis24, idx24, 1, 2),
        }

    # 9 - August 2024 unwind (USDJPY vs Nikkei 225), real historical window
    try:
        uj_aug = yf_close("JPY=X", start="2024-07-01", end="2024-09-07")
        nk_aug = yf_close("^N225", start="2024-07-01", end="2024-09-07")
        ax = sorted(set(uj_aug) & set(nk_aug))
        if len(ax) >= 20:
            charts["unwind"] = {
                "labels": ax,
                "usdjpy": [round(uj_aug[d], 1) for d in ax],
                "nikkei": [round(nk_aug[d], 0) for d in ax],
            }
    except Exception as e:
        warnv.append("Aug-2024 unwind (yfinance) failed: %s" % e)

    payload = {
        "updated": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "asof": (max(usdjpy) if usdjpy else TODAY.isoformat()),
        "charts": charts,
    }
    if warnv:
        payload["warnings"] = warnv

    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, separators=(",", ":"))

    print("wrote %s  (%d charts, asof %s)" % (OUT_PATH, len(charts), payload["asof"]))
    print("  charts:", ", ".join(sorted(charts)))
    for w in warnv:
        print("  [warn]", w)
    return 0


if __name__ == "__main__":
    sys.exit(main())
