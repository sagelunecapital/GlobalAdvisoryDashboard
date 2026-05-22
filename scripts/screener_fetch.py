#!/usr/bin/env python3
"""
screener_fetch.py
Fetches raw screener data — no AI enrichment (done separately via Claude Code).

  1. US movers       — TradingView screener N1XsQe0l (Playwright)
  2. China/HK movers — TradingView screener YUifpXoa (Playwright)
  3. US IPOs         — TradingView scanner API (america)
  4. HK IPOs         — TradingView scanner API (hongkong)

Outputs:
  prototypes/screener_movers.json    {updated_at, by_date:{date:[rows]}}
  prototypes/screener_movers_cn.json {updated_at, by_date:{date:[rows]}}
  prototypes/screener_ipos.json      {fetched_at, us:[...], hk:[...]}
"""

import asyncio
import json
import requests
from datetime import date, datetime, timezone, timedelta
from pathlib import Path

import yfinance as yf
from playwright.async_api import async_playwright

ROOT          = Path(__file__).resolve().parent.parent
MOVERS_OUT    = ROOT / "prototypes" / "screener_movers.json"
MOVERS_CN_OUT = ROOT / "prototypes" / "screener_movers_cn.json"
IPOS_OUT      = ROOT / "prototypes" / "screener_ipos.json"

TV_SCREENER_US_URL = "https://www.tradingview.com/screener/N1XsQe0l/"
TV_SCREENER_CN_URL = "https://www.tradingview.com/screener/YUifpXoa/"
TV_IPO_URL         = "https://scanner.tradingview.com/global/scan?label-product=calendar-ipo"

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# ── JS extractors ────────────────────────────────────────────────────────────

# US: letter-based tickers, mkt cap as "1.23B" (USD)
_TV_EXTRACT_JS_US = r"""
() => {
  const rows = [];
  document.querySelectorAll('tr[class*="row"]').forEach(tr => {
    const cells = Array.from(tr.querySelectorAll('td'));
    if (cells.length < 3) return;
    const texts = cells.map(td => td.textContent.trim());

    // Extract ticker from leaf elements to avoid grabbing first chars of company name
    const firstCell = cells[0];
    let ticker = null;
    const leaves = Array.from(firstCell.querySelectorAll('*'))
      .filter(el => el.children.length === 0);
    for (const leaf of leaves) {
      const t = leaf.textContent.trim();
      if (/^[A-Z][A-Z0-9\.]{0,5}$/.test(t) && t.length >= 2) {
        ticker = t; break;
      }
    }
    // Fallback: stop at CamelCase boundary (UpperLower) or space
    if (!ticker) {
      const m = texts[0].match(/^([A-Z][A-Z0-9\.]{0,5})(?=[A-Z][a-z]|\s|$)/);
      if (m) ticker = m[1];
    }
    if (!ticker || ticker.length < 2) return;

    // Company: full cell text minus ticker, strip trailing type badges (D, CEF, ETF…)
    let company = firstCell.textContent.replace(ticker, '').trim()
      .replace(/[A-Z]+$/, '').trim()
      .replace(/\s+[A-Z]+$/, '').trim();

    let changePct = null;
    for (const t of texts) {
      const m = t.match(/^([+\-]?\d+\.?\d*)%$/);
      if (m) { changePct = parseFloat(m[1]); break; }
    }
    let mktCap = null;
    for (const t of texts) {
      const m = t.match(/^([\d.]+)\s*(B|M|T)$/i);
      if (m) {
        const mult = {b: 1e9, m: 1e6, t: 1e12}[m[2].toLowerCase()] || 1e9;
        mktCap = parseFloat(m[1]) * mult;
        break;
      }
    }
    if (changePct !== null) {
      rows.push({ ticker, company, change_pct: changePct, mkt_cap: mktCap });
    }
  });
  return rows;
}
"""

# CN/HK: numeric tickers (e.g. 2382), mkt cap as "68.54 B HKD" (converted to USD)
_TV_EXTRACT_JS_CN = r"""
() => {
  const rows = [];
  document.querySelectorAll('tr[class*="row"]').forEach(tr => {
    const cells = Array.from(tr.querySelectorAll('td'));
    if (cells.length < 3) return;
    const texts = cells.map(td => td.textContent.trim());

    const firstCell = cells[0];
    let ticker = null;
    const leaves = Array.from(firstCell.querySelectorAll('*'))
      .filter(el => el.children.length === 0);
    for (const leaf of leaves) {
      const t = leaf.textContent.trim();
      if (/^([0-9]{3,5}|[A-Z0-9\.]{2,6})$/.test(t)) { ticker = t; break; }
    }
    if (!ticker) {
      const m = texts[0].match(/^([0-9]{3,5}|[A-Z0-9\.]{2,6})(?=[^A-Z0-9\.]|$)/);
      if (m) ticker = m[1];
    }
    if (!ticker || ticker.length < 2) return;
    let company = firstCell.textContent.replace(ticker, '').trim()
      .replace(/[A-Z]+$/, '').trim()
      .replace(/\s+[A-Z]+$/, '').trim();
    let changePct = null;
    for (const t of texts) {
      const m = t.match(/^([+\-]?\d+\.?\d*)%$/);
      if (m) { changePct = parseFloat(m[1]); break; }
    }
    let mktCap = null;
    for (const t of texts) {
      const m = t.match(/([\d.]+)\s+(B|M|T)\s+HKD/i);
      if (m) {
        const mult = {B: 1e9, M: 1e6, T: 1e12}[m[2].toUpperCase()] || 1e9;
        mktCap = Math.round(parseFloat(m[1]) * mult / 7.78);
        break;
      }
      const m2 = t.match(/^([\d.]+)\s*(B|M|T)$/i);
      if (m2 && mktCap === null) {
        const mult = {b: 1e9, m: 1e6, t: 1e12}[m2[2].toLowerCase()] || 1e9;
        mktCap = parseFloat(m2[1]) * mult;
        break;
      }
    }
    if (changePct !== null) {
      rows.push({ ticker, company, change_pct: changePct, mkt_cap: mktCap });
    }
  });
  return rows;
}
"""


