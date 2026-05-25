@echo off
setlocal

set "ROOT=%~dp0"

cd /d "%ROOT%"

py scripts\open_public_dashboard.py
if %ERRORLEVEL%==0 goto done

python scripts\open_public_dashboard.py
if %ERRORLEVEL%==0 goto done

echo Public dashboard launcher failed. Python may not be installed or available.
pause

:done

endlocal
