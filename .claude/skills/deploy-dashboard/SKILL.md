---
name: deploy-dashboard
description: Run the daily dashboard data pipeline end to end - regenerate, verify at content level, commit, push to main, confirm live.
---

# Deploy Dashboard

Full daily run: regenerate data -> verify -> commit -> push -> confirm live.
Wall clock is ~11-15 min, almost all of it the pipeline itself (2038-ticker
sector sweep, Barchart headless browser, CFTC 500-week pull). Don't try to
speed that part up; do run it in the background.

This skill is checked into a OneDrive-synced repo and runs on more than one
machine. **Resolve the environment (step 0) instead of assuming paths.**

---

## 0. Resolve the environment

`scripts/update_and_deploy.ps1` hardcodes two things that exist on some
machines and not others. Check, then adapt:

| Hardcoded in the script | If it resolves | If it does not |
|---|---|---|
| `$projectRoot = P:\OneDrive\[03] Cowork` | nothing to do | `subst P: "<parent of OneDrive>"` so the path resolves; **remove it after** with `subst P: /D` |
| `...\Programs\Python\Python313\python.exe` | used directly | script falls back to `Get-Command python` - verify that fallback has the packages below |

```powershell
Test-Path -LiteralPath "P:\OneDrive\[03] Cowork"          # projectRoot resolvable?
Test-Path "C:\Users\lance\AppData\Local\Programs\Python\Python313\python.exe"
(Get-Command python).Source                                # what the fallback would be
```

Required packages on whichever interpreter wins: `yfinance pandas numpy
requests sodapy playwright` plus `python -m playwright install chromium`
(Playwright drives `barchart_fetch.py` for the ZQ strip; `sodapy` drives
`cot_report_pull.py`). A missing one fails a single step, and the script only
WARNs - it does not abort.

Windows gotchas that bite every run:
- `Test-Path`, `cd`, `Set-Location` on the repo path need **`-LiteralPath`** - the
  `[03]` is parsed as a wildcard otherwise. Passing the bracketed path as an
  *argument* to `python.exe` is fine.
- `Invoke-WebRequest` needs **`-UseBasicParsing`** or it dies with "PowerShell is
  in NonInteractive mode". `Invoke-RestMethod` is unaffected - prefer it.
- Confirm the branch is **`main`** (the script aborts otherwise; `main` is the
  deploy target, not `staging`).

## 1. Regenerate (dry run first, always)

```powershell
Set-Location -LiteralPath "<projectRoot>"; & ".\scripts\update_and_deploy.ps1" -DryRun
```

`-DryRun` regenerates everything and prints the would-commit diff **without**
committing or pushing. Run it in the background. Doing this first means one
slow pipeline run instead of two.

Two steps fail *silently or semi-silently* and are the #1 recurring problem -
yfinance throttles late in the run because the sector collector hammers Yahoo
with ~3k tickers first. Check the log for both before moving on:

- **`export_price_json.py`** drops failed contracts from `price_data.json`
  entirely, exits 0, prints no warning. The only tell is `Exported 28 tickers`
  instead of **`Exported 35 tickers`**. Re-run until it prints 35.
- **`carry_export.py`** intersects dates across all 10 G10 pairs, so one flaky
  pair gives an empty set and `IndexError: list index out of range`. A
  different pair fails each attempt - just retry the script standalone until it
  writes `carry.json`.

Benign and expected, not failures: `investing.com ... HTTP 403` (falls back to
FRED/yfinance), `MMTH unavailable - set EODDATA_API_KEY` in
`update_dashboard.py` (`fetch_regime.py` gets MMTH from Barchart instead), and
a scatter of `possibly delisted` per-ticker noise from the sector sweep.

## 2. Verify at content level

`git diff --stat` is **useless** here - every JSON is minified to one line, so a
dropped contract and a routine update both read as "1 line changed". Run the
checker:

```powershell
& <python> scripts/verify_pipeline_diff.py          # vs HEAD, before staging
```

Exit 1 = do not commit; the FAIL text names the fix. It catches dropped
top-level keys, `price_data.json` under 35 contracts, COT history erosion, and
backwards dates. Two WARNs are expected every run and are **not** data loss:

- `cot_data.json` obs shrinks while last dates advance - the rolling 500-week
  window shedding its oldest week as a new one lands. **Decide with the last
  date, never the obs delta.** Dates advanced => real update, keep it. Dates
  unchanged => pure erosion (CFTC releases Fridays only, so a mid-week re-pull
  never adds data) => `git checkout HEAD -- prototypes/cot_data.json`.
- `mfra_group.json` obs delta - each group's `idio_tickers` is recomputed per
  window. Confirm `as_of` advanced and the group count held (354).

`index.html` is **not** covered by the checker (it is HTML, not JSON). Verify it
by hand - its embedded data block must match the regenerated JSON:

```powershell
git diff --unified=0 -- prototypes/index.html | Select-String 'updated 20|const ND='
Select-String -Path prototypes/index.html -Pattern '<spx value from regime.json>'
```

The `// monthly obs ... updated <ts>` comment and `const ND=<trading days>`
must both advance, and the SPX/EMA/GDPNow scalars must match `regime.json`.

## 3. Commit the exact file list

Stage **only** the 14 generated pipeline files (the `$dataFiles` array in
`update_and_deploy.ps1` plus `prototypes/index.html`). Never `git add -A`.

Screener JSONs (`screener_movers*.json`, `screener_ipos.json`) are deployed
**separately** by the `enrich-deploy` skill and must stay unstaged - they are
often dirty in the working tree. Confirm the split before committing:

```powershell
git diff --cached --name-only   # expect exactly the 14
git diff --name-only            # screener files, if dirty, remain here
```

Also confirm nothing is silently blocked: `git check-ignore -- <the 14>` must
return nothing. (HTML dashboards have been gitignored by accident before.)

Then commit `chore: update dashboard data <yyyy-MM-dd HH:mm>` and
`git push origin main`. The pre-push hook validates screener JSON via a
configured `core.hooksPath` even though `.git/hooks/` looks empty; name-only
WARNs are non-blocking, and `weekly_returns missing` refers to the screener
files, not this commit.

## 4. Confirm the live URL serves the new values

**Not done until this passes.** Vercel builds take ~30-60s; poll with a
cache-buster.

```powershell
$r = Invoke-RestMethod -Uri ("https://global-advisory-dashboard.vercel.app/regime.json?cb=" + (Get-Random))
$r.updated; $r.regime_class; $r.spx
```

`updated` must match the new `regime.json` stamp. Spot-check a second file
(`mfra_group.json` `as_of`, or `cot_data.json` last date) to confirm the whole
commit deployed rather than just one file. Then remove any `subst` from step 0.

Every generated JSON the UI reads must be in `$dataFiles`; when a script starts
emitting a new one, add it to that array **and** to `DATA_FILES` in
`scripts/verify_pipeline_diff.py` in the same change.
