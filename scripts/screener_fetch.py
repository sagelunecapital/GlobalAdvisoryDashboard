#!/usr/bin/env python3
"""
screener_fetch.py
Fetches:
  1. Top movers from Finviz (Playwright headless – React-rendered page)
  2. IPO calendar from TradingView scanner API (requests.post)

Outputs:
  prototypes/screener_movers.json
  prototypes/screener_ipos.json
"""

import asyncio
import json
import requests
from datetime import date, datetime, timedelta
from pathlib import Path

from playwright.async_api import async_playwright

ROOT       = Path(__file__).resolve().parent.parent
MOVERS_OUT = ROOT / "prototypes" / "screener_movers.json"
IPOS_OUT   = ROOT / "prototypes" / "screener_ipos.json"

FINVIZ_URL = (
    "https://finviz.com/screener.ashx"
    "?v=111"
    "&f=cap_smallover,ind_stocksonlyspac,sh_curvol_o1000,sh_price_o1,"
    "sh_relvol_o2,ta_averagetruerange_o1,ta_perf_d5o,ta_sma200_pa"
    "&ft=4&o=-change"
)

TV_IPO_URL = "https://scanner.tradingview.com/global/scan?label-product=calendar-ipo"

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# JS injected into the rendered Finviz page to extract screener rows.
# v=111 column order: No, Ticker, Company, Sector, Industry,
#                     Country, Mkt Cap, P/E, Price, Change, Volume
_FINVIZ_EXTRACT_JS = """
() => {
  const rows = document.querySelectorAll('table tr');
  const out = [];
  rows.forEach(row => {
    const cells = row.querySelectorAll('td');
    if (cells.length < 11) return;
    const a = cells[1].querySelector('a');
    if (!a || !/^[A-Z]{1,5}$/.test(a.textContent.trim())) return;
    out.push({
      ticker:   cells[1].textContent.trim(),
      company:  cells[2].textContent.trim(),
      sector:   cells[3].textContent.trim(),
      industry: cells[4].textContent.trim(),
      country:  cells[5].textContent.trim(),
      mkt_cap:  cells[6].textContent.trim(),
      pe:       cells[7].textContent.trim(),
      price:    cells[8].textContent.trim(),
      change:   cells[9].textContent.trim(),
      volume:   cells[10].textContent.trim(),
    });
  });
  return out;
}
"""


def _parse_float(s):
    try:
        return float(str(s).replace("%", "").replace(",", "").replace("$", "").strip())
    except Exception:
        return None


def _parse_vol(s):
    s = str(s).replace(",", "").strip()
    try:
        if s.upper().endswith("M"):
            return int(float(s[:-1]) * 1_000_000)
        if s.upper().endswith("K"):
            return int(float(s[:-1]) * 1_000)
        if s.upper().endswith("B"):
            return int(float(s[:-1]) * 1_000_000_000)
        return int(float(s))
    except Exception:
        return None


def _parse_mc(s):
    s = str(s).strip()
    try:
        if s.upper().endswith("T"):
            return float(s[:-1]) * 1e12
        if s.upper().endswith("B"):
            return float(s[:-1]) * 1e9
        if s.upper().endswith("M"):
            return float(s[:-1]) * 1e6
        return float(s)
    except Exception:
        return None


async def _fetch_movers_async() -> list[dict]:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(user_agent=BROWSER_UA)
        page = await ctx.new_page()
        await page.goto(FINVIZ_URL, wait_until="load", timeout=45_000)
        # Wait until at least one ticker row is visible
        await page.wait_for_selector("table tr td a", timeout=20_000)
        raw = await page.evaluate(_FINVIZ_EXTRACT_JS)
        await browser.close()
    return raw


def fetch_movers() -> list[dict]:
    print("[screener] Fetching Finviz movers (headless)...", flush=True)
    raw = asyncio.run(_fetch_movers_async())
    movers = []
    for r in raw:
        movers.append({
            "ticker":     r["ticker"],
            "company":    r["company"],
            "sector":     r["sector"],
            "industry":   r["industry"],
            "country":    r["country"],
            "mkt_cap":    _parse_mc(r["mkt_cap"]),
            "pe":         _parse_float(r["pe"]),
            "price":      _parse_float(r["price"]),
            "change_pct": _parse_float(r["change"]),
            "volume":     _parse_vol(r["volume"]),
        })
    print(f"[screener] Got {len(movers)} movers from Finviz.", flush=True)
    return movers


