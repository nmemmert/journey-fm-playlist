@echo off
REM Journey FM Playlist Creator - Windows Launcher

cd /d "%~dp0"

REM Activate virtual environment if it exists
if exist .venv\Scripts\activate.bat (
    call .venv\Scripts\activate.bat
)

REM Run the application
python journey_fm_app.py

pause