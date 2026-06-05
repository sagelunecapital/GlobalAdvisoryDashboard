"""
reverse_fxctg10.py
==================
Reverse-engineer Bloomberg's FXCTG10 ('Managed' G10 carry) index from its
realised daily returns.

Two regressions:
  (1) Factor model -- FXCTG10 daily return regressed on the 10 individual G10
      currency USD-funded carry returns. Coefficients = average NET weights
      (long if +, short if -), revealing the basket Bloomberg actually runs.
  (2) Single-factor -- FXCTG10 regressed on MY equal-weight 3v3 replication, to
      extract leverage (beta) and alpha (the proprietary 'managed' overlay).

Then it builds an improved replication (levered to the fitted beta) and re-tests
correlation / tracking error / total return against the actual index.

Usage:  FRED_API_KEY=... python scripts/reverse_fxctg10.py
"""
import os, csv, math, json
import warnings
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd

from fx_carry_index import load_fred, BUSINESS_DAYS, G10_UNIVERSE

BBG_XLSX = r"C:\Users\lance\Downloads\Book1.xlsx"
MINE_CSV = "data/fx_carry_g10_fred.csv"
START, END = "2002-04-01", "2026-01-30"
NONUSD = [c for c in G10_UNIVERSE if c != "USD"]


def load_bbg():
    df = pd.read_excel(BBG_XLSX, sheet_name="Sheet1")
    df.columns = ["date", "bbg"]
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    return dict(zip(df["date"], df["bbg"].astype(float)))


def currency_excess_returns(dates, rates, fx):
    """Daily USD-funded carry return of being long currency c:
        r_c[t] = (1+rate_c/(100*260))*(fx_c[t]/fx_c[t-1]) - (1+rate_USD/(100*260))
    Returns {c: {date: ret}} for the 10 non-USD currencies."""
    out = {c: {} for c in NONUSD}
    for k in range(1, len(dates)):
        d, dp = dates[k], dates[k - 1]
        ru = rates["USD"].get(d)
        if ru is None:
            continue
        usd_leg = 1 + ru / (100 * BUSINESS_DAYS)
        for c in NONUSD:
            rc = rates[c].get(d)
            if rc is None or c not in fx or d not in fx[c] or dp not in fx[c]:
                continue
            out[c][d] = (1 + rc / (100 * BUSINESS_DAYS)) * (fx[c][d] / fx[c][dp]) - usd_leg
    return out


def ols(y, X):
    """OLS with intercept. X: (n,k). Returns (coefs incl intercept, r2, resid)."""
    A = np.column_stack([np.ones(len(y)), X])
    coef, *_ = np.linalg.lstsq(A, y, rcond=None)
    yhat = A @ coef
    ss_res = np.sum((y - yhat) ** 2)
    ss_tot = np.sum((y - y.mean()) ** 2)
    r2 = 1 - ss_res / ss_tot
    return coef, r2, y - yhat


