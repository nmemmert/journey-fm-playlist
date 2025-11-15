# Setup Task Scheduler for Journey FM Playlist Updater
# Run this script as Administrator to create scheduled tasks

param(
    [string]$Type = "Both",  # Interval, Startup, Both
    [int]$Interval = 15,
    [string]$Unit = "Minutes"  # Minutes, Hours, Days
)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$psScript = "$scriptDir\run_journey_playlist.ps1"

if ($Type -eq "Interval" -or $Type -eq "Both") {
    $action = New-ScheduledTaskAction -Execute "PowerShell.exe" -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$psScript`""
    $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -$Unit $Interval)
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
    Register-ScheduledTask -TaskName "Journey FM Playlist Updater - Every $Interval $Unit" -Action $action -Trigger $trigger -Settings $settings -Description "Updates Plex playlist with recently played songs every $Interval $Unit"
    Write-Host "Created task: Every $Interval $Unit" -ForegroundColor Green
}

if ($Type -eq "Startup" -or $Type -eq "Both") {
    $action = New-ScheduledTaskAction -Execute "PowerShell.exe" -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$psScript`""
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $trigger.Delay = "PT1M"  # 1 minute delay
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
    Register-ScheduledTask -TaskName "Journey FM Playlist Updater - At Startup" -Action $action -Trigger $trigger -Settings $settings -Description "Updates Plex playlist with recently played songs at startup"
    Write-Host "Created task: At Startup" -ForegroundColor Green
}

Write-Host "Scheduled tasks created successfully!" -ForegroundColor Green
