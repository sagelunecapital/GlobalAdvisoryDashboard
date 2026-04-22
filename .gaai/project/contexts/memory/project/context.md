---
type: memory
category: project
id: PROJECT-001
tags:
  - product
  - vision
  - scope
  - fund-management
  - dashboard
  - market-regimes
created_at: 2026-04-17
updated_at: 2026-04-18
depends_on:
  code_paths: []
  decisions: []
  epics: []
refresh_tier: 2
---

# Project Memory

## Project Overview

**Name:** Fund Manager Daily Dashboard

**Purpose:** A consolidated decision-support dashboard for fund managers. Aggregates daily market data and signals from multiple sources into a single interface, surfaces how those signals interact, and produces an alignment read that enables cohesive investment decisions. Starting with the market regime module; additional data modules to be added incrementally.

**Target Users:** Fund managers (internal team). Not a public product.

---

## Core Problems Being Solved

- Daily market data is fragmented across multiple sources — no single consolidated view
- Signal interaction and cross-indicator alignment is assessed manually, introducing inconsistency
- Decision-making requires reconciling multiple data points; the dashboard should surface the cohesive read directly

---

## Success Metrics

- All daily-check data consolidated in one interface
- Market regime correctly computed and displayed in real time
- Signal interaction and alignment visible without manual cross-referencing
- Fund managers can arrive at a cohesive decision read from the dashboard alone

---

## Tech Stack & Conventions

- **Language(s):** Python 3.x (DEC-2026-04-22-01)
- **Frameworks:** None yet — DB layer only
- **Data sources:** yfinance `^GSPC` for SPX; EODData (`EODDATA_API_KEY`) for MMTH (DEC-2026-04-22-02)
- **Database:** SQLite (WAL mode, `data/` directory)
- **Dependencies:** `requirements.txt` (yfinance, pandas, requests, pytest)
- **Key conventions:** `spx_daily_high` column name (DEC-2026-04-18-01); EMA via `pandas.ewm(span=N, adjust=False).mean()`; 2yr SPX fetch for EMA warm-up, trim to 1yr post-computation

---

## Architectural Boundaries

- TBD — no codebase yet

---

## Known Constraints

- No hard technical constraints declared yet
- Build incrementally: Market Regime module first, additional modules added over time

---

## Out of Scope (Permanent)

- TBD — to be defined as scope solidifies

---

## Module Inventory

### Module 1: Market Regimes (in scope — first to build)

Classifies current market conditions into one of three regimes: Red, Yellow, Green.

**Indicators:**
- SPX 12-day EMA
- SPX 25-day EMA
- MMTH — % of all US stocks above their 200-day MA (barcharts.com has this readily available)

**Data Sources:**
- MMTH: barcharts.com (confirmed available)
- SPX price + EMAs: TBD (no preferred source declared; Delivery to determine)

**Data Persistence:**
- A persistent database stores all historical indicator data (SPX price, 12d EMA, 25d EMA, MMTH)
- Minimum initial load: 1 year of historical data
- New daily data is appended on each refresh
- Historical data is never deleted

**Divergence Definition:**
SPX makes a new high (or low) but MMTH does not confirm with a corresponding new high (or low).
- *Bearish divergence:* SPX new high, MMTH lower than prior high
- *Bullish divergence:* SPX new low, MMTH higher than prior low (i.e., MMTH did not follow price down)

**Data Rules:**
- SPX price used in all calculations = **daily high**, not closing price
- Divergence period anchor = the **prior period's high** (the last confirmed high before the current run). Consecutive days that all make new highs against the same prior anchor belong to the same divergence run — they are NOT compared against each other (yesterday's high is not the anchor).
- Report date = **last trading session date**, not the viewer's current calendar date (e.g., if viewed on a Saturday, the report is dated Friday).

**Regime Classification Logic (8 conditions, validated):**

| # | Condition | Regime | Notes |
|---|-----------|--------|-------|
| 1 | SPX > 12d EMA, no divergence | 🟢 Green | Standard bull |
| 2 | SPX between 12d and 25d EMA, no divergence | 🟡 Yellow | Standard caution |
| 3 | SPX < 25d EMA, no divergence | 🔴 Red | Standard bear |
| 4 | SPX > 12d EMA + bearish divergence | 🟡 Yellow | Divergence downgrades Green |
| 5 | SPX < 25d EMA + bullish divergence | 🟡 Yellow | Divergence upgrades Red |
| 6 | SPX < 25d EMA + bearish divergence | 🔴 Red | Doubly bad, still Red |
| 7 | SPX between EMAs + bearish divergence | 🔴 Red | Theoretically valid, practically unlikely |
| 8 | SPX between EMAs + bullish divergence | 🟡 Yellow | Theoretically valid, practically unlikely |

**Design note ("price is king"):** EMA position is the baseline regime anchor. Divergence can shift regime by one step (Green↔Yellow, Red↔Yellow) but never two steps. Revisit classification if live output shows errors.

### Future Modules (known names — not yet scoped)

Each module maps to one or more Epics. Module name is declared in each Epic's `module` frontmatter field.

| Module | Status | Epic(s) |
|---|---|---|
| Market Regime | Active — E01 | E01 |
| Macro | Future | TBD |
| Liquidity | Future | TBD |
| Breadth | Future | TBD |
| Execution | Future | TBD |

Additional modules may be added incrementally. Each module feeds into the cross-signal alignment layer.
