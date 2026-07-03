Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot

Push-Location "$Root\frontend"
npm install
npm run build
Pop-Location

Write-Host "Frontend production build is ready. Start backend and open http://127.0.0.1:8000/"
