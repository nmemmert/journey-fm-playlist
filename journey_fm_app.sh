#!/bin/bash
# Journey FM Playlist Creator - Linux Startup Script

# Get the directory where this script is located
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

# Create virtual environment if it doesn't exist
if [ ! -d "$DIR/.venv" ]; then
    python3 -m venv "$DIR/.venv"
fi

# Activate virtual environment
source "$DIR/.venv/bin/activate"

# Install dependencies
pip install -r "$DIR/requirements.txt"

# Run the application
cd "$DIR"
python3 journey_fm_app.py