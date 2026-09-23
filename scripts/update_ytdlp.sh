#!/usr/bin/env bash
# yt-dlp deve essere aggiornato spesso (YouTube cambia API frequentemente)
echo "Aggiornamento yt-dlp..."
set -euo pipefail
cd "$(dirname "$0")/.."
venv/bin/python -m pip install -U 'yt-dlp[default]'
venv/bin/python -m yt_dlp --version
