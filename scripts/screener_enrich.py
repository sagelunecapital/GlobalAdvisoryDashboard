#!/usr/bin/env python3
"""
screener_enrich.py
Enriches US movers with Claude-generated catalysts, catalyst_type,
continuation flags, and thematic group assignments.

Reads / writes: prototypes/screener_movers.json
Requires: ANTHROPIC_API_KEY environment variable
"""

import asyncio
import json
import os
import re
import time
from datetime import date, timedelta
from pathlib import Path

import anthropic
import requests
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

ROOT       = Path(__file__).resolve().parent.parent
MOVERS_OUT = ROOT / "prototypes" / "screener_movers.json"

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

CATALYST_TYPES = ("earnings", "guidance", "analyst", "macro", "other")


def _prev_trading_day(d: date) -> date:
    d = d - timedelta(days=1)
    while d.weekday() >= 5:
        d = d - timedelta(days=1)
    return d


# ── Helpers ──────────────────────────────────────────────────────────────────

def _ddg_fool_links(ticker: str, move_date: str) -> list[str]:
    query = f'site:fool.com {ticker} {move_date}'
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


def _ddg_news_snippets(ticker: str, move_date: str) -> str:
    query = f'{ticker} stock move news {move_date}'
    url   = f'https://html.duckduckgo.com/html/?q={requests.utils.quote(query)}'
    try:
        resp = requests.get(url, headers={"User-Agent": BROWSER_UA}, timeout=15)
        soup = BeautifulSoup(resp.text, "html.parser")
        snippets = [s.get_text(" ", strip=True) for s in soup.select(".result__snippet")]
        return "\n".join(snippets[:6])
    except Exception:
        return ""


# ── Summarisation ─────────────────────────────────────────────────────────────

_SUMMARY_RULES = """\
Rules:
- Refer to the stock by ticker only (e.g. HPQ, ZM) - never use the full company name
- Use plain hyphens (-) instead of em dashes
- 3-4 sentences maximum
- Lead with the most specific, stock-level catalyst (earnings beat/miss, guidance raise/cut, \
product launch, M&A, FDA decision, analyst action)
- Mention broad market or sector tailwinds only if they are the sole driver; \
if a stock-specific catalyst exists, omit or compress generic macro commentary to one clause at most
- catalyst_type must be exactly one of: earnings, guidance, analyst, macro, other
  - earnings: an earnings report (beat, miss, in-line) is the primary driver
  - guidance: forward guidance raise or cut is the primary driver (even if paired with earnings)
  - analyst: analyst upgrade, downgrade, or price target change is the primary driver
  - macro: no stock-specific catalyst; purely a broad market / sector move
  - other: product launch, M&A, FDA/regulatory decision, partnership, or any other specific event
Return ONLY a JSON object with two fields: {"catalyst": "...", "catalyst_type": "..."}"""


def _summarise(client: anthropic.Anthropic,
               ticker: str, change_pct: float,
               move_date: str, article_text: str | None,
               snippets: str) -> dict:
    if article_text:
        prompt = (
            f"You are a concise financial analyst. "
            f"Based on the Motley Fool article below, explain why {ticker} moved "
            f"{change_pct:+.2f}% on {move_date}.\n\n"
            f"{_SUMMARY_RULES}\n\n"
            f"Article:\n{article_text[:5000]}"
        )
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=350,
            messages=[{"role": "user", "content": prompt}],
        )
        source = "Motley Fool"
    else:
        prompt = (
            f"Search for news about why {ticker} stock moved {change_pct:+.2f}% on {move_date}. "
            f"Then explain the catalyst.\n\n"
            f"{_SUMMARY_RULES}"
        )
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=500,
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 2}],
            messages=[{"role": "user", "content": prompt}],
        )
        source = "Claude | Web"

    text_parts = [block.text.strip() for block in msg.content if hasattr(block, "text")]
    raw = " ".join(p for p in text_parts if p)

    # Parse JSON response; fall back to raw text if needed
    m = re.search(r'\{.*\}', raw, re.DOTALL)
    if m:
        try:
            parsed = json.loads(m.group())
            catalyst = parsed.get("catalyst", raw).strip()
            catalyst_type = parsed.get("catalyst_type", "other")
            if catalyst_type not in CATALYST_TYPES:
                catalyst_type = "other"
            return {"catalyst": catalyst, "catalyst_type": catalyst_type, "source": source, "source_url": None}
        except Exception:
            pass

    # Fallback: use raw text, no catalyst_type
    lines = [l for l in raw.splitlines() if not l.startswith("#")]
    return {"catalyst": "\n".join(lines).strip(), "catalyst_type": "other", "source": source, "source_url": None}


# ── Group detection ───────────────────────────────────────────────────────────

