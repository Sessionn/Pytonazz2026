#!/usr/bin/env bash
# yt-dlp deve essere aggiornato spesso (YouTube cambia API frequentemente)
echo "Aggiornamento yt-dlp..."
pip install -U yt-dlp
echo "Versione: $(yt-dlp --version)"