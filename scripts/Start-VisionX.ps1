param(
    [Parameter(Position=0)]
    [ValidateSet('start', 'stop', 'status')]
    [string]$Action = 'start',
    [switch]$CheckOnly,
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
$frontendPath = Join-Path $projectRoot 'frontend'
$appUrl = 'http://127.0.0.1:8000'
$ownedServer = $null
$startedSuccessfully = $false
$logDirectory = Join-Path $projectRoot 'logs'
$pidFile = Join-Path $logDirectory 'server.pid'

function Get-ProjectServer {
    $listeners = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
    foreach ($listener in $listeners) {
        $process = Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.OwningProcess)" -ErrorAction SilentlyContinue
        if ($process -and $process.CommandLine -like '*uvicorn*' -and $process.CommandLine -like "*$projectRoot*") {
            return $process
        }
    }
    return $null
}

function Save-ServerPid {
    $process = Get-ProjectServer
    if ($process) {
        New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
        Set-Content -LiteralPath $pidFile -Value $process.ProcessId -Encoding ascii
    }
}

function Invoke-Checked {
    param([string]$Program, [string[]]$Arguments)
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Program failed (exit code $LASTEXITCODE)."
    }
}

function Test-VisionX {
    try {
        $schema = Invoke-RestMethod "$appUrl/openapi.json" -TimeoutSec 3
        $health = Invoke-RestMethod "$appUrl/api/health" -TimeoutSec 3
        return $schema.info.title -eq 'VisionX AI Analyzer' -and $health.status -eq 'ok' -and $schema.paths.PSObject.Properties.Name -contains '/api/session'
    } catch { return $false }
}

try {
    Write-Host "`nVisionX AI Analyzer" -ForegroundColor Cyan
    Write-Host "Project: $projectRoot"
    if ($Action -eq 'status') {
        if (Test-VisionX) {
            Write-Host "SERVER RUNNING: $appUrl" -ForegroundColor Green
        } else {
            Write-Host 'SERVER OFFLINE. Run: Run-VisionX.bat start' -ForegroundColor Yellow
        }
        exit 0
    }
    if ($Action -eq 'stop') {
        $process = Get-ProjectServer
        if ($process) {
            & taskkill.exe /PID $process.ProcessId /T /F | Out-Host
            if ($LASTEXITCODE -ne 0) { throw 'Could not stop the VisionX server.' }
            if (Test-Path -LiteralPath $pidFile) { Remove-Item -LiteralPath $pidFile }
            Write-Host 'SERVER STOPPED.' -ForegroundColor Green
        } else {
            Write-Host 'No VisionX server from this project is running on port 8000.'
        }
        exit 0
    }
    $node = Get-Command node.exe -ErrorAction SilentlyContinue
    $npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if (-not $node -or -not $npm) {
        throw 'Install Node.js 22.12 or newer (with npm), then run this launcher again.'
    }
    $nodeVersion = [version]((& $node.Source --version).Trim().TrimStart('v'))
    if ($LASTEXITCODE -ne 0 -or $nodeVersion -lt [version]'22.12.0') {
        throw 'Node.js 22.12 or newer is required.'
    }

    if (-not (Test-Path -LiteralPath $pythonPath)) {
        $pythonCommand = Get-Command py.exe -ErrorAction SilentlyContinue
        if (-not $pythonCommand) { $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue }
        if (-not $pythonCommand) { throw 'Install Python 3.12 or 3.13, then run this launcher again.' }
        if ($CheckOnly) {
            Write-Host 'Python found. The virtual environment will be created on first launch.'
        } else {
            Write-Host 'Creating Python virtual environment...'
            Invoke-Checked -Program $pythonCommand.Source -Arguments @('-m', 'venv', '.venv')
        }
    }

    if ($CheckOnly) {
        if (Test-Path -LiteralPath $pythonPath) {
            Invoke-Checked -Program $pythonPath -Arguments @('--version')
        }
        Write-Host 'Launcher prerequisite check passed. No files or services changed.' -ForegroundColor Green
        exit 0
    }

    if (-not (Test-Path -LiteralPath (Join-Path $projectRoot '.env'))) {
        Copy-Item -LiteralPath (Join-Path $projectRoot '.env.example') -Destination (Join-Path $projectRoot '.env')
    }

    # Install only when the environment lacks one of the application's dependencies.
    & $pythonPath -c 'import fastapi, uvicorn, multipart, ultralytics, cv2, numpy, PIL, torch, torchvision, lap, sqlalchemy, aiosqlite, asyncpg, pydantic_settings, dotenv, httpx, slowapi, loguru, yaml' 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'Installing Python dependencies. First setup can take several minutes...'
        Invoke-Checked -Program $pythonPath -Arguments @('-m', 'pip', 'install', '-r', 'requirements.txt')
    }

    Push-Location -LiteralPath $frontendPath
    try {
        if (-not (Test-Path -LiteralPath 'node_modules\.bin\vite.cmd')) {
            Write-Host 'Installing frontend dependencies...'
            if (Test-Path -LiteralPath 'package-lock.json') {
                Invoke-Checked -Program $npm.Source -Arguments @('ci')
            } else {
                Invoke-Checked -Program $npm.Source -Arguments @('install')
            }
        }
        Write-Host 'Building the web dashboard...'
        Invoke-Checked -Program $npm.Source -Arguments @('run', 'build')
    } finally { Pop-Location }

    if (Test-VisionX) {
        Write-Host "VisionX is already running at $appUrl" -ForegroundColor Green
        Save-ServerPid
        if (-not $NoBrowser) { Start-Process $appUrl }
        exit 0
    }

    $listener = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
    if ($listener) { throw 'Port 8000 is occupied by another service. Stop that service, then try again.' }

    New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
    $stdout = Join-Path $logDirectory 'server.stdout.log'
    $stderr = Join-Path $logDirectory 'server.stderr.log'
    Write-Host 'SERVER START: launching the Python backend...' -ForegroundColor Cyan
    $ownedServer = Start-Process -FilePath $pythonPath `
        -ArgumentList @('-m', 'uvicorn', 'main:app', '--app-dir', 'backend', '--host', '127.0.0.1', '--port', '8000') `
        -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput $stdout -RedirectStandardError $stderr

    $ready = $false
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        $ownedServer.Refresh()
        if ($ownedServer.HasExited) {
            Get-Content -LiteralPath $stderr -Tail 20 | Out-Host
            throw 'Backend exited during startup. See logs\server.stderr.log.'
        }
        if (Test-VisionX) { $ready = $true; break }
        Start-Sleep -Seconds 1
    }
    if (-not $ready) { throw 'Backend did not become ready. See logs\server.stderr.log.' }
    Save-ServerPid
    $startedSuccessfully = $true

    Write-Host "`nFull app ready: $appUrl" -ForegroundColor Green
    Write-Host 'The Python server serves both the web dashboard and the AI API.'
    Write-Host "Logs: $logDirectory"
    if (-not $NoBrowser) { Start-Process $appUrl }
    Write-Host 'SERVER RUNNING. You can close this window; the server stays running.'
    Write-Host 'To stop it later: Run-VisionX.bat stop'
} catch {
    Write-Host "`nERROR: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
} finally {
    if ($ownedServer -and -not $startedSuccessfully) {
        $ownedServer.Refresh()
        if (-not $ownedServer.HasExited) {
            # Windows virtual-environment Python can launch a child interpreter.
            # Stop only the process tree created by this launcher.
            & taskkill.exe /PID $ownedServer.Id /T /F 2>$null | Out-Null
        }
    }
}
