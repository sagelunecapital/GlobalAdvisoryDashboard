$projectRoot = Split-Path $PSScriptRoot
$python = "C:\Users\lance\AppData\Local\Programs\Python\Python313\python.exe"

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

$changes = git diff --name-only prototypes/index.html
if ($changes) {
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm"
    git add prototypes/index.html
    git commit -m "chore: update dashboard data $timestamp"
    git push origin main
}

# Return to previous branch and restore stash
git checkout - --quiet
git stash pop --quiet
