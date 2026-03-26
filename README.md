# Journey FM Playlist Creator

Desktop app + script that pulls recently played songs from Journey FM / Spirit FM and updates a Plex playlist.

## What It Does

- Scrapes recently played songs from:
  - `https://www.myjourneyfm.com/recently-played/`
  - `https://spiritfm.com/ajax/now_playing_history.txt`
  - `https://www.klove.com/music/songs`
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

Interactive install now captures defaults and writes `.env` (auto with optional values):

```bash
./install.sh
```

The installer sets defaults:
- UPDATE_UNIT=Minutes
- CONTAINER_RUN_MODE=loop
- SERVER_IP=172.16.16.106
- PLAYLIST_NAME=Radio
- SELECTED_STATIONS=journey_fm,spirit_fm,klove
- UPDATE_INTERVAL=15
- AUTO_UPDATE=true
- PLEX_TOKEN=pU-m3HWYUZU6iXJFhJyA
- PYTHONUNBUFFERED=1
- JOURNEYFM_DATA_DIR=/data
- TERM=xterm
- CHROME_BINARY=/usr/bin/chromium
- JOURNEYFM_CONTAINER=1
- LANG=C.UTF-8
- CHROMEDRIVER_PATH=/usr/bin/chromedriver

Web dashboard defaults to enabled with start at http://localhost:8765 (or `DASHBOARD_PORT`).