# ── TradingView screener fetch ────────────────────────────────────────────────

async def _fetch_tv_screener_async(url: str, extract_js: str) -> list[dict]:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(user_agent=BROWSER_UA)
        page = await ctx.new_page()
        await page.goto(url, wait_until="networkidle", timeout=45_000)
        try:
            await page.click(
                'button[class*="segmentedControl"]:not([class*="checked"])',
                timeout=8_000,
            )
            await page.wait_for_selector('tr[class*="row"]', timeout=15_000)
        except Exception:
            pass
        await page.wait_for_timeout(2_000)
        rows = await page.evaluate(extract_js)
        await browser.close()
    return rows


# ── TradingView IPO fetch ────────────────────────────────────────────────────

def _fetch_tv_ipos(markets: list[str]) -> list[dict]:
    today = date.today()
    start_ts = int(datetime.combine(today - timedelta(days=14), datetime.min.time()).timestamp())
    end_ts   = int(datetime.combine(today + timedelta(days=90), datetime.max.time()).timestamp())

    body = {
        "columns": [
            "logo", "name", "description", "typespecs", "type", "exchange", "market",
            "ipo_offer_time", "ipo_offer_price_usd", "ipo_offer_status",
            "ipo_offer_status.tr", "ipo_offered_shares", "ipo_deal_amount_usd",
            "ipo_market_cap_usd", "ipo_price_range_usd", "source-logoid",
        ],
        "filter": [{
            "left": "ipo_offer_time",
            "operation": "in_range",
            "right": [start_ts, end_ts],
        }],
        "ignore_unknown_fields": False,
        "options": {"lang": "en"},
        "sort": {"sortBy": "ipo_offer_time", "sortOrder": "asc"},
        "markets": markets,
        "preset": "ipo_calendar",
    }
    headers = {
        "User-Agent": BROWSER_UA,
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Origin": "https://www.tradingview.com",
        "Referer": "https://www.tradingview.com/",
    }
    resp = requests.post(TV_IPO_URL, headers=headers, json=body, timeout=30)
    resp.raise_for_status()
    rows = resp.json().get("data", [])

    ipos = []
    for row in rows:
        d = row.get("d", [])
        if len(d) < 15:
            continue
        ticker      = d[1] or row.get("s", "").split(":")[-1]
        company     = d[2] or ""
        exch        = d[5] or ""
        offer_ts    = d[7]
        price_usd   = d[8]
        status      = d[10] or d[9] or ""
        shares      = d[11]
        deal_amt    = d[12]
        mkt_cap     = d[13]
        price_range = d[14]
        ipo_date = datetime.utcfromtimestamp(offer_ts).strftime("%Y-%m-%d") if offer_ts else None
        ipos.append({
            "ticker":          ticker,
            "company":         company,
            "exchange":        exch,
            "date":            ipo_date,
            "price_usd":       float(price_usd)  if price_usd  else None,
            "price_range":     price_range        or None,
            "status":          status,
            "shares":          int(shares)        if shares     else None,
            "deal_amount_usd": float(deal_amt)    if deal_amt   else None,
            "mkt_cap_usd":     float(mkt_cap)     if mkt_cap    else None,
        })
    return ipos


def _enrich_ipo_closes(ipos: list[dict], existing_by_ticker: dict) -> list[dict]:
    today = date.today()
    for ipo in ipos:
        ticker = ipo.get("ticker")
        if not ticker:
            continue
        if existing_by_ticker.get(ticker, {}).get("ipo_close") is not None:
            ipo["ipo_close"] = existing_by_ticker[ticker]["ipo_close"]
            continue
        ipo_date_str = ipo.get("date")
        if not ipo_date_str:
            continue
        ipo_date = date.fromisoformat(ipo_date_str)
        if ipo_date >= today:
            continue
        try:
            end = ipo_date + timedelta(days=5)
            yf_ticker = f"{int(ticker):04d}.HK" if ticker.isdigit() else ticker
            hist = yf.download(yf_ticker, start=ipo_date.isoformat(), end=end.isoformat(),
                               progress=False, auto_adjust=True)
            if not hist.empty:
                close_val = hist["Close"].iloc[0]
                if hasattr(close_val, "item"):
                    close_val = close_val.item()
                ipo["ipo_close"] = round(float(close_val), 2)
                print(f"[screener]   {ticker} IPO close: ${ipo['ipo_close']:.2f}", flush=True)
        except Exception as e:
            print(f"[screener]   {ticker} close fetch failed: {e}", flush=True)
    return ipos


