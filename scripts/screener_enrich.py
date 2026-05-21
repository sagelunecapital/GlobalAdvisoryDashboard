#!/usr/bin/env python3
"""
screener_enrich.py
For each mover in today's screener data, finds a catalyst article from Motley Fool
and summarizes it with Claude API.  Falls back to a Claude-generated summary based
on web search results when no article is found.

Reads / writes: prototypes/screener_movers.json  (adds catalyst/source per mover)
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

# ── Helpers ─────────────────────────────────────────────────────────────────

def _ddg_fool_links(ticker: str, company: str, move_date: str) -> list[str]:
    """Use DuckDuckGo HTML endpoint to find Motley Fool article URLs."""
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
    """Return the visible text of a Motley Fool article (up to 6000 chars)."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx  = await browser.new_context(user_agent=BROWSER_UA)
        page = await ctx.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=25_000)
            # Try to grab the article body
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
    """Fetch DuckDuckGo news snippets as fallback context for Claude."""
    query = f'{ticker} {company} stock move news {move_date}'
    url   = f'https://html.duckduckgo.com/html/?q={requests.utils.quote(query)}'
    try:
        resp = requests.get(url, headers={"User-Agent": BROWSER_UA}, timeout=15)
        soup = BeautifulSoup(resp.text, "html.parser")
        snippets = [s.get_text(" ", strip=True) for s in soup.select(".result__snippet")]
        return "\n".join(snippets[:6])
    except Exception:
        return ""


# ── Summarisation ────────────────────────────────────────────────────────────

def _summarise(client: anthropic.Anthropic,
               ticker: str, company: str, change_pct: float,
               move_date: str, article_text: str | None,
               snippets: str) -> dict:
    """
    Call Claude to write a 3-4 sentence catalyst summary.
    Returns {'catalyst': str, 'source': str, 'source_url': str | None}
    """
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

    # Extract text from final response (web_search may produce multiple content blocks)
    text_parts = [block.text.strip() for block in msg.content if hasattr(block, "text")]
    text = " ".join(p for p in text_parts if p)
    # Strip any header lines Claude may prepend (e.g. "# Company +X% on DATE")
    lines = [l for l in text.splitlines() if not l.startswith("#")]
    catalyst = "\n".join(lines).strip()
    return {
        "catalyst":    catalyst,
        "source":      source,
        "source_url":  None,
    }


# ── Per-mover enrichment ─────────────────────────────────────────────────────

async def _enrich_one(client: anthropic.Anthropic,
                       mover: dict, move_date: str) -> dict:
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
            # Confirm the article is about today's move (look for ticker or >10% / price ref)
            pct_pat = re.compile(r'\d+\s*%', re.I)
            if ticker.upper() in text.upper() and pct_pat.search(text):
                article_text = text
                source_url   = link
                print(f"  [{ticker}] article captured ({len(text)} chars)", flush=True)
                break

    if not article_text:
        print(f"  [{ticker}] no article found — using web snippets + Claude knowledge", flush=True)
        snippets = _ddg_news_snippets(ticker, company, move_date)
    else:
        snippets = ""

    result = _summarise(client, ticker, company, change_pct,
                         move_date, article_text, snippets)
    result["source_url"] = source_url

    mover.update(result)
    return mover


# ── Main ─────────────────────────────────────────────────────────────────────

async def _run():
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("[enrich] ANTHROPIC_API_KEY not set — skipping enrichment.", flush=True)
        return

    if not MOVERS_OUT.exists():
        print("[enrich] screener_movers.json not found — run screener_fetch.py first.", flush=True)
        return

    data = json.loads(MOVERS_OUT.read_text())
    by_date = data.get("by_date", {})
    today   = date.today().isoformat()

    movers = by_date.get(today, [])
    if not movers:
        print(f"[enrich] No movers for {today} — nothing to enrich.", flush=True)
        return

    # Only enrich movers that don't already have a catalyst
    to_enrich = [m for m in movers if not m.get("catalyst")]
    if not to_enrich:
        print(f"[enrich] All {len(movers)} movers already enriched.", flush=True)
        return

    print(f"[enrich] Enriching {len(to_enrich)} movers for {today}...", flush=True)
    client = anthropic.Anthropic(api_key=api_key)

    enriched = []
    for mover in movers:
        if not mover.get("catalyst"):
            mover = await _enrich_one(client, mover, today)
            time.sleep(0.5)   # be gentle with APIs
        enriched.append(mover)

    by_date[today] = enriched
    data["by_date"] = by_date
    MOVERS_OUT.write_text(json.dumps(data, indent=2))
    print(f"[enrich] Done — saved -> {MOVERS_OUT}", flush=True)


def main():
    asyncio.run(_run())


if __name__ == "__main__":
    main()
