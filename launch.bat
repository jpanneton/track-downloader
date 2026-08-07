@echo off
REM Run from this folder whatever the shortcut was started in
cd /d "%~dp0"

REM The py launcher picks a suitable Python, fall back to the one on PATH
set PYTHON=py -3
where py >nul 2>&1 || set PYTHON=python

%PYTHON% download_tracks.py --gui

REM Keep the window open so a failure can be read
if errorlevel 1 pause
