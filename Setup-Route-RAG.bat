@echo off
setlocal
cd /d "%~dp0"
if not exist "%~dp0.venv\Scripts\python.exe" (
  echo Run Start-TransitOpt-All.bat first to prepare the environment.
  pause
  exit /b 1
)
"%~dp0.venv\Scripts\python.exe" -m pip install "transformers>=4.45,<5" "sentencepiece>=0.2,<1"
if errorlevel 1 (pause & exit /b 1)
"%~dp0.venv\Scripts\python.exe" "%~dp0scripts\prepare_route_rag.py"
if errorlevel 1 (pause & exit /b 1)
echo Route RAG model is installed. Open http://127.0.0.1:8000/rag
endlocal
