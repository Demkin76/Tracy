param([switch]$SkipBuild, [int]$Port = 8000)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    uv sync --locked --extra dev
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
}
if (-not (Test-Path -LiteralPath '.env')) {
    & '.\.venv\Scripts\python.exe' -m scripts.setup_demo
    if ($LASTEXITCODE -ne 0) { throw 'Local setup failed.' }
}
if (-not $SkipBuild) {
    npm.cmd --prefix frontend ci
    if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
    npm.cmd --prefix frontend run build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
}
Write-Host "Tracy: http://127.0.0.1:$Port/control"
Write-Host 'Create an account, or use your existing login. Ctrl+C stops the server.'
& '.\.venv\Scripts\python.exe' -m uvicorn backend.main:create_app --factory --host 127.0.0.1 --port $Port --workers 1