Manual setup:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python journey_fm_app.py
```

## Configuration

Use the GUI setup wizard (first launch) or edit `config.json` directly.

The Plex token is now stored in your OS credential store via `keyring` when available.
On Windows this means the app no longer needs to persist `PLEX_TOKEN` in `config.json`.

Example `config.json`:

```json
{
  "SERVER_IP": "192.168.1.100",
  "PLAYLIST_NAME": "Journey FM Recently Played",
  "AUTO_UPDATE": true,
  "UPDATE_INTERVAL": 15,
  "UPDATE_UNIT": "Minutes",
  "SELECTED_STATIONS": "journey_fm,spirit_fm,klove"
}
```

You can also provide runtime env vars:

- `PLEX_TOKEN`
- `SERVER_IP`
- `PLAYLIST_NAME`
- `AUTO_UPDATE`
- `UPDATE_INTERVAL`
- `UPDATE_UNIT`
- `SELECTED_STATIONS`

Optional browser override:

- `CHROME_BINARY` (absolute path to Chrome/Chromium executable)

If `CHROME_BINARY` is not set, the app auto-detects browser locations for Windows/Linux/macOS and then falls back to `PATH`.

## Running Without GUI

Run one update cycle from CLI:

```bash
python main.py
```

Run one update cycle and start a local web dashboard for live counts and station metrics:

```bash
python main.py --serve-web
```

Advanced options:

- `--host`: Web dashboard listen host (default `127.0.0.1`)
- `--port`: Web dashboard listen port (default `8765`)
- `--no-open`: Do not open default browser automatically

Example:

```bash
python main.py --serve-web --host 0.0.0.0 --port 8765 --no-open
```

## Container Deployment

Container mode is intended for scheduled/headless playlist updates. The container now runs as a long-lived loop and sleeps between syncs instead of relying on restart churn.

1. Copy `.env.example` to `.env` and fill in your Plex values.

```bash
cp .env.example .env
```

2. Edit `.env` in the project root:

```env
PLEX_TOKEN=your-plex-token
SERVER_IP=192.168.1.100
PLAYLIST_NAME=Journey FM Recently Played
SELECTED_STATIONS=journey_fm,spirit_fm,klove
UPDATE_INTERVAL=15
UPDATE_UNIT=Minutes
CONTAINER_RUN_MODE=loop
```

3. Build and run with Docker Compose:

```bash
docker-compose up -d --build
```

Podman equivalent:

```bash
podman compose up -d --build
```

4. Trigger a one-off run and review logs:

```bash
docker-compose run --rm -e CONTAINER_RUN_MODE=once journey-fm-playlist
docker-compose logs -f journey-fm-playlist
```

Podman equivalent:

```bash
podman compose run --rm -e CONTAINER_RUN_MODE=once journey-fm-playlist
podman compose logs -f journey-fm-playlist
```

## GitHub Container Build

GitHub Actions now builds the container on every pull request to `main` and on every push to `main`.
Pushes to `main` also publish the image to GitHub Container Registry.

Image location:

```text
ghcr.io/nmemmert/journey-fm-playlist
```

Pull with Podman:

```bash
podman pull ghcr.io/nmemmert/journey-fm-playlist:latest
```

If the package is private, authenticate first:

```bash
podman login ghcr.io
```

Notes:

- The container uses Chromium + chromedriver in headless mode.
- Runtime state is stored in the named volume mounted at `/data`, so `config.json`, `playlist_history.db`, `playlist_log.txt`, `amazon_buy_list.txt`, and `debug_scrapes/` persist without bind-mounting the repo.
- GUI (`journey_fm_app.py`) is still intended to run natively on your desktop.
- In container mode, environment variables are preferred over local config or keyring storage.
- The Compose file is Podman-friendly because it uses a named volume instead of a source bind mount.

### Podman Quick Start

On a Podman host, the shortest path is:

```bash
git clone https://github.com/nmemmert/journey-fm-playlist.git
cd journey-fm-playlist
cp .env.example .env
podman compose up -d --build
```

Useful follow-up commands:

```bash
podman compose logs -f journey-fm-playlist
podman compose run --rm -e CONTAINER_RUN_MODE=once journey-fm-playlist
podman compose down
```

## GUI Notes

- Minimize-to-tray on close when tray is available.
- Tray menu supports Show / Update Now / Quit.
- Auto-update runs on configurable interval.
- Works on X11 and Wayland Linux sessions.
- Updated visual style includes a dashboard hero section, richer status chips, and a refreshed control layout.
- Setup now includes Plex connection testing, keyring-backed token storage, playlist browsing with item counts, music-only filtering, and typed creation of new playlist names.

## Output Files

- `config.json` - non-secret runtime settings shared by GUI and CLI
- `playlist_history.db` - update history and statistics data
- `playlist_log.txt` - GUI update logs
- `amazon_buy_list.txt` - missing songs with Amazon links
- `playlist_export.csv` - exported playlist from GUI action
- `debug_scrapes/` - captured raw station responses for scraper debugging

In container mode these files live under `/data` inside the container volume.

## Troubleshooting

- **Server not found**: verify `SERVER_IP`, Plex availability, and that you are signed in with the correct account token.
- **No songs added**: confirm scraped songs exist in your Plex library and metadata is correct.
- **Browser startup errors**: install Chrome/Chromium or set `CHROME_BINARY` explicitly.
- **No tray icon**: some desktop environments disable or hide legacy trays.
- **GUI fails at startup (`libGL.so.1` / PySide6 import errors)**: install missing system graphics libs (Linux example: `sudo apt install libgl1`) and reinstall Python deps with `pip install -r requirements.txt`.

## Core Files

- `journey_fm_app.py` - desktop GUI and tray app
- `main.py` - CLI entrypoint for a single update run
- `run_container.py` - loop/once runner used by container deployments
- `journeyfm/` - shared service modules (config, scraper, Plex, history, orchestration)
- `requirements.txt` - Python dependencies
- `install.sh` - Linux setup helper

## Pre-Release Checklist

- Verify `config.json` has valid `SERVER_IP`, `PLAYLIST_NAME`, and station/schedule settings.
- Run one CLI update: `python main.py` and confirm songs/history are written.
- Run GUI update: `python journey_fm_app.py` and verify status/log output updates.
- Confirm tray behavior (minimize to tray, Show/Update/Quit actions).
- On Windows/Linux, confirm Chrome/Chromium detection or set `CHROME_BINARY`.
- Export playlist once and verify `playlist_export.csv` is created.
- For container mode, run `docker-compose run --rm -e CONTAINER_RUN_MODE=once journey-fm-playlist` and verify logs/history output.