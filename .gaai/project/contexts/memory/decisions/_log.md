---
type: memory
category: decisions
id: DECISIONS-LOG
tags:
  - decisions
  - governance
created_at: 2026-04-18
updated_at: 2026-04-22
---

# Decision Log

> Append-only. Never delete or overwrite decisions.
> Only the Discovery Agent may add entries (or Bootstrap Agent during initialization).
> Format: one entry per decision, newest at top.
> For large projects, split by domain: `decisions/auth.md`, `decisions/api.md`, etc.

---

### DEC-2026-04-22-02 — MMTH Source: EODData (yfinance ^MMTH Unavailable)

**Context:** E01S06 required fetching MMTH (% of US stocks above their 200-day MA). The execution plan specified yfinance `^MMTH` as primary with EODData as fallback.
**Decision:** EODData (`eodhistoricaldata.com`) is the active data source for MMTH. yfinance `^MMTH` returns HTTP 404 (ticker delisted or never supported on Yahoo Finance as of 2026-04-22).
**Rationale:** Live verification during implementation confirmed `^MMTH` unavailability. EODData fallback is implemented in `src/fetch/mmth.py` and requires `EODDATA_API_KEY` environment variable. All tests use mocked fixtures.
**Impact:** Production deployment requires configuring `EODDATA_API_KEY` before running historical load or daily append. E01S01 (live fetch) must use the same EODData source for MMTH. Pre-go-live prerequisite: confirm EODData free tier covers 252+ days of MMTH history.
**Date:** 2026-04-22

---

### DEC-2026-04-22-01 — Tech Stack: Python + SQLite + yfinance + pandas

**Context:** E01S06 was the first code story for the project; no tech stack was declared. Tech choice was left open for Delivery.
**Decision:** The project uses Python 3.x with SQLite (WAL mode via built-in `sqlite3`), yfinance for SPX data, and pandas for EMA computation.
**Rationale:** Python: dominant for financial data/EMA work; yfinance and pandas provide direct SPX OHLC and EMA computation. SQLite: only candidate satisfying zero-ops overhead AND ACID guarantees simultaneously (CSV fails AC6; PostgreSQL adds operational cost). WAL mode enables concurrent reads without blocking.
**Impact:** All future delivery stories use this stack. `spx_daily_high` EMA computation uses `pandas.ewm(span=N, adjust=False).mean()`. DB files stored in `data/` directory. `requirements.txt` is the dependency manifest.
**Date:** 2026-04-22

---

## Entry Template

```markdown
### DEC-YYYY-MM-DD-NN — [Decision Title]

**Context:** Why a decision was needed.
**Decision:** What was chosen.
**Rationale:** Why this option.
**Impact:** What it affects.
**Date:** YYYY-MM-DD
```

---

### DEC-2026-04-18-03 — Report Date = Last Trading Session Date

**Context:** The dashboard is sometimes viewed on non-trading days (weekends, holidays). A naive implementation would stamp the regime read with the calendar date, which would be wrong — markets were not open and no new data exists.
**Decision:** The date displayed on any Market Regime read is the date of the most recent trading session, not the viewer's current calendar date.
**Rationale:** Displaying a Saturday or holiday date on a regime read would imply fresh data that does not exist, misleading fund managers on data freshness.
**Impact:** E01S04 AC5 — the display layer must derive and show the trading session date separately from the fetch timestamp.
**Date:** 2026-04-18

---

### DEC-2026-04-18-02 — Divergence Anchor = Prior Period Swing High/Low (Same-Run Rule)

**Context:** SPX can make multiple consecutive new highs against the same prior swing high (a "run"). A naive implementation might compare each day's high against the previous day's high, resetting the anchor daily and potentially masking divergence.
**Decision:** The divergence anchor is the prior period's swing high (or low) — the last confirmed peak/trough before the current run began. All days within the same run are compared against this single anchor, not against each other.
**Rationale:** Confirmed by live data: SPX made new highs on April 15, 16, and 17 all against the same prior high of 7,002.28 (Jan 28). MMTH was divergent across all three days. Resetting the anchor daily would have produced incorrect divergence readings on days 2 and 3 of the run.
**Impact:** E01S02 AC1 and AC2 — divergence detection logic must preserve the original anchor for the duration of a run.
**Date:** 2026-04-18

---

### DEC-2026-04-18-01 — SPX Price = Daily High (Not Close)

**Context:** The regime classification compares SPX price against its EMAs to determine market position. The question was whether to use the daily closing price or the daily high.
**Decision:** All SPX price values used in indicator storage, divergence detection, EMA comparison, and display are the **daily high**, not the closing price.
**Rationale:** The daily high reflects the full extent of price action during the session and is the relevant measure for detecting new highs/lows in divergence analysis.
**Impact:** E01S01 AC1, E01S02 AC1/AC2, E01S04 AC2, E01S06 AC2 — all references to "SPX price" mean daily high.
**Date:** 2026-04-18

---

<!-- Add decisions above this line, newest first -->
