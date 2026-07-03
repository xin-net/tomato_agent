Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot

Write-Host "== Backend tests =="
Push-Location "$Root\backend"
python -m pytest -q
Pop-Location

Write-Host "== Frontend build =="
Push-Location "$Root\frontend"
npm run build
Pop-Location

Write-Host "== Verification completed =="
