Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot

$BackendHealth = "http://127.0.0.1:8000/health"
try {
    Invoke-WebRequest $BackendHealth -UseBasicParsing -TimeoutSec 3 | Out-Null
} catch {
    Write-Warning "FastAPI is not reachable at $BackendHealth. Start .\scripts\dev-backend.ps1 and wait for /health before using the workbench."
}

Push-Location "$Root\frontend"
npm install
npm run dev -- --host=127.0.0.1 --port=5174
Pop-Location
