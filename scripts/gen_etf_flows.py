# Generates prototypes/etf_flows.json for the dashboard ETF Flows tab.
#
# Source: etfdb.com ETF profile pages, Fund Flows chart
#         (https://etfdb.com/etf/<TICKER>/#fund-flows), Highcharts series "Fund Flow".
# The page renders daily bars in $ billions; stored here as $ millions.
#
# Window definition is CALIBRATED, not assumed: summing daily bars over calendar
# months with an inclusive start reproduces etfdb's own 3M/6M/1Y totals to a mean
# absolute error of $1.5M (worst $4.8M, which is the site's display rounding).
# The reconciliation is recomputed here and embedded in the output.
#
# Input:  data/etf_flows_daily.json  (from scripts/scrape_etf_flows.py)
# Output: prototypes/etf_flows.json
import json, io, os, sys, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "data", "etf_flows_daily.json")
OUT = os.path.join(ROOT, "prototypes", "etf_flows.json")

ORDER = ["XLK", "XLF", "XLV", "XLY", "XLI", "XLC", "XLP", "XLE", "XLU", "XLRE", "XLB"]
MONTHS = {"3M": 3, "6M": 6, "1Y": 12}
LABEL = {"3M": "3 Month", "6M": "6 Month", "1Y": "1 Year"}


def minus_months(dt, n):
    y, m = dt.year, dt.month - n
    while m <= 0:
        m += 12
        y -= 1
    leap = (y % 4 == 0 and (y % 100 != 0 or y % 400 == 0))
    dim = [31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]
    return datetime.date(y, m, min(dt.day, dim))


src = json.load(io.open(SRC, encoding="utf-8"))
T = src["tickers"]
missing = [t for t in ORDER if t not in T or T[t].get("error")]
if missing:
    print("REFUSING TO WRITE: no daily series for %s" % ", ".join(missing))
    sys.exit(1)

LAST = datetime.date.fromisoformat(max(max(x[0] for x in T[t]["daily"]) for t in ORDER))
START_1Y = minus_months(LAST, 12)

tickers, recon = {}, []
for tk in ORDER:
    v = T[tk]
    bars = sorted((datetime.date.fromisoformat(x[0]), x[1]) for x in v["daily"])

    periods = {}
    for key, nm in MONTHS.items():
        start = minus_months(LAST, nm)
        total = sum(val for dt, val in bars if start <= dt <= LAST)
        stated = (v.get("summary", {}).get(LABEL[key]) or {})
        periods[key] = {
            "total": round(total, 2),
            "page_display": stated.get("display"),
            "page_millions": stated.get("millions"),
            "start": start.isoformat(), "end": LAST.isoformat(),
        }
        if stated.get("millions") is not None:
            recon.append({"ticker": tk, "period": key,
                          "page": stated["millions"], "bars": round(total, 2),
                          "abs_err": round(abs(total - stated["millions"]), 2)})

    # ship one year of daily bars; the UI derives 3M/6M by slicing
    window = [[dt.isoformat(), round(val, 3)] for dt, val in bars if START_1Y <= dt <= LAST]
    run, cum = 0.0, []
    for dt, val in window:
        run += val
        cum.append(round(run, 2))

    tickers[tk] = {
        "sector": v["sector"],
        "periods": periods,
        "daily": window,          # [date, net flow $M] - the chart's own bars
        "cumulative": cum,        # running sum across the 1Y window
    }

# net across the complex, on the union of dates
alldates = sorted({d for tk in ORDER for d, _ in tickers[tk]["daily"]})
idx = {tk: dict(tickers[tk]["daily"]) for tk in ORDER}
net_daily, run, net_cum = [], 0.0, []
for d in alldates:
    s = sum(idx[tk].get(d, 0.0) for tk in ORDER)
    net_daily.append([d, round(s, 3)])
    run += s
    net_cum.append(round(run, 2))

net_periods = {}
for key, nm in MONTHS.items():
    start = minus_months(LAST, nm).isoformat()
    net_periods[key] = {
        "total": round(sum(v for d, v in net_daily if start <= d <= LAST.isoformat()), 2),
        "start": start, "end": LAST.isoformat(),
    }

errs = [r["abs_err"] for r in recon]
doc = {
    "generated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "scraped_at": src.get("scraped_at"),
    "source": "etfdb.com Fund Flows chart (Highcharts series 'Fund Flow')",
    "source_url_pattern": "https://etfdb.com/etf/{TICKER}/#fund-flows",
    "unit": "USD millions",
    "as_of": LAST.isoformat(),
    "window_rule": "Calendar months, inclusive start: [as_of - N months, as_of]. "
                   "Calibrated against etfdb's own stated totals.",
    "order": ORDER,
    "tickers": tickers,
    "net": {"daily": net_daily, "cumulative": net_cum, "periods": net_periods},
    "reconciliation": {
        "checks": len(recon),
        "mean_abs_err": round(sum(errs) / len(errs), 2) if errs else None,
        "max_abs_err": round(max(errs), 2) if errs else None,
        "note": "Daily bars summed over the window vs the figure etfdb prints. "
                "Residuals are the site's display rounding (3 significant figures).",
        "rows": sorted(recon, key=lambda r: -r["abs_err"])[:10],
    },
}

io.open(OUT, "w", encoding="utf-8").write(json.dumps(doc, indent=1))

# ---- assertions ----
chk = json.load(io.open(OUT, encoding="utf-8"))
assert len(chk["tickers"]) == 11, "expected 11 tickers"
assert chk["reconciliation"]["max_abs_err"] < 10.0, "reconciliation drifted: %s" % chk["reconciliation"]["max_abs_err"]
for tk in ORDER:
    t = chk["tickers"][tk]
    assert len(t["daily"]) == len(t["cumulative"]), "cumulative length mismatch for " + tk
    assert abs(t["cumulative"][-1] - sum(v for _, v in t["daily"])) < 0.5, "cumulative does not close for " + tk
assert len(chk["net"]["daily"]) == len(chk["net"]["cumulative"])
print("OK  wrote %s (%d bytes)" % (OUT, os.path.getsize(OUT)))
print("  as of %s | %d tickers | %d daily bars each (1Y window)"
      % (chk["as_of"], len(chk["tickers"]), len(chk["tickers"]["XLK"]["daily"])))
print("  reconciliation: %d checks, mean err $%.2fM, max $%.2fM"
      % (chk["reconciliation"]["checks"], chk["reconciliation"]["mean_abs_err"],
         chk["reconciliation"]["max_abs_err"]))
for k in ("3M", "6M", "1Y"):
    print("  NET %s across 11 sectors: $%s M" % (k, format(chk["net"]["periods"][k]["total"], ",.0f")))