def fetch_ipos() -> list[dict]:
    print("[screener] Fetching IPOs from TradingView...", flush=True)
    today = date.today()
    start = today - timedelta(days=14)
    end   = today + timedelta(days=90)

    start_ts = int(datetime.combine(start, datetime.min.time()).timestamp())
    end_ts   = int(datetime.combine(end,   datetime.max.time()).timestamp())

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
        "markets": ["america"],
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

        # d[0]=logo, d[1]=ticker_symbol, d[2]=company_name, d[3]=typespecs,
        # d[4]=type, d[5]=exchange, d[6]=market, d[7]=ipo_offer_time (unix),
        # d[8]=price_usd, d[9]=status_code, d[10]=status_display,
        # d[11]=shares, d[12]=deal_amount, d[13]=mkt_cap, d[14]=price_range
        ticker  = d[1] or row.get("s", "").split(":")[-1]
        company = d[2] or ""
        exch    = d[5] or ""
        offer_ts = d[7]
        price_usd  = d[8]
        status     = d[10] or d[9] or ""
        shares     = d[11]
        deal_amt   = d[12]
        mkt_cap    = d[13]
        price_range = d[14]

        if offer_ts:
            ipo_date = datetime.utcfromtimestamp(offer_ts).strftime("%Y-%m-%d")
        else:
            ipo_date = None

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

    # Filter: deal size OR market cap >= $300M
    ipos = [
        i for i in ipos
        if (i.get("deal_amount_usd") or 0) >= 300e6
        or (i.get("mkt_cap_usd")     or 0) >= 300e6
    ]

    print(f"[screener] Got {len(ipos)} IPOs ($300M+ filter) from TradingView.", flush=True)
    return ipos


def enrich_ipo_closes(ipos: list[dict], existing_by_ticker: dict) -> list[dict]:
    """Fetch closing price on IPO day for past IPOs using yfinance."""
    import yfinance as yf
    today = date.today()
    for ipo in ipos:
        ticker = ipo.get("ticker")
        if not ticker:
            continue
        # Carry over already-fetched close
        if existing_by_ticker.get(ticker, {}).get("ipo_close") is not None:
            ipo["ipo_close"] = existing_by_ticker[ticker]["ipo_close"]
            continue
        ipo_date_str = ipo.get("date")
        if not ipo_date_str:
            continue
        ipo_date = date.fromisoformat(ipo_date_str)
        if ipo_date >= today:   # Future or today — no close yet
            continue
        try:
            end = ipo_date + timedelta(days=5)
            hist = yf.download(
                ticker,
                start=ipo_date.isoformat(),
                end=end.isoformat(),
                progress=False,
                auto_adjust=True,
            )
            if not hist.empty:
                close_val = hist["Close"].iloc[0]
                # yfinance may return a Series; extract scalar
                if hasattr(close_val, "item"):
                    close_val = close_val.item()
                ipo["ipo_close"] = round(float(close_val), 2)
                print(f"[screener]   {ticker} IPO close: ${ipo['ipo_close']:.2f}", flush=True)
        except Exception as e:
            print(f"[screener]   {ticker} close fetch failed: {e}", flush=True)
    return ipos


def main():
    now_iso = datetime.utcnow().isoformat() + "Z"
    today   = date.today().isoformat()

    # ── Movers: accumulate by date ──────────────────────────────────────────
    existing_by_date: dict = {}
    if MOVERS_OUT.exists():
        try:
            existing_by_date = json.loads(MOVERS_OUT.read_text()).get("by_date", {})
        except Exception:
            existing_by_date = {}

    try:
        movers = fetch_movers()
    except Exception as e:
        print(f"[screener] Movers fetch FAILED: {e}", flush=True)
        movers = []

    if movers:
        existing_by_date[today] = movers

    MOVERS_OUT.write_text(json.dumps({
        "updated_at": now_iso,
        "by_date":    existing_by_date,
    }, indent=2))
    print(f"[screener] Saved -> {MOVERS_OUT}", flush=True)

    # ── IPOs: preserve existing close prices, enrich new ones ──────────────
    existing_by_ticker: dict = {}
    if IPOS_OUT.exists():
        try:
            for old in json.loads(IPOS_OUT.read_text()).get("ipos", []):
                if old.get("ticker"):
                    existing_by_ticker[old["ticker"]] = old
        except Exception:
            pass

    try:
        ipos = fetch_ipos()
    except Exception as e:
        print(f"[screener] IPO fetch FAILED: {e}", flush=True)
        ipos = []

    ipos = enrich_ipo_closes(ipos, existing_by_ticker)

    IPOS_OUT.write_text(json.dumps({
        "fetched_at": now_iso,
        "ipos":       ipos,
    }, indent=2))
    print(f"[screener] Saved -> {IPOS_OUT}", flush=True)


if __name__ == "__main__":
    main()
