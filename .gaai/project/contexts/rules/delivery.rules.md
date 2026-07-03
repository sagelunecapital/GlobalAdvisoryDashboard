---
type: rules
category: delivery
id: PROJ-RULES-DELIVERY-001
scope: project
created_at: 2026-04-27
updated_at: 2026-05-22
---

# Project Delivery Rules

Project-specific governance constraints for the Fund Manager Daily Dashboard.
These extend (not override) the core base.rules.md.

---

## Data Layer Rules

### R1 — SQLite WAL Mode Mandatory

Every SQLite connection in `src/` must enable `PRAGMA journal_mode=WAL` and `PRAGMA foreign_keys=ON`.
Connections that omit WAL mode fail code review.

### R2 — Module DB Isolation

`src/macro/db/` must NOT import from `src/db/` and vice versa.
Cross-module data access is forbidden until a dedicated integration layer exists.

### R3 — SPX Price = Daily High

All references to "SPX price" in indicator storage, divergence detection, EMA computation, and display use the **daily high** (`spx_daily_high` column). Using close price violates DEC-2026-04-18-01.

---

## Testing Rules

### R4 — No Live External API Calls in Tests

Tests must never call FRED, yfinance, EODData, or GDPNow live. All external HTTP calls must be mocked.
Violation: a test that fails only when the network is unavailable.

### R5 — DivergenceResult DATA_GAP Must Be Handled Explicitly

Any code consuming `detect_divergence()` must handle all four DivergenceResult cases explicitly:
BEARISH, BULLISH, NO_DIVERGENCE, DATA_GAP. Treating DATA_GAP as NO_DIVERGENCE is forbidden (per DEC-2026-04-25-01 AC5).

---

## Dashboard / Production Rules

### R6 — Do Not Add Long-Term Features to update_dashboard.py

`update_dashboard.py` is a temporary production pattern (DEC-2026-04-27-01) superseded by E06.
New data signals intended to persist long-term must target the E06 API endpoints, not `update_dashboard.py`.
Bug fixes and urgent data corrections are acceptable.

### R7 — FRED API Key Must Not Be Hardcoded in New Code

New code (E06 endpoints and any refactors) must read `FRED_KEY` from `os.environ.get("FRED_KEY")`.
The existing hardcoded key in `update_dashboard.py` is a known debt — do not replicate this pattern.

### R8 — E06 Endpoints Must Be Stateless

Vercel serverless functions in `api/` must not depend on SQLite or local filesystem state.
All data must be fetched live from FRED, yfinance, or EODData on each request.

---

## Divergence / Regime Rules

### R9 — Divergence Lookback = 90 Calendar Days Minimum

`SWING_LOOKBACK_DAYS = 90` in `src/analysis/divergence.py`. DB must contain ≥90 calendar days of
history before divergence results are considered reliable. Return DATA_GAP otherwise.

### R10 — Report Date = Last Trading Session (Not Calendar Date)

Any display of market regime or indicator data shows the date of the most recent trading session,
not the viewer's current calendar date (DEC-2026-04-18-03). Never display a weekend or holiday date
as a regime read date.

---

## Windows / Cross-Platform Rules

### R11 — ASCII-Only Output in Python Scripts

All `print()` and `sys.stderr.write()` output in Python scripts must be ASCII-only.
Windows console (cp1252) crashes on Unicode characters — no emoji, no non-ASCII symbols.
Violation: any print statement containing characters outside 0x00–0x7F.

### R12 — Use pathlib.Path for All Path Construction

New Python scripts must use `pathlib.Path` for all internal path construction.
No `os.path.join`, no string concatenation, no `os.getcwd()` for path operations.
Anchor project root as `Path(__file__).absolute().parent`.

### R13 — No Hardcoded Absolute Paths

Scripts must not hardcode absolute paths (`C:\Users\...`, `P:\OneDrive\...`).
Use `Path(__file__).absolute().parent` to derive the project root.
Violation: any string literal containing a drive letter or absolute path prefix.

---

## Screener Rules

### R14 — Screener Enrichment Patches JSON In-Place

Claude enrichment of screener data (catalyst, source, catalyst_type, group_id) patches
`prototypes/screener_movers.json`, `prototypes/screener_movers_cn.json`, and
`prototypes/screener_ipos.json` directly. It never overwrites the full file from scratch —
only patches the target fields within existing records.
Violation: any enrichment step that reads raw fetch data and writes a complete file replacement.

### R15 — HK Tickers Require .HK Suffix for yfinance

yfinance lookups for HK-listed stocks must append `.HK` to the numeric ticker:
`f"{int(ticker):04d}.HK"`. Without the suffix, yfinance returns no data.
HK prices and market caps are stored in USD; multiply by 7.78 for HKD display.
