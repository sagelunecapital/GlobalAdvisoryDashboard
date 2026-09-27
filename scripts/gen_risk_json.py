# Generates prototypes/risk.json for the dashboard Risk tab.
#
# All figures measured against a fixed $300,000 notional NAV - never account equity.
#
# Inputs:
#   data/ibkr_live.json   - book + working stops from an in-session IBKR MCP read
#                           (scripts/ibkr_mcp_import.py); used while it is the fresher one
#   data/ibkr_flex.json   - the unattended book of record (scripts/ibkr_flex_fetch.py)
#   data/risk_manual.json - human judgment: fallback stops, themes, scenarios, news, notes
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
#   var_share  Euler contribution  sig_i * sum_j rho_ij sig_j / sigma_p^2  (sums to 1)
import json, io, os, sys, math, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FLEX = os.path.join(ROOT, "data", "ibkr_flex.json")
LIVE = os.path.join(ROOT, "data", "ibkr_live.json")
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


def fetched_at(snap, path):
    try:
        return datetime.datetime.strptime(snap["fetched_at"], "%Y-%m-%dT%H:%M:%SZ") \
                                .replace(tzinfo=datetime.timezone.utc)
    except (KeyError, ValueError):
        fail("%s has no usable fetched_at stamp" % path)


def tranches(h, snap_stops, is_live):
    """Stop tranches for one holding, nearest (highest) first. A live broker read is
    the only source while it is the book - a stop missing from it was cancelled, not
    forgotten, so it is never back-filled from the judgment file. Otherwise the
    judgment file supplies either `stops` or a single `stop`."""
    if is_live:
        return sorted([{"qty": float(t["qty"]), "stop": float(t["stop"])}
                       for t in (snap_stops or [])], key=lambda t: -t["stop"])
    if h.get("stops"):
        tr = [{"qty": float(t["qty"]), "stop": float(t["stop"])} for t in h["stops"]]
    else:
        tr = [{"qty": None, "stop": float(h["stop"])}]
    return sorted(tr, key=lambda t: -t["stop"])


