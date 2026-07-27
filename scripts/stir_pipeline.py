#!/usr/bin/env python3
"""STIR pipeline - Build a CME-FedWatch-style Fed Funds dashboard.

Implements the methodology from the Capital Flows Research STIR
Replication Playbook (Cfr_Stir_Replication_Playbook.pdf in this repo).

Outputs prototypes/stir.json for the Global Advisory Dashboard's
"US STIR" tab. Run with --plot to also pop up the four Plotly charts
described in the playbook.

Data sources
  EFFR / SOFR : New York Fed JSON API (markets.newyorkfed.org)
  ZQ futures  : Yahoo Finance (e.g. ZQM26.CBT)        - 30-day Fed Funds
  SR3 futures : Yahoo Finance (e.g. SR3M26.CME)       - 3-month SOFR
  FOMC dates  : hard-coded list (refresh annually from federalreserve.gov)
"""

# A1 - imports, palette, schemas
from __future__ import annotations
import json
import warnings
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import yfinance as yf

warnings.filterwarnings("ignore")

CFR = {
    "bg":     "#000000", "panel":     "#080808", "rule":      "#3D2510",
    "orange": "#FE7C04", "orangeHot": "#FF9533", "orangeDim": "#5A2C00",
    "text":   "#D0D0D0", "green":     "#00E676", "red":       "#FF1744",
}

_CME_MONTH_CODES = {1: "F", 2: "G", 3: "H", 4: "J", 5: "K", 6: "M",
                    7: "N", 8: "Q", 9: "U", 10: "V", 11: "X", 12: "Z"}
_CME_MONTH_TO_NUM = {v: k for k, v in _CME_MONTH_CODES.items()}


def _cme_symbol(root: str, expiry: date) -> str:
    return f"{root}{_CME_MONTH_CODES[expiry.month]}{expiry.year % 10}"


@dataclass
class Contract:
    symbol: str
    root:   str
    expiry: date
    settle: float


def to_strip(contracts: list[Contract]) -> pd.DataFrame:
    return pd.DataFrame([c.__dict__ for c in contracts])


ROOT           = Path(__file__).resolve().parent.parent
JSON_OUT       = ROOT / "prototypes" / "stir.json"
BARCHART_CACHE = Path(__file__).resolve().parent / "barchart_zq_cache.json"

# The ZQ cache is only usable if its as_of_date is within this many calendar days
# of today - enough to cover a weekend plus one holiday. Beyond that the strip is
# stale and must not be published as if it were current.
BARCHART_MAX_AGE_DAYS = 4

# Provenance of the ZQ strip for this run, surfaced into stir.json so the UI can
# show the strip's true vintage rather than implying it is live.
ZQ_PROVENANCE: dict = {
    "source":   None,   # barchart | yfinance | unavailable
    "as_of":    None,
    "age_days": None,
    "stale":    False,
    "note":     None,
}


# A2 - Loaders (real implementations, replacing the playbook's make_mock_*)

# Hand-maintained FOMC schedule. Refresh annually from federalreserve.gov.
FOMC_SCHEDULE: list[date] = [
    date(2026, 6, 17),  date(2026, 7, 29),  date(2026, 9, 16),
    date(2026, 10, 28), date(2026, 12, 9),
    date(2027, 1, 27),  date(2027, 3, 17),  date(2027, 4, 28),
    date(2027, 6, 16),  date(2027, 7, 28),  date(2027, 9, 15),
    date(2027, 10, 27), date(2027, 12, 8),
]

NY_FED_URL = ("https://markets.newyorkfed.org/api/rates/"
              "{kind}/{name}/last/{n}.json")


def load_ref_rates(days: int = 90) -> pd.DataFrame:
    """EFFR + SOFR daily series from the NY Fed public JSON API."""
    cols: dict[str, pd.Series] = {}
    for kind, name in [("unsecured", "effr"), ("secured", "sofr")]:
        r = requests.get(
            NY_FED_URL.format(kind=kind, name=name, n=days), timeout=30
        )
        r.raise_for_status()
        rows = r.json().get("refRates", [])
        cols[name] = pd.Series({
            pd.to_datetime(row["effectiveDate"]).date(): float(row["percentRate"])
            for row in rows
        }).sort_index()
    df = pd.DataFrame(cols).dropna(how="all")
    df.index = pd.DatetimeIndex(df.index)
    return df


