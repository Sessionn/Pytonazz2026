# Pytonazz2026 Developer Manual

Questo documento e' il manuale tecnico storico del bot. Per il manuale sviluppatore unico e aggiornato usa [DEVELOPER_MANUAL.md](DEVELOPER_MANUAL.md), che raccoglie flussi runtime, aggiunta comandi custom, resolver, test, logging e deploy.

## 1. Architettura generale

Pytonazz2026 e' un bot Discord asincrono basato su `discord.py`.

Flusso di avvio:

1. `main.py` carica `.env` via `python-dotenv`.
2. `config.py` costruisce `Config`, normalizzando variabili, path, proxy, cookie, FFmpeg, yt-dlp, cache e dashboard.
3. `setup_logging()` configura logger leggibili con tag di dominio.
4. `ensure_runtime_dirs()` prepara directory runtime.
5. `init_db(enabled=Config.CACHE_ENABLED)` inizializza o ricrea lo schema SQLite.
6. Se la cache e' attiva, `start_dashboard_thread()` avvia Flask/Waitress in thread separato.
7. `load_extensions()` carica i cogs elencati in `core/runtime.py`.
8. `on_ready()` sincronizza slash commands, avvia watchdog hot-reload e rotazione status.

Moduli principali:

```text
main.py
config.py
core/runtime.py
core/cache_db.py
core/source_resolver/
core/music/
data/database/dashboard/
cogs/
ui/
tools/
tests/
```

## 2. Runtime e cogs

I cogs caricati di default sono definiti in `core/runtime.py`:

```text
cogs.ai
cogs.birthdays
cogs.dj
cogs.dev
cogs.dev_audio
cogs.dev_cache
cogs.filters
cogs.fun
cogs.help
cogs.moderation
cogs.music
cogs.tts
cogs.welcome
```

Il watchdog di `main.py` controlla gli mtime dei file dei cogs ogni 5 secondi e prova `bot.reload_extension()` quando un cog cambia. Questo e' comodo in sviluppo, ma in produzione resta preferibile riavviare il processo dopo deploy importanti.

## 3. Configurazione

`config.py` e' l'unico punto centrale per le variabili d'ambiente.

### Discord

- `DISCORD_TOKEN`: token bot.
- `DISCORD_CLIENT_ID`, `DISCORD_CLIENT_SECRET`: usati per OAuth Discord della console DJ.
- `OWNER_ID`: owner principale.
- `DEV_IDS`: CSV di sviluppatori autorizzati.
- `GUILD_IDS`: CSV per sync slash commands mirato.

### Spotify

- `SPOTIFY_CLIENT_ID`
- `SPOTIFY_CLIENT_SECRET`
- `SPOTIFY_HINT_WAIT_SECONDS`, default `0.25`
- `SPOTIFY_AMBIGUOUS_WAIT_SECONDS`, default `0.75`

Spotify non streamma audio. Serve per:

- canonicalizzare query testuali;
- scegliere title/artist ufficiali;
- recuperare cover album;
- migliorare ranking e guardrail del resolver.

### yt-dlp e FFmpeg

- `COOKIE_FILE`: file cookie Netscape per YouTube.
- `YTDLP_PROXY`: proxy per yt-dlp.
- `FFMPEG_PROXY`: proxy per FFmpeg. Se vuoto, usa `YTDLP_PROXY` solo se e' HTTP/HTTPS.
- `YTDLP_PATH`, `FFMPEG_PATH`: path diagnostici/log; FFmpeg deve comunque essere raggiungibile da Discord.py.

`Config.YDL_OPTIONS` imposta:

- formato bestaudio;
- cookie se presenti;
- `socket_timeout=8`;
- retry a `1`, per limitare tempo perso su errori anti-bot;
- proxy se configurato.

`Config.FFMPEG_OPTIONS` usa opzioni reconnect compatibili con FFmpeg Ubuntu 4.4.2. Non usare `-reconnect_max_retries`: alcune build FFmpeg non la supportano.

### Cache e dashboard

- `CACHE_ENABLED=true`
- `DB_PATH=data/database/cache.db`
- `CACHE_TTL_DAYS=30`
- `CACHE_MAX_ENTRIES=500`
- `DASHBOARD_SOCKET=127.0.0.1:5000`
- `DASH_USER`, `DASH_PASSWORD`
- `DASH_SECRET_KEY`
- `DASH_TRUST_PROXY=true`
- `DASH_SESSION_SECURE=true`
- `DASH_SESSION_SAMESITE=Lax`
- `DASHBOARD_PUBLIC_BASE_URL`
- `DJ_CONSOLE_CALLBACK_URL`

