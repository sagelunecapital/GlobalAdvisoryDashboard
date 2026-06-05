#!/usr/bin/env python3
"""
carry_export.py  --  daily G10 FX carry index for the dashboard.

Builds the 3v3 equal-weight, monthly-rebalanced G10 carry replication
(fx_carry_index engine) from yfinance FX + FRED 3M rates, then applies the
recovered FXCTG10 calibration (leverage beta + managed alpha) so the published
series tracks Bloomberg's FXCTG10 "Managed" carry index.

  published daily return = alpha_d + beta * carry_return   (recumulated, base 100)

Calibration (beta, alpha_d) is read from data/carry_calibration.json, which is
written by scripts/reverse_fxctg10.py. Re-run that against a refreshed Bloomberg
FXCTG10 export to recalibrate; this daily export needs NO Bloomberg file.

Output: prototypes/carry.json
  {updated, start, base, beta, alpha_pct_yr, dates:[...], carry:[...]}
"""
import os
import json
from datetime import datetime, timezone
from pathlib import Path

from fx_carry_index import load_hybrid, build_index, G10_UNIVERSE, BUSINESS_DAYS

ROOT     = Path(__file__).resolve().parent.parent
CALIB_F  = ROOT / "data" / "carry_calibration.json"
OUT_F    = ROOT / "prototypes" / "carry.json"
FRED_KEY = os.environ.get("FRED_API_KEY", "2e8783a45bc0ff35dda158225a6b2b02")
START    = "2002-04-01"

# Fallback if the calibration file is missing (reverse_fxctg10.py, 2002-04 -> 2026-01).
_DEFAULT = {"beta": 0.9818, "alpha_d": 0.007285 / BUSINESS_DAYS}


def _calibration():
    try:
        c = json.loads(CALIB_F.read_text(encoding="utf-8"))
        return float(c["beta"]), float(c["alpha_d"])
    except Exception as e:
        print(f"[carry] calibration file unavailable ({e}); using defaults.")
        return _DEFAULT["beta"], _DEFAULT["alpha_d"]


def main():
    beta, alpha_d = _calibration()
    print(f"[carry] beta={beta:.4f}  alpha={alpha_d * BUSINESS_DAYS * 100:+.2f}%/yr")

    end = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    dates, rates, fx = load_hybrid(START, end, api_key=FRED_KEY)
    print(f"[carry] loaded {len(dates)} daily obs ({dates[0]} -> {dates[-1]})")

    res = build_index(dates, rates, fx, G10_UNIVERSE,
                      n_long=3, n_short=3, rebalance="monthly")

    # Apply leverage + managed alpha to each daily carry return, recumulate base 100.
    out_dates = [res.dates[0]]
    out_level = [100.0]
    lvl = 100.0
    for k in range(1, len(res.dates)):
        c = res.daily_carry[k]
        r = 0.0 if c is None else (alpha_d + beta * c)
        lvl *= (1.0 + r)
        out_dates.append(res.dates[k])
        out_level.append(round(lvl, 4))

    payload = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "start": out_dates[0],
        "base": 100,
        "beta": round(beta, 4),
        "alpha_pct_yr": round(alpha_d * BUSINESS_DAYS * 100, 3),
        "dates": out_dates,
        "carry": out_level,
    }
    OUT_F.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    print(f"[carry] wrote {len(out_dates)} pts -> {OUT_F}  "
          f"(last {out_dates[-1]} = {out_level[-1]})")


if __name__ == "__main__":
    main()
