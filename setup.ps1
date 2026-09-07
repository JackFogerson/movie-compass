param(
    [string]$TmdbApiKey
)

$ErrorActionPreference = "Stop"
$projectRoot = $PSScriptRoot
Set-Location -LiteralPath $projectRoot

if (-not $TmdbApiKey -and (Test-Path -LiteralPath ".env")) {
    $savedKeyLine = Get-Content -LiteralPath ".env" | Where-Object { $_ -like "TMDB_API_KEY=*" } | Select-Object -First 1
    if ($savedKeyLine) {
        $TmdbApiKey = $savedKeyLine.Substring("TMDB_API_KEY=".Length).Trim()
    }
}
if (-not $TmdbApiKey) {
    $secureKey = Read-Host "Paste your TMDB API key (stored only in this laptop's ignored .env file)" -AsSecureString
    $keyPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
    try {
        $TmdbApiKey = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($keyPointer)
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($keyPointer)
    }
}
if (-not $TmdbApiKey) {
    throw "A TMDB API key is required for title search and current-release metadata."
}

$environmentText = @"
APP_ENV=development
LOG_LEVEL=INFO
DATABASE_URL=sqlite+pysqlite:///./data/personal.sqlite3
TMDB_API_KEY=$TmdbApiKey
OPENAI_API_KEY=
DATA_DIR=./data
TMDB_CACHE_TTL_SECONDS=2592000
"@
[IO.File]::WriteAllText((Join-Path $projectRoot ".env"), $environmentText)

if (-not (Test-Path -LiteralPath ".venv\Scripts\python.exe")) {
    python -m venv .venv
}
& ".venv\Scripts\python.exe" -m pip install -e ".[dev]"
& ".venv\Scripts\python.exe" scripts/init_local_db.py

Write-Host "Movie Compass is ready. Run .\start.ps1 and open http://127.0.0.1:8765/."
Write-Host "Use Download profile on the old laptop, then Add profile here to transfer a person."
