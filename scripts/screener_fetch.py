#!/usr/bin/env python3
"""
screener_fetch.py
Fetches and enriches screener data in one pass:
  1. Top movers from Finviz (Playwright headless)
  2. IPO calendar from TradingView scanner API
  3. Catalyst enrichment via Claude API (skipped if ANTHROPIC_API_KEY not set)

Outputs:
  prototypes/screener_movers.json
  prototypes/screener_ipos.json
"""

import asyncio
import json
import os
import re
import time
import requests
from datetime import date, datetime, timedelta
from pathlib import Path

import anthropic
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

ROOT       = Path(__file__).resolve().parent.parent
MOVERS_OUT = ROOT / "prototypes" / "screener_movers.json"
IPOS_OUT   = ROOT / "prototypes" / "screener_ipos.json"

FINVIZ_URL = (
    "https://finviz.com/screener.ashx"
    "?v=111"
    "&f=cap_smallover,ind_stocksonlyspac,sh_curvol_o1000,sh_price_o1,"
    "sh_relvol_o2,ta_averagetruerange_o1,ta_perf_d5o,ta_perf2_1wup,ta_sma20_pa,ta_sma50_pa"
    "&ft=4&c=0,1,2,3,4,5,6,7,67,65,66,42&preset=s151594605"
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


# ── Parsers ──────────────────────────────────────────────────────────────────

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


# ── Finviz fetch ─────────────────────────────────────────────────────────────

async def _fetch_movers_async() -> list[dict]:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(user_agent=BROWSER_UA)
        page = await ctx.new_page()
        await page.goto(FINVIZ_URL, wait_until="load", timeout=45_000)
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


# ── TradingView IPO fetch ────────────────────────────────────────────────────

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

    ipos = [
        i for i in ipos
        if (i.get("deal_amount_usd") or 0) >= 300e6
        or (i.get("mkt_cap_usd")     or 0) >= 300e6
    ]

    print(f"[screener] Got {len(ipos)} IPOs ($300M+ filter) from TradingView.", flush=True)
    return ipos


def enrich_ipo_closes(ipos: list[dict], existing_by_ticker: dict) -> list[dict]:
    import yfinance as yf
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
            hist = yf.download(ticker, start=ipo_date.isoformat(), end=end.isoformat(),
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


# ── Catalyst enrichment (Claude API) ────────────────────────────────────────

def _ddg_fool_links(ticker: str, company: str, move_date: str) -> list[str]:
    query = f'site:fool.com {ticker} {company} {move_date}'
    url   = f'https://html.duckduckgo.com/html/?q={requests.utils.quote(query)}'
    try:
        resp = requests.get(url, headers={"User-Agent": BROWSER_UA}, timeout=15)
        soup = BeautifulSoup(resp.text, "html.parser")
        links = []
        for a in soup.select("a.result__url"):
            href = a.get("href", "")
            if "fool.com" in href and any(
                seg in href for seg in ["/investing/", "/the-", "/earnings/", "/coverage/"]
            ):
                links.append(href)
        return links[:3]
    except Exception:
        return []


async def _scrape_article(url: str) -> str | None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx  = await browser.new_context(user_agent=BROWSER_UA)
        page = await ctx.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=25_000)
            text = await page.evaluate("""
                () => {
                    for (const sel of ['article', '[data-testid="article-body"]',
                                       '.article-body', '.tailwind-article-body',
                                       'main']) {
                        const el = document.querySelector(sel);
                        if (el && el.innerText.length > 200)
                            return el.innerText.slice(0, 6000);
                    }
                    return document.body.innerText.slice(0, 6000);
                }
            """)
            return text.strip() if text and len(text) > 100 else None
        except Exception:
            return None
        finally:
            await browser.close()


def _ddg_news_snippets(ticker: str, company: str, move_date: str) -> str:
    query = f'{ticker} {company} stock move news {move_date}'
    url   = f'https://html.duckduckgo.com/html/?q={requests.utils.quote(query)}'
    try:
        resp = requests.get(url, headers={"User-Agent": BROWSER_UA}, timeout=15)
        soup = BeautifulSoup(resp.text, "html.parser")
        snippets = [s.get_text(" ", strip=True) for s in soup.select(".result__snippet")]
        return "\n".join(snippets[:6])
    except Exception:
        return ""


def _summarise(client: anthropic.Anthropic,
               ticker: str, company: str, change_pct: float,
               move_date: str, article_text: str | None, snippets: str) -> dict:
    if article_text:
        prompt = (
            f"You are a concise financial analyst. "
            f"Based on the Motley Fool article below, write exactly 3-4 sentences "
            f"explaining why {company} ({ticker}) moved {change_pct:+.2f}% on {move_date}. "
            f"Be specific: name the exact catalyst (earnings beat, product launch, M&A, etc.), "
            f"cite key figures where mentioned, and explain the business context. "
            f"Write only the summary — no headers, no preamble.\n\n"
            f"Article:\n{article_text[:5000]}"
        )
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        source = "Motley Fool"
    else:
        prompt = (
            f"Search for news about why {company} ({ticker}) stock moved "
            f"{change_pct:+.2f}% on {move_date}. "
            f"Then write exactly 3-4 sentences explaining the catalyst. "
            f"Name the exact event (earnings beat/miss, analyst action, product news, "
            f"M&A, FDA/regulatory decision, macro event), cite key figures, "
            f"and explain the business context. "
            f"Write only the summary — no headers, no preamble."
        )
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=500,
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 2}],
            messages=[{"role": "user", "content": prompt}],
        )
        source = "Claude | Web"

    text_parts = [block.text.strip() for block in msg.content if hasattr(block, "text")]
    text = " ".join(p for p in text_parts if p)
    lines = [l for l in text.splitlines() if not l.startswith("#")]
    catalyst = "\n".join(lines).strip()
    return {"catalyst": catalyst, "source": source, "source_url": None}


