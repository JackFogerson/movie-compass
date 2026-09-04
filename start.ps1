$ErrorActionPreference = "Stop"
$projectRoot = $PSScriptRoot
Set-Location -LiteralPath $projectRoot

if (-not (Test-Path -LiteralPath ".env")) {
    throw "Run .\setup.ps1 once before starting Movie Compass."
}
if (-not (Test-Path -LiteralPath ".venv\Scripts\python.exe")) {
    throw "The virtual environment is missing. Run .\setup.ps1 again."
}

& ".venv\Scripts\python.exe" -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8765
