@echo off
REM Run from this folder whatever the shortcut was started in
cd /d "%~dp0"

REM The py launcher picks a suitable Python, fall back to the one on PATH
set PYTHON=py -3
where py >nul 2>&1 || set PYTHON=python

git pull
if errorlevel 1 goto :failed

REM A pull can bring in a new dependency, the app won't start without it
%PYTHON% -m pip install -r requirements.txt
if errorlevel 1 goto :failed

echo.
echo Up to date.
pause
exit /b 0

:failed
echo.
echo Update failed, see the message above.
pause
exit /b 1
