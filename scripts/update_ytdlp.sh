#!/usr/bin/env bash
set -euo pipefail
# yt-dlp deve essere aggiornato spesso (YouTube cambia API frequentemente)
echo "Aggiornamento yt-dlp..."
python -m pip install -U yt-dlp
echo "Versione: $(yt-dlp --version)"