# ── Main ─────────────────────────────────────────────────────────────────────

async def _main_async():
    now_iso = datetime.now(timezone.utc).isoformat()
    today   = date.today().isoformat()

    # ── US Movers ──────────────────────────────────────────────────────────
    print("[screener] Fetching US movers...", flush=True)
    existing_us: dict = {}
    if MOVERS_OUT.exists():
        try:
            existing_us = json.loads(MOVERS_OUT.read_text()).get("by_date", {})
        except Exception:
            pass

    try:
        raw_us = await _fetch_tv_screener_async(TV_SCREENER_US_URL, _TV_EXTRACT_JS_US)
        us_movers = [{
            "ticker":     r["ticker"],
            "company":    r.get("company", ""),
            "mkt_cap":    r.get("mkt_cap"),
            "change_pct": r.get("change_pct"),
        } for r in raw_us if r.get("ticker")]
        print(f"[screener] Got {len(us_movers)} US movers.", flush=True)
        existing_us[today] = us_movers
    except Exception as e:
        print(f"[screener] US movers fetch FAILED: {e}", flush=True)

    MOVERS_OUT.write_text(json.dumps({"updated_at": now_iso, "by_date": existing_us}, indent=2))
    print(f"[screener] Saved -> {MOVERS_OUT}", flush=True)

    # ── China/HK Movers ────────────────────────────────────────────────────
    print("[screener] Fetching China/HK movers...", flush=True)
    existing_cn: dict = {}
    if MOVERS_CN_OUT.exists():
        try:
            existing_cn = json.loads(
                MOVERS_CN_OUT.read_text(encoding="utf-8")
            ).get("by_date", {})
        except Exception:
            pass

    try:
        raw_cn = await _fetch_tv_screener_async(TV_SCREENER_CN_URL, _TV_EXTRACT_JS_CN)
        cn_movers = [{
            "ticker":     r["ticker"],
            "company":    r.get("company", ""),
            "mkt_cap":    r.get("mkt_cap"),
            "change_pct": r.get("change_pct"),
        } for r in raw_cn if r.get("ticker")]
        print(f"[screener] Got {len(cn_movers)} China/HK movers.", flush=True)
        existing_cn[today] = cn_movers
    except Exception as e:
        print(f"[screener] China movers fetch FAILED: {e}", flush=True)

    MOVERS_CN_OUT.write_text(
        json.dumps({"updated_at": now_iso, "by_date": existing_cn}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"[screener] Saved -> {MOVERS_CN_OUT}", flush=True)

    # ── IPOs (US + HK) ────────────────────────────────────────────────────
    existing_ipos: dict = {}
    if IPOS_OUT.exists():
        try:
            existing_ipos = json.loads(IPOS_OUT.read_text())
        except Exception:
            pass
    if "ipos" in existing_ipos and "us" not in existing_ipos:
        existing_ipos["us"] = existing_ipos.pop("ipos")

    existing_by_ticker_us: dict = {
        i["ticker"]: i for i in existing_ipos.get("us", []) if i.get("ticker")
    }
    try:
        us_ipos = _fetch_tv_ipos(["america"])
        us_ipos = [
            i for i in us_ipos
            if (i.get("deal_amount_usd") or 0) >= 300e6
            or (i.get("mkt_cap_usd")     or 0) >= 300e6
        ]
        print(f"[screener] Got {len(us_ipos)} US IPOs ($300M+ filter).", flush=True)
    except Exception as e:
        print(f"[screener] US IPO fetch FAILED: {e}", flush=True)
        us_ipos = list(existing_by_ticker_us.values())
    us_ipos = _enrich_ipo_closes(us_ipos, existing_by_ticker_us)

    existing_hk = existing_ipos.get("hk", [])
    try:
        hk_ipos = _fetch_tv_ipos(["hongkong"])
        hk_ipos = [
            i for i in hk_ipos
            if (i.get("deal_amount_usd") or 0) >= 50e6
            or (i.get("mkt_cap_usd")     or 0) >= 50e6
        ]
        print(f"[screener] Got {len(hk_ipos)} HK IPOs ($50M+ filter).", flush=True)
    except Exception as e:
        print(f"[screener] HK IPO fetch FAILED: {e}", flush=True)
        hk_ipos = existing_hk

    IPOS_OUT.write_text(json.dumps({"fetched_at": now_iso, "us": us_ipos, "hk": hk_ipos}, indent=2))
    print(f"[screener] Saved -> {IPOS_OUT}", flush=True)

    print("[screener] Done.", flush=True)


def main():
    asyncio.run(_main_async())


if __name__ == "__main__":
    main()
