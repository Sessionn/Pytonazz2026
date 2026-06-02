# Pytonazz2026

Pytonazz2026 e' un bot Discord modulare scritto in Python, costruito su `discord.py` 2.x. Il progetto copre musica, AI, moderazione, welcome/goodbye, compleanni, TTS, console DJ remota e una dashboard web per ispezionare il cache database musicale.

Questo README e' la panoramica del progetto. Per i dettagli tecnici usa:

- [DOCS.md](DOCS.md): manuale tecnico e operativo per sviluppatori.
- [CACHE_DB.md](CACHE_DB.md): schema, algoritmo e manutenzione del cache DB musicale.
- [SETUP_UBUNTU_VM.md](SETUP_UBUNTU_VM.md): installazione e deploy su VM Ubuntu.
- [QUERY_CACHE_SETUP.md](QUERY_CACHE_SETUP.md): note storiche e operative sulla query cache.
- [CACHE_DB_REVIEW_2026-06.md](CACHE_DB_REVIEW_2026-06.md): review architetturale della cache.

## Funzioni principali

- Musica Discord: `/play`, `/search`, playlist/album Spotify, YouTube, SoundCloud, queue, loop, seek, history, autoplay e filtri live.
- Resolve musicale: `yt-dlp` per sorgenti audio, Spotify per canonicalizzazione e cover, FFmpeg per playback voice.
- Cache DB musicale: SQLite normalizzato con tracce canoniche, sorgenti risolte, query/alias osservati, stream URL temporanei e viste compatibili.
- Dashboard web: Flask + Waitress, login, statistiche DB, tabelle cache, associazioni Spotify, eliminazioni, schema DB e console DJ.
- Console DJ remota: OAuth Discord, controllo ruolo DJ, eventi server-sent e azioni player da browser.
- AI: risposte tramite Groq, memoria per canale, supporto immagini e ricerca live via trigger web.
- Community: compleanni, welcome/goodbye, autorole, quote card, 8-ball, roulette.
- Moderazione: purge, ruoli, kick, ban, timeout, isolamento/museruola, gestione canali voice.
- Dev tools: sync slash commands, restart, maintenance, backup/restore config, runtime command enable/disable, cache commands.

## Stack

- Python 3.10+.
- `discord.py` 2.x per bot, slash commands, voice e UI.
- `yt-dlp` per ricerca ed estrazione stream.
- FFmpeg per playback audio su Discord.
- `spotipy` per metadati Spotify, cover e canonicalizzazione.
- SQLite via `sqlite3` per cache persistente.
- Flask + Waitress per dashboard locale.
- Groq API per AI.
- Edge TTS per sintesi vocale.
- Pillow per quote card.
- `httpx` / `aiohttp` per richieste HTTP.

## Avvio rapido

```bash
git clone <repo-url> Pytonazz2026
cd Pytonazz2026
python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
python main.py
```

Su Windows PowerShell:

```powershell
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python main.py
```

Lo script `scripts/setup.sh` automatizza setup base su Linux:

```bash
bash scripts/setup.sh
```

## Requisiti esterni

- Bot Discord creato nel Developer Portal, token in `DISCORD_TOKEN`.
- FFmpeg installato nel sistema o disponibile in `PATH`.
- Spotify app opzionale ma consigliata per cover e matching: `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`.
- Groq API key opzionale se vuoi usare il modulo AI: `GROQ_API_KEY`.
- Cookie YouTube opzionali ma utili su VPS/VM: `COOKIE_FILE=/percorso/assoluto/cookies.txt`.

## Variabili importanti

Le variabili sono lette da `config.py` tramite `.env`.

