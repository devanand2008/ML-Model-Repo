@echo off
setlocal
cd /d "%~dp0"
echo Opening the full application screen recorder.
echo Sign in, click Record guided tour, and choose this app tab.
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\Start-VisionX.ps1" start -OpenPath /record-demo %*
if errorlevel 1 (pause & exit /b 1)
endlocal
