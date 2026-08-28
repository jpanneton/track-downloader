#!/bin/sh
# Double-clicked from Finder on macOS, or run as ./update.command elsewhere

# Run from this folder whatever the Finder was started in
cd "$(dirname "$0")" || exit 1

# python3 is what macOS and most distributions ship, python may not exist
PYTHON=python3
command -v python3 >/dev/null 2>&1 || PYTHON=python

# A pull can bring in a new dependency, the app won't start without it
if git pull && "$PYTHON" -m pip install -r requirements.txt; then
    printf '\nUp to date, press Return to close.\n'
else
    printf '\nUpdate failed, see the message above. Press Return to close.\n'
fi

read -r _
