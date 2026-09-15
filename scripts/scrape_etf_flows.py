# Daily Fund Flow series + exact summary strings for the 11 SPDR sector ETFs.
# Step 1 of 2: run this, then scripts/gen_etf_flows.py to build prototypes/etf_flows.json.
#   - navigates straight to /etf/<TICKER>/#fund-flows so the section activates natively
#   - fresh browser context per ticker (Highcharts state leaked across navigations)
#   - text_content(), since a collapsed section renders no inner_text
#   - writes progress.txt incrementally so buffering can never hide what happened
# Nothing is fabricated: a ticker that fails is recorded with its error.
import re, json, io, os, sys, time, datetime
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "etf_flows_daily.json")
PROG = os.path.join(ROOT, "data", "etf_flows_scrape.log")

TICKERS = ["XLB", "XLC", "XLE", "XLF", "XLI", "XLK", "XLP", "XLRE", "XLU", "XLV", "XLY"]
SECTOR = {
    "XLB": "Materials", "XLC": "Communication Services", "XLE": "Energy",
    "XLF": "Financials", "XLI": "Industrials", "XLK": "Technology",
    "XLP": "Consumer Staples", "XLRE": "Real Estate", "XLU": "Utilities",
    "XLV": "Health Care", "XLY": "Consumer Discretionary",
}
PERIODS = ["5 Day", "1 Month", "3 Month", "6 Month", "1 Year", "3 Year", "5 Year", "10 Year"]
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

OPEN_JS = """
() => {
  ['#fund-flows_tab', "a[href='#fund-flows']", '#fund-flows-collapse'].forEach(sel => {
    document.querySelectorAll(sel).forEach(e => {
      try { e.scrollIntoView(); } catch (x) {}
      try { e.click(); } catch (x) {}
      e.classList.add('in','show','active');
      if (e.style) { e.style.display=''; e.style.visibility='visible'; e.style.height='auto'; }
    });
  });
  return true;
}
"""

SERIES_JS = """
() => {
  const H = window.Highcharts;
  if (!H || !H.charts) return null;
  const found = [];
  H.charts.filter(Boolean).forEach(c => {
    const cid = (c.renderTo && c.renderTo.id) || '';
    (c.series || []).forEach(s => {
      if (s.name !== 'Fund Flow') return;
      const x = s.xData || [], y = s.yData || [];
      if (!x.length) return;
      found.push({container: cid, n: x.length, points: x.map((v, i) => [v, y[i]])});
    });
  });
  if (!found.length) return null;
  found.sort((a, b) => {
    const pa = a.container.indexOf('fund-flow') >= 0 ? 0 : 1;
    const pb = b.container.indexOf('fund-flow') >= 0 ? 0 : 1;
    return pa - pb || b.n - a.n;
  });
  return found[0];
}
"""

MULT = {"K": 1e-3, "M": 1.0, "B": 1e3, "T": 1e6}


def to_millions(s):
    m = re.match(r"^\s*(-?)\s*\$?\s*([\d,]+(?:\.\d+)?)\s*([KMBT])?\s*$", s or "")
    if not m:
        return None
    sign = -1.0 if m.group(1) == "-" else 1.0
    return sign * float(m.group(2).replace(",", "")) * MULT[(m.group(3) or "M").upper()]


def note(line):
    with io.open(PROG, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(line)
    sys.stdout.flush()


def fetch(ctx, tk):
    pg = ctx.new_page()
    try:
        pg.goto("https://etfdb.com/etf/%s/#fund-flows" % tk,
                wait_until="domcontentloaded", timeout=60000)
        try:
            pg.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass
        pg.evaluate(OPEN_JS)
        pg.wait_for_timeout(2000)
        for _ in range(8):
            pg.mouse.wheel(0, 1400)
            pg.wait_for_timeout(200)
        pg.evaluate(OPEN_JS)

        series = None
        for _ in range(16):
            try:
                series = pg.evaluate(SERIES_JS)
            except Exception:
                series = None
            if series and series.get("n"):
                break
            pg.wait_for_timeout(1500)

        summary = {}
        el = pg.query_selector("#fund-flows-collapse")
        if el:
            raw = re.sub(r"\s+", " ", el.text_content() or "")
            for p in PERIODS:
                m = re.search(re.escape(p) + r" Net Flows:\s*(-?[\d.,]+\s*[KMBT]?)", raw)
                disp = m.group(1).strip() if m else None
                summary[p] = {"display": disp, "millions": to_millions(disp)}
        return series, summary
    finally:
        try:
            pg.close()
        except Exception:
            pass


res, problems = {}, []
with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    for tk in TICKERS:
        series, summary, err = None, {}, None
        for attempt in (1, 2, 3):
            ctx = b.new_context(user_agent=UA, viewport={"width": 1440, "height": 1400})
            try:
                series, summary = fetch(ctx, tk)
                if series:
                    break
                err = "Fund Flow series not found (attempt %d)" % attempt
            except Exception as e:
                err = "%s (attempt %d)" % (str(e)[:110], attempt)
            finally:
                try:
                    ctx.close()
                except Exception:
                    pass
            time.sleep(3)

        if not series:
            problems.append((tk, err or "unknown"))
            res[tk] = {"sector": SECTOR[tk], "error": err, "summary": summary, "daily": []}
            note("%-5s FAILED  %s" % (tk, err))
            continue

        daily = []
        for x, y in series["points"]:
            if y is None:
                continue
            d = datetime.datetime.fromtimestamp(x / 1000.0, datetime.timezone.utc).strftime("%Y-%m-%d")
            daily.append([d, round(float(y) * 1000.0, 4)])
        daily.sort()
        res[tk] = {"sector": SECTOR[tk], "container": series["container"],
                   "summary": summary, "daily": daily}
        note("%-5s OK  %4d bars  %s..%s   3M=%s  6M=%s  1Y=%s" % (
            tk, len(daily), daily[0][0], daily[-1][0],
            summary.get("3 Month", {}).get("display"),
            summary.get("6 Month", {}).get("display"),
            summary.get("1 Year", {}).get("display")))
        time.sleep(1.5)
    b.close()

doc = {
    "scraped_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "source": "etfdb.com ETF profile pages, Fund Flows chart (Highcharts series 'Fund Flow')",
    "source_url_pattern": "https://etfdb.com/etf/{TICKER}/#fund-flows",
    "daily_unit": "USD millions per day (page renders $B; multiplied by 1000)",
    "tickers": res, "problems": problems,
}
json.dump(doc, io.open(OUT, "w", encoding="utf-8"), indent=1)
ok = [t for t in TICKERS if not res[t].get("error")]
note("")
note("DONE  %d/%d tickers with daily series" % (len(ok), len(TICKERS)))
for t, e in problems:
    note("  PROBLEM %s: %s" % (t, e))
