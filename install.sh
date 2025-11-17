#!/bin/bash
# Journey FM Playlist Creator - Linux Installer

echo "Journey FM Playlist Creator - Linux Installer"
echo "=============================================="

# Get the directory where this script is located
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

echo "Installing in: $DIR"

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

# Install Chromium browser
if ! command -v chromium-browser > /dev/null 2>&1; then
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
update-desktop-database ~/.local/share/applications

# Make scripts executable
chmod +x "$DIR/journey_fm_app.sh"

echo "Installation complete!"
echo "You can now find 'Journey FM Playlist' in your applications menu."
echo "Or run: $DIR/journey_fm_app.sh"