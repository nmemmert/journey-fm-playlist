# Setup Task Scheduler for Journey FM Playlist Updater
# Run this script as Administrator to create scheduled tasks

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$psScript = "$scriptDir\run_journey_playlist.ps1"

# Task 1: Run every 15 minutes
$action1 = New-ScheduledTaskAction -Execute "PowerShell.exe" -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$psScript`""
$trigger1 = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 15)
$settings1 = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

Register-ScheduledTask -TaskName "Journey FM Playlist Updater - Every 15 Minutes" -Action $action1 -Trigger $trigger1 -Settings $settings1 -Description "Updates Plex playlist with recently played songs from Journey FM every 15 minutes" -Force

# Task 2: Run at startup
$action2 = New-ScheduledTaskAction -Execute "PowerShell.exe" -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$psScript`""
$trigger2 = New-ScheduledTaskTrigger -AtStartup
$trigger2.Delay = "PT1M"  # 1 minute delay after startup
$settings2 = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

Register-ScheduledTask -TaskName "Journey FM Playlist Updater - At Startup" -Action $action2 -Trigger $trigger2 -Settings $settings2 -Description "Updates Plex playlist with recently played songs from Journey FM at computer startup" -Force

Write-Host "Scheduled tasks created successfully!" -ForegroundColor Green
Write-Host "Task 1: Runs every 15 minutes" -ForegroundColor Cyan
Write-Host "Task 2: Runs at computer startup (with 60 second delay)" -ForegroundColor Cyan
Write-Host ""
Write-Host "You can view and manage these tasks in Task Scheduler." -ForegroundColor Yellow
