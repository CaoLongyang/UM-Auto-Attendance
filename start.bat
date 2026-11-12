@echo off
chcp 65001 >nul
cd /d "%~dp0"
title UM Auto Attendance Manager

set "PY=venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

echo Starting Auto Attendance ...
"%PY%" gui.py

if errorlevel 1 (
  echo.
  echo The app exited with an error - copy the message above when asking for help.
  pause
)
