# update_and_deploy.ps1  -  Complete daily dashboard data pipeline (single source of truth).
# Collect -> export -> commit -> push. Run manually each morning, or via the
# "GAAI Dashboard Update" scheduled task (idempotent: skips commit when nothing changed).
#
# Operates on the live working copy on `main` and commits ONLY the generated data files
# listed below, so any other uncommitted work (screener enrichment, code edits, untracked
# files) is left untouched. NO git stash is used -> no stash pileup, no conflict markers.
#
# Screener data (screener_movers*.json, screener_ipos.json) is committed SEPARATELY by the
# manual enrichment step and is intentionally NOT handled here (decoupled, commit ae103d0).
#
# Usage:
#   .\update_and_deploy.ps1            # full run: regenerate data, commit, push
#   .\update_and_deploy.ps1 -DryRun    # regenerate data only; show diff; NO commit/push
param([switch]$DryRun)

$projectRoot = "P:\OneDrive\[03] Cowork"
Start-Transcript -Path "$env:TEMP\gaai_dashboard_update.log" -Append -Force

$hardcoded = "C:\Users\lance\AppData\Local\Programs\Python\Python313\python.exe"
$python = if (Test-Path $hardcoded) { $hardcoded } else { (Get-Command python -ErrorAction Stop).Source }

Set-Location -LiteralPath $projectRoot
Write-Host "projectRoot: $projectRoot"
Write-Host "python: $python"
if ($DryRun) { Write-Host "*** DRY RUN - no commit, no push ***" }

# --- Guard: must be on main (dashboard deploys from main) ---
$branch = (git rev-parse --abbrev-ref HEAD).Trim()
if ($branch -ne "main") {
    Write-Warning "Not on main (on '$branch'). Switch to main before the data update. Aborting."
    Stop-Transcript; exit 1
}

# --- Sync remote, fast-forward only (local is the data source) ---
git fetch origin main --quiet
git merge --ff-only origin/main --quiet
if (-not $?) { Write-Warning "Could not fast-forward from origin/main - continuing; check push at end." }

function Invoke-Step($relPath, $warn) {
    & $python (Join-Path $projectRoot $relPath)
    if (-not $?) { Write-Warning $warn }
}

# 1. Macro / regime  (gdpnow.json must be refreshed BEFORE update_dashboard.py reads it)
Invoke-Step "scripts\fetch_gdpnow.py"  "fetch_gdpnow.py failed - GDPNow may be stale."
Invoke-Step "update_dashboard.py"      "update_dashboard.py failed - macro data not updated."
Invoke-Step "scripts\fetch_regime.py"  "fetch_regime.py failed - regime.json may be stale."

# 2. STIR
Invoke-Step "scripts\barchart_fetch.py" "barchart_fetch.py failed - ZQ cache stale (stir falls back to yfinance)."
Invoke-Step "scripts\stir_pipeline.py"  "stir_pipeline.py failed - stir.json may be stale."

# 2b. Warsh Playbook tab data (reads stir.json above; FRED + yfinance for the rest)
Invoke-Step "scripts\fetch_warsh.py"    "fetch_warsh.py failed - warsh.json may be stale (tab falls back to illustrative curves)."

# 2c. Yen & Carry tab data (FRED + yfinance: USDJPY/DXY, fair-value, correlation, Aug-2024 unwind)
Invoke-Step "scripts\fetch_yen.py"      "fetch_yen.py failed - yen.json may be stale (tab falls back to illustrative curves)."

# 2d. Cross-Asset Regimes tab data (yfinance ^GSPC/DX-Y.NYB + FRED DGS10/DGS2/DFII10/T10YIE)
Invoke-Step "scripts\cross_asset_fetch.py" "cross_asset_fetch.py failed - cross_asset.json may be stale."

# 3. Sector rotation: the collector refreshes sector_rotation.db AND auto-exports
#    sector_rotation.json + ticker_perf.json internally (no separate export step needed).
#    MFRA then computes/exports from the same DB.
Invoke-Step "scripts\sector_data_collector.py" "sector_data_collector.py failed - DB NOT refreshed; sector/ticker/mfra JSON will be STALE."
Invoke-Step "scripts\mfra_compute.py"           "mfra_compute.py failed - mfra table may be stale."
Invoke-Step "scripts\mfra_export.py"            "mfra_export.py failed - mfra_group.json may be stale."

# 4. COT + price
Invoke-Step "scripts\cot_report_pull.py"   "cot_report_pull.py failed - COT DB may be stale."
Invoke-Step "scripts\export_cot_json.py"   "export_cot_json.py failed - cot_data.json may be stale."
Invoke-Step "scripts\export_price_json.py" "export_price_json.py failed - price_data.json may be stale."

# 5. FX carry index (G10 carry replication w/ recovered FXCTG10 alpha; reads data/carry_calibration.json)
Invoke-Step "scripts\carry_export.py"      "carry_export.py failed - carry.json may be stale."

# --- Commit ONLY the generated pipeline data files (explicit list; screener excluded) ---
$dataFiles = @(
    "prototypes/index.html",
    "prototypes/regime.json",
    "prototypes/gdpnow.json",
    "prototypes/sector_rotation.json",
    "prototypes/stir.json",
    "prototypes/warsh.json",
    "prototypes/yen.json",
    "prototypes/ticker_perf.json",
    "prototypes/mfra_group.json",
    "prototypes/cot_data.json",
    "prototypes/price_data.json",
    "prototypes/carry.json",
    "prototypes/cross_asset.json"
)
$changes = git diff --name-only -- $dataFiles
if ($changes) {
    if ($DryRun) {
        Write-Host "Data files that WOULD be committed:"
        git diff --stat -- $dataFiles
    } else {
        $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm"
        git add -- $dataFiles
        git commit -m "chore: update dashboard data $timestamp"
        git push origin main
        if (-not $?) { Write-Warning "git push failed - local files updated but remote is stale." }
    }
} else {
    Write-Host "No data changes detected - skipping commit."
}

Stop-Transcript
exit 0
