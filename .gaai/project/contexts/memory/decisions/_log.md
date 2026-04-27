---
type: memory
category: decisions
id: DECISIONS-LOG
tags:
  - decisions
  - governance
created_at: 2026-04-18
updated_at: 2026-04-25
---

# Decision Log

> Append-only. Never delete or overwrite decisions.
> Only the Discovery Agent may add entries (or Bootstrap Agent during initialization).
> Format: one entry per decision, newest at top.
> For large projects, split by domain: `decisions/auth.md`, `decisions/api.md`, etc.

---

### DEC-2026-04-27-04 — src/ Library and update_dashboard.py are Parallel Implementations (Accepted)

**Context:** The `src/` library (built for E01) persists data to local SQLite via structured modules. `update_dashboard.py` independently implements fetch + compute + inject logic for the dashboard with no dependency on `src/`. `src/macro/db/macro_schema.py` explicitly states it does NOT import from `src/db/`. Two codebase paths cover overlapping data concerns.
**Decision:** Parallel implementation is accepted as a short-term architectural reality. `src/` is the local development/testing data pipeline; `update_dashboard.py` is the dashboard production injection tool. No forced unification before E06.
**Rationale:** E06 (Vercel serverless, stateless) is the designated consolidation point. Attempting to unify `src/` and `update_dashboard.py` before E06 would create rework. The isolation also prevents circular dependencies.
**Impact:** Delivery agents must NOT attempt to refactor `update_dashboard.py` to call `src/`. E06 re-implements all fetch logic stateless. Once E06 is deployed, `update_dashboard.py` becomes redundant.
**Date:** 2026-04-27

---

### DEC-2026-04-27-03 — E06 Architecture: Vercel Python Serverless Functions (Stateless, No SQLite)

**Context:** E06 requires replacing the HTML data injection pattern with live API calls on every dashboard load. SQLite is not viable in Vercel serverless (no persistent filesystem). Alternatives evaluated: Vercel KV (caching fallback), Railway/Render (separate backend), or stateless fetch-on-every-request.
**Decision:** E06 implements Python Serverless Functions under Vercel's `api/` directory. Each endpoint fetches live data from FRED, yfinance, and/or EODData on every request — completely stateless, no SQLite dependency.
**Rationale:** Vercel stateless is the simplest architecture that satisfies the requirement. Vercel KV is a identified fallback if timeout constraints (H-2) cannot be met during architecture validation (E06S01). Railway/Render adds operational overhead and is explicitly out of scope unless Vercel fallbacks fail.
**Impact:** E06 endpoints are completely independent of the `src/` SQLite library. E06S01 (architecture validation) is a hard gate — H-1, H-2, H-3 must be verified before any endpoint story proceeds.
**Date:** 2026-04-27

---

### DEC-2026-04-27-02 — Infrastructure: GitHub Actions + Vercel Static Hosting

**Context:** Dashboard must be browser-accessible without a dedicated server. Pre-computed historical chart data (regime, GDPNow) must update daily.
**Decision:** `prototypes/` directory is the Vercel `outputDirectory` (static hosting). Two GH Actions workflows commit updated `regime.json` (22:00 UTC) and `gdpnow.json` (21:00 UTC) to the repo weekdays. Vercel auto-deploys on push.
**Rationale:** Static Vercel hosting requires zero infrastructure management. GH Actions provides free scheduled compute for daily data commits. Historical data is small enough to commit to the repo without a dedicated storage layer.
**Impact:** Historical chart/time-series data (regime.json, gdpnow.json) continues this pattern after E06 — E06 only replaces current-value indicators with live API calls. Any change to the `prototypes/` directory structure requires updating `vercel.json`.
**Date:** 2026-04-27

---

### DEC-2026-04-27-01 — Dashboard Architecture: HTML Data Injection via update_dashboard.py (Current Production)

**Context:** Dashboard requires daily data updates across multiple modules (SPX regime, liquidity, macro, cross-signal). A monolithic script emerged as the first delivery approach for the live dashboard.
**Decision:** `update_dashboard.py` is the current live production pattern: fetches all data from FRED, yfinance, EODData, and yfinance BTC-USD inline, computes all signals, and injects JS variable blocks into `prototypes/index.html` between `// ─── DATA BLOCK START ───` and `// ─── DATA BLOCK END ───` markers. Run manually or via Windows Task Scheduler daily after market close.
**Rationale:** Fastest path to a working live dashboard during E01–E05 delivery. Script injection requires no backend infrastructure. Accepted as a temporary pattern explicitly superseded by E06.
**Impact:** E06 is explicitly designed to replace this pattern. Once E06 is live, `update_dashboard.py` becomes redundant. The DATA BLOCK marker pattern in `index.html` will be replaced by fetch() calls to `/api/*` endpoints. Do not add new long-term features to `update_dashboard.py`.
**Date:** 2026-04-27

---

### DEC-2026-04-25-01 — Divergence Detection API: detect_divergence() Signature and DivergenceResult Enum

**Context:** E01S02 implemented the divergence detection layer. Downstream stories (E01S03 classify regime, E01S05 refresh) must consume the divergence output.
**Decision:** `detect_divergence(db_path: str, as_of_date: str, _db_rows=None) -> tuple[DivergenceResult, str]` in `src/analysis/divergence.py`. `DivergenceResult` is an enum with 4 members: `BEARISH`, `BULLISH`, `NO_DIVERGENCE`, `DATA_GAP`. Swing anchor uses a trough-based 90-day lookback: the prior swing HIGH is the max of all rows before the global minimum (trough) in the 90-day window; the prior swing LOW is the min of all rows after the global maximum (peak). `SWING_LOOKBACK_DAYS = 90` is a module-level constant.
**Rationale:** Enum return type prevents downstream consumers from accidentally conflating DATA_GAP with NO_DIVERGENCE (structurally distinct). Trough-based anchor satisfies DEC-2026-04-18-02 same-run persistence: the trough date is stable even when the market makes consecutive new highs within the same run. Verified by test_T9 (two-day same-run anchor persistence).
**Impact:** E01S03 (regime classification) must call `detect_divergence(db_path, as_of_date)` and handle all 4 `DivergenceResult` cases explicitly. Treat `DATA_GAP` as an unavailable input (not clean no-divergence) — per AC5 contract. `DATA_GAP` is returned, not raised. DB must contain ≥90 calendar days of history before divergence detection is reliable.
**Date:** 2026-04-25

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
