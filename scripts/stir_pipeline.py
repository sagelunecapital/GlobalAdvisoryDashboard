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


ROOT     = Path(__file__).resolve().parent.parent
JSON_OUT = ROOT / "prototypes" / "stir.json"


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


def _fetch_settle(symbol: str) -> float | None:
    try:
        h = yf.Ticker(symbol).history(period="5d")
        if h.empty:
            return None
        return float(h["Close"].iloc[-1])
    except Exception:
        return None


def load_strip(today: date,
               zq_months: int = 18,
               sr3_quarters: int = 8) -> pd.DataFrame:
    """Settlement strip: ZQ (Fed Funds, monthly) and SR3 (3M SOFR, quarterly)."""
    contracts: list[Contract] = []

    # ZQ - one per calendar month, ~18 months out
    for i in range(zq_months):
        m = ((today.month - 1 + i) % 12) + 1
        y = today.year + (today.month + i - 1) // 12
        exp = _expiry_for_month(y, m)
        sym = f"ZQ{_CME_MONTH_CODES[m]}{y % 100:02d}.CBT"
        s = _fetch_settle(sym)
        if s is not None:
            contracts.append(Contract(_cme_symbol("ZQ", exp), "ZQ", exp, s))

    # SR3 - quarterly listings (Mar/Jun/Sep/Dec), ~2 years out
    cur_q = ((today.month - 1) // 3) * 3 + 3
    y, q = today.year, cur_q
    for _ in range(sr3_quarters):
        if q > 12:
            q -= 12
            y += 1
        exp = _expiry_for_month(y, q)
        sym = f"SR3{_CME_MONTH_CODES[q]}{y % 100:02d}.CME"
        s = _fetch_settle(sym)
        if s is not None:
            contracts.append(Contract(_cme_symbol("SR3", exp), "SR3", exp, s))
        q += 3

    return to_strip(contracts).sort_values(["root", "expiry"]).reset_index(drop=True)


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
        rows.append({"meeting":   d,
                     "post_rate": post,
                     "cum_cuts":  (effr_today - post) / 0.25})
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
            "hike25": 100 * mass.get(-1, 0.0)}


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


# Dashboard JSON export (consumed by prototypes/index.html, US STIR tab)
def build_dashboard_payload(strip: pd.DataFrame, ref_rates: pd.DataFrame,
                            fomc_dates: list[date], path_df: pd.DataFrame,
                            effr: float, sofr: float) -> dict:
    sofr_strip = strip[strip["root"] == "SR3"].reset_index(drop=True)
    ff_strip   = strip[strip["root"] == "ZQ"].reset_index(drop=True)

    sofr_term = find_terminal(sofr_strip, effr) if not sofr_strip.empty else None
    ff_term   = find_terminal(ff_strip,   effr) if not ff_strip.empty   else None

    def _rows(s: pd.DataFrame, term_sym: str | None) -> list[dict]:
        return [
            {"symbol":       r["symbol"],
             "expiry":       r["expiry"].isoformat(),
             "settle":       round(r["settle"], 4),
             "implied_rate": round(r["implied_rate"], 4),
             "vs_ocr_bp":    round(r["vs_ocr_bp"], 1),
             "is_terminal":  term_sym is not None and r["symbol"] == term_sym}
            for _, r in s.iterrows()
        ]

    spreads = spread_matrix(ff_strip, effr)
    spread_rows = []
    if not spreads.empty:
        for sym, row in spreads.iterrows():
            spread_rows.append({
                "contract": sym,
                **{k: (None if pd.isna(v) else int(v)) for k, v in row.items()},
            })

    path_rows = []
    for _, r in path_df.iterrows():
        probs = meeting_probs(r["post_rate"], effr)
        path_rows.append({
            "meeting":   r["meeting"].isoformat(),
            "post_rate": round(r["post_rate"], 4),
            "cum_cuts":  round(r["cum_cuts"], 2),
            "probs":     {k: round(v, 1) for k, v in probs.items()},
        })

    asof = (ref_rates.index[-1].date().isoformat()
            if len(ref_rates) else date.today().isoformat())

    return {
        "updated":      datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "asof_date":    asof,
        "effr":         round(effr, 4),
        "sofr":         round(sofr, 4),
        "basis_bp":     round((sofr - effr) * 100, 1),
        "sofr_strip":   _rows(sofr_strip, sofr_term["symbol"] if sofr_term is not None else None),
        "ff_strip":     _rows(ff_strip,   ff_term["symbol"]   if ff_term   is not None else None),
        "fomc_dates":   [d.isoformat() for d in fomc_dates],
        "meeting_path": path_rows,
        "spreads":      spread_rows,
        "cb_levels":    [round(lv, 2) for lv in cb_levels(effr, band_bp=150)],
        "cb_settle":    round(round(effr / 0.25) * 0.25, 2),
    }


# A6 - End-to-end driver
def main(show_plots: bool = False) -> None:
    today = date.today()

    print("[1] Loading reference rates (NY Fed)...", flush=True)
    ref_rates = load_ref_rates(days=90)
    OCR  = float(ref_rates["effr"].dropna().iloc[-1])
    SOFR = float(ref_rates["sofr"].dropna().iloc[-1])
    print(f"    EFFR {OCR:.4f}%   SOFR {SOFR:.4f}%   "
          f"basis {(SOFR - OCR) * 100:+.1f} bp", flush=True)

    print("[2] Loading futures strip (yfinance: ZQ + SR3)...", flush=True)
    strip = load_strip(today)
    if strip.empty:
        raise RuntimeError("No futures contracts loaded - check yfinance access")
    print(f"    Loaded {len(strip)} contracts "
          f"({(strip['root'] == 'ZQ').sum()} ZQ, "
          f"{(strip['root'] == 'SR3').sum()} SR3)", flush=True)

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
    payload = build_dashboard_payload(strip, ref_rates, fomc_dates, path, OCR, SOFR)
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