def load_fomc_dates(today: date) -> list[date]:
    return [d for d in FOMC_SCHEDULE if d >= today]


def _expiry_for_month(y: int, m: int) -> date:
    return date(y, m, monthrange(y, m)[1])


def _fetch_history(symbol: str) -> dict | None:
    """Return {settle, px_1d, px_5d, px_1m, volume, oi, oi_chg} for a contract.

    OI is fetched best-effort from Ticker.info; many CME futures don't expose
    it on Yahoo Finance, in which case it stays None. PX deltas are change
    in price (not implied rate) over the trailing 1/5/21 trading sessions.
    """
    try:
        tk = yf.Ticker(symbol)
        h  = tk.history(period="35d")
        if h.empty:
            return None
        closes = h["Close"]
        settle = float(closes.iloc[-1])
        def _back(n: int) -> float | None:
            if len(closes) <= n:
                return None
            return round(settle - float(closes.iloc[-1 - n]), 4)
        vol = h["Volume"].iloc[-1] if "Volume" in h.columns else None
        oi = None
        try:
            info = tk.info or {}
            oi = info.get("openInterest")
        except Exception:
            oi = None
        return {
            "settle":  round(settle, 4),
            "px_1d":   _back(1),
            "px_5d":   _back(5),
            "px_1m":   _back(21),
            "volume":  int(vol) if vol is not None and not pd.isna(vol) else None,
            "oi":      int(oi) if oi else None,
            "oi_chg":  None,   # not available from yfinance free feed
        }
    except Exception:
        return None