La dashboard deve stare dietro reverse proxy HTTPS se esposta fuori dalla macchina.

## 4. Musica: flusso `/play`

File principali:

- `cogs/music.py`: slash commands e orchestrazione.
- `core/source_resolver/__init__.py`: resolve testuale, URL, Spotify, playlist.
- `core/source_resolver/scoring.py`: normalizzazione, Jaccard, durata, penalita'.
- `core/source_resolver/spotify.py`: client Spotify e ranking item.
- `core/source_resolver/ytdlp.py`: opzioni yt-dlp e utility URL.
- `core/music/player.py`: player Discord voice, FFmpeg, queue playback.
- `core/music/queue.py`: struttura coda.
- `core/music/live_fx.py`: filtri live PCM.

Flusso per query testuale:

1. `cogs/music.py` riceve `/play query`.
2. `SourceResolver.resolve_choices(query, ..., n=1)` prova cache DB se attiva.
3. Se cache hit e stream URL temporaneo valido: ritorna subito.
4. Se cache miss: per query testuali usa `ytsearch1` e allarga a piu' candidati solo quando il primo risultato e' sospetto.
5. Costruisce query YouTube, spesso canonicalizzata da Spotify.
6. Esegue `ytsearch1` per il direct play.
7. Applica scoring Spotify/YouTube:
   - `full`: title, artist, cover e Spotify URL vengono applicati;
   - `cover_only`: cover/Spotify URL vengono applicati, ma title/artist YouTube restano piu' conservativi;
   - `skip`: non arricchisce.
8. Salva risultato in cache DB.
9. `MusicPlayer.play_next()` usa `track.stream_url` se presente, altrimenti chiama `resolve_fresh_url()`.
10. FFmpeg riproduce lo stream in voice.

Per playlist/album Spotify il resolver usa stream asincroni e batch, cosi' il bot puo' iniziare a caricare la prima traccia senza aspettare l'intera lista.

## 5. Resolver: accuratezza e performance

Il resolver bilancia tempo e correttezza. Le scelte principali sono:

- cache-first solo per `n==1`;
- `ytsearch1` per direct play;
- `ytsearch3` solo dove servono piu' candidati o fallback multi-risultato;
- Spotify in parallelo o con finestra breve per query ambigue;
- query canonica Spotify con suffisso `audio` solo quando la query originale e' corta/ambigua e non richiede varianti;
- retry yt-dlp ridotti a `1`.

### Cosa significa retry

`retry` non significa "quante ricerche YouTube fa il bot". Significa quante volte yt-dlp riprova una richiesta che e' gia' fallita. Esempio generico:

- `ytsearch1:titolo artista` e' una ricerca.
- se YouTube risponde con timeout, errore temporaneo o anti-bot, `retries=1` concede un tentativo extra.
- `retries=2` concede due tentativi extra, ma puo' far salire molto il tempo su VM.

Ridurre retry taglia tempo nei casi problematici, ma rende yt-dlp meno paziente verso errori transitori.

### Limite pratico VM

Su alcune VM YouTube/yt-dlp puo' impiegare 4-6 secondi anche per una singola `ytsearch1`, specialmente con segnali anti-bot. In quel caso il bot non puo' riprodurre prima di avere uno stream audio valido. Cache DB e stream URL temporanei sono il modo principale per rendere veloci replay e query simili.

## 6. Cache DB

La cache persistente e' in `core/cache_db.py`. Lo schema attuale e' normalizzato:

- `cache_tracks`: identita' logica del brano.
- `cache_sources`: sorgenti riproducibili e metadati tecnici.
- `cache_queries`: query osservate, alias, metodi di match.
- `song_cache`: vista compatibile per dashboard/test legacy.
- `query_aliases`: vista compatibile.

Vedi [CACHE_DB.md](CACHE_DB.md) per schema e algoritmo.

Comandi owner:

- `/cache status`
- `/cache stats`
- `/cache on`
- `/cache off`
- `/cache prune`
- `/cache invalidate`
- `/cache clear`
- `/cache export`

Script:

```bash
python tools/rebuild_cache_db.py --backup
python tools/renumber_cache_ids.py --db data/database/cache.db --apply
python tools/dedupe_cache_db.py --db data/database/cache.db --apply
python tools/benchmark_resolve.py "titolo artista"
python tools/benchmark_ytdlp.py "titolo artista"
```

