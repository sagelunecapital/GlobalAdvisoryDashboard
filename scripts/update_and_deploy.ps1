$projectRoot = Split-Path $PSScriptRoot
$hardcoded = "C:\Users\lance\AppData\Local\Programs\Python\Python313\python.exe"
$python = if (Test-Path $hardcoded) { $hardcoded } else { (Get-Command python -ErrorAction Stop).Source }

Set-Location -LiteralPath $projectRoot

# Stash any in-progress work on current branch, switch to main for data commit
git stash push -m "pre-data-update stash" --quiet
git fetch origin main --quiet
git checkout main --quiet
git pull origin main --quiet

& $python (Join-Path $projectRoot "update_dashboard.py")
if (-not $?) {
    git checkout - --quiet
    git stash pop --quiet
    exit 1
}

& $python (Join-Path $projectRoot "scripts\fetch_regime.py")
if (-not $?) {
    git checkout - --quiet
    git stash pop --quiet
    exit 1
}

# Sector rotation: collect daily data then export to JSON for the dashboard
& $python (Join-Path $projectRoot "scripts\sector_data_collector.py")
if (-not $?) {
    Write-Warning "sector_data_collector.py failed — continuing without sector data update."
}

& $python (Join-Path $projectRoot "scripts\export_sector_json.py")
if (-not $?) {
    Write-Warning "export_sector_json.py failed — sector_rotation.json may be stale."
}

$changes = git diff --name-only prototypes/index.html prototypes/regime.json prototypes/sector_rotation.json
if ($changes) {
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm"
    git add prototypes/index.html prototypes/regime.json prototypes/sector_rotation.json
    git commit -m "chore: update dashboard data $timestamp"
    git push origin main
}

# Return to previous branch and restore stash
git checkout - --quiet
git stash pop --quiet

# Sync the data files from main into the current branch so the local dashboard
# reflects the latest data regardless of which branch is checked out.
$currentBranch = git rev-parse --abbrev-ref HEAD
if ($currentBranch -ne "main") {
    git checkout main -- prototypes/index.html prototypes/regime.json prototypes/sector_rotation.json --quiet
}
