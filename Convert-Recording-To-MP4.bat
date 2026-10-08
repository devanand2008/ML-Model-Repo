@echo off
setlocal
cd /d "%~dp0"
if "%~1"=="" (
    echo Drag your recorded WebM file onto this BAT file.
    pause
    exit /b 1
)
"%~dp0.venv\Scripts\python.exe" "%~dp0scripts\convert_recording.py" "%~1"
if errorlevel 1 (pause & exit /b 1)
endlocal
