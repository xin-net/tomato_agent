Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot

Push-Location "$Root\backend"
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
Pop-Location
