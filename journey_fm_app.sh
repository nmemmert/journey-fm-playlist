#!/bin/bash
# Journey FM Playlist Creator - Linux Startup Script

# Get the directory where this script is located
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

# Activate virtual environment if it exists
if [ -d "$DIR/.venv" ]; then
    source "$DIR/.venv/bin/activate"
fi

# Run the application
cd "$DIR"
python journey_fm_app.py