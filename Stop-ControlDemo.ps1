$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$python = (Resolve-Path -LiteralPath '.venv\Scripts\python.exe').Path
foreach ($service in @(@{ Port=8000; Module='backend.main:create_app' }, @{ Port=8011; Module='scripts.control_test_provider:app' })) {
    $listener = Get-NetTCPConnection -State Listen -LocalPort $service.Port -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $listener) { continue }
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)"
    $parent = Get-CimInstance Win32_Process -Filter "ProcessId=$($process.ParentProcessId)"
    if ($process.CommandLine -notlike "*$($service.Module)*" -or ($process.ExecutablePath -ne $python -and $parent.ExecutablePath -ne $python)) {
        throw "Port $($service.Port) belongs to another service or checkout; refusing to stop it."
    }
    Stop-Process -Id $listener.OwningProcess
}
Write-Host 'Local demo services stopped. Persistent intents and receipts remain in data/.'
