# Journey FM Playlist Creator

Desktop app + script that pulls recently played songs from Journey FM / Spirit FM and updates a Plex playlist.

## What It Does

- Scrapes recently played songs from:
  - `https://www.myjourneyfm.com/recently-played/`
  - `https://spiritfm.com/ajax/now_playing_history.txt`
- Matches tracks in your Plex Music library with title/artist normalization.
- Creates or updates your configured Plex playlist.
- Avoids adding duplicates already in the target playlist.
- Tracks run history in `playlist_history.db`.
- Writes missing songs to `amazon_buy_list.txt` with Amazon search links.
- Provides a GUI with system tray support, settings, log viewer, history, stats, analytics, and CSV export.

## Requirements

- Python 3.10+
- Plex account token + reachable Plex server
- A Chrome/Chromium browser for Selenium scraping

Dependencies are listed in `requirements.txt` (GUI uses `PySide6`).

## Install

### Windows

Simple install from GitHub (recommended):

1. Open **PowerShell**.
2. Run:

```powershell
git clone https://github.com/nmemmert/journey-fm-playlist.git
cd journey-fm-playlist
.\install_windows.bat
```

3. Launch from:
   - Start Menu: **Journey FM Playlist Creator**
   - Desktop shortcut: **Journey FM Playlist Creator**

No Git? Download ZIP from GitHub (**Code -> Download ZIP**), extract, open PowerShell in that folder, and run:

```powershell
.\install_windows.bat
```

If script execution is blocked:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\install_windows.ps1
```

Optional installer switches:

- `-NoDesktopShortcut` skips Desktop shortcut creation
- `-NoStartMenuShortcut` skips Start Menu shortcut creation

Manual install (advanced):

```powershell
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python journey_fm_app.py
```

Installer files:

- `install_windows.bat` - one-click installer launcher
- `install_windows.ps1` - installer logic

### Linux

Quick setup:

```bash
./install.sh
```

Manual setup:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python journey_fm_app.py
```

## Configuration

Use the GUI setup wizard (first launch) or edit `config.json` directly.

Example `config.json`:

```json
{
  "PLEX_TOKEN": "your-plex-token",
  "SERVER_IP": "192.168.1.100",
  "PLAYLIST_NAME": "Journey FM Recently Played",
  "AUTO_UPDATE": true,
  "UPDATE_INTERVAL": 15,
  "UPDATE_UNIT": "Minutes",
  "SELECTED_STATIONS": "journey_fm,spirit_fm"
}
```

You can also provide runtime env vars:

- `PLEX_TOKEN`
- `SERVER_IP`
- `PLAYLIST_NAME`

Optional browser override:

- `CHROME_BINARY` (absolute path to Chrome/Chromium executable)

If `CHROME_BINARY` is not set, the app auto-detects browser locations for Windows/Linux/macOS and then falls back to `PATH`.

## Running Without GUI

Run one update cycle from CLI:

```bash
python main.py
```

## GUI Notes

- Minimize-to-tray on close when tray is available.
- Tray menu supports Show / Update Now / Quit.
- Auto-update runs on configurable interval.
- Works on X11 and Wayland Linux sessions.

## Output Files

- `config.json` - runtime settings shared by GUI and CLI
- `playlist_history.db` - update history and statistics data
- `playlist_log.txt` - GUI update logs
- `amazon_buy_list.txt` - missing songs with Amazon links
- `playlist_export.csv` - exported playlist from GUI action

## Troubleshooting

- **Server not found**: verify `SERVER_IP`, Plex availability, and that you are signed in with the correct account token.
- **No songs added**: confirm scraped songs exist in your Plex library and metadata is correct.
- **Browser startup errors**: install Chrome/Chromium or set `CHROME_BINARY` explicitly.
- **No tray icon**: some desktop environments disable or hide legacy trays.
- **GUI fails at startup (`libGL.so.1` / PySide6 import errors)**: install missing system graphics libs (Linux example: `sudo apt install libgl1`) and reinstall Python deps with `pip install -r requirements.txt`.

## Core Files

- `journey_fm_app.py` - desktop GUI and tray app
- `main.py` - scraping + Plex update pipeline
- `requirements.txt` - Python dependencies
- `install.sh` - Linux setup helper

## Pre-Release Checklist

- Verify `config.json` has valid `PLEX_TOKEN`, `SERVER_IP`, and `PLAYLIST_NAME`.
- Run one CLI update: `python main.py` and confirm songs/history are written.
- Run GUI update: `python journey_fm_app.py` and verify status/log output updates.
- Confirm tray behavior (minimize to tray, Show/Update/Quit actions).
- On Windows/Linux, confirm Chrome/Chromium detection or set `CHROME_BINARY`.
- Export playlist once and verify `playlist_export.csv` is created.