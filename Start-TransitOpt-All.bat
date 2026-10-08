@echo off
setlocal
title TransitOpt - Full ML Web Application
cd /d "%~dp0"
echo Starting all application modules on one shared ML server...
echo Passenger navigation, admin, YOLO cameras, bus crowding,
echo traffic prediction, XGBoost demand, fleet optimization and reports.
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\Start-VisionX.ps1" start %*
if errorlevel 1 (pause & exit /b 1)
echo.
echo Full app:       http://127.0.0.1:8000/
echo Camera ML:      http://127.0.0.1:8000/ml
echo Admin:          http://127.0.0.1:8000/admin
echo Passenger:      http://127.0.0.1:8000/passenger
echo Guided recorder:http://127.0.0.1:8000/record-demo
echo Phone HTTPS:    Run-TransitOpt-Phone.bat start
echo Stop app:       Run-TransitOpt.bat stop
endlocal
