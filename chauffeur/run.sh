#!/usr/bin/env bash

echo "Starting Chauffeur..."
cd /app

# A virtual display for browse missions (services/browse.py): a headed
# Chromium on it is an ordinary browser to a site's human check, where a
# headless one gets challenged (2026-10-11, three image grids). Without
# Xvfb the runner stays headless, as before.
if command -v Xvfb >/dev/null 2>&1; then
    Xvfb :99 -screen 0 1440x900x24 -nolisten tcp >/dev/null 2>&1 &
    export DISPLAY=:99
    echo "Virtual display :99 up for browse missions"
fi

exec uvicorn main:app --host 0.0.0.0 --port 8000
