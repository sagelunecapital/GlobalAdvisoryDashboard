#!/usr/bin/env python3
"""
screener_fetch_cn.py
Fetches China/HK movers from the TradingView CN screener (Playwright headless).

Output: prototypes/screener_movers_cn.json  {updated_at, by_date:{date:[rows]}}
"""

import asyncio
import json
from datetime import date, datetime, timedelta
from pathlib import Path


def _safe_trading_day(d: date) -> date:
    """Return d if weekday, else the most recent Friday."""
    while d.weekday() >= 5:
        d = d - timedelta(days=1)
    return d

from playwright.async_api import async_playwright

ROOT          = Path(__file__).resolve().parent.parent
MOVERS_CN_OUT = ROOT / "prototypes" / "screener_movers_cn.json"

TV_SCREENER_CN_URL = "https://www.tradingview.com/screener/YUifpXoa/"

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# Extracts rows from a TradingView screener page.
# HK stocks: 4-5 digit numeric ticker, mkt cap as "68.54 B HKD" (converted to USD).
_EXTRACT_JS = r"""
() => {
  const rows = [];
  document.querySelectorAll('tr[class*="row"]').forEach(tr => {
    const cells = Array.from(tr.querySelectorAll('td'));
    if (cells.length < 3) return;
    const texts = cells.map(td => td.textContent.trim());
    const first = texts[0];
    if (!first) return;
    const tickerM = first.match(/^([0-9]{3,5}|[A-Z0-9\.]{2,6})/);
    if (!tickerM) return;
    const ticker = tickerM[1];
    if (ticker.length < 2) return;
    let company = first.slice(ticker.length).replace(/\s+[A-Z]\s*$/, '').trim();
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


async def _fetch_async() -> list:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(user_agent=BROWSER_UA)
        page = await ctx.new_page()
        await page.goto(TV_SCREENER_CN_URL, wait_until="networkidle", timeout=45_000)
        # Switch from chart view to table view
        try:
            await page.click(
                'button[class*="segmentedControl"]:not([class*="checked"])',
                timeout=8_000,
            )
            await page.wait_for_selector('tr[class*="row"]', timeout=15_000)
        except Exception:
            pass
        await page.wait_for_timeout(2_000)
        rows = await page.evaluate(_EXTRACT_JS)
        await browser.close()
    return rows


def main():
    print("[screener_cn] Fetching TradingView China movers...", flush=True)
    now_iso  = datetime.utcnow().isoformat() + "Z"
    today    = _safe_trading_day(date.today()).isoformat()

    existing_by_date: dict = {}
    if MOVERS_CN_OUT.exists():
        try:
            existing_by_date = json.loads(
                MOVERS_CN_OUT.read_text(encoding="utf-8")
            ).get("by_date", {})
        except Exception:
            pass

    try:
        movers = asyncio.run(_fetch_async())
        print(f"[screener_cn] Got {len(movers)} movers.", flush=True)
    except Exception as e:
        print(f"[screener_cn] Fetch FAILED: {e}", flush=True)
        movers = existing_by_date.get(today, [])

    if movers:
        existing_by_date[today] = movers

    MOVERS_CN_OUT.write_text(
        json.dumps(
            {"updated_at": now_iso, "by_date": existing_by_date},
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"[screener_cn] Saved -> {MOVERS_CN_OUT}", flush=True)


if __name__ == "__main__":
    main()
