param(
    [switch]$NoDesktopShortcut,
    [switch]$NoStartMenuShortcut
)

$ErrorActionPreference = "Stop"

Write-Host "Journey FM Playlist Creator - Windows Installer" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

function Get-PythonCommand {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        return @("py", "-3")
    }

    if (Get-Command python -ErrorAction SilentlyContinue) {
        return @("python")
    }

    throw "Python 3 is not installed or not available on PATH. Install Python 3.10+ and try again."
}

function Invoke-Python {
    param(
        [string[]]$BaseCommand,
        [string[]]$Arguments
    )

    $command = $BaseCommand[0]
    $prefixArgs = @()
    if ($BaseCommand.Count -gt 1) {
        $prefixArgs = $BaseCommand[1..($BaseCommand.Count - 1)]
    }

    & $command @prefixArgs @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed: $command $($prefixArgs -join ' ') $($Arguments -join ' ')"
    }
}

$pythonCmd = Get-PythonCommand
Write-Host "Using Python command: $($pythonCmd -join ' ')" -ForegroundColor Yellow

$venvDir = Join-Path $scriptDir ".venv"
$venvPython = Join-Path $venvDir "Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    Write-Host "Creating virtual environment..." -ForegroundColor Yellow
    Invoke-Python -BaseCommand $pythonCmd -Arguments @("-m", "venv", ".venv")
} else {
    Write-Host "Virtual environment already exists." -ForegroundColor Yellow
}

Write-Host "Upgrading pip..." -ForegroundColor Yellow
& $venvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) {
    throw "Failed to upgrade pip."
}

Write-Host "Installing dependencies from requirements.txt..." -ForegroundColor Yellow
& $venvPython -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    throw "Failed to install dependencies from requirements.txt."
}

# Create icon assets for shortcuts
try {
    Write-Host "Ensuring icon assets are available..." -ForegroundColor Yellow
    & $venvPython create_icon.py
}
catch {
    Write-Warning "Icon generation failed: $($_.Exception.Message)"
}

$shell = New-Object -ComObject WScript.Shell
$targetPath = Join-Path $scriptDir "run_app.bat"
$iconIco = Join-Path $scriptDir "icon.ico"
$iconPng = Join-Path $scriptDir "icon.png"
$iconLocation = "$env:SystemRoot\System32\shell32.dll,220"
if (Test-Path $iconIco) {
    $iconLocation = $iconIco
} elseif (Test-Path $iconPng) {
    $iconLocation = $iconPng
}

function New-AppShortcut {
    param(
        [string]$ShortcutPath
    )

    $shortcut = $shell.CreateShortcut($ShortcutPath)
    $shortcut.TargetPath = $targetPath
    $shortcut.WorkingDirectory = $scriptDir
    $shortcut.IconLocation = $iconLocation
    $shortcut.Description = "Launch Journey FM Playlist Creator"
    $shortcut.Save()
}

if (-not $NoDesktopShortcut) {
    try {
        Write-Host "Creating desktop shortcut..." -ForegroundColor Yellow
        $desktop = [Environment]::GetFolderPath("Desktop")
        $shortcutPath = Join-Path $desktop "Journey FM Playlist Creator.lnk"
        New-AppShortcut -ShortcutPath $shortcutPath
    }
    catch {
        Write-Warning "Desktop shortcut creation failed: $($_.Exception.Message)"
    }
}

if (-not $NoStartMenuShortcut) {
    try {
        Write-Host "Creating Start Menu shortcut..." -ForegroundColor Yellow
        $programs = [Environment]::GetFolderPath("Programs")
        $shortcutPath = Join-Path $programs "Journey FM Playlist Creator.lnk"
        New-AppShortcut -ShortcutPath $shortcutPath
    }
    catch {
        Write-Warning "Start Menu shortcut creation failed: $($_.Exception.Message)"
    }
}

Write-Host "" 
Write-Host "Installation complete." -ForegroundColor Green
Write-Host "Launch the app with: run_app.bat" -ForegroundColor Green
Write-Host "Or run the GUI directly with: .venv\Scripts\pythonw.exe journey_fm_app.py" -ForegroundColor Green
