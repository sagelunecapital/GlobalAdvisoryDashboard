$projectRoot = Split-Path $PSScriptRoot
$python = "C:\Users\lance\AppData\Local\Programs\Python\Python313\python.exe"

Set-Location $projectRoot

& $python (Join-Path $projectRoot "update_dashboard.py")
if (-not $?) { exit 1 }

$changes = git -C $projectRoot diff --name-only prototypes/index.html
if ($changes) {
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm"
    git -C $projectRoot add prototypes/index.html
    git -C $projectRoot commit -m "chore: update dashboard data $timestamp"
    git -C $projectRoot push
}
