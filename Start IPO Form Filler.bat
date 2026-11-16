@echo off
rem Starts the IPO Form Filler and opens it in your browser.
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Python 3 is required. Install it from https://www.python.org/downloads/ and try again.
  pause
  exit /b 1
)
python server.py
pause
