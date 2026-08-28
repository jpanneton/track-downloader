#!/bin/sh
# Double-clicked from Finder on macOS, or run as ./launch.command elsewhere

# Run from this folder whatever the Finder was started in
cd "$(dirname "$0")" || exit 1

# python3 is what macOS and most distributions ship, python may not exist
PYTHON=python3
command -v python3 >/dev/null 2>&1 || PYTHON=python

"$PYTHON" download_tracks.py --gui
status=$?

# Keep the window open so a failure can be read
if [ $status -ne 0 ]; then
    printf '\nExited with status %s, press Return to close.\n' "$status"
    read -r _
fi
