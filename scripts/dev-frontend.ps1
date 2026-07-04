Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot

Push-Location "$Root\frontend"
npm install
npm run dev -- --host=127.0.0.1 --port=5174
Pop-Location