async def _enrich_one(client: anthropic.Anthropic, mover: dict, move_date: str) -> dict:
    ticker     = mover["ticker"]
    company    = mover.get("company", ticker)
    change_pct = mover.get("change_pct") or 0.0

    print(f"  [{ticker}] searching Motley Fool...", flush=True)
    links = _ddg_fool_links(ticker, company, move_date)

    article_text = None
    source_url   = None
    for link in links:
        print(f"  [{ticker}] trying {link[:70]}...", flush=True)
        text = await _scrape_article(link)
        if text:
            pct_pat = re.compile(r'\d+\s*%', re.I)
            if ticker.upper() in text.upper() and pct_pat.search(text):
                article_text = text
                source_url   = link
                print(f"  [{ticker}] article captured ({len(text)} chars)", flush=True)
                break

    if not article_text:
        print(f"  [{ticker}] no article — using web snippets + Claude knowledge", flush=True)
        snippets = _ddg_news_snippets(ticker, company, move_date)
    else:
        snippets = ""

    result = _summarise(client, ticker, company, change_pct, move_date, article_text, snippets)
    result["source_url"] = source_url
    mover.update(result)
    return mover


async def _enrich_movers(movers: list[dict], today: str) -> list[dict]:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("[enrich] ANTHROPIC_API_KEY not set — skipping enrichment.", flush=True)
        return movers

    to_enrich = [m for m in movers if not m.get("catalyst")]
    if not to_enrich:
        print(f"[enrich] All {len(movers)} movers already enriched.", flush=True)
        return movers

    print(f"[enrich] Enriching {len(to_enrich)} movers for {today}...", flush=True)
    client = anthropic.Anthropic(api_key=api_key)

    enriched = []
    for mover in movers:
        if not mover.get("catalyst"):
            mover = await _enrich_one(client, mover, today)
            time.sleep(0.5)
        enriched.append(mover)
    return enriched


# ── Main ─────────────────────────────────────────────────────────────────────

async def _main_async():
    now_iso = datetime.utcnow().isoformat() + "Z"
    today   = date.today().isoformat()

    # Movers
    existing_by_date: dict = {}
    if MOVERS_OUT.exists():
        try:
            existing_by_date = json.loads(MOVERS_OUT.read_text()).get("by_date", {})
        except Exception:
            pass

    try:
        movers = fetch_movers()
    except Exception as e:
        print(f"[screener] Movers fetch FAILED: {e}", flush=True)
        movers = existing_by_date.get(today, [])

    if movers:
        movers = await _enrich_movers(movers, today)
        existing_by_date[today] = movers

    MOVERS_OUT.write_text(json.dumps({"updated_at": now_iso, "by_date": existing_by_date}, indent=2))
    print(f"[screener] Saved -> {MOVERS_OUT}", flush=True)

    # IPOs
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

    IPOS_OUT.write_text(json.dumps({"fetched_at": now_iso, "ipos": ipos}, indent=2))
    print(f"[screener] Saved -> {IPOS_OUT}", flush=True)


def main():
    asyncio.run(_main_async())


if __name__ == "__main__":
    main()