def main():
    print("=" * 70)
    print("REVERSE-ENGINEERING FXCTG10")
    print("=" * 70)
    bbg = load_bbg()
    dates, rates, fx = load_fred(START, END)
    cxr = currency_excess_returns(dates, rates, fx)

    mine_lvl = {r["date"]: float(r["index_level"])
                for r in csv.DictReader(open(MINE_CSV, encoding="utf-8"))}

    # common dates where we have: bbg, mine, and all 10 currency returns
    common = [d for d in dates
              if d in bbg and d in mine_lvl and all(d in cxr[c] for c in NONUSD)]
    common = sorted(common)
    # daily returns
    def rets(level_map):
        return np.array([level_map[common[i]] / level_map[common[i - 1]] - 1
                         for i in range(1, len(common))])
    bbg_r = rets(bbg)
    mine_r = rets(mine_lvl)
    Xc = np.column_stack([[cxr[c][common[i]] for i in range(1, len(common))]
                          for c in NONUSD])
    print(f"  aligned obs: {len(bbg_r)}  ({common[1]} -> {common[-1]})\n")

    # ---- (1) factor model: recover net weights ----
    coef, r2, _ = ols(bbg_r, Xc)
    print("(1) FACTOR MODEL  FXCTG10 ~ individual currency carry returns")
    print(f"    R^2 = {r2:.3f}   (alpha {coef[0]*BUSINESS_DAYS*100:+.2f}%/yr)")
    print("    Recovered AVERAGE net weights (long +, short -):")
    weights = {c: coef[1 + i] for i, c in enumerate(NONUSD)}
    for c in sorted(weights, key=lambda c: -weights[c]):
        bar = "#" * int(abs(weights[c]) * 30)
        print(f"      {c:4s} {weights[c]:+.3f}  {bar}")
    print()

    # ---- (2) single factor: leverage + alpha vs my replication ----
    coef2, r2b, _ = ols(bbg_r, mine_r.reshape(-1, 1))
    alpha_d, beta = coef2[0], coef2[1]
    print("(2) SINGLE-FACTOR  FXCTG10 ~ my equal-weight 3v3 replication")
    print(f"    beta (leverage)   = {beta:.3f}")
    print(f"    alpha             = {alpha_d*BUSINESS_DAYS*100:+.2f}%/yr")
    print(f"    R^2               = {r2b:.3f}")
    print(f"    corr              = {math.sqrt(max(r2b,0)):.3f}\n")

    # Persist calibration for the daily export (carry_export.py reads this).
    calib = {
        "beta": float(beta),
        "alpha_d": float(alpha_d),
        "alpha_pct_yr": float(alpha_d * BUSINESS_DAYS * 100),
        "r2": float(r2b),
        "corr": float(math.sqrt(max(r2b, 0))),
        "net_weights": {c: float(weights[c]) for c in NONUSD},
        "fit_start": common[1],
        "fit_end": common[-1],
        "fit_obs": len(bbg_r),
    }
    with open("data/carry_calibration.json", "w", encoding="utf-8") as f:
        json.dump(calib, f, indent=2)
    print("  wrote data/carry_calibration.json")

    # ---- (3) improved replication: lever my returns to fitted beta (+alpha) ----
    def stats(model_r, label):
        # rebuild a level path from returns, rebased to bbg start
        lvl = [bbg[common[0]]]
        for r in model_r:
            lvl.append(lvl[-1] * (1 + r))
        bl = [bbg[d] for d in common]
        n = len(model_r)
        te = math.sqrt(np.mean((model_r - bbg_r) ** 2)) * math.sqrt(BUSINESS_DAYS)
        corr = np.corrcoef(model_r, bbg_r)[0, 1]
        print(f"    {label:28s} corr={corr:.3f}  TE={te*100:4.2f}%/yr  "
              f"end={lvl[-1]:.1f} vs bbg {bl[-1]:.1f}  "
              f"({(lvl[-1]/lvl[0]-1)*100:+.1f}% vs {(bl[-1]/bl[0]-1)*100:+.1f}%)")
        return lvl

    print("(3) IMPROVED REPLICATION vs actual FXCTG10")
    stats(mine_r, "baseline (mine, 1.0x)")
    lvl_lev = stats(beta * mine_r, f"levered {beta:.2f}x")
    lvl_full = stats(alpha_d + beta * mine_r, f"levered {beta:.2f}x + alpha")

    # write best model path for charting
    with open("data/fxctg10_model.csv", "w", encoding="utf-8") as f:
        f.write("date,bbg,mine_baseline,mine_levered\n")
        base = [bbg[common[0]]]
        for r in mine_r:
            base.append(base[-1] * (1 + r))
        for i, d in enumerate(common):
            f.write(f"{d},{bbg[d]:.4f},{base[i]:.4f},{lvl_lev[i]:.4f}\n")
    print("\n  wrote data/fxctg10_model.csv")


if __name__ == "__main__":
    main()
