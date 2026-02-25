@echo off
REM Journey FM Playlist Creator - Windows Installer Launcher

cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_windows.ps1"
if errorlevel 1 (
  echo.
  echo Installation failed. See output above for details.
  pause
  exit /b 1
)

echo.
echo Installation finished successfully.
pause
