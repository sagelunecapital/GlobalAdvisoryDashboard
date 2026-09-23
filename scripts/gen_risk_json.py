# Generates prototypes/risk.json for the dashboard Risk tab.
#
# All figures measured against a fixed $300,000 notional NAV - never account equity.
#
# Inputs:
#   data/ibkr_flex.json   - the book of record (scripts/ibkr_flex_fetch.py, Flex Web Service)
#   data/risk_manual.json - human judgment: stops, themes, scenarios, news, notes
#   yfinance              - live marks and the daily bars behind vol / ATR / VaR
# Output:
#   prototypes/risk.json
#
# The split matters. Everything price-driven is recomputed every run: marks, stop
# distances, vol, ATR, touch probabilities, VaR, correlation, gross, stop_total and
# the budget meters. Everything in risk_manual.json is left exactly as authored and
# stamped with reviewed_on; when live prices drift past drift_tolerance the output
# carries judgment_stale=true so the tab can say the scenarios need re-deriving
# rather than quietly presenting old arithmetic as current.
#
# Methods, all reproducing the hand-built 15 Sep 2026 issue:
#   vol_d      sample stdev of simple daily returns over the window
#   vol_a      vol_d * sqrt(252)
#   pN         P(stop touched within N sessions), reflection principle, zero drift:
#              2 * Phi(-ln(S/B) / (vol_d * sqrt(N)))
#   VaR        parametric, z95=1.645 / z99=2.326 on the correlated portfolio sigma
#   var_share  (mv_i * vol_i)^2 / sigma_p^2
import json, io, os, sys, math, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FLEX = os.path.join(ROOT, "data", "ibkr_flex.json")
MANUAL = os.path.join(ROOT, "data", "risk_manual.json")
OUT = os.path.join(ROOT, "prototypes", "risk.json")

WINDOW = 60          # daily bars behind vol / correlation
ATR_N = 14           # Wilder ATR period
Z95, Z99 = 1.645, 2.326
HORIZONS = (5, 21, 63)
FLEX_MAX_AGE_H = 36  # a Flex snapshot older than this is not publishable


def fail(msg):
    print("FATAL: " + msg)
    sys.exit(1)


