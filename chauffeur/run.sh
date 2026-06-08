#!/usr/bin/env bash

echo "Starting Chauffeur..."
cd /app
exec uvicorn main:app --host 0.0.0.0 --port 8000