def main():
    man = load(MANUAL, "judgment inputs")

    # ---- book of record: the snapshot covering the LATEST session, still fresh ----
    # ibkr_live.json comes from an in-session IBKR MCP read (scripts/ibkr_mcp_import.py):
    # same-day book plus working stops. ibkr_flex.json comes from the unattended Flex
    # fetch, which lags about a business day. Ranking on report_date (not fetch time)
    # keeps a later Flex fetch of an OLDER statement - e.g. the one update_and_deploy.ps1
    # runs right before this script - from overriding a session read. A tie goes to
    # the live read, which also carries the stops. Neither may be over FLEX_MAX_AGE_H.
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    cands = []
    for path in (LIVE, FLEX):
        if os.path.exists(path):
            snap = load(path, "IBKR book")
            t = fetched_at(snap, path)
            age_h = (now_utc - t).total_seconds() / 3600.0
            if age_h < -0.1:
                fail("%s fetched_at %s is in the future - it must be UTC"
                     % (path, snap["fetched_at"]))
            cands.append({"t": t, "age_h": age_h, "path": path, "snap": snap,
                          "live": path == LIVE, "rd": snap.get("report_date") or ""})
    if not cands:
        fail("no IBKR book: run scripts/ibkr_flex_fetch.py (or ibkr_mcp_import.py in-session)")
    fresh = [c for c in cands if c["age_h"] <= FLEX_MAX_AGE_H]
    if not fresh:
        fail("IBKR snapshot is %.1fh old (limit %dh). Re-run scripts/ibkr_flex_fetch.py; "
             "refusing to publish a stale book."
             % (min(c["age_h"] for c in cands), FLEX_MAX_AGE_H))
    book = max(fresh, key=lambda c: (c["rd"], c["live"]))
    fetched, book_path, flex, is_live = book["t"], book["path"], book["snap"], book["live"]
    snap_stops = flex.get("stops", {}) if is_live else {}
    print("  book: %s (%s, report %s, fetched %s)" % (os.path.basename(book_path),
          flex.get("source"), book["rd"], flex["fetched_at"]))
    for c in fresh:
        if c is not book:
            print("  passed over: %s (report %s)" % (os.path.basename(c["path"]), c["rd"]))

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

    # ---- freshest mark wins -------------------------------------------------
    # Marks normally come from the last yfinance close. When the broker statement
    # covers a LATER session than yfinance has published, the statement mark is
    # the fresher truth and is used instead. The comparison is on date, never on
    # source preference: pinning marks to Flex would have hidden the XOP stop-out,
    # where yfinance was a session ahead of a stale statement. Vol, ATR and VaR
    # always stay on the yfinance bar series.
    bar_date = bars[syms[0]].index[-1].date()
    flex_date = None
    try:
        flex_date = datetime.datetime.strptime(flex["report_date"], "%Y-%m-%d").date()
    except (KeyError, ValueError, TypeError):
        pass
    # A live MCP book never supplies marks: its market_price includes extended hours.
    use_flex_marks = (not is_live) and flex_date is not None and flex_date > bar_date
    mark_date = (flex_date if use_flex_marks else bar_date).strftime("%Y-%m-%d")
    mark_source = ("%s statement %s (yfinance closes lag at %s)"
                   % (flex.get("source", "broker"), mark_date, bar_date.strftime("%Y-%m-%d"))
                   ) if use_flex_marks else ("yfinance close %s" % mark_date)
    if use_flex_marks:
        print("  marks: using %s marks - newer than the last yfinance close %s"
              % (flex_date.strftime("%Y-%m-%d"), bar_date.strftime("%Y-%m-%d")))

    # ---- per-position ----
    pos = []
    for s in syms:
        h = holdings[s]
        lv = live[s]
        df = bars[s]
        close = df["Close"].astype(float)
        px = float(close.iloc[-1])
        prev = float(close.iloc[-2])
        if use_flex_marks and lv.get("mark_flex"):
            # statement covers a later session: its mark is today's, and the last
            # yfinance close becomes the prior mark the daily move is measured from
            px, prev = float(lv["mark_flex"]), float(close.iloc[-1])
        qty = float(lv["qty"])
        avg = float(lv["avg"])
        trs = tranches(h, snap_stops.get(s), is_live)
        if not trs:
            fail("%s: the IBKR read shows no working stop. A cancelled stop must not be "
                 "published from risk_manual.json - re-place it in TWS and re-read, or "
                 "re-read the book." % s)
        if trs[0]["qty"] is None:
            # A single judgment-file stop covers the lot - but only the lot it was
            # recorded against. A resized position needs its stops re-read.
            if h.get("qty") is not None and abs(float(h["qty"]) - qty) > 1e-9:
                fail("%s: risk_manual.json records its stop against %.0f shares; IBKR "
                     "now holds %.0f. Re-read the stops before publishing."
                     % (s, float(h["qty"]), qty))
            trs[0]["qty"] = qty
        covered = sum(t["qty"] for t in trs)
        if abs(covered - qty) > 1e-9:
            fail("%s: stops cover %.0f of %.0f shares. Every share needs a stop on the "
                 "board - fix the order in TWS or the stops in risk_manual.json."
                 % (s, covered, qty))
        stop = trs[0]["stop"]                    # nearest tranche: the first to fire
        stop_src = ("IBKR working orders, read %s" % flex["fetched_at"][:10]) if is_live \
            else "risk_manual.json"
        # Checked BEFORE anything is written: a tranche at or through the mark means
        # the book or the stops are stale, and its negative risk would shrink stop_total.
        if trs[0]["stop"] >= px:
            fail("%s stop %.2f is at or above the mark %.2f - the book or the stops "
                 "are stale (stopped out?). Re-read before publishing." % (s, stop, px))

        vol_d = float(rets[s].std(ddof=1))
        # Wilder ATR on true range
        high = df["High"].astype(float)
        low = df["Low"].astype(float)
        pc = close.shift(1)
        tr = pd.concat([high - low, (high - pc).abs(), (low - pc).abs()], axis=1).max(axis=1)
        atr = float(tr.dropna().ewm(alpha=1.0 / ATR_N, adjust=False).mean().iloc[-1])

        mv = qty * px
        stop_risk = sum(t["qty"] * (px - t["stop"]) for t in trs)
        stop_eff = px - stop_risk / qty          # share-weighted stop across tranches
        p = {
            "sym": s,
            "name": h["name"],
            "theme": h["theme"],
            "sub": h["sub"],
            "qty": qty,
            "px": px,
            "avg": avg,
            "stop": stop,
            "stops": trs,
            "stop_eff": stop_eff,
            "stop_source": stop_src,
            "stop_confirmed_on": flex["fetched_at"][:10] if is_live
                                 else h.get("stop_confirmed_on"),
            "daily": qty * (px - prev),
            "unreal": qty * (px - avg),
            "vol_d": vol_d,
            "vol_a": vol_d * math.sqrt(252.0),
            "atr": atr,
            "mv": mv,
            "pct_nav": mv / NAV,
            "stop_dist": (px - stop) / px,
            "stop_risk": stop_risk,
            "stop_vs_cost": sum(t["qty"] * (t["stop"] - avg) for t in trs),
            "atr_mult": (px - stop) / atr if atr > 0 else None,
        }
        for n, key in zip(HORIZONS, ("p5", "p21", "p63")):
            p[key] = touch_prob(px, stop, vol_d, n)
        p["theme_used"] = p["stop_risk"] / THEME
        p["max_shares_theme"] = THEME / (px - stop_eff) if px > stop_eff else None
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
    rho = lambda a, b: 1.0 if a == b else float(rets[a].corr(rets[b]))
    for p in pos:
        s = p["sym"]
        # Euler contribution: sig_i * sum_j rho_ij sig_j / sigma_p^2. Sums to 1 across
        # the book, so the column reconciles with its 100% total. The standalone
        # sig_i^2 / sigma_p^2 is kept for reference; it ignores covariance.
        p["var_share"] = (sig[s] * sum(rho(s, b) * sig[b] for b in syms) / sigma_p ** 2
                          if sigma_p > 0 else None)
        p["var_standalone"] = (sig[s] ** 2) / (sigma_p ** 2) if sigma_p > 0 else None
    # Undiversified VaR (every correlation = 1): the gap to var99 is the whole
    # diversification benefit the parametric figure is taking credit for.
    var99_rho1 = Z99 * sum(sig.values())
    # VaR taking no credit for negative correlations (floored at zero), since a
    # 60-bar negative estimate is no dependable hedge.
    var99_noneg = Z99 * math.sqrt(max(0.0, sum(
        max(0.0, rho(a, b)) * sig[a] * sig[b] for a in syms for b in syms)))

    # Historical check on the parametric figures: today's holdings replayed over the
    # same window. Computed, not authored, so the tail note can never go stale.
    rdf = pd.DataFrame({s: rets[s] for s in syms}).dropna()
    pnl = sum(rdf[s] * next(p["mv"] for p in pos if p["sym"] == s) for s in syms)
    hist = {
        "n": int(len(pnl)),
        "var95": float(-pnl.quantile(0.05)),
        "var99": float(-pnl.quantile(0.01)),
        "worst": float(-pnl.min()),
        "worst_date": pnl.idxmin().strftime("%Y-%m-%d"),
    }
    pair_corr = [{"a": a, "b": b, "rho": float(rdf[a].corr(rdf[b]))}
                 for i, a in enumerate(syms) for b in syms[i + 1:]]
    # The single largest daily move per name in the window. One earnings day can
    # dominate a 60-bar vol, beta and VaR estimate, and its exit from the window
    # moves every one of them - so say which day, and when it rolls off.
    last_bar = rdf.index[-1]
    outliers = []
    for s in syms:
        r = rdf[s]
        d = r.abs().idxmax()
        k = list(rdf.index).index(d)             # bars since the window opened
        rolls = (last_bar + pd.offsets.BDay(k + 1)).strftime("%Y-%m-%d")
        outliers.append({"sym": s, "date": d.strftime("%Y-%m-%d"), "ret": float(r[d]),
                         "vol_ex": float(r.drop(d).std(ddof=1)), "vol": float(r.std(ddof=1)),
                         "rolls_off": rolls})

    stop_total = sum(p["stop_risk"] for p in pos)
    # Gap cases: each a named loss with the stop giving nothing. They are alternative
    # events, not additive - the portfolio meter shows the worst one, and each loads
    # the theme of the name it hits. `gap` (single, UNG) is the pre-27 Sep form.
    gaps = man.get("gaps") or [dict(man["gap"], name="gas gap", sym="UNG")]
    theme_of = {p["sym"]: p["theme"] for p in pos}
    for g in gaps:
        if g["sym"] not in theme_of:
            fail("gap case '%s' names %s, which is not held" % (g["name"], g["sym"]))
        g["theme"] = theme_of[g["sym"]]
        g["total"] = float(g["total"])
    worst_gap = max(gaps, key=lambda g: g["total"])
    gap_total = worst_gap["total"]

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
    # Price drift alone cannot see the book changing under the judgment: a new name
    # has no price_basis entry, a closed one leaves nothing to drift, and a resized
    # position moves no price at all. basis_book records the book the scenarios were
    # authored against; any difference from the live book marks them stale too.
    basis_book = {k: float(v) for k, v in man.get("basis_book", {}).items()}
    live_book = {p["sym"]: p["qty"] for p in pos}
    book_changes = []
    for s in sorted(set(basis_book) | set(live_book)):
        a, b = basis_book.get(s), live_book.get(s)
        if a is None:
            book_changes.append("%s %.0f opened" % (s, b))
        elif b is None:
            book_changes.append("%s %.0f closed" % (s, a))
        elif abs(a - b) > 1e-9:
            book_changes.append("%s %.0f -> %.0f" % (s, a, b))
    if not basis_book:
        book_changes.append("no basis_book recorded")
    stale = stale or bool(book_changes)

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
        if use_flex_marks and lv.get("mark_flex"):
            px = float(lv["mark_flex"])
        excluded = {"sym": s, "qty": float(lv["qty"]), "px": px,
                    "mv": float(lv["qty"]) * px,
                    "unreal": float(lv["qty"]) * (px - float(lv["avg"])),
                    "reason": cfg["reason"]}

    themes = sorted({p["theme"] for p in pos})

    # Stop risk per theme, and the binding theme - the one nearest its own cap.
    theme_stop = {th: sum(p["stop_risk"] for p in pos if p["theme"] == th) for th in themes}
    binding_theme = max(theme_stop, key=lambda th: theme_stop[th]) if theme_stop else None
    binding_abs = theme_stop.get(binding_theme, 0.0)
    # The worst gap case inside the binding theme, if it has one.
    bind_gaps = [g["total"] for g in gaps if g["theme"] == binding_theme]
    bind_gap = max(bind_gaps) if bind_gaps else None

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
    # Data-driven notes, appended so they always describe today's book.
    ratio = hist["worst"] / var99 if var99 > 0 else None
    if hist["var95"] > var95:
        tail = ("Parametric VaR understates the tail on this window: the historical 5th "
                "percentile loss is $%s against a parametric 95%% figure of $%s"
                % (format(round(hist["var95"]), ","), format(round(var95), ",")))
    else:
        tail = ("Parametric VaR sits above this window's history: the historical 5th "
                "percentile loss is $%s against a parametric 95%% figure of $%s, because "
                "the volatility estimate includes large up-days. That is a sample "
                "property, not safety - %d days is a short tail sample"
                % (format(round(hist["var95"]), ","), format(round(var95), ","), hist["n"]))
    notes.append("%s. The worst day for today's holdings in the window was $%s on %s, "
                 "%.2fx the 99%% VaR." % (tail, format(round(hist["worst"]), ","),
                                          hist["worst_date"], ratio))
    # Name the single days that drive the vol estimates, and when they roll off.
    big = [o for o in outliers if o["vol"] > 0 and o["vol_ex"] / o["vol"] < 0.85]
    if big:
        notes.append("One day drives the 60-bar statistics for %s: %s. Vol, beta, VaR and "
                     "touch odds all fall when %s leaves the window - a lower reading then "
                     "is the window rolling, not risk falling, and it can land just before "
                     "the next report."
                     % (", ".join(o["sym"] for o in big),
                        "; ".join("%s %+.1f%% on %s (daily vol %.2f%%, %.2f%% without it; "
                                  "rolls off about %s)" % (o["sym"], 100 * o["ret"], o["date"],
                                  100 * o["vol"], 100 * o["vol_ex"], o["rolls_off"]) for o in big),
                        "it" if len(big) == 1 else "each"))
    if pair_corr:
        se = 1.0 / math.sqrt(max(1, hist["n"] - 3))
        neg = [c for c in pair_corr if c["rho"] < 0]
        notes.append("Pairwise correlations over the window: %s. With %d observations "
                     "each carries a standard error near %.2f, so treat any value inside "
                     "about +/-%.2f as indistinguishable from zero, and a negative one as "
                     "no dependable hedge.%s"
                     % ("; ".join("%s-%s %+.2f" % (c["a"], c["b"], c["rho"]) for c in pair_corr),
                        hist["n"], se, 2 * se,
                        (" Taking no credit for the negative ones lifts 99%% VaR from $%s to $%s."
                         % (format(round(var99), ","), format(round(var99_noneg), ",")))
                        if neg else ""))
    # Both causes can hold at once; say each. Inserted in reverse so the book note leads.
    if worst > tol:
        notes.insert(0, "Scenario, slippage and gap figures were authored on %s at "
                        "%s and prices have since moved %.1f%%. Treat those rows as "
                        "indicative until they are re-derived; the positions, stops, "
                        "vol, VaR and budget meters above are live."
                     % (man["reviewed_on"],
                        ", ".join("%s $%.2f" % (s, v) for s, v in sorted(basis.items())),
                        100 * worst))
    if book_changes:
        notes.insert(0, "Scenario, slippage and gap figures were authored on %s against a "
                        "different book (%s). Treat those rows as indicative until they "
                        "are re-derived; the positions, stops, vol, VaR and budget meters "
                        "above are live." % (man["reviewed_on"], "; ".join(book_changes)))

    now = datetime.datetime.now(datetime.timezone.utc)
    doc = {
        "updated": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "export_pulled": fetched.strftime("%d %b %Y"),
        # Say what the book actually came from - the tab prints this verbatim.
        "source": "%s + marks from %s" % (flex.get("source", "unknown source"), mark_source),
        "vol_window": vol_window,
        "mark_date": mark_date,
        "mark_source": mark_source,
        "flex_report_date": flex.get("report_date"),
        "nav": NAV,
        "unit": 0.01 * NAV,
        "judgment_reviewed_on": man["reviewed_on"],
        "judgment_stale": stale,
        "judgment_drift": drift,
        "judgment_book_changes": book_changes,
        "limits": {
            "theme_pct": man["limits"]["theme_pct"], "theme_abs": THEME,
            "portfolio_pct": man["limits"]["portfolio_pct"], "portfolio_abs": PORT,
            "basis": man["limits"]["basis"],
            "provisional": man["limits"]["provisional"],
            "set_on": man["limits"]["set_on"],
        },
        "positions": pos,
        "totals": {
            "gross": gross, "gross_pct": gross / NAV,
            "net_pct": sum(p["mv"] if p["qty"] > 0 else -p["mv"] for p in pos) / NAV,
            "daily": sum(p["daily"] for p in pos),
            "unreal": sum(p["unreal"] for p in pos),
            "stop_total": stop_total, "stop_pct": stop_total / NAV,
            "gap_total": gap_total, "gap_pct": gap_total / NAV,
            "gap_name": worst_gap["name"], "gaps": gaps,
            "var95": var95, "var99": var99, "correlation": corr,
            "var99_rho1": var99_rho1, "var99_noneg": var99_noneg, "hist_var": hist,
            "pair_corr": pair_corr, "outliers": outliers,
            "long_only": all(p["qty"] > 0 for p in pos),
            # The theme meter tracks the BINDING theme - the one closest to its own
            # 2% cap. Measuring the whole book against a single theme budget only
            # made sense while the book was effectively one theme.
            "theme_binding": binding_theme,
            "theme_binding_abs": binding_abs,
            "theme_used": binding_abs / THEME, "portfolio_used": stop_total / PORT,
            # A gap case loads only the theme of the name it hits; the theme meter
            # shows the worst one inside the binding theme, if there is one.
            "theme_gap_applies": bind_gap is not None,
            "theme_gap_abs": bind_gap,
            "theme_used_gap": (bind_gap / THEME) if bind_gap is not None else None,
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
            [{"name": "Portfolio - all stops fill cleanly", "budget": PORT, "cur": stop_total}]
            + [{"name": "Portfolio - %s, no stop protection" % g["name"], "budget": PORT,
                "cur": g["total"]} for g in gaps]
            + [{"name": "Portfolio - VaR 99%, correlation-adjusted", "budget": PORT, "cur": var99}]
            + [{"name": "%s theme - all stops fill cleanly" % t, "budget": THEME,
                "cur": sum(p["stop_risk"] for p in pos if p["theme"] == t)} for t in themes]
            # Each gap case belongs to the theme of the name it hits.
            # VaR is book-wide and is measured against the portfolio cap, not a
            # theme cap - comparing it to 2% of NAV manufactured a false breach.
            + [{"name": "%s theme - %s, no stop protection" % (g["theme"], g["name"]),
                "budget": THEME, "cur": g["total"]} for g in gaps]
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
    assert abs(sum(p["var_share"] for p in d["positions"]) - 1.0) < 1e-9, \
        "Euler variance contributions must sum to 1"
    assert t["gap_total"] == max(g["total"] for g in t["gaps"]), "gap_total is not the worst gap"
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
    assert t["var99_rho1"] >= t["var99"] - 0.01, "undiversified VaR below diversified VaR"
    # marks may only ever move forward: never price a book off a stale statement
    assert d["mark_date"] >= bar_date.strftime("%Y-%m-%d"), \
        "mark_date %s is older than the yfinance bars %s" % (d["mark_date"], bar_date)
    assert t["var99"] <= t["stop_total"] * 50, "VaR implausibly large vs stop risk"
    for p in d["positions"]:
        assert p["px"] > 0 and p["qty"] != 0, "bad price/qty for " + p["sym"]
        assert p["stop"] < p["px"], "stop above mark for " + p["sym"]
        assert 0 <= p["p5"] <= p["p21"] <= p["p63"] <= 1, "touch probs not monotonic for " + p["sym"]
        assert abs(p["stop_risk"] - sum(t["qty"] * (p["px"] - t["stop"])
                                        for t in p["stops"])) < 0.01, \
            "stop_risk inconsistent for " + p["sym"]
        assert abs(sum(t["qty"] for t in p["stops"]) - p["qty"]) < 1e-9, \
            "stop tranches do not cover the position for " + p["sym"]
        assert p["stop"] == max(t["stop"] for t in p["stops"]), \
            "stop must be the nearest tranche for " + p["sym"]
        assert all(t["stop"] < p["px"] for t in p["stops"]), "tranche above mark for " + p["sym"]
    for r in d["limit_rows"]:
        if r["cur"] > r["budget"]:
            print("  BREACH %s: $%.0f of $%.0f" % (r["name"], r["cur"], r["budget"]))

    print("OK  wrote %s  (%d bytes)" % (OUT, os.path.getsize(OUT)))
    print("  marks %s | Flex pulled %s | vol window %s"
          % (d["mark_date"], d["export_pulled"], d["vol_window"]))
    for p in d["positions"]:
        print("  %-5s %8.0f @ %8.2f  stop %-17s risk $%8.2f  p21 %4.1f%%  [%s]"
              % (p["sym"], p["qty"], p["px"],
                 " / ".join("%.2f" % t["stop"] for t in p["stops"]),
                 p["stop_risk"], 100 * p["p21"], p["stop_source"]))
    print("  gross $%.2f | stop risk $%.2f | VaR95 $%.2f VaR99 $%.2f | corr %s"
          % (t["gross"], t["stop_total"], t["var95"], t["var99"],
             ("%.3f" % t["correlation"]) if t["correlation"] is not None else "n/a"))
    print("  binding theme %s: $%.0f = %.1f%% of $%.0f | portfolio used %.1f%% of $%.0f"
          % (t["theme_binding"], t["theme_binding_abs"], 100 * t["theme_used"],
             d["limits"]["theme_abs"],
             100 * t["portfolio_used"], d["limits"]["portfolio_abs"]))
    if d["judgment_stale"]:
        print("  JUDGMENT STALE: prices moved %.1f%% since %s%s - scenarios need re-deriving"
              % (100 * worst, d["judgment_reviewed_on"],
                 ("; book changed: " + "; ".join(book_changes)) if book_changes else ""))


if __name__ == "__main__":
    main()