def phi(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def touch_prob(spot, barrier, vol_d, days):
    """P(barrier touched within `days` sessions). Reflection principle, zero drift."""
    if spot <= 0 or barrier <= 0 or vol_d <= 0 or days <= 0:
        return None
    if barrier >= spot:          # already at or through the stop
        return 1.0
    x = math.log(spot / barrier)
    return min(1.0, 2.0 * phi(-x / (vol_d * math.sqrt(days))))


def load(path, what):
    if not os.path.exists(path):
        fail("%s missing (%s). Run the step that produces it before this one." % (path, what))
    with io.open(path, encoding="utf-8") as f:
        return json.load(f)


def main():
    man = load(MANUAL, "judgment inputs")
    flex = load(FLEX, "IBKR book of record")

    # ---- the Flex snapshot must be fresh, or we are publishing yesterday's book ----
    try:
        fetched = datetime.datetime.strptime(flex["fetched_at"], "%Y-%m-%dT%H:%M:%SZ") \
                          .replace(tzinfo=datetime.timezone.utc)
    except (KeyError, ValueError):
        fail("data/ibkr_flex.json has no usable fetched_at stamp")
    age_h = (datetime.datetime.now(datetime.timezone.utc) - fetched).total_seconds() / 3600.0
    if age_h > FLEX_MAX_AGE_H:
        fail("IBKR snapshot is %.1fh old (limit %dh). Re-run scripts/ibkr_flex_fetch.py; "
             "refusing to publish a stale book." % (age_h, FLEX_MAX_AGE_H))

    NAV = float(man["nav"])
    THEME = man["limits"]["theme_pct"] * NAV
    PORT = man["limits"]["portfolio_pct"] * NAV
    holdings = man["holdings"]
    excluded_cfg = man.get("excluded", {})

    # ---- reconcile the live book against what the judgment file knows about ----
    live = {p["sym"]: p for p in flex["positions"]}
    unknown = [s for s in live if s not in holdings and s not in excluded_cfg]
    if unknown:
        fail("IBKR holds %s, which data/risk_manual.json neither tracks nor excludes. "
             "A new position must not silently vanish from the risk board - add it to "
             "holdings (with a stop and a theme) or to excluded, then re-run."
             % ", ".join(sorted(unknown)))
    gone = [s for s in holdings if s not in live]
    if gone:
        fail("data/risk_manual.json tracks %s but IBKR no longer holds it. Remove it "
             "from holdings (and re-derive the scenarios) before publishing."
             % ", ".join(sorted(gone)))

    syms = sorted(holdings)

    # ---- prices: yfinance for live marks and the bars behind every statistic ----
    try:
        import yfinance as yf
        import pandas as pd
    except ImportError as e:
        fail("yfinance/pandas required for marks and vol (%s)" % e)

    need = syms + sorted(excluded_cfg)
    raw = yf.download(need, period="6mo", interval="1d",
                      auto_adjust=False, progress=False, group_by="ticker")
    if raw is None or len(raw) == 0:
        fail("yfinance returned no bars for %s" % ", ".join(need))

    bars = {}
    for s in need:
        try:
            df = raw[s] if len(need) > 1 else raw
            df = df.dropna(subset=["Close"])
        except KeyError:
            fail("yfinance returned no frame for %s" % s)
        if len(df) < WINDOW + 1:
            fail("%s has only %d usable bars, need %d" % (s, len(df), WINDOW + 1))
        bars[s] = df

    rets = {}
    for s in syms:
        c = bars[s]["Close"].astype(float)
        rets[s] = c.pct_change().dropna().iloc[-WINDOW:]
        if len(rets[s]) < WINDOW:
            fail("%s: only %d returns in the window" % (s, len(rets[s])))

    win = bars[syms[0]].index[-WINDOW:]
    vol_window = "%s - %s (%d daily bars)" % (
        win[0].strftime("%d %b"), win[-1].strftime("%d %b %Y"), WINDOW)

    # ---- per-position ----
    pos = []
    for s in syms:
        h = holdings[s]
        lv = live[s]
        df = bars[s]
        close = df["Close"].astype(float)
        px = float(close.iloc[-1])
        prev = float(close.iloc[-2])
        qty = float(lv["qty"])
        avg = float(lv["avg"])
        stop = float(h["stop"])

        if stop >= px:
            print("  WARNING %s stop %.2f is at or above the mark %.2f" % (s, stop, px))

        vol_d = float(rets[s].std(ddof=1))
        # Wilder ATR on true range
        high = df["High"].astype(float)
        low = df["Low"].astype(float)
        pc = close.shift(1)
        tr = pd.concat([high - low, (high - pc).abs(), (low - pc).abs()], axis=1).max(axis=1)
        atr = float(tr.dropna().ewm(alpha=1.0 / ATR_N, adjust=False).mean().iloc[-1])

        mv = qty * px
        p = {
            "sym": s,
            "name": h["name"],
            "theme": h["theme"],
            "sub": h["sub"],
            "qty": qty,
            "px": px,
            "avg": avg,
            "stop": stop,
            "stop_confirmed_on": h.get("stop_confirmed_on"),
            "daily": qty * (px - prev),
            "unreal": qty * (px - avg),
            "vol_d": vol_d,
            "vol_a": vol_d * math.sqrt(252.0),
            "atr": atr,
            "mv": mv,
            "pct_nav": mv / NAV,
            "stop_dist": (px - stop) / px,
            "stop_risk": qty * (px - stop),
            "stop_vs_cost": qty * (stop - avg),
            "atr_mult": (px - stop) / atr if atr > 0 else None,
        }
        for n, key in zip(HORIZONS, ("p5", "p21", "p63")):
            p[key] = touch_prob(px, stop, vol_d, n)
        p["theme_used"] = p["stop_risk"] / THEME
        p["max_shares_theme"] = THEME / (px - stop) if px > stop else None
        p["headroom"] = (p["max_shares_theme"] / qty) if p["max_shares_theme"] else None
        pos.append(p)

    gross = sum(p["mv"] for p in pos)
    for p in pos:
        p["pct_book"] = p["mv"] / gross

    # ---- portfolio VaR: parametric, correlation-adjusted ----
    sig = {p["sym"]: p["mv"] * p["vol_d"] for p in pos}
    var_sum = sum(v * v for v in sig.values())
    cross = 0.0
    corr = None
    if len(syms) == 2:
        a, b = syms
        corr = float(rets[a].corr(rets[b]))
        cross = 2.0 * corr * sig[a] * sig[b]
    elif len(syms) > 2:
        for i, a in enumerate(syms):
            for b in syms[i + 1:]:
                cross += 2.0 * float(rets[a].corr(rets[b])) * sig[a] * sig[b]
    sigma_p = math.sqrt(max(0.0, var_sum + cross))
    var95, var99 = Z95 * sigma_p, Z99 * sigma_p
    for p in pos:
        p["var_share"] = (sig[p["sym"]] ** 2) / (sigma_p ** 2) if sigma_p > 0 else None

    stop_total = sum(p["stop_risk"] for p in pos)
    gap_total = float(man["gap"]["total"])

    # ---- is the authored judgment still anchored to today's prices? ----
    basis = man.get("price_basis", {})
    tol = float(man.get("drift_tolerance", 0.05))
    drift = {}
    for p in pos:
        b = basis.get(p["sym"])
        if b:
            drift[p["sym"]] = (p["px"] - b) / b
    worst = max((abs(v) for v in drift.values()), default=0.0)
    stale = worst > tol

    # ---- excluded holding (UI renders a single one) ----
    if len(excluded_cfg) > 1:
        fail("the Risk tab renders exactly one excluded holding; %d configured"
             % len(excluded_cfg))
    excluded = None
    for s, cfg in excluded_cfg.items():
        lv = live.get(s)
        if not lv:
            continue
        px = float(bars[s]["Close"].astype(float).iloc[-1])
        excluded = {"sym": s, "qty": float(lv["qty"]), "px": px,
                    "mv": float(lv["qty"]) * px,
                    "unreal": float(lv["qty"]) * (px - float(lv["avg"])),
                    "reason": cfg["reason"]}

    themes = sorted({p["theme"] for p in pos})

    # Stop risk per theme, and the binding theme - the one nearest its own cap.
    theme_stop = {th: sum(p["stop_risk"] for p in pos if p["theme"] == th) for th in themes}
    binding_theme = max(theme_stop, key=lambda th: theme_stop[th]) if theme_stop else None
    binding_abs = theme_stop.get(binding_theme, 0.0)
    # The authored gas gap is a UNG-only figure, so it loads whichever theme UNG sits in.
    gap_theme = next((p["theme"] for p in pos if p["sym"] == "UNG"), None)

    # {SYM_PCT} placeholders in not_configured resolve to live concentration
    by_sym = {p["sym"]: p for p in pos}
    not_configured = []
    for line in man["not_configured"]:
        for s, p in by_sym.items():
            line = line.replace("{%s_PCT}" % s, "%.1f%%" % (100 * p["pct_book"]))
        not_configured.append(line)

    # news "affects" carries the live exposure alongside the authored text
    news = []
    for n in man["news"]:
        n = dict(n)
        p = by_sym.get(n.get("affects"))
        if p:
            n["affects"] = "%s, $%s" % (p["sym"], format(int(round(p["mv"])), ","))
        news.append(n)

    notes = list(man["notes"])
    if stale:
        notes.insert(0, "Scenario, slippage and gap figures were authored on %s at "
                        "%s and prices have since moved %.1f%%. Treat those rows as "
                        "indicative until they are re-derived; the positions, stops, "
                        "vol, VaR and budget meters above are live."
                     % (man["reviewed_on"],
                        ", ".join("%s $%.2f" % (s, v) for s, v in sorted(basis.items())),
                        100 * worst))

    now = datetime.datetime.now(datetime.timezone.utc)
    doc = {
        "updated": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "export_pulled": fetched.strftime("%d %b %Y"),
        # Say what the book actually came from - the tab prints this verbatim.
        "source": "%s + live marks" % flex.get("source", "unknown source"),
        "vol_window": vol_window,
        "mark_date": bars[syms[0]].index[-1].strftime("%Y-%m-%d"),
        "flex_report_date": flex.get("report_date"),
        "nav": NAV,
        "unit": 0.01 * NAV,
        "judgment_reviewed_on": man["reviewed_on"],
        "judgment_stale": stale,
        "judgment_drift": drift,
        "limits": {
            "theme_pct": man["limits"]["theme_pct"], "theme_abs": THEME,
            "portfolio_pct": man["limits"]["portfolio_pct"], "portfolio_abs": PORT,
            "basis": man["limits"]["basis"],
            "provisional": man["limits"]["provisional"],
            "set_on": man["limits"]["set_on"],
        },
        "positions": pos,
        "totals": {
            "gross": gross, "gross_pct": gross / NAV, "net_pct": gross / NAV,
            "daily": sum(p["daily"] for p in pos),
            "unreal": sum(p["unreal"] for p in pos),
            "stop_total": stop_total, "stop_pct": stop_total / NAV,
            "gap_total": gap_total, "gap_pct": gap_total / NAV,
            "var95": var95, "var99": var99, "correlation": corr,
            # The theme meter tracks the BINDING theme - the one closest to its own
            # 2% cap. Measuring the whole book against a single theme budget only
            # made sense while the book was effectively one theme.
            "theme_binding": binding_theme,
            "theme_binding_abs": binding_abs,
            "theme_used": binding_abs / THEME, "portfolio_used": stop_total / PORT,
            # The gas gap is authored on UNG alone, so it loads only UNG's theme.
            "theme_gap_applies": gap_theme == binding_theme,
            "theme_used_gap": (gap_total / THEME) if gap_theme == binding_theme else None,
            "portfolio_used_gap": gap_total / PORT,
            # VaR is computed book-wide; there is no per-theme covariance, so the
            # theme meter carries no VaR segment rather than borrowing the book's.
            "theme_used_var99": None, "portfolio_used_var99": var99 / PORT,
            "themes_live": len(themes), "themes_supported": PORT / THEME,
        },
        "excluded": excluded,
        "scenarios": man["scenarios"],
        "slippage": man["slippage"],
        "gross_permitted": [dict(r, gross=PORT / r["stop"]) for r in man["gross_permitted"]],
        "limit_rows": (
            [{"name": "Portfolio - all stops fill cleanly", "budget": PORT, "cur": stop_total},
             {"name": "Portfolio - gas gap, no stop protection", "budget": PORT, "cur": gap_total},
             {"name": "Portfolio - VaR 99%, correlation-adjusted", "budget": PORT, "cur": var99}]
            + [{"name": "%s theme - all stops fill cleanly" % t, "budget": THEME,
                "cur": sum(p["stop_risk"] for p in pos if p["theme"] == t)} for t in themes]
            # The gas gap is a UNG-only figure, so it belongs to UNG's theme budget.
            # VaR is book-wide and is measured against the portfolio cap, not a
            # theme cap - comparing it to 2% of NAV manufactured a false breach.
            + ([{"name": "%s theme - gas gap, no stop protection" % gap_theme,
                 "budget": THEME, "cur": gap_total}] if gap_theme else [])
            + [{"name": "Portfolio - VaR 95%, correlation-adjusted", "budget": PORT,
                "cur": var95}]
            + [{"name": "%s - position risk at stop" % p["sym"], "budget": THEME,
                "cur": p["stop_risk"]} for p in pos]
        ),
        "not_configured": not_configured,
        "regime": {"note": "Read live from regime.json by the tab."},
        "news_as_of": man.get("news_as_of"),
        "news": news,
        "notes": notes,
    }

    with io.open(OUT, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=1, ensure_ascii=True)

    # ---- assertions: invariants, NOT a pinned snapshot. These must hold at any price. ----
    d = json.load(io.open(OUT, encoding="utf-8"))
    t = d["totals"]
    assert d["nav"] == 300000.0, "NAV must be the 300k mandate"
    assert abs(d["limits"]["theme_abs"] - 0.02 * NAV) < 1e-9, "theme budget must be 2% of NAV"
    assert abs(d["limits"]["portfolio_abs"] - 0.06 * NAV) < 1e-9, "portfolio budget must be 6% of NAV"
    assert d["positions"], "no positions"
    assert abs(t["gross"] - sum(p["mv"] for p in d["positions"])) < 0.01, "gross != sum of mv"
    assert abs(t["stop_total"] - sum(p["stop_risk"] for p in d["positions"])) < 0.01, \
        "stop_total != sum of stop_risk"
    assert abs(sum(p["pct_book"] for p in d["positions"]) - 1.0) < 1e-9, "pct_book must sum to 1"
    assert abs(t["theme_used"] - t["theme_binding_abs"] / d["limits"]["theme_abs"]) < 1e-9, \
        "theme_used inconsistent"
    assert t["theme_binding_abs"] <= t["stop_total"] + 0.01, \
        "binding theme cannot exceed the whole book"
    _theme_stop = {}
    for p in d["positions"]:
        _theme_stop[p["theme"]] = _theme_stop.get(p["theme"], 0.0) + p["stop_risk"]
    assert abs(t["theme_binding_abs"] - max(_theme_stop.values())) < 0.01, \
        "theme_binding_abs is not the worst theme"
    assert t["var99"] > t["var95"] > 0, "VaR ordering broken"
    assert t["var99"] <= t["stop_total"] * 50, "VaR implausibly large vs stop risk"
    for p in d["positions"]:
        assert p["px"] > 0 and p["qty"] != 0, "bad price/qty for " + p["sym"]
        assert p["stop"] < p["px"], "stop above mark for " + p["sym"]
        assert 0 <= p["p5"] <= p["p21"] <= p["p63"] <= 1, "touch probs not monotonic for " + p["sym"]
        assert abs(p["stop_risk"] - p["qty"] * (p["px"] - p["stop"])) < 0.01, \
            "stop_risk inconsistent for " + p["sym"]
    for r in d["limit_rows"]:
        if r["cur"] > r["budget"]:
            print("  BREACH %s: $%.0f of $%.0f" % (r["name"], r["cur"], r["budget"]))

    print("OK  wrote %s  (%d bytes)" % (OUT, os.path.getsize(OUT)))
    print("  marks %s | Flex pulled %s | vol window %s"
          % (d["mark_date"], d["export_pulled"], d["vol_window"]))
    for p in d["positions"]:
        print("  %-5s %8.0f @ %8.2f  stop %7.2f  risk $%7.2f  p21 %4.1f%%"
              % (p["sym"], p["qty"], p["px"], p["stop"], p["stop_risk"], 100 * p["p21"]))
    print("  gross $%.2f | stop risk $%.2f | VaR95 $%.2f VaR99 $%.2f | corr %s"
          % (t["gross"], t["stop_total"], t["var95"], t["var99"],
             ("%.3f" % t["correlation"]) if t["correlation"] is not None else "n/a"))
    print("  binding theme %s: $%.0f = %.1f%% of $%.0f | portfolio used %.1f%% of $%.0f"
          % (t["theme_binding"], t["theme_binding_abs"], 100 * t["theme_used"],
             d["limits"]["theme_abs"],
             100 * t["portfolio_used"], d["limits"]["portfolio_abs"]))
    if d["judgment_stale"]:
        print("  JUDGMENT STALE: prices moved %.1f%% since %s - scenarios need re-deriving"
              % (100 * worst, d["judgment_reviewed_on"]))


if __name__ == "__main__":
    main()
