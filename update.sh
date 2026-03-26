#!/bin/bash
# Update script for Journey FM Playlist project.
#  - pulls latest code from GitHub
#  - rebuilds and restarts container
#  - supports docker or podman (auto-detect or ask)

set -e

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
cd "$REPO_DIR"

if [ ! -d .git ]; then
    echo "Error: this directory is not a git repository. Run this script from repository root."
    exit 1
fi

# Determine container tool
CONTAINER_TOOL=""
if command -v docker >/dev/null 2>&1; then
    CONTAINER_TOOL="docker"
fi
if command -v podman >/dev/null 2>&1; then
    if [ -n "$CONTAINER_TOOL" ]; then
        echo "Both docker and podman are installed. Choose one:"
        select t in docker podman; do
            [ -n "$t" ] && CONTAINER_TOOL="$t" && break
            echo "Invalid choice"
        done
    else
        CONTAINER_TOOL="podman"
    fi
fi

if [ -z "$CONTAINER_TOOL" ]; then
    echo "No docker or podman binary found. Please install one and retry."
    exit 1
fi

COMPOSE_CMD="$CONTAINER_TOOL compose"

# Pull latest branch
echo "Pulling latest code from origin/main..."
git fetch origin
if git rev-parse --abbrev-ref HEAD | grep -q "^main$"; then
    git reset --hard origin/main
else
    echo "Not on main branch; pulling and fast-forwarding current branch if possible..."
    git pull --ff-only
fi

# Rebuild and restart in compose
echo "Building container with $COMPOSE_CMD..."
$COMPOSE_CMD build

echo "Bringing container up..."
$COMPOSE_CMD up -d

# Provide status
echo "Container status:"
$COMPOSE_CMD ps

echo "Done. Web dashboard is available at http://localhost:8765 (if enabled)."