def _load_barchart_zq(today: date) -> list[dict]:
    """Load ZQ contracts from the barchart_fetch.py cache.

    Returns [] if the cache is missing, unparseable, or STALE - callers must
    treat [] as "fall back to yfinance".

    The stale case is the dangerous one and the reason for the age check: a stale
    cache parses perfectly and silently republishes weeks-old settles as current,
    which also pins oi_chg at exactly 0 forever because consecutive snapshots are
    byte-identical. That failure mode went unnoticed for two weeks.
    """
    if not BARCHART_CACHE.exists():
        print("    [ZQ] Barchart cache absent.", flush=True)
        ZQ_PROVENANCE.update(note="barchart cache absent")
        return []
    try:
        data = json.loads(BARCHART_CACHE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[stir] Barchart cache load failed: {e}", flush=True)
        ZQ_PROVENANCE.update(note=f"barchart cache unreadable: {e}")
        return []

    as_of_raw = data.get("as_of_date")
    try:
        as_of = date.fromisoformat(as_of_raw)
    except (TypeError, ValueError):
        print(f"    [ZQ] Barchart cache has no usable as_of_date "
              f"({as_of_raw!r}) - treating as stale.", flush=True)
        ZQ_PROVENANCE.update(note=f"barchart cache bad as_of_date {as_of_raw!r}")
        return []

    age = (today - as_of).days
    if age > BARCHART_MAX_AGE_DAYS:
        print(f"    [ZQ] Barchart cache STALE: as_of {as_of} is {age}d old "
              f"(max {BARCHART_MAX_AGE_DAYS}d). Rejecting - "
              f"run scripts/barchart_fetch.py.", flush=True)
        ZQ_PROVENANCE.update(
            note=f"barchart cache rejected as stale (as_of {as_of}, {age}d old)")
        return []

    rows = []
    for c in data.get("contracts", []):
        sym_bc = c.get("symbol_bc", "")
        if len(sym_bc) < 5:
            continue
        mc   = sym_bc[2]
        yr2  = sym_bc[3:]
        if mc not in _CME_MONTH_TO_NUM or not yr2.isdigit():
            continue
        month_num = _CME_MONTH_TO_NUM[mc]
        year      = 2000 + int(yr2)
        exp       = _expiry_for_month(year, month_num)
        rows.append({
            "symbol":  _cme_symbol("ZQ", exp),
            "root":    "ZQ",
            "expiry":  exp,
            "settle":  c["settle"],
            "px_1d":   None,
            "px_5d":   None,
            "px_1m":   None,
            "volume":  c.get("volume"),
            "oi":      c.get("oi"),
            "oi_chg":  None,
        })
    if rows:
        ZQ_PROVENANCE.update(source="barchart", as_of=as_of.isoformat(),
                             age_days=age, stale=False, note=None)
        print(f"    [ZQ] Barchart cache OK: {len(rows)} contracts, "
              f"as_of {as_of} ({age}d old).", flush=True)
    else:
        ZQ_PROVENANCE.update(note="barchart cache parsed but held no contracts")
    return rows


def load_strip(today: date,
               zq_months: int = 36,
               sr3_quarters: int = 12) -> pd.DataFrame:
    """Settlement strip: ZQ (Fed Funds, monthly via Barchart cache) and SR3 (3M SOFR, quarterly via yfinance)."""
    rows: list[dict] = []

    # ZQ - prefer Barchart cache (60+ contracts to 2031); fall back to yfinance
    bc_rows = _load_barchart_zq(today)
    if bc_rows:
        rows.extend(bc_rows)
    else:
        print("    [ZQ] Falling back to yfinance (fresh settles, but this feed "
              "exposes little or no OI)...", flush=True)
        yf_rows = []
        for i in range(zq_months):
            m = ((today.month - 1 + i) % 12) + 1
            y = today.year + (today.month + i - 1) // 12
            exp = _expiry_for_month(y, m)
            sym = f"ZQ{_CME_MONTH_CODES[m]}{y % 100:02d}.CBT"
            d = _fetch_history(sym)
            if d is not None:
                yf_rows.append({"symbol": _cme_symbol("ZQ", exp), "root": "ZQ",
                                "expiry": exp, **d})
        rows.extend(yf_rows)
        prior_note = ZQ_PROVENANCE.get("note")
        if yf_rows:
            ZQ_PROVENANCE.update(
                source="yfinance", as_of=today.isoformat(), age_days=0,
                stale=False,
                note=f"{prior_note}; served from yfinance fallback"
                     if prior_note else "served from yfinance fallback")
            print(f"    [ZQ] yfinance fallback returned {len(yf_rows)} contracts.",
                  flush=True)
        else:
            ZQ_PROVENANCE.update(source="unavailable", stale=True)

    # SR3 - quarterly listings (Mar/Jun/Sep/Dec), ~2 years out
    cur_q = ((today.month - 1) // 3) * 3 + 3
    y, q = today.year, cur_q
    for _ in range(sr3_quarters):
        if q > 12:
            q -= 12
            y += 1
        exp = _expiry_for_month(y, q)
        sym = f"SR3{_CME_MONTH_CODES[q]}{y % 100:02d}.CME"
        d = _fetch_history(sym)
        if d is not None:
            rows.append({"symbol": _cme_symbol("SR3", exp), "root": "SR3",
                         "expiry": exp, **d})
        q += 3

    if not rows:
        # Every source failed. Return a typed-but-empty frame so callers hit the
        # explicit "no contracts loaded" guard instead of a bare KeyError from
        # sort_values on a column-less DataFrame.
        return pd.DataFrame(columns=["symbol", "root", "expiry", "settle",
                                     "px_1d", "px_5d", "px_1m",
                                     "volume", "oi", "oi_chg"])
    return (pd.DataFrame(rows)
            .sort_values(["root", "expiry"])
            .reset_index(drop=True))


# A3 - Implied rate, terminal, strip view
def implied_rate(settle: float) -> float:
    return 100.0 - settle


def add_implied(strip: pd.DataFrame, ocr: float) -> pd.DataFrame:
    out = strip.copy()
    out["implied_rate"] = 100.0 - out["settle"]
    out["vs_ocr_bp"]    = (out["implied_rate"] - ocr) * 100.0
    return out


def find_terminal(strip_view: pd.DataFrame, ocr: float) -> pd.Series:
    """First peak (hiking) or trough (cutting) on the strip relative to OCR."""
    active = strip_view[strip_view["settle"] > 0].reset_index(drop=True)
    if active.empty:
        return strip_view.iloc[0]
    front  = active.iloc[0]
    hiking = front["implied_rate"] >= ocr
    best   = front
    for _, row in active.iloc[1:].iterrows():
        if hiking and row["implied_rate"] >= best["implied_rate"]:
            best = row
        elif not hiking and row["implied_rate"] <= best["implied_rate"]:
            best = row
        else:
            break
    return best


def plot_strip(strip_view: pd.DataFrame, ocr: float, title: str) -> go.Figure:
    term = find_terminal(strip_view, ocr)
    colors = [CFR["orangeHot"] if s == term["symbol"] else CFR["orangeDim"]
              for s in strip_view["symbol"]]
    fig = go.Figure(go.Bar(
        x=strip_view["symbol"], y=strip_view["implied_rate"],
        marker_color=colors, marker_line_color="#9A4A02",
        hovertemplate="%{x}<br>%{y:.3f}%<extra></extra>",
    ))
    fig.add_hline(
        y=ocr, line_dash="dash", line_color=CFR["orange"],
        annotation_text="EFFECTIVE FFR", annotation_position="right",
        annotation_font=dict(color=CFR["orange"], family="Segoe UI"),
    )
    fig.update_layout(
        title=dict(text=title,
                   font=dict(color=CFR["orange"], family="Bahnschrift", size=20)),
        template="plotly_dark", paper_bgcolor=CFR["bg"], plot_bgcolor="#050505",
        font=dict(family="Segoe UI", color=CFR["text"]),
        yaxis_title="Implied rate (%)", xaxis_title=None,
        margin=dict(l=60, r=20, t=60, b=40), height=420,
    )
    return fig


# A4 - Meeting-path math, probabilities
def post_meeting_rate(contract_rate: float, prev_rate: float,
                      meeting_day: int, days_in_month: int) -> float:
    """Recover the rate priced for the period AFTER an FOMC meeting.

    monthly_avg = ((D-1)*prev + (N-D+1)*post) / N
    """
    days_after = days_in_month - meeting_day + 1
    if days_after <= 0:
        return contract_rate
    return (contract_rate * days_in_month
            - (meeting_day - 1) * prev_rate) / days_after


def build_meeting_path(zq_strip: pd.DataFrame, effr_today: float,
                       fomc_dates: list[date]) -> pd.DataFrame:
    zq_by_month = {(r["expiry"].year, r["expiry"].month): r["implied_rate"]
                   for _, r in zq_strip.iterrows()}
    fomc_keys = {(d.year, d.month) for d in fomc_dates}
    prev = effr_today
    rows: list[dict] = []
    for d in fomc_dates:
        rate = zq_by_month.get((d.year, d.month))
        if rate is None:
            continue
        N = monthrange(d.year, d.month)[1]
        ny, nm = (d.year + (d.month == 12), d.month % 12 + 1)
        next_rate = zq_by_month.get((ny, nm))
        next_has_meeting = (ny, nm) in fomc_keys
        if next_rate is not None and not next_has_meeting:
            post = next_rate                                 # next-month shortcut
        else:
            post = post_meeting_rate(rate, prev, d.day, N)
        # ZQ contract for this meeting's calendar month (e.g. ZQM6 for June 2026)
        contract = f"ZQ{_CME_MONTH_CODES[d.month]}{d.year % 10}"
        rows.append({"meeting":      d,
                     "contract":     contract,
                     "contract_rate": rate,
                     "post_rate":    post,
                     "cum_cuts":     (effr_today - post) / 0.25,
                     "cum_hikes":    (post - effr_today) / 0.25})
        prev = post
    return pd.DataFrame(rows)


def meeting_probs(post_rate: float, effr: float) -> dict[str, float]:
    """CME-FedWatch-style P(target rate) - interpolation between 25 bp levels."""
    raw = (effr - post_rate) / 0.25
    lower = int(np.floor(raw))
    frac  = raw - lower
    mass: dict[int, float] = {lower: 1 - frac}
    if frac > 0.001:
        mass[lower + 1] = frac
    return {"hold":   100 * mass.get(0,  0.0),
            "cut25":  100 * mass.get(1,  0.0),
            "cut50":  100 * mass.get(2,  0.0),
            "cut75":  100 * mass.get(3,  0.0),
            "hike25": 100 * mass.get(-1, 0.0),
            "hike50": 100 * mass.get(-2, 0.0)}


# A5 - Spread matrix, meeting-path plot, CB LVL overlay
def spread_matrix(strip_view: pd.DataFrame, ocr: float,
                  horizons_m: tuple[int, ...] = (3, 6, 9, 12)) -> pd.DataFrame:
    if strip_view.empty:
        return pd.DataFrame()
    rows: list[dict] = []
    for _, row in strip_view.iterrows():
        row_mo = row["expiry"].month + 12 * row["expiry"].year
        spreads: dict[str, float] = {}
        for h in horizons_m:
            target = row_mo + h
            forward = strip_view[strip_view["expiry"].apply(
                lambda d: d.month + 12 * d.year >= target)]
            spreads[f"+{h}M"] = (round((forward.iloc[0]["implied_rate"]
                                        - row["implied_rate"]) * 100)
                                  if not forward.empty else float("nan"))
        rows.append({"contract": row["symbol"], **spreads})
    return pd.DataFrame(rows).set_index("contract")


def plot_meeting_path(path: pd.DataFrame, effr: float) -> go.Figure:
    fig = go.Figure(go.Scatter(
        x=path["meeting"], y=path["post_rate"], mode="lines+markers",
        line=dict(color=CFR["orangeHot"], width=2.4, shape="hv"),
        marker=dict(color=CFR["bg"],
                    line=dict(color=CFR["orangeHot"], width=1.5), size=8),
    ))
    fig.add_hline(y=effr, line_dash="dash", line_color=CFR["orange"],
                  annotation_text="EFFECTIVE FFR", annotation_position="right",
                  annotation_font=dict(color=CFR["orange"]))
    fig.update_layout(template="plotly_dark", paper_bgcolor=CFR["bg"],
                      plot_bgcolor="#050505",
                      font=dict(family="Segoe UI", color=CFR["text"]),
                      margin=dict(l=60, r=40, t=60, b=40), height=420)
    return fig


def cb_levels(effr: float, band_bp: int = 100, step_bp: int = 25) -> list[float]:
    settle = round(effr / 0.25) * 0.25
    n = band_bp // step_bp
    return [settle + (i - n) * (step_bp / 100.0) for i in range(2 * n + 1)]


def plot_cb_lvl(path: pd.DataFrame, effr: float) -> go.Figure:
    fig    = plot_meeting_path(path, effr)
    settle = round(effr / 0.25) * 0.25
    for lv in cb_levels(effr, band_bp=150):
        is_settle = abs(lv - settle) < 0.01
        fig.add_hline(
            y=lv,
            line_color=CFR["orange"] if is_settle else CFR["orangeDim"],
            line_dash="solid" if is_settle else "dot",
            line_width=1.4 if is_settle else 0.6,
        )
    return fig


# Dashboard JSON export (consumed by prototypes/index.html, "Yields" tab)
def _kpis(s: pd.DataFrame, today: date, ocr: float, steps_6m: int, steps_12m: int) -> dict:
    """Terminal KPI block: highest implied rate in 18-month window,
    plus its spread vs EFFR and vs the +6M / +12M contracts (by contract count from terminal).
    """
    empty = {"terminal": None, "vs_effr_bp": None, "vs_6m_bp": None, "vs_12m_bp": None,
             "terminal_symbol": None, "h6_symbol": None, "h12_symbol": None,
             "h6_rate": None, "h12_rate": None}
    if s.empty:
        return empty

    # Limit search to 18-month window
    cutoff_key = today.year * 12 + today.month + 18
    s18 = s[s["expiry"].apply(lambda d: d.year * 12 + d.month) <= cutoff_key]
    if s18.empty:
        s18 = s

    # Terminal = highest implied rate in the 18M window
    term_pos = int(s18["implied_rate"].idxmax())  # label == iloc position (reset_index strip)
    term = s.loc[term_pos]
    term_rate = float(term["implied_rate"])

    def _at_steps(steps: int):
        pos = term_pos + steps
        if pos >= len(s):
            return None, None
        r = s.iloc[pos]
        return r["symbol"], float(r["implied_rate"])

    h6_sym,  h6_rate  = _at_steps(steps_6m)
    h12_sym, h12_rate = _at_steps(steps_12m)

    return {
        "terminal":        round(term_rate, 4),
        "terminal_symbol": term["symbol"],
        "vs_effr_bp":      round((term_rate - ocr) * 100, 1),
        "vs_6m_bp":        round((term_rate - h6_rate)  * 100, 1) if h6_rate  is not None else None,
        "vs_12m_bp":       round((term_rate - h12_rate) * 100, 1) if h12_rate is not None else None,
        "h6_symbol":       h6_sym,
        "h12_symbol":      h12_sym,
        "h6_rate":         round(h6_rate,  4) if h6_rate  is not None else None,
        "h12_rate":        round(h12_rate, 4) if h12_rate is not None else None,
    }


def build_dashboard_payload(strip: pd.DataFrame, ref_rates: pd.DataFrame,
                            fomc_dates: list[date], path_df: pd.DataFrame,
                            effr: float, sofr: float, today: date) -> dict:
    sofr_strip = strip[strip["root"] == "SR3"].reset_index(drop=True)
    ff_strip   = strip[strip["root"] == "ZQ"].reset_index(drop=True)

    ff_kpis   = _kpis(ff_strip,   today, effr, steps_6m=6,  steps_12m=12)
    sofr_kpis = _kpis(sofr_strip, today, effr, steps_6m=2,  steps_12m=4)

    def _rows(s: pd.DataFrame, term_sym: str | None) -> list[dict]:
        return [
            {"symbol":       r["symbol"],
             "expiry":       r["expiry"].isoformat(),
             "year":         r["expiry"].year,
             "settle":       round(float(r["settle"]), 4),
             "implied_rate": round(float(r["implied_rate"]), 4),
             "vs_ocr_bp":    round(float(r["vs_ocr_bp"]), 1),
             "px_1d":        None if r.get("px_1d") is None or pd.isna(r["px_1d"]) else round(float(r["px_1d"]), 4),
             "px_5d":        None if r.get("px_5d") is None or pd.isna(r["px_5d"]) else round(float(r["px_5d"]), 4),
             "px_1m":        None if r.get("px_1m") is None or pd.isna(r["px_1m"]) else round(float(r["px_1m"]), 4),
             "volume":       None if r.get("volume") is None or pd.isna(r["volume"]) else int(r["volume"]),
             "oi":           None if r.get("oi")     is None or pd.isna(r["oi"])     else int(r["oi"]),
             "oi_chg":       None if r.get("oi_chg") is None or pd.isna(r["oi_chg"]) else int(r["oi_chg"]),
             "is_terminal":  term_sym is not None and r["symbol"] == term_sym}
            for _, r in s.iterrows()
        ]

    def _spread_rows(view: pd.DataFrame) -> list[dict]:
        m = spread_matrix(view, effr)
        if m.empty:
            return []
        out = []
        for sym, row in m.iterrows():
            out.append({"contract": sym,
                        **{k: (None if pd.isna(v) else int(v)) for k, v in row.items()}})
        return out

    path_rows = []
    for _, r in path_df.iterrows():
        probs = meeting_probs(r["post_rate"], effr)
        path_rows.append({
            "meeting":       r["meeting"].isoformat(),
            "contract":      r["contract"],
            "contract_rate": round(float(r["contract_rate"]), 4),
            "post_rate":     round(float(r["post_rate"]), 4),
            "cum_cuts":      round(float(r["cum_cuts"]),  2),
            "cum_hikes":     round(float(r["cum_hikes"]), 2),
            "probs":         {k: round(v, 1) for k, v in probs.items()},
        })

    asof = (ref_rates.index[-1].date().isoformat()
            if len(ref_rates) else date.today().isoformat())

    return {
        "updated":      datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "asof_date":    asof,
        # Vintage of the ZQ strip specifically. asof_date above tracks the NY Fed
        # reference rates, which keep advancing even when the futures feed is dead.
        "zq_provenance": dict(ZQ_PROVENANCE),
        "effr":         round(effr, 4),
        "sofr":         round(sofr, 4),
        "basis_bp":     round((sofr - effr) * 100, 1),
        "kpis": {"ff": ff_kpis, "sofr": sofr_kpis},
        "sofr_strip":    _rows(sofr_strip, sofr_kpis.get("terminal_symbol")),
        "ff_strip":      _rows(ff_strip,   ff_kpis.get("terminal_symbol")),
        "fomc_dates":    [d.isoformat() for d in fomc_dates],
        "meeting_path":  path_rows,
        "spreads_ff":    _spread_rows(ff_strip),
        "spreads_sofr":  _spread_rows(sofr_strip),
        "cb_levels":     [round(lv, 2) for lv in cb_levels(effr, band_bp=150)],
        "cb_settle":     round(round(effr / 0.25) * 0.25, 2),
    }


# oi_chg is a session-over-session delta. If two snapshots are further apart than
# this, their difference is a multi-week accumulation, not a daily change, and
# publishing it as one would be worse than publishing nothing.
OI_CHG_MAX_GAP_DAYS = 4


def _oi_vintage(payload: dict, key: str) -> str | None:
    """Snapshot date governing the OI figures in `key`, or None if unknowable.

    ff_strip OI comes from the Barchart cache, which carries its own as_of that
    moves independently of asof_date (the NY Fed reference-rate date). Keying the
    ZQ delta off asof_date meant a freshly refreshed strip still reported a zero
    change whenever EFFR had not yet published for that session.

    For ff_strip this deliberately does NOT fall back to asof_date. A payload
    written before zq_provenance existed carries an asof_date that tracks EFFR and
    can be weeks newer than the ZQ figures sitting beside it - trusting it is what
    manufactured the permanent phantom oi_chg=0. An unknown vintage must read as
    unknown. sofr_strip OI is pulled from yfinance at request time, so it has no
    vintage of its own and legitimately follows asof_date.
    """
    if key == "ff_strip":
        return (payload.get("zq_provenance") or {}).get("as_of")
    return payload.get("asof_date")


def apply_oi_chg(payload: dict, prior_path: Path) -> None:
    """Derive per-contract open-interest change by diffing against the previously
    published stir.json. Neither data feed (yfinance free, Barchart) exposes an OI
    delta, so it is computed from consecutive daily snapshots, matched by symbol.

    The comparison is keyed on the vintage of the strip that owns the OI figures
    (see _oi_vintage), not on the payload-wide asof_date.

    Must be called BEFORE prior_path is overwritten.
      - new snapshot (prior vintage < current): oi_chg = oi_now - oi_prev
      - same snapshot (prior vintage == current): carry the prior delta forward,
        so a same-day redeploy does not blank the column
      - snapshots more than OI_CHG_MAX_GAP_DAYS apart: leave None. After a feed
        outage the two nearest snapshots are weeks apart and their difference is
        not a daily change.
      - no prior file / unknown vintage / prior vintage newer: leave None
    """
    try:
        prior = json.loads(prior_path.read_text(encoding="utf-8"))
    except Exception:
        return  # first run or unreadable prior: oi_chg stays None
    for key in ("sofr_strip", "ff_strip"):
        cur_v, prior_v = _oi_vintage(payload, key), _oi_vintage(prior, key)
        if not (cur_v and prior_v):
            print(f"    [oi_chg] {key}: vintage unknown "
                  f"(cur={cur_v}, prior={prior_v}) - leaving blank", flush=True)
            continue
        if cur_v > prior_v:
            try:
                gap = (date.fromisoformat(cur_v) - date.fromisoformat(prior_v)).days
            except ValueError:
                continue
            if gap > OI_CHG_MAX_GAP_DAYS:
                print(f"    [oi_chg] {key}: snapshots {gap}d apart "
                      f"({prior_v} -> {cur_v}), not a session delta - "
                      f"leaving blank", flush=True)
                continue
        prev_rows = prior.get(key) or []
        prev_oi  = {r["symbol"]: r.get("oi")     for r in prev_rows if r.get("symbol")}
        prev_chg = {r["symbol"]: r.get("oi_chg") for r in prev_rows if r.get("symbol")}
        for row in payload.get(key) or []:
            sym = row.get("symbol")
            if cur_v == prior_v:
                row["oi_chg"] = prev_chg.get(sym)                   # same snapshot: keep prior delta
            elif cur_v > prior_v and row.get("oi") is not None and prev_oi.get(sym) is not None:
                row["oi_chg"] = int(row["oi"]) - int(prev_oi[sym])  # snapshot-over-snapshot change


# A6 - End-to-end driver
def main(show_plots: bool = False) -> None:
    today = date.today()

    print("[1] Loading reference rates (NY Fed)...", flush=True)
    ref_rates = load_ref_rates(days=90)
    OCR  = float(ref_rates["effr"].dropna().iloc[-1])
    SOFR = float(ref_rates["sofr"].dropna().iloc[-1])
    print(f"    EFFR {OCR:.4f}%   SOFR {SOFR:.4f}%   "
          f"basis {(SOFR - OCR) * 100:+.1f} bp", flush=True)

    print("[2] Loading futures strip (ZQ: Barchart cache, SR3: yfinance)...", flush=True)
    strip = load_strip(today)
    if strip.empty:
        raise RuntimeError("No futures contracts loaded - check yfinance access")
    n_zq = int((strip["root"] == "ZQ").sum())
    if n_zq == 0:
        # Both sources failed. Publishing now would ship a Fed Funds tab with no
        # strip, no meeting path and no terminal rate, so fail loudly instead and
        # leave the previous stir.json in place.
        raise RuntimeError(
            "ZQ strip empty: Barchart cache stale/absent AND the yfinance "
            f"fallback returned nothing ({ZQ_PROVENANCE.get('note')}). Refusing "
            "to publish stir.json without a Fed Funds strip - run "
            "scripts/barchart_fetch.py."
        )
    print(f"    Loaded {len(strip)} contracts "
          f"({n_zq} ZQ, {(strip['root'] == 'SR3').sum()} SR3)", flush=True)
    print(f"    ZQ source: {ZQ_PROVENANCE['source']} "
          f"(as_of {ZQ_PROVENANCE['as_of']}, "
          f"age {ZQ_PROVENANCE['age_days']}d)", flush=True)

    print("[3] Computing implied rates and terminal...", flush=True)
    strip = add_implied(strip, OCR)

    sofr_strip = strip[strip["root"] == "SR3"].reset_index(drop=True)
    ff_strip   = strip[strip["root"] == "ZQ"].reset_index(drop=True)

    fomc_dates = load_fomc_dates(today)
    print(f"[4] {len(fomc_dates)} FOMC meetings ahead. Building meeting path...",
          flush=True)
    path = build_meeting_path(ff_strip, OCR, fomc_dates)
    print(f"    Path covers {len(path)} meetings", flush=True)

    print("[5] Exporting dashboard JSON...", flush=True)
    payload = build_dashboard_payload(strip, ref_rates, fomc_dates, path,
                                      OCR, SOFR, today)
    apply_oi_chg(payload, JSON_OUT)   # derive OI change from the prior published snapshot (before overwrite)
    JSON_OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(JSON_OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, separators=(",", ":"))
    print(f"    Written: {JSON_OUT.name} "
          f"({len(payload['ff_strip'])} ZQ, {len(payload['sofr_strip'])} SR3, "
          f"{len(payload['meeting_path'])} meetings)", flush=True)

    if show_plots:
        plot_strip(sofr_strip, OCR, "PRODUCTS - SOFR (SR3) STRIP").show()
        plot_strip(ff_strip,   OCR, "PRODUCTS - FED FUNDS (ZQ) STRIP").show()
        plot_meeting_path(path, OCR).show()
        print(spread_matrix(ff_strip, OCR))
        plot_cb_lvl(path, OCR).show()

    print("Done.", flush=True)


if __name__ == "__main__":
    import sys
    main(show_plots=("--plot" in sys.argv))