```env
DISCORD_TOKEN=
OWNER_ID=
DEV_IDS=
GUILD_IDS=

SPOTIFY_CLIENT_ID=
SPOTIFY_CLIENT_SECRET=
SPOTIFY_HINT_WAIT_SECONDS=0.25
SPOTIFY_AMBIGUOUS_WAIT_SECONDS=0.75

GROQ_API_KEY=

CACHE_ENABLED=true
DB_PATH=data/database/cache.db
CACHE_TTL_DAYS=30
CACHE_MAX_ENTRIES=500

DASHBOARD_SOCKET=127.0.0.1:5000
DASH_USER=admin
DASH_PASSWORD=
DASH_SECRET_KEY=
DASH_TRUST_PROXY=true
DASH_SESSION_SECURE=true
DASH_SESSION_SAMESITE=Lax
DASHBOARD_PUBLIC_BASE_URL=
DJ_CONSOLE_CALLBACK_URL=

COOKIE_FILE=
YTDLP_PROXY=
FFMPEG_PROXY=
LOG_LEVEL=INFO
SHOW_BANNER=true
```

Vedi [.env.example](.env.example) e [SETUP_UBUNTU_VM.md](SETUP_UBUNTU_VM.md) per deploy completo.

## Struttura repository

```text
.
|-- main.py                         # entrypoint bot, load cogs, status rotation, dashboard bootstrap
|-- config.py                       # parser .env e opzioni runtime
|-- requirements.txt                # dipendenze Python
|-- cogs/                           # comandi slash e domini funzionali
|-- core/                           # logica condivisa: player, resolver, cache, permessi, runtime
|-- core/source_resolver/           # yt-dlp, Spotify, scoring e resolve musicale
|-- core/music/                     # player voice, queue, input parser, live FX
|-- data/database/dashboard/        # Flask app, template, CSS/JS dashboard e DJ console
|-- tools/                          # manutenzione DB, benchmark, audit
|-- scripts/                        # setup e deploy slash commands
|-- tests/                          # test script-style eseguibili con python
|-- assets/                         # prompt, config JSON, status, dati statici
|-- ui/                             # embed e view Discord
```

## Cache DB e reset

Il cache DB non e' piu' una singola tabella legacy: usa schema normalizzato con:

- `cache_tracks`: identita' logica/canonica della traccia.
- `cache_sources`: sorgenti riproducibili, stream URL temporaneo, cover e metadati.
- `cache_queries`: query osservate, alias e associazioni.
- viste compatibili `song_cache` e `query_aliases`.

Reset DB:

```bash
python tools/rebuild_cache_db.py --backup
```

Non usare `source tools/rebuild_cache_db.py`: e' uno script Python, non shell.

Dettagli: [CACHE_DB.md](CACHE_DB.md).

## Deploy VM

Su Ubuntu la dashboard deve ascoltare su `127.0.0.1:5000` e stare dietro reverse proxy HTTPS. Non esporre direttamente la porta `5000`.

Percorso consigliato:

```text
Internet -> 80/443 -> Caddy -> 127.0.0.1:5000 -> dashboard Flask
Discord voice -> processo Python -> FFmpeg
```

Guida completa: [SETUP_UBUNTU_VM.md](SETUP_UBUNTU_VM.md).

## Debug performance musicale

Benchmark resolver:

```bash
python tools/benchmark_resolve.py "trust me"
```

Benchmark yt-dlp diretto:

```bash
python tools/benchmark_ytdlp.py "Trust Me Pandora"
```

Nota sui retry: in `config.py`, `retries`, `fragment_retries` e `extractor_retries` indicano quanti tentativi extra yt-dlp fa dopo un errore. Non sono "quante ricerche YouTube normali" fa il bot. Ridurli taglia tempo quando YouTube risponde male o con anti-bot, ma puo' rendere meno tolleranti alcuni errori temporanei.

## Test

I test sono script Python indipendenti:

```bash
python tests/test_resolver_spotify_canonical_fallback_cover.py
python tests/test_cache_thumbnail_stream.py
```

Esecuzione completa in PowerShell:

```powershell
Get-ChildItem tests -Filter *.py | ForEach-Object { .\venv\Scripts\python.exe $_.FullName }
```

Esecuzione completa in bash:

```bash
for f in tests/*.py; do python "$f"; done
```

## Licenza e note

Progetto personale a scopo ludico, didattico e operativo per una community Discord. Non committare `.env`, cookie, token Discord, segreti Spotify, chiavi Groq o backup contenenti dati reali.
