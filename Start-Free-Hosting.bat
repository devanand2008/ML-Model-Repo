@echo off
setlocal
cd /d "%~dp0"
title TransitOpt - Free Render Hosting
if not exist ".venv\Scripts\python.exe" (
  echo First run Start-TransitOpt-All.bat to set up the full ML app.
  pause
  exit /b 1
)
echo Keep this window and the laptop running for online ML.
echo The website address is printed below. Your existing app login still applies.
".venv\Scripts\python.exe" scripts\start_free_hosting.py %*
if errorlevel 1 pause
endlocal
