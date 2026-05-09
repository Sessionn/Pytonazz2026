#!/usr/bin/env bash
set -e
echo "=== Pitonazz — Setup iniziale ==="

# Python deps
pip install -r requirements.txt
echo "✅ Dipendenze Python installate."

# FFmpeg check
if command -v ffmpeg &>/dev/null; then
  echo "✅ FFmpeg: $(ffmpeg -version 2>&1 | head -1)"
else
  echo ""
  echo "❌ FFmpeg NON trovato! Installalo:"
  echo "   Ubuntu/Debian : sudo apt install ffmpeg"
  echo "   macOS          : brew install ffmpeg"
  echo "   Windows        : https://ffmpeg.org/download.html"
  echo ""
fi

# .env check
if [ ! -f .env ]; then
  if [ -f .env.example ]; then
    cp .env.example .env
    echo "📄 .env creato da .env.example — ricordati di compilarlo!"
  else
    cat > .env <<'EOF'
DISCORD_TOKEN=
OWNER_ID=
DEV_IDS=
DEV_ID=
SPOTIFY_CLIENT_ID=
SPOTIFY_CLIENT_SECRET=
GEMINI_API_KEY=
GROQ_API_KEY=
GUILD_IDS=
YTDLP_PROXY=
SHOW_BANNER=true
EOF
    echo "📄 .env.example non trovato: creato .env base — ricordati di compilarlo!"
  fi
else
  echo "✅ .env già presente."
fi

echo ""
echo "Avvia con: python main.py"