def _assign_groups(client: anthropic.Anthropic, movers: list[dict], move_date: str) -> list[dict]:
    """Identify thematic groups and assign group_id + group_summary."""
    if len(movers) < 2:
        return movers

    mover_list = "\n".join(
        f"- {m['ticker']} ({m.get('change_pct', 0):+.2f}%): {m.get('catalyst', '')[:200]}"
        for m in movers
    )

    prompt = (
        f"Below are stock movers from {move_date} with their catalysts.\n\n"
        f"{mover_list}\n\n"
        f"Identify stocks that moved for the SAME specific thematic reason "
        f"(same sector theme such as quantum computing, AI infrastructure, biotech catalyst, "
        f"same news event, same macro driver). "
        f"Group by shared catalyst - do NOT group just because stocks are in the same sector.\n"
        f"Include a ticker in a group even if it did not appear in yesterday's movers, "
        f"as long as it belongs to the same theme today.\n\n"
        f"Return a JSON array of groups (empty array [] if no clear groups):\n"
        f'[{{"group_id": "short-kebab-slug", "tickers": ["TICK1","TICK2"], '
        f'"group_summary": "2-3 sentences on the shared catalyst. Ticker symbols only, no company names. '
        f'Plain hyphens, no em dashes."}}]\n'
        f"Return ONLY the JSON array, no other text."
    )

    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = " ".join(b.text.strip() for b in msg.content if hasattr(b, "text"))
    m = re.search(r'\[.*\]', raw, re.DOTALL)
    if not m:
        return movers

    try:
        groups = json.loads(m.group())
    except Exception:
        return movers

    ticker_to_group: dict[str, dict] = {}
    for g in groups:
        gid     = g.get("group_id", "")
        summary = g.get("group_summary", "")
        for t in g.get("tickers", []):
            ticker_to_group[t.upper()] = {"group_id": gid, "group_summary": summary}

    for mover in movers:
        assignment = ticker_to_group.get(mover["ticker"].upper())
        if assignment:
            mover["group_id"]      = assignment["group_id"]
            mover["group_summary"] = assignment["group_summary"]

    print(f"[enrich] Groups detected: {[g.get('group_id') for g in groups]}", flush=True)
    return movers


# ── Continuation detection ────────────────────────────────────────────────────

def _mark_continuation(movers: list[dict], by_date: dict, date_key: str) -> list[dict]:
    """Flag movers whose ticker also appeared on the previous trading day."""
    prev_key     = _prev_trading_day(date.fromisoformat(date_key)).isoformat()
    prev_tickers = {m["ticker"].upper() for m in by_date.get(prev_key, [])}
    for mover in movers:
        if mover["ticker"].upper() in prev_tickers:
            mover["continuation"] = True
    flagged = [m["ticker"] for m in movers if m.get("continuation")]
    if flagged:
        print(f"[enrich] Continuation flags: {flagged}", flush=True)
    return movers


# ── Per-mover enrichment ──────────────────────────────────────────────────────

async def _enrich_one(client: anthropic.Anthropic, mover: dict, move_date: str) -> dict:
    ticker     = mover["ticker"]
    change_pct = mover.get("change_pct") or 0.0

    print(f"  [{ticker}] searching Motley Fool...", flush=True)
    links = _ddg_fool_links(ticker, move_date)

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
        print(f"  [{ticker}] no article - using web snippets + Claude", flush=True)
        snippets = _ddg_news_snippets(ticker, move_date)
    else:
        snippets = ""

    result = _summarise(client, ticker, change_pct, move_date, article_text, snippets)
    result["source_url"] = source_url
    mover.update(result)
    return mover


# ── Main ──────────────────────────────────────────────────────────────────────

async def _run():
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("[enrich] ANTHROPIC_API_KEY not set - skipping.", flush=True)
        return

    if not MOVERS_OUT.exists():
        print("[enrich] screener_movers.json not found - run screener_fetch.py first.", flush=True)
        return

    data    = json.loads(MOVERS_OUT.read_text())
    by_date = data.get("by_date", {})

    # Use prev_trading_day as the date key (matches screener_fetch.py logic)
    date_key = _prev_trading_day(date.today()).isoformat()
    movers   = by_date.get(date_key, [])

    if not movers:
        print(f"[enrich] No movers for {date_key} - nothing to enrich.", flush=True)
        return

    # Mark continuation moves before enrichment
    movers = _mark_continuation(movers, by_date, date_key)

    to_enrich = [m for m in movers if not m.get("catalyst")]
    if not to_enrich:
        print(f"[enrich] All {len(movers)} movers already enriched.", flush=True)
        # Still re-run group detection in case it was skipped
        _assign_groups(anthropic.Anthropic(api_key=api_key), movers, date_key)
        by_date[date_key] = movers
        data["by_date"]   = by_date
        MOVERS_OUT.write_text(json.dumps(data, indent=2))
        return

    print(f"[enrich] Enriching {len(to_enrich)} movers for {date_key}...", flush=True)
    client = anthropic.Anthropic(api_key=api_key)

    enriched = []
    for mover in movers:
        if not mover.get("catalyst"):
            mover = await _enrich_one(client, mover, date_key)
            time.sleep(0.5)
        enriched.append(mover)

    # Assign thematic groups across all enriched movers
    enriched = _assign_groups(client, enriched, date_key)

    by_date[date_key] = enriched
    data["by_date"]   = by_date
    MOVERS_OUT.write_text(json.dumps(data, indent=2))
    print(f"[enrich] Done - saved -> {MOVERS_OUT}", flush=True)


def main():
    asyncio.run(_run())


if __name__ == "__main__":
    main()
