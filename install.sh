#!/bin/bash
# Journey FM Playlist Creator - Linux Installer

set -e

echo "Journey FM Playlist Creator - Linux Installer"
echo "=============================================="

# Get the directory where this script is located
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

echo "Installing in: $DIR"

# Default configuration values
DEFAULT_PLEX_TOKEN="pU-m3HWYUZU6iXJFhJyA"
DEFAULT_SERVER_IP="172.16.16.106"
DEFAULT_PLAYLIST_NAME="Radio"
DEFAULT_SELECTED_STATIONS="journey_fm,spirit_fm,klove"
DEFAULT_AUTO_UPDATE="true"
DEFAULT_UPDATE_INTERVAL="15"
DEFAULT_UPDATE_UNIT="Minutes"
DEFAULT_CONTAINER_RUN_MODE="loop"
DEFAULT_ENABLE_WEB_DASHBOARD="true"
DEFAULT_DASHBOARD_PORT="8765"
DEFAULT_JOURNEYFM_DATA_DIR="/data"
DEFAULT_CHROME_BINARY="/usr/bin/chromium"
DEFAULT_CHROMEDRIVER_PATH="/usr/bin/chromedriver"
DEFAULT_JOURNEYFM_CONTAINER="1"
DEFAULT_PYTHONUNBUFFERED="1"
DEFAULT_PYTHONDONTWRITEBYTECODE="1"
DEFAULT_LANG="C.UTF-8"
DEFAULT_TERM="xterm"

# Helper for interactive prompts
ask_value() {
    local prompt="$1"
    local default="$2"
    local var
    read -p "$prompt [$default]: " var
    if [ -z "$var" ]; then
        var="$default"
    fi
    echo "$var"
}

echo "Configuring environment for .env file (press Enter to accept defaults)."

PLEX_TOKEN=$(ask_value "Plex token" "$DEFAULT_PLEX_TOKEN")
SERVER_IP=$(ask_value "Plex server IP" "$DEFAULT_SERVER_IP")
PLAYLIST_NAME=$(ask_value "Playlist name" "$DEFAULT_PLAYLIST_NAME")
SELECTED_STATIONS=$(ask_value "Selected stations" "$DEFAULT_SELECTED_STATIONS")
AUTO_UPDATE=$(ask_value "Auto update" "$DEFAULT_AUTO_UPDATE")
UPDATE_INTERVAL=$(ask_value "Update interval" "$DEFAULT_UPDATE_INTERVAL")
UPDATE_UNIT=$(ask_value "Update unit (Minutes/Hours)" "$DEFAULT_UPDATE_UNIT")
CONTAINER_RUN_MODE=$(ask_value "Container run mode (loop/once)" "$DEFAULT_CONTAINER_RUN_MODE")
ENABLE_WEB_DASHBOARD=$(ask_value "Enable web dashboard" "$DEFAULT_ENABLE_WEB_DASHBOARD")
DASHBOARD_PORT=$(ask_value "Dashboard port" "$DEFAULT_DASHBOARD_PORT")
JOURNEYFM_DATA_DIR=$(ask_value "Data volume path" "$DEFAULT_JOURNEYFM_DATA_DIR")
CHROME_BINARY=$(ask_value "Chrome binary path" "$DEFAULT_CHROME_BINARY")
CHROMEDRIVER_PATH=$(ask_value "Chromedriver path" "$DEFAULT_CHROMEDRIVER_PATH")

cat > "$DIR/.env" << EOF
PLEX_TOKEN=$PLEX_TOKEN
SERVER_IP=$SERVER_IP
PLAYLIST_NAME=$PLAYLIST_NAME
SELECTED_STATIONS=$SELECTED_STATIONS
AUTO_UPDATE=$AUTO_UPDATE
UPDATE_INTERVAL=$UPDATE_INTERVAL
UPDATE_UNIT=$UPDATE_UNIT
CONTAINER_RUN_MODE=$CONTAINER_RUN_MODE
ENABLE_WEB_DASHBOARD=$ENABLE_WEB_DASHBOARD
DASHBOARD_PORT=$DASHBOARD_PORT
JOURNEYFM_DATA_DIR=$JOURNEYFM_DATA_DIR
CHROME_BINARY=$CHROME_BINARY
CHROMEDRIVER_PATH=$CHROMEDRIVER_PATH
JOURNEYFM_CONTAINER=$DEFAULT_JOURNEYFM_CONTAINER
PYTHONUNBUFFERED=$DEFAULT_PYTHONUNBUFFERED
PYTHONDONTWRITEBYTECODE=$DEFAULT_PYTHONDONTWRITEBYTECODE
LANG=$DEFAULT_LANG
TERM=$DEFAULT_TERM
EOF

echo ".env file created at $DIR/.env"

# Ensure Docker compose exists
if ! command -v docker-compose > /dev/null 2>&1 && ! command -v docker > /dev/null 2>&1; then
    echo "docker-compose/docker not found. install docker and docker-compose before running container mode." >&2
fi

# Check if Python 3 is installed
if ! command -v python3 > /dev/null 2>&1; then
    echo "Python 3 not found. Installing Python 3..."
    sudo apt update && sudo apt install -y python3 python3-pip python3-venv
fi

# Create virtual environment
echo "Creating virtual environment..."
python3 -m venv "$DIR/.venv"

# Activate virtual environment
source "$DIR/.venv/bin/activate"

# Install Python dependencies
echo "Installing Python dependencies..."
pip install -r "$DIR/requirements.txt"

# Install Chromium browser if not available
if ! command -v chromium-browser > /dev/null 2>&1 && ! command -v chromium > /dev/null 2>&1; then
    echo "Installing Chromium browser..."
    sudo apt update && sudo apt install -y chromium-browser
fi

# Create desktop entry
echo "Creating desktop entry..."
mkdir -p ~/.local/share/applications

cat > ~/.local/share/applications/journey-fm.desktop << EOF
[Desktop Entry]
Name=Journey FM Playlist
Exec=$DIR/journey_fm_app.sh
Icon=$DIR/icon.png
Type=Application
Categories=Utility;
EOF

chmod +x ~/.local/share/applications/journey-fm.desktop

# Update desktop database
echo "Updating desktop database..."
update-desktop-database ~/.local/share/applications || true

# Make scripts executable
chmod +x "$DIR/journey_fm_app.sh"

# Optionally start web dashboard and/or app
echo "Installation complete!"
echo "Run with Docker compose (server at http://localhost:$DASHBOARD_PORT):"
echo "  docker compose up -d"
echo "To start GUI app: $DIR/journey_fm_app.sh"
