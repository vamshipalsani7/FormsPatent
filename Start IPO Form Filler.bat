@echo off
title IPO Form Filler
rem Starts the IPO Form Filler and opens it in your browser.
rem Keep this window open while you use the tool; close it to stop.
cd /d "%~dp0"

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (
  where python >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo.
  echo  Python 3 is needed to run IPO Form Filler.
  echo  1. Download it from https://www.python.org/downloads/
  echo  2. During installation, tick "Add python.exe to PATH".
  echo  3. Then double-click this file again.
  echo.
  pause
  exit /b 1
)

echo Starting IPO Form Filler... (your browser will open)
%PY% server.py
if errorlevel 1 (
  echo.
  echo  The tool stopped with an error. If it says the port is in use,
  echo  it may already be running - look for it in your browser at
  echo  http://127.0.0.1:8765
  echo.
)
pause
