#!/usr/bin/env bash
# Installa il provider POT locale richiesto da alcuni stream YouTube moderni.
set -euo pipefail

cd "$(dirname "$0")/.."
image="${PYTONAZZ_POT_IMAGE:-brainicism/bgutil-ytdlp-pot-provider:2.0.0}"

venv/bin/python -m pip install --upgrade bgutil-ytdlp-pot-provider

if docker container inspect pytonazz-pot-provider >/dev/null 2>&1; then
  docker start pytonazz-pot-provider >/dev/null
else
  docker run -d --name pytonazz-pot-provider --restart unless-stopped \
    -p 127.0.0.1:4416:4416 "$image"
fi

for _ in {1..20}; do
  if curl --fail --silent --show-error http://127.0.0.1:4416/ping >/dev/null; then
    echo "POT provider pronto su 127.0.0.1:4416"
    exit 0
  fi
  sleep 1
done

echo "Il container POT non risponde su 127.0.0.1:4416" >&2
exit 1