## 7. Dashboard e console DJ

La dashboard vive in `data/database/dashboard/app.py`.

Route principali:

- `/login`, `/logout`
- `/`
- `/api/stats`
- `/api/events`
- `/api/songs`
- `/api/aliases`
- `/api/tracks`
- `/api/sources`
- `/api/queries`
- `/api/schema`
- `/api/associate`
- `/api/delete/<id>`
- `/api/aliases/<id>`

Console DJ:

- `/dj-console`
- `/dj-console/login`
- `/dj-console/callback`
- `/dj-console/state`
- `/dj-console/action`
- `/dj-console/events`

La console DJ usa OAuth Discord per identificare l'utente, poi `core/dj_access.py` verifica ruolo e permessi. Le azioni vengono inoltrate al player del server tramite controller condiviso.

## 8. AI

`cogs/ai.py` gestisce risposte conversazionali e contesto per canale. Usa Groq tramite `core/ai_client.py` e runtime/memoria dedicati.

Caratteristiche:

- risposta a menzioni/DM secondo logica del cog;
- memoria breve per canale;
- supporto immagini;
- trigger web testuali per arricchire prompt con ricerca live;
- cooldown configurato in `Config.AI_COOLDOWN_SECONDS`.

## 9. TTS

`cogs/tts.py` usa `edge-tts` per generare audio temporaneo, poi FFmpeg/Discord voice per riprodurlo. Il volume TTS e' gestibile dai comandi dev.

## 10. Moderazione

`cogs/moderation.py` copre:

- `/purge`
- `/ruolo`
- `/kick`
- `/ban`
- `/timeout`
- museruola/sordina e liste
- gestione voice isolation/quarantine
- comandi canale/permessi definiti nel cog

I controlli condivisi sono in:

- `core/cmd_perm.py`
- `core/moderation/actions.py`
- `core/moderation/state.py`
- `core/moderation/utils.py`
- `core/moderation/isolation_registry.py`

## 11. Welcome, goodbye, autorole

`cogs/welcome.py` gestisce gruppi:

- `/welcome ...`
- `/goodbye ...`
- `/autorole ...`

Persistenza e rendering:

- `core/welcome/store.py`
- `core/welcome/render.py`
- `core/welcome/assets.py`
- `ui/welcome/embeds.py`

Supporta messaggi, embed, immagini, field dinamici, preview e reset.

## 12. Compleanni

`cogs/birthdays.py` gestisce gruppo `/bday`.

Comandi principali:

- `/bday set`
- `/bday remove`
- `/bday check`
- `/bday list`
- `/bday adminset`
- `/bday adminremove`
- `/bday channel`
- `/bday tags`
- `/bday messages_set`
- `/bday messages_add`
- `/bday messages_remove`
- `/bday messages_list`
- `/bday test`

I dati sono salvati in JSON sotto `assets/data`.

## 13. Fun, help, dev tools

Fun:

- `/8ball`
- `/citazione`
- `/roulette`

Help:

- `/help`
- `/devhelp`

Developer:

- `/restart`
- `/sync`
- `/maintenance`
- `/backupconfig`
- `/restoreconfig`
- `/disable_command`
- `/enable_command`
- `/command_list`
- `/set_log_channel`
- `/tts_volume`
- `/status add/remove/edit/list/set/interval`
- `/say`
- `/announce`
- `/cog_list`
- `/ai_reset`
- `/debug`

Dev audio:

- comandi di test MP3/voice in `cogs/dev_audio.py`.

## 14. Filtri audio

`cogs/filters.py` espone filtri preset:

- `/filteroff`
- `/nightcore`
- `/vaporwave`
- `/audio8d`
- `/bassboost`
- `/trebleboost`
- `/vocalboost`
- `/radio`
- `/nightmode`

`core/music/live_fx.py` applica trasformazioni PCM live. `MusicPlayer` conserva stato EQ, filtri e notifica dashboard/DJ console.

## 15. Test

I test sono script Python, non una suite pytest classica.

Comandi di esempio generici:

```bash
python tests/test_scoring_guardrails.py
python tests/test_resolver_spotify_canonical_fallback_cover.py
python tests/test_cache_thumbnail_stream.py
python tests/test_dashboard_api.py
```

Tutti i test in bash:

```bash
for f in tests/*.py; do python "$f"; done
```

Tutti i test in PowerShell:

```powershell
Get-ChildItem tests -Filter *.py | ForEach-Object { .\venv\Scripts\python.exe $_.FullName }
```

