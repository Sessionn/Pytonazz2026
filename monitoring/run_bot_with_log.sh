#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
mkdir -p monitoring/logs

LOG_FILE="${PYTONAZZ_BOT_LOG:-monitoring/logs/bot.log}"
PYTHON_BIN="${PYTONAZZ_PYTHON:-venv/bin/python}"

exec "$PYTHON_BIN" main.py 2>&1 | tee -a "$LOG_FILE"
