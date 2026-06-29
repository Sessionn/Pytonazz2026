# Lavalink per link-up

Questo setup e' sperimentale e serve per confrontare il backend attuale con
Lavalink/Wavelink sulla VM, senza scrivere nel DB cache.

## Avvio

```bash
cd ~/Pytonazz2026/infra/lavalink
docker compose up -d
docker compose logs -f lavalink
```

## Config bot/benchmark

Default usati dal branch:

```env
AUDIO_BACKEND=current
LAVALINK_URI=http://127.0.0.1:2333
LAVALINK_PASSWORD=youshallnotpass
LAVALINK_SEARCH_SOURCE=youtube_music
LAVALINK_SPOTIFY_NATIVE=true
```

Il compose legge `../../.env` per passare a LavaSrc le stesse credenziali
`SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET` gia' usate dal bot. Se LavaSrc non
riesce a risolvere un link Spotify, il backend sperimentale ricade sul ponte
Python `Spotify -> metadata -> Lavalink search`.

Benchmark:

```bash
cd ~/Pytonazz2026
. venv/bin/activate
python tools/benchmark_audio_backends.py --backend both --jsonl /tmp/link-up-bench.jsonl
```

Il benchmark imposta `Config.CACHE_ENABLED = False` e svuota le cache runtime tra
un caso e l'altro.
