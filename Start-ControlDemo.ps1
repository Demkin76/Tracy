param([switch]$SkipBuild, [switch]$NewScenario)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    uv sync --locked --extra dev --extra frameworks
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
}
$python = (Resolve-Path -LiteralPath '.venv\Scripts\python.exe').Path
if (-not (Test-Path -LiteralPath '.env')) {
    & $python -m scripts.setup_demo
    if ($LASTEXITCODE -ne 0) { throw 'Setup failed.' }
}
if (-not (Test-Path -LiteralPath 'data\tracy-owner.json')) {
    & $python -m scripts.bootstrap_owner
    if ($LASTEXITCODE -ne 0) { throw 'Owner setup failed.' }
}
if (-not $SkipBuild) {
    npm.cmd --prefix frontend ci
    if ($LASTEXITCODE -ne 0) { throw 'Frontend installation failed.' }
    npm.cmd --prefix frontend run build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
}
function Start-ServiceProcess([int]$Port, [string]$Module, [string]$Name, [string]$ExpectedTitle, [switch]$Factory) {
    $listener = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($listener) {
        $process = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)"
        $parent = Get-CimInstance Win32_Process -Filter "ProcessId=$($process.ParentProcessId)"
        if ($process.CommandLine -notlike "*$Module*" -or ($process.ExecutablePath -ne $python -and $parent.ExecutablePath -ne $python)) {
            throw "Port $Port belongs to another process or checkout."
        }
    } else {
        $arguments = @('-m', 'uvicorn', $Module, '--host', '127.0.0.1', '--port', "$Port", '--workers', '1')
        if ($Factory) { $arguments += '--factory' }
        $process = Start-Process -FilePath $python -ArgumentList $arguments -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput "$PSScriptRoot\data\$Name.out.log" -RedirectStandardError "$PSScriptRoot\data\$Name.err.log"
        $process.Id | Set-Content -LiteralPath "data\$Name.pid"
    }
    $ready = $false
    for ($attempt = 0; $attempt -lt 40; $attempt++) {
        try {
            $schema = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/openapi.json" -TimeoutSec 2
            if ($schema.info.title -ne $ExpectedTitle) { throw 'Wrong service title' }
            $ready = $true
            break
        } catch { Start-Sleep -Milliseconds 250 }
    }
    if (-not $ready) { throw "Service on port $Port did not start. See data\$Name.err.log." }
}
Start-ServiceProcess -Port 8000 -Module 'backend.main:create_app' -Name 'control-server' -ExpectedTitle 'Tracy' -Factory
Start-ServiceProcess -Port 8011 -Module 'scripts.control_test_provider:app' -Name 'control-provider' -ExpectedTitle 'Tracy local test provider'
if ($NewScenario -or -not (Test-Path -LiteralPath 'data\control-demo.json')) {
    & $python -m scripts.prepare_control_demo
    if ($LASTEXITCODE -ne 0) { throw 'Demo scenario creation failed.' }
}
Write-Host 'Tracy control center: http://127.0.0.1:8000/control'
Write-Host 'Login: data/tracy-owner.json. Services run in the background.'
Write-Host 'Use -NewScenario to create fresh approval requests; existing evidence is preserved.'
