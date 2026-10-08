param(
    [Parameter(Position=0)][ValidateSet('start','stop','status')][string]$Action='start',
    [string]$Address=''
)
$ErrorActionPreference='Stop'
$projectRoot=Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$pythonPath=Join-Path $projectRoot '.venv\Scripts\python.exe'
$tlsDirectory=Join-Path $projectRoot 'data\phone_tls'
$logDirectory=Join-Path $projectRoot 'logs'
function Get-PhoneGateway {
    foreach ($listener in (Get-NetTCPConnection -LocalPort 8443 -State Listen -ErrorAction SilentlyContinue)) {
        $process=Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.OwningProcess)" -ErrorAction SilentlyContinue
        if ($process.CommandLine -like '*phone_gateway:app*' -and $process.CommandLine -like "*$projectRoot*") { return $process }
    }
    return $null
}
try {
    $existing=Get-PhoneGateway
    if ($Action -eq 'stop') {
        if ($existing) { & taskkill.exe /PID $existing.ProcessId /T /F | Out-Host }
        Write-Host 'Phone access stopped. Laptop app is unchanged.';exit 0
    }
    if ($Action -eq 'status') {
        if ($existing) { $saved=Get-Content -LiteralPath (Join-Path $tlsDirectory 'address.txt');Write-Host "PHONE ACCESS RUNNING: https://${saved}:8443" }
        else { Write-Host 'Phone access is offline. Run Run-TransitOpt-Phone.bat start.' }
        exit 0
    }
    if (-not $Address) {
        $Address=(Get-NetIPConfiguration | Where-Object { $_.IPv4DefaultGateway -and $_.NetAdapter.Status -eq 'Up' } | ForEach-Object { $_.IPv4Address.IPAddress } | Select-Object -First 1)
    }
    if (-not $Address) { throw 'Connect the laptop to Wi-Fi or pass -Address with its private IPv4 address.' }
    if (-not (Test-Path -LiteralPath $pythonPath)) { & "$PSScriptRoot\Start-VisionX.ps1" start -NoBrowser }
    & $pythonPath -c 'import cryptography'
    if ($LASTEXITCODE -ne 0) { & $pythonPath -m pip install 'cryptography>=46,<49';if ($LASTEXITCODE -ne 0) { throw 'Certificate dependency installation failed' } }
    & $pythonPath "$PSScriptRoot\prepare_phone_auth.py"
    if ($LASTEXITCODE -ne 0) { throw 'Could not prepare authenticated phone access' }
    if ($existing) {
        & taskkill.exe /PID $existing.ProcessId /T /F | Out-Null
    }
    # Restart the owned backend so updated credentials apply to its one ML process.
    & "$PSScriptRoot\Start-VisionX.ps1" stop -NoBrowser
    & "$PSScriptRoot\Start-VisionX.ps1" start -NoBrowser
    if ($LASTEXITCODE -ne 0) { throw 'Laptop server failed to start' }
    & $pythonPath "$PSScriptRoot\phone_tls.py" $Address
    if ($LASTEXITCODE -ne 0) { throw 'Could not generate phone HTTPS certificate' }
    if (Get-NetTCPConnection -LocalPort 8443 -State Listen -ErrorAction SilentlyContinue) { throw 'Port 8443 is occupied by another service' }
    New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
    $helper=Start-Process -FilePath $pythonPath -ArgumentList @('-m','uvicorn','phone_gateway:app','--app-dir','scripts','--host',$Address,'--port','8443','--ssl-keyfile','data/phone_tls/server.key','--ssl-certfile','data/phone_tls/server.crt','--no-access-log') -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logDirectory 'phone.stdout.log') -RedirectStandardError (Join-Path $logDirectory 'phone.stderr.log')
    $ready=$false
    for ($attempt=0;$attempt -lt 20;$attempt++) {
        $helper.Refresh();if ($helper.HasExited) { throw 'Phone gateway exited; inspect logs/phone.stderr.log' }
        if (Get-PhoneGateway) { $ready=$true;break };Start-Sleep -Seconds 1
    }
    if (-not $ready) { throw 'Phone gateway did not become ready' }
    Write-Host "PHONE URL: https://${Address}:8443" -ForegroundColor Green
    Write-Host "Transfer and manually trust this public certificate on your own phone: $tlsDirectory\transitopt-phone-ca.crt"
    Write-Host 'Keep private .key files on this laptop. No device trust or firewall settings were changed.'
    Write-Host 'Use the administrator password in .env. Open /connect for camera setup.'
} catch { Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red;exit 1 }
