#!/usr/bin/env python3
"""
barchart_fetch.py
Fetches ZQ (Fed Funds) futures strip from Barchart via headless Chromium,
intercepting the internal API call the page makes on load.

Outputs:  scripts/barchart_zq_cache.json
Run:      python scripts/barchart_fetch.py
"""

import json
import asyncio
from datetime import date, datetime
from pathlib import Path

from playwright.async_api import async_playwright

OUT_F = Path(__file__).resolve().parent / "barchart_zq_cache.json"

ZQ_URL  = "https://www.barchart.com/futures/quotes/ZQ*0/futures-prices"
API_PAT = "/proxies/core-api/v1/quotes/get"


async def fetch_zq() -> list[dict]:
    captured: list[dict] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        )
        page = await ctx.new_page()

        async def handle_response(response):
            if API_PAT in response.url and "root=ZQ" in response.url:
                try:
                    data = await response.json()
                    if data and data.get("data"):
                        captured.extend(data["data"])
                except Exception:
                    pass

        page.on("response", handle_response)

        await page.goto(ZQ_URL, wait_until="networkidle", timeout=30_000)
        await browser.close()

    return captured


def parse_contracts(raw: list[dict]) -> list[dict]:
    """Map Barchart fields to the same schema used by stir_pipeline._fetch_history."""
    out = []
    for r in raw:
        sym_bc = r.get("symbol", "")        # e.g. ZQK26
        sym_raw = r.get("raw", {})

        # Settle price: use previousPrice (prior day settle); fall back to lastPrice
        settle = sym_raw.get("previousPrice") or sym_raw.get("lastPrice")
        if not settle or settle == 0:
            continue

        volume = sym_raw.get("volume")
        oi     = sym_raw.get("openInterest")

        # Convert Barchart 2-digit year symbol → stir_pipeline convention (1-digit year)
        # ZQK26 → ZQK6,  ZQK27 → ZQK7, etc.
        if len(sym_bc) >= 5:
            root_month = sym_bc[:4]          # e.g. ZQK2 — no, let's split properly
            # format: ZQ + monthCode + 2-digit-year  e.g. ZQK26
            root     = sym_bc[:2]            # ZQ
            mc       = sym_bc[2]             # K
            yr2      = sym_bc[3:]            # 26
            yr1      = yr2[-1]               # 6
            sym_1d   = f"{root}{mc}{yr1}"    # ZQK6
        else:
            sym_1d = sym_bc

        out.append({
            "symbol_bc": sym_bc,   # Barchart format (ZQK26)
            "symbol":    sym_1d,   # Pipeline format (ZQK6)
            "settle":    round(float(settle), 4),
            "volume":    int(volume) if volume is not None else None,
            "oi":        int(oi)     if oi     is not None else None,
        })

    return out


def main():
    print("[barchart_fetch] Launching headless browser...", flush=True)
    raw = asyncio.run(fetch_zq())
    if not raw:
        print("[barchart_fetch] ERROR: No data captured — Barchart page may have changed.")
        raise SystemExit(1)

    contracts = parse_contracts(raw)
    print(f"[barchart_fetch] Captured {len(contracts)} ZQ contracts.", flush=True)

    payload = {
        "fetched_at": datetime.utcnow().isoformat() + "Z",
        "as_of_date": date.today().isoformat(),
        "contracts":  contracts,
    }
    OUT_F.write_text(json.dumps(payload, indent=2))
    print(f"[barchart_fetch] Saved -> {OUT_F}", flush=True)

    # Quick preview
    for c in contracts[:5]:
        print(f"  {c['symbol']:6s}  settle={c['settle']:.4f}  vol={c['volume']}  oi={c['oi']}")
    if len(contracts) > 5:
        print(f"  ... and {len(contracts)-5} more")


if __name__ == "__main__":
    main()
