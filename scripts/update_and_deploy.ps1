$projectRoot = "P:\OneDrive\[03] Cowork"
Start-Transcript -Path "$env:TEMP\gaai_dashboard_update.log" -Append -Force

$hardcoded = "C:\Users\lance\AppData\Local\Programs\Python\Python313\python.exe"
$python = if (Test-Path $hardcoded) { $hardcoded } else { (Get-Command python -ErrorAction Stop).Source }

Set-Location -LiteralPath $projectRoot
Write-Host "projectRoot: $projectRoot"
Write-Host "python: $python"

# Stash any in-progress work on current branch, switch to main for data commit
git stash push -m "pre-data-update stash" --quiet
git fetch origin main --quiet
git checkout main --quiet
git pull -X ours origin main --quiet

& $python (Join-Path $projectRoot "update_dashboard.py")
if (-not $?) {
    Write-Warning "update_dashboard.py failed  -  continuing without macro data update."
}

& $python (Join-Path $projectRoot "scripts\fetch_regime.py")
if (-not $?) {
    Write-Warning "fetch_regime.py failed  -  continuing without regime data update."
}

& $python (Join-Path $projectRoot "scripts\barchart_fetch.py")
if (-not $?) {
    Write-Warning "barchart_fetch.py failed  -  ZQ cache may be stale (stir_pipeline will fall back to yfinance)."
}

& $python (Join-Path $projectRoot "scripts\stir_pipeline.py")
if (-not $?) {
    Write-Warning "stir_pipeline.py failed  -  stir.json may be stale."
}

& $python (Join-Path $projectRoot "scripts\export_sector_json.py")
if (-not $?) {
    Write-Warning "export_sector_json.py failed  -  sector_rotation.json may be stale."
}

& $python (Join-Path $projectRoot "scripts\export_ticker_perf.py")
if (-not $?) {
    Write-Warning "export_ticker_perf.py failed  -  ticker_perf.json may be stale."
}

& $python (Join-Path $projectRoot "scripts\mfra_compute.py")
if (-not $?) {
    Write-Warning "mfra_compute.py failed  -  mfra_group.json may be stale."
}

& $python (Join-Path $projectRoot "scripts\mfra_export.py")
if (-not $?) {
    Write-Warning "mfra_export.py failed  -  mfra_group.json may be stale."
}

& $python (Join-Path $projectRoot "scripts\cot_report_pull.py")
if (-not $?) {
    Write-Warning "cot_report_pull.py failed  -  cot DB may be stale."
}

& $python (Join-Path $projectRoot "scripts\export_cot_json.py")
if (-not $?) {
    Write-Warning "export_cot_json.py failed  -  cot_data.json may be stale."
}

$changes = git diff --name-only prototypes/index.html prototypes/regime.json prototypes/sector_rotation.json prototypes/stir.json prototypes/ticker_perf.json prototypes/mfra_group.json prototypes/screener_movers.json prototypes/screener_ipos.json prototypes/cot_data.json
if ($changes) {
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm"
    git add prototypes/index.html prototypes/regime.json prototypes/sector_rotation.json prototypes/stir.json prototypes/ticker_perf.json prototypes/mfra_group.json prototypes/screener_movers.json prototypes/screener_ipos.json prototypes/cot_data.json
    git commit -m "chore: update dashboard data $timestamp"
    git push origin main
    if (-not $?) { Write-Warning "git push failed  -  local files still updated but remote is stale." }
} else {
    Write-Host "  No data changes detected  -  skipping commit."
}

# Return to previous branch and restore stash
git checkout - --quiet
git stash pop --quiet

# Sync the data files from main into the current branch so the local dashboard
# reflects the latest data regardless of which branch is checked out.
$currentBranch = git rev-parse --abbrev-ref HEAD
if ($currentBranch -ne "main") {
    git checkout main -- prototypes/index.html prototypes/regime.json prototypes/sector_rotation.json prototypes/stir.json prototypes/ticker_perf.json --quiet
}

Stop-Transcript
exit 0
