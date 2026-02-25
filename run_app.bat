@echo off
REM Journey FM Playlist Creator - Windows Launcher

cd /d "%~dp0"

REM Prefer virtual environment pythonw if it exists
if exist .venv\Scripts\pythonw.exe (
    .venv\Scripts\pythonw.exe journey_fm_app.py
    exit /b %errorlevel%
)

REM Fallback to PATH pythonw
pythonw journey_fm_app.py