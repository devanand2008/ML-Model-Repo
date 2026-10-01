@echo off
setlocal
title VisionX AI Analyzer
cd /d "%~dp0"
echo VisionX server launcher - default command: START
echo Commands: Run-VisionX.bat start ^| stop ^| status
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\Start-VisionX.ps1" %*
if errorlevel 1 (
    echo.
    echo VisionX could not start. See the message above.
    pause
    exit /b 1
)
endlocal
