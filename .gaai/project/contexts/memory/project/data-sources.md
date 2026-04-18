---
type: memory
category: project
id: PROJECT-002
tags:
  - data-sources
  - market-data
  - spx
  - mmth
  - market-regimes
created_at: 2026-04-18
updated_at: 2026-04-18
---

# Confirmed Market Data Sources

Sources verified against user-provided data on 2026-04-18.

---

## SPX (S&P 500) OHLC Historical Data

- **Source:** [Investing.com — S&P 500 Historical Data](https://www.investing.com/indices/us-spx-500-historical-data)
- **Data available:** Daily OHLC going back years
- **Verified:** April 15, 2026 High = 7,026.24 ✓

## MMTH (% Stocks Above 200-Day MA)

- **Primary source:** [EODData — INDEX/MMTH](https://www.eoddata.com/stockquote/INDEX/MMTH.htm)
  - Provides daily OHLC for MMTH; confirmed accurate to user data
  - Verified: Apr 15 = 54.99, Apr 16 = 55.45, Apr 17 = 58.54 ✓
- **Secondary source:** [Barchart — $MMTH](https://www.barchart.com/stocks/quotes/$MMTH)
  - Good for current value and recent range; interactive chart requires login for full history

## Data Rule (from project context)

- Always use SPX **daily high** (not close) for regime classification
- Report date = last trading session date (not viewer's calendar date)
