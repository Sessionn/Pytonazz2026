#!/usr/bin/env bash
set -euo pipefail

echo "=== Pitonazz - Setup iniziale ==="

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python3}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  PYTHON_BIN="python"
fi
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "ERRORE: Python non trovato. Installa Python 3.11+ e riprova."
  exit 1
fi

if [ ! -d ".venv" ]; then
  "$PYTHON_BIN" -m venv .venv
  echo "OK: virtualenv creato in .venv"
fi

if [ -f ".venv/bin/activate" ]; then
  # shellcheck disable=SC1091
  source ".venv/bin/activate"
elif [ -f ".venv/Scripts/activate" ]; then
  # shellcheck disable=SC1091
  source ".venv/Scripts/activate"
fi

python -m pip install --upgrade pip
python -m pip install -r requirements.txt
echo "OK: dipendenze Python installate."

if command -v ffmpeg >/dev/null 2>&1; then
  echo "OK: FFmpeg: $(ffmpeg -version 2>&1 | head -1)"
else
  echo ""
  echo "ERRORE: FFmpeg non trovato. Installalo:"
  echo "   Ubuntu/Debian : sudo apt install ffmpeg"
  echo "   macOS          : brew install ffmpeg"
  echo "   Windows        : https://ffmpeg.org/download.html"
  echo ""
fi

if [ ! -f .env ]; then
  if [ -f .env.example ]; then
    cp .env.example .env
    echo "OK: .env creato da .env.example. Compilalo con segreti nuovi."
  else
    cat > .env <<'EOF'
DISCORD_TOKEN=
OWNER_ID=
DEV_IDS=
DEV_ID=
SPOTIFY_CLIENT_ID=
SPOTIFY_CLIENT_SECRET=
GROQ_API_KEY=
GUILD_IDS=
YTDLP_PROXY=
SHOW_BANNER=true
EOF
    echo "OK: .env.example non trovato, creato .env base. Compilalo con segreti nuovi."
  fi
else
  echo "OK: .env gia presente."
fi

mkdir -p data/logs data/tmp assets

if python -m yt_dlp --version >/dev/null 2>&1; then
  echo "OK: yt-dlp disponibile: $(python -m yt_dlp --version)"
else
  echo "WARN: yt-dlp non verificabile."
fi

echo ""
echo "Avvia con: python main.py"
