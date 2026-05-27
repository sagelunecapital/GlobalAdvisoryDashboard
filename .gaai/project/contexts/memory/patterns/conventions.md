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
  - screener
  - windows
created_at: 2026-04-27
updated_at: 2026-05-22
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

### Net Liquidity Formula

`Net Liquidity = WALCL - WDTGAL - WLRRAL` (Federal Reserve balance sheet minus Treasury General Account minus Reverse Repo)

### Path Construction (Windows-safe)

Use `pathlib.Path` for ALL path operations — no string concatenation, no `os.path.join`, no `os.getcwd()`:

```python
_PROJECT_ROOT = Path(__file__).absolute().parent
_DATA_DIR = _PROJECT_ROOT / "data"
_BACKLOG = _PROJECT_ROOT / ".gaai" / "project" / "contexts" / "backlog" / "active.backlog.yaml"
```

This avoids PowerShell bracket-path issues and works cross-platform. See `gaai_deliver.py` as reference.

### ASCII-Only Output (Windows Console)

All `print()` and `sys.stderr.write()` in Python scripts must be ASCII-only. Windows console (cp1252) crashes on Unicode characters. No emoji, no non-ASCII symbols in any output statement.

### Screener JSON Patching (Enrichment)

Claude enriches screener data by patching JSON files directly — never via API calls in scripts. Fields to patch: `catalyst`, `source`, `source_url`, `catalyst_type`, `group_id`, `group_summary`. Enrichment preserves all existing fields; never overwrites committed enriched data (use git history as the safety net).

---

## Test Patterns

### External API Mocking (Mandatory)

All tests for code that calls external APIs (yfinance, FRED, EODData, GDPNow) must mock the external calls. No live API calls in the test suite. Use `unittest.mock.patch` or `pytest` fixtures.

See `tests/conftest.py` and individual test files for fixture patterns.

### Path Object Mocking

Do NOT use `patch.object(Path, 'exists', ...)` — `WindowsPath.exists` is read-only on Windows. Instead, replace the module-level path constant:

```python
fake_path = MagicMock(spec=Path)
fake_path.exists.return_value = True
with patch.object(module, "_SOME_PATH", fake_path):
    ...
```

### pytest configuration

`pytest.ini` disables the pylint plugin: `addopts = -p no:pylint`. Test coverage via `pytest-cov`.

---

## Architecture Patterns

### Module Isolation Rule

`src/macro/` and `src/liquidity/` are self-contained — do NOT import from `src/db/`. Each module's DB layer is independent. Do not add cross-module imports.

### DB Path Convention

DB files are stored in `data/` directory relative to the project root. The `get_connection()` functions create `data/` if it doesn't exist via `path.parent.mkdir(parents=True, exist_ok=True)`.

### Enum Return for Ambiguous Results

When a function can return multiple structurally distinct states, use an enum. `DivergenceResult` (BEARISH, BULLISH, NO_DIVERGENCE, DATA_GAP) and `RegimeLabel` (GREEN, YELLOW, RED) are the reference patterns. DATA_GAP is structurally distinct from NO_DIVERGENCE and must not be conflated.

### Screener Data Structure

US movers: `{updated_at: str, by_date: {YYYY-MM-DD: [row, ...]}}`
Row fields: `ticker, company, sector, industry, country, mkt_cap (USD float), pe, price, change_pct, volume, catalyst, source, source_url, catalyst_type, group_id, group_summary`

IPOs: `{fetched_at: str, us: [...], hk: [...]}` — both keyed arrays of IPO objects
IPO fields: `ticker, company, date, price_usd, mkt_cap_usd, ipo_close, description`
HK display: multiply `price_usd` and `mkt_cap_usd` by 7.78 (HKD/USD)

---

## Anti-Patterns (Avoid)

### FRED API Key in Source Code

`update_dashboard.py` currently hardcodes `FRED_KEY = "..."` in source. This is a known security concern — must be moved to an environment variable before E06 deployment or public repo exposure.

### Calling Live External APIs in Tests

Tests must never call FRED, yfinance, EODData, or GDPNow directly. Tests that do this are flaky and slow. Always mock at the HTTP or library level.

### Sharing DB Schema Between Modules

Do not make `src/macro/db/` import from `src/db/` or vice versa. Each module's schema is intentionally isolated.

### Destructive git checkout

Never use `git checkout <branch> --` against files with uncommitted changes — it silently overwrites local edits. Always stash or commit first.

### Duplicating existing module logic for new markets

When extending to a new market/region (e.g., China screener), parameterize existing code rather than copy-pasting. Search for existing implementations first.
