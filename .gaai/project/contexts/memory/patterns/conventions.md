---
type: memory
category: patterns
id: PATTERNS-001
tags:
  - patterns
  - conventions
  - procedural
  - python
  - sqlite
  - testing
  - dashboard
created_at: 2026-04-27
updated_at: 2026-04-27
---

# Patterns & Conventions

> Procedural memory: how things are done in this project.
> Agent-maintained. Updated when durable patterns are confirmed.
> The Delivery Agent loads this before every implementation task.

---

## Code Patterns

### SQLite Connection (WAL mode)

All DB connections must enable WAL journal mode and foreign keys:

```python
conn = sqlite3.connect(str(path))
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA foreign_keys=ON")
return conn
```

See `src/db/schema.py` and `src/macro/db/macro_schema.py` for reference implementations.

### EMA Computation

Use `pandas.ewm` with `adjust=False` (DEC-2026-04-22-01):

```python
ema12 = highs.ewm(span=12, adjust=False).mean()
ema25 = highs.ewm(span=25, adjust=False).mean()
```

Fetch 2 years of data for warm-up; trim to 1 year post-computation.

### FRED API Fetch Pattern

```python
def fetch_fred(series_id, start=DATA_ORIGIN, freq=None, aggr=None, units=None):
    params = {"series_id": series_id, "api_key": FRED_KEY, "file_type": "json", ...}
    r = requests.get(FRED_BASE, params=params, timeout=30)
    r.raise_for_status()
    return {obs["date"]: float(obs["value"]) for obs in r.json()["observations"] if obs["value"] != "."}
```

Always filter out FRED "." (missing) values. Use `timeout=30`.

### Dashboard Data Injection (Current Pattern — pre-E06)

Live data is injected into `prototypes/index.html` between marker comments:

```python
BLOCK_START = "// ─── DATA BLOCK START ───"
BLOCK_END   = "// ─── DATA BLOCK END ───"
```

`update_dashboard.py` uses regex to find and replace the block with computed JS variables. This pattern will be replaced by E06 live API calls.

### Time-Series Utility Functions (update_dashboard.py)

Standard helpers used throughout the injection pipeline:
- `yoy_pct(arr, lag=12)` — year-over-year % change (lag = 12 months)
- `mom_pct(arr)` — month-over-month % change
- `moving_avg(arr, w)` — simple moving average with None-safe window
- `forward_fill(arr)` — forward-fill None gaps (for sparse monthly series)
- `align(keys, d, default=None)` — align a dict to a list of keys with default
- `resample_monthly(day_dict)` — daily → last value per month

### net liquidity formula

`Net Liquidity = WALCL − WDTGAL − WLRRAL` (Federal Reserve balance sheet minus Treasury General Account minus Reverse Repo)

---

## Test Patterns

### External API Mocking (Mandatory)

All tests for code that calls external APIs (yfinance, FRED, EODData, GDPNow) must mock the external calls. No live API calls in the test suite. Use `unittest.mock.patch` or `pytest` fixtures.

See `tests/conftest.py` and individual test files for fixture patterns.

### pytest configuration

`pytest.ini` disables the pylint plugin: `addopts = -p no:pylint`. Test coverage via `pytest-cov`.

---

## Architecture Patterns

### Module Isolation Rule

`src/macro/` is self-contained and does NOT import from `src/db/`. Each module's DB layer is independent. Do not add cross-module imports between `src/db/` and `src/macro/db/`.

### DB Path Convention

DB files are stored in `data/` directory relative to the project root. The `get_connection()` / `get_macro_connection()` functions create `data/` if it doesn't exist via `path.parent.mkdir(parents=True, exist_ok=True)`.

### Enum Return for Ambiguous Results

When a function can return multiple structurally distinct states (e.g., divergence detection), use an enum rather than strings or booleans. `DivergenceResult` (BEARISH, BULLISH, NO_DIVERGENCE, DATA_GAP) is the reference pattern — DATA_GAP is structurally distinct from NO_DIVERGENCE and must not be conflated.

---

## Anti-Patterns (Avoid)

### FRED API Key in Source Code

`update_dashboard.py` currently hardcodes `FRED_KEY = "..."` in source. This is a known security concern — must be moved to an environment variable before any E06 deployment or public repo exposure. Use `os.environ.get("FRED_KEY")` instead.

### Calling Live External APIs in Tests

Tests must never call FRED, yfinance, EODData, or GDPNow directly. Tests that do this are flaky (network-dependent) and slow. Always mock at the HTTP or library level.

### Sharing DB Schema Between Modules

Do not make `src/macro/db/` import from `src/db/` or vice versa. Each module's schema is intentionally isolated. Cross-module queries belong in a dedicated integration layer (not yet built).
