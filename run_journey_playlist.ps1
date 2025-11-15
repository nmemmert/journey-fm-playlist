# Journey FM Playlist Updater - PowerShell Script
# Run this script to update your Plex playlist with recently played songs from Journey FM

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonExe = "$scriptDir\.venv\Scripts\python.exe"
$mainScript = "$scriptDir\main.py"
$logFile = "$scriptDir\playlist_log.txt"

# Run the Python script and capture output
$output = & $pythonExe $mainScript 2>&1 | Out-String

# Append the full output to the log file
Add-Content -Path $logFile -Value $output
