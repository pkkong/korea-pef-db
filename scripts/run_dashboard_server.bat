@echo off
cd /d "%~dp0\.."

where py >nul 2>nul
if %ERRORLEVEL%==0 (
  py scripts\serve_dashboard.py
  exit /b %ERRORLEVEL%
)

python scripts\serve_dashboard.py
