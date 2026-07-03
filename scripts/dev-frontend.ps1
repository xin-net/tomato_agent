Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot

Push-Location "$Root\frontend"
npm install
npm run dev
Pop-Location