## 16. Setup VM e deploy

Per installazione completa segui [SETUP_UBUNTU_VM.md](SETUP_UBUNTU_VM.md).

### VM operativa attuale

La VM di produzione usa `screen`, non un servizio `pytonazz.service` systemd.

Layout:

- repo: `~/Pytonazz2026`;
- branch: `main-2`;
- venv: `~/Pytonazz2026/venv`;
- script runtime: `~/.local/bin/pytonazz-bot`;
- utility WARP manuale: `~/.local/bin/rotate-warp`;
- cookie YouTube: `/home/sessionn/cookies.txt`;
- dashboard: `127.0.0.1:5000`;
- reverse proxy: Caddy su `80/443`;
- servizi host rilevanti: `cron`, `caddy`, `docker`, `warp-svc`.

Alias shell:

```bash
gp   # cd ~/Pytonazz2026 && git pull && cd ~
sta  # start bot
sto  # stop bot
res  # restart bot
scr  # screen -r pytonazz
```

Autostart:

```bash
@reboot sleep 15 && /home/sessionn/.local/bin/pytonazz-bot start
```

La home dell'utente deve restare pulita. Sono ammessi solo repo, dotfile/cartelle utente, script operativi in `~/.local/bin` e `~/cookies.txt`. Probe, benchmark temporanei, log screen e backup manuali vanno eliminati a fine lavoro; se serve conservarli per poco, tenerli fuori dal repo e non committarli.

Deploy tipico sulla VM attuale:

```bash
cd ~/Pytonazz2026
git pull
source venv/bin/activate
pip install -r requirements.txt
python -m py_compile config.py main.py
res
```

Controlli rapidi:

```bash
screen -list
ss -ltnp | grep -E ':80|:443|:5000|:40000'
systemctl is-active cron caddy docker warp-svc
```

Deploy generico con systemd, se in futuro si passa a un servizio dedicato:

```bash
sudo systemctl restart pytonazz
sudo systemctl status pytonazz --no-pager
```

## 17. Troubleshooting

### `source tools/rebuild_cache_db.py` fallisce

E' normale: e' uno script Python. Usa:

```bash
python tools/rebuild_cache_db.py --backup
```

### `cannot pull with rebase: unstaged changes`

Hai modifiche locali. Su VM, se sono file runtime (`cache.db-wal`, `screenlog.0`, backup DB), non committarli. Se invece sono file codice copiati manualmente, riallinea con cautela:

```bash
git status --short
git stash push -m vm-local-code -- config.py core/source_resolver/__init__.py
git pull --rebase
```

### FFmpeg non riproduce e stampa `Unrecognized option`

Controlla:

```bash
ffmpeg -version
```

Ubuntu 22.04 usa spesso FFmpeg 4.4.2. Il bot evita opzioni non portabili come `-reconnect_max_retries`.

### Resolve lento su VM

Misura:

```bash
python tools/benchmark_resolve.py "titolo artista"
python tools/benchmark_ytdlp.py "titolo artista"
```

Se `ytsearch1` costa 4-6 secondi, il limite e' YouTube/yt-dlp/rete VM. Soluzioni pragmatiche:

- cache DB attiva;
- cookie YouTube aggiornati;
- non azzerare spesso il DB;
- proxy buono se la VM e' penalizzata da YouTube;
- accettare cold miss intorno a 4-6s.

### Spotify cover non applicata

Controlla benchmark:

```bash
python tools/benchmark_resolve.py "titolo artista"
```

Se `spotify_probe_ms=... cover=True` ma finale `cover='youtube'`, e' un problema di scoring/fallback resolver. I test da rilanciare:

```bash
python tests/test_resolver_spotify_canonical_fallback_cover.py
python tests/test_resolver_spotify_late_hint.py
```

## 18. Regole di sviluppo

- Non committare `.env`, cookie, DB runtime o backup con dati reali.
- Dopo modifiche al resolver, esegui test scoring, Spotify fallback e cache thumbnail.
- Dopo modifiche dashboard, esegui `tests/test_dashboard_api.py` e `tests/test_dashboard_security.py`.
- Dopo modifiche player/voice, esegui `tests/test_dj_player.py` e test manuale in voice.
- Dopo modifiche cache DB, esegui test cache e smoke rebuild:

```bash
python tools/rebuild_cache_db.py --db /tmp/cache_smoke.db --backup
```

Su Windows usa un path temporaneo compatibile, ad esempio `C:\tmp\cache_smoke.db`.
