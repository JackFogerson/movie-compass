$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $true
$projectRoot = $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$secretDirectory = Join-Path $projectRoot "build\packaging-secrets"
$secretFile = Join-Path $secretDirectory "tmdb-access.key"

$sharedTmdbKey = $env:MOVIE_COMPASS_SHARED_TMDB_KEY
if ([string]::IsNullOrWhiteSpace($sharedTmdbKey) -and (Test-Path -LiteralPath ".env")) {
    $keyLine = Get-Content -LiteralPath ".env" | Where-Object { $_ -like "TMDB_API_KEY=*" } | Select-Object -First 1
    if ($keyLine) { $sharedTmdbKey = $keyLine.Substring("TMDB_API_KEY=".Length).Trim() }
}
New-Item -ItemType Directory -Path $secretDirectory -Force | Out-Null
Set-Content -LiteralPath $secretFile -Value $sharedTmdbKey -NoNewline

$python = if (Test-Path -LiteralPath ".venv\Scripts\python.exe") {
    ".venv\Scripts\python.exe"
} else {
    "python"
}

try {
    & $python -c "import PyInstaller, webview"
    $desktopDependenciesReady = $true
} catch {
    $desktopDependenciesReady = $false
}
if (-not $desktopDependenciesReady) {
    & $python -m pip install -e ".[desktop]"
    if ($LASTEXITCODE -ne 0) { throw "Desktop dependencies could not be installed." }
}

& $python -m PyInstaller `
    --noconfirm `
    --onedir `
    --windowed `
    --name "MovieCompass" `
    --paths "backend" `
    --collect-all "webview" `
    --add-data "backend/app/static;app/static" `
    --add-data "data/bootstrap;data/bootstrap" `
    --add-data "$secretFile;data/bootstrap" `
    --add-data "ml/artifacts/__init__.py;ml/artifacts" `
    --add-data "ml/artifacts/movielens.py;ml/artifacts" `
    --add-data "ml/artifacts/movielens-32m-9ded58306c28/catalog.csv.gz;ml/artifacts/movielens-32m-9ded58306c28" `
    --add-data "ml/artifacts/movielens-32m-9ded58306c28/manifest.json;ml/artifacts/movielens-32m-9ded58306c28" `
    --add-data "ml/artifacts/movielens-32m-9ded58306c28/movie_ids.npy;ml/artifacts/movielens-32m-9ded58306c28" `
    --add-data "ml/artifacts/movielens-32m-9ded58306c28/ratings_csr.npz;ml/artifacts/movielens-32m-9ded58306c28" `
    --add-data "ml/artifacts/movielens-32m-9ded58306c28/user_ids.npy;ml/artifacts/movielens-32m-9ded58306c28" `
    --add-data "ml/artifacts/movielens-32m-9ded58306c28/collaborative/latent_factor.joblib;ml/artifacts/movielens-32m-9ded58306c28/collaborative" `
    --add-data "ml/artifacts/movielens-32m-9ded58306c28/collaborative/manifest.json;ml/artifacts/movielens-32m-9ded58306c28/collaborative" `
    "scripts/desktop_launcher.py"
if ($LASTEXITCODE -ne 0) { throw "PyInstaller could not build Movie Compass." }

Copy-Item -LiteralPath "desktop\START HERE.txt" -Destination "dist\MovieCompass\START HERE.txt" -Force
$archive = "dist\MovieCompass-Windows.zip"
if (Test-Path -LiteralPath $archive) {
    Remove-Item -LiteralPath $archive -Force
}
Compress-Archive -LiteralPath "dist\MovieCompass" -DestinationPath $archive -CompressionLevel Optimal

Write-Host "Desktop app built at dist\MovieCompass\MovieCompass.exe"
Write-Host "Ready-to-share download created at dist\MovieCompass-Windows.zip"
Remove-Item -LiteralPath $secretFile -Force -ErrorAction SilentlyContinue
