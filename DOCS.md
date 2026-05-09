# 📖 PYTONAZZ 2026 — DOCUMENTAZIONE TECNICA COMPLETA

> **Documento:** Manuale tecnico, guida operativa e indice funzionale  
> **Repository:** `Sessionn/Pytonazz2026`  
> **Versione:** commit `7c880a2`  
> **Data:** 11/04/2026  

---

## Indice

- [1. Panoramica del Progetto](#1-panoramica-del-progetto)
- [2. Architettura e Gerarchia dei File](#2-architettura-e-gerarchia-dei-file)
- [3. Dipendenze e Requisiti](#3-dipendenze-e-requisiti)
- [4. Configurazione e Variabili d'Ambiente](#4-configurazione-e-variabili-dambiente)
- [5. Entrypoint — main.py](#5-entrypoint--mainpy)
- [6. Modulo Core](#6-modulo-core)
- [7. Cogs — Funzionalità Pubbliche](#7-cogs--funzionalità-pubbliche)
- [8. Cogs — Funzionalità Admin/Dev](#8-cogs--funzionalità-admindev)
- [9. Assets, Embeds, Views](#9-assets-embeds-views)
- [10. Meccanismi Trasversali](#10-meccanismi-trasversali)
- [11. Guida agli Aggiornamenti](#11-guida-agli-aggiornamenti)

---

## 1. Panoramica del Progetto

### 1.1 Cos'è Pytonazz

Pytonazz è un **Discord bot multiuso scritto in Python** basato su `discord.py 2.x`, con architettura a **cog** (moduli estensibili e hot-reloadabili). Funzionalità principali: musica avanzata, AI integrata, moderazione, benvenuto, compleanni, TTS e divertimento.

Progettato per deployment su **VM Linux** con supporto proxy WARP/Squid per aggirare restrizioni YouTube sulle VPS.

### 1.2 Filosofia di Design

- **Cog-first:** ogni feature è incapsulata in un cog separato, hot-reloadabile senza restart
- **Configurazione runtime:** i settings operativi sopravvivono ai restart tramite `bot_config.json`
- **Separazione netta:**
  - `config.py` → segreti e costanti da `.env` + costanti audio/timing hardcoded
  - `core/bot_config.py` → runtime config persistente
  - `core/constants.py` → costanti condivise tra moduli
- **Slash commands only:** nessun prefisso testuale usabile dagli utenti (il bot risponde solo alle mention e agli slash command)
  - Nota Discord UI: quando un utente scrive `@bot`, il menu a tendina con suggerimenti dei comandi dell'applicazione è comportamento nativo del client Discord e non è disattivabile via codice del bot.
  - Nota operativa server: nelle aree dove si usa solo l'AI a mention, valutare permessi Discord più restrittivi su **Use Application Commands** per ridurre rumore e suggerimenti non desiderati.
- **Owner-protected:** comandi dev usano `owner_check`, non semplici permission check Discord

### 1.3 Target d'Uso

Bot privato/semi-pubblico per server Discord. Il modulo dev è riservato a owner/dev configurati in `.env` (`OWNER_ID`, `DEV_IDS`, con `DEV_ID` come alias legacy).

---

## 2. Architettura e Gerarchia dei File

```
Pytonazz2026/
│
├── main.py                      ← Entrypoint: avvio bot, watchdog, setup_hook
├── config.py                    ← Classe Config: legge .env, costanti audio/timing
├── requirements.txt             ← Dipendenze pip
├── .gitignore
├── README.md                    ← Copertina repository
├── DOCS.md                      ← Questo documento
│
├── core/                        ← Moduli di supporto condivisi (non cog)
│   ├── ai_client.py             ← Client AI multi-provider (Gemini + fallback Groq)
│   ├── banner.py                ← Stampa ASCII banner all'avvio
│   ├── birthday_store.py        ← Persistenza compleanni (JSON per guild)
│   ├── bot_config.py            ← Runtime config persistente (JSON)
│   ├── ai_runtime.py            ← Stato runtime condiviso del cog AI (memoria/rate-limit/cache)
│   ├── cmd_perm.py              ← Source of truth per decorator `perm(...)` usato da help
│   ├── constants.py             ← TYPE_MAP, STAT_MAP, UNDISABLEABLE
│   ├── crossfade.py             ← Helper crossfade (clamp + filter graph FFmpeg)
│   ├── log_colors.py            ← Formattatori log ANSI colorati
│   ├── permissions.py           ← Check owner/dev/admin (+ re-export `perm`)
│   ├── player.py                ← MusicPlayer: logica riproduzione per guild
│   ├── queue.py                 ← MusicQueue: deque-based con loop/shuffle/history
│   ├── quote_card.py            ← Generatore immagine citazione (Pillow + httpx)
│   ├── source_resolver/           ← Resolver multi-fonte (orchestratore + sotto-moduli)
│   │   ├── __init__.py            ← Orchestratore resolver: import + flusso principale
│   │   ├── scoring.py             ← Scoring puro: Jaccard, penalità varianti, confidence
│   │   ├── spotify.py             ← Helper Spotify: client factory, selezione item
│   │   └── ytdlp.py               ← yt-dlp: logger, _make_opts(), _strip_yt_radio()
│   └── welcome_store.py           ← Persistenza config welcome/goodbye/autorole
│
├── cogs/                        ← Cog Discord (auto-caricati all'avvio)
│   ├── ai.py                    ← AI: risponde a @mention e DM (Gemini + fallback Groq)
│   ├── birthdays.py             ← Sistema compleanni con notifiche auto
│   ├── dev.py                   ← Pannello sviluppatore (solo owner)
│   ├── dev_audio.py             ← Comandi audio dev (solo owner)
│   ├── filters.py               ← Filtri audio FFmpeg
│   ├── fun.py                   ← Roulette, poll, 8ball, citazione
│   ├── help.py                  ← Sistema /help interattivo paginato
│   ├── moderation.py            ← /purge, /ruolo
│   ├── music.py                 ← Cog principale musica (25+ comandi)
│   ├── tts.py                   ← Text-to-Speech via edge-tts
│   ├── welcome.py               ← Welcome/Goodbye/AutoRole
│   └── custom/                  ← (opzionale) cog personalizzati extra
│
├── embeds/
│   └── music_embeds.py          ← Factory embed Discord
│
├── views/
│   ├── player_view.py           ← Bottoni controllo player
│   └── queue_view.py            ← Paginazione coda
│
├── assets/
│   ├── status_messages.py       ← STATUS_CYCLE: attività base in rotazione
│   ├── prompts/
│   │   ├── ai_prompt.txt        ← System prompt AI (cache invalidabile con /ai_reset)
│   ├── config/                  ← JSON generati a runtime (non committare)
│       ├── bot_config.json
│       ├── custom_statuses.json
│   └── data/                    ← JSON runtime compleanni
│       └── birthdays.json
│
├── data/
│   ├── welcome_config.json      ← Config welcome/goodbye/autorole runtime
│   ├── welcome_images/          ← Immagini locali uploadate via /welcome set e /goodbye set
│   └── tmp/                     ← File temporanei runtime
│
├── tools/
└── scripts/
```

---

## 3. Dipendenze e Requisiti

### 3.1 Dipendenze Python

| Pacchetto | Versione min | Scopo |
|---|---|---|
| `discord.py` | ≥ 2.3.2 | Framework principale Discord |
| `yt-dlp` | ≥ 2024.12.1 | Estrazione stream audio YouTube/SoundCloud |
| `spotipy` | ≥ 2.24.0 | API Spotify (metadati, playlist, album, artista) |
| `python-dotenv` | ≥ 1.0.1 | Lettura file `.env` |
| `watchdog` | ≥ 4.0.0 | Hot-reload cog a runtime |
| `PyNaCl` | any | Crittografia voice Discord (obbligatorio) |
| `davey` | any | Implementazione protocollo Discord DAVE (E2EE audio/video) richiesta in alcuni server/deploy |
| `groq` | ≥ 0.13.0 | Fallback/emergency AI provider |
| `google-genai` | ≥ 1.0.0 | Provider AI principale (Gemini) |
| `httpx` | ≥ 0.27.0 | Fetch asincrono avatar (quote card) + check yt-dlp |
| `Pillow` | ≥ 10.0.0 | Generazione immagine citazione |
| `edge-tts` | ≥ 6.1.9 | TTS Microsoft Edge Neural Voices (gratuito) |
| `ffmpeg` | sistema | **Non pip** — binario di sistema |

### 3.2 Dipendenze di Sistema

- **FFmpeg** nel PATH: `sudo apt install ffmpeg` (Linux) / [ffmpeg.org](https://ffmpeg.org/download.html) (Windows)
- **Python 3.10+**

### 3.3 Installazione Rapida

```bash
git clone https://github.com/Sessionn/Pytonazz2026
cd Pytonazz2026
pip install -r requirements.txt
# Creare .env (vedi sezione 4.1)
python main.py
```

---

## 4. Configurazione e Variabili d'Ambiente

### 4.1 File `.env`

Non incluso nel repository. Va creato manualmente nella root.

```env
# OBBLIGATORIO
DISCORD_TOKEN=il_tuo_token_discord

# OPZIONALE: Spotify
SPOTIFY_CLIENT_ID=...
SPOTIFY_CLIENT_SECRET=...

# OPZIONALE: AI providers
GEMINI_API_KEY=...
GROQ_API_KEY=...

# OPZIONALE: Owner/Dev
OWNER_ID=123456789
DEV_IDS=123456789,987654321
DEV_ID=123456789  # alias legacy/fallback

# OPZIONALE: Guild-lock comandi slash (sync più veloce)
GUILD_IDS=123456,789012

# OPZIONALE: Proxy SOCKS5 per VM/VPS (es. WARP)
YTDLP_PROXY=socks5://127.0.0.1:40000
FFMPEG_PROXY=http://127.0.0.1:3128  # opzionale, fallback su YTDLP_PROXY solo se HTTP/HTTPS
```

> ⚠️ Per i comandi `/dev` configura almeno `OWNER_ID` (consigliato) oppure `DEV_IDS`/`DEV_ID` legacy.

### 4.2 Classe `Config` (`config.py`)

La classe `Config` è divisa in due categorie: variabili lette dal `.env` tramite `os.getenv()` e costanti hardcoded modificabili solo nel file `config.py`.

#### Variabili da `.env`

| Attributo | Default | Descrizione |
|---|---|---|
| `DISCORD_TOKEN` | — | Token bot Discord |
| `SPOTIFY_CLIENT_ID/SECRET` | `""` | Credenziali Spotify |
| `GEMINI_API_KEY` | `""` | Chiave Google Gemini API |
| `GROQ_API_KEY` | `""` | Chiave Groq API |
| `OWNER_ID` | `None` | ID proprietario (int) |
| `DEV_IDS` | `[]` | Lista ID dev separati da virgola (include owner) |
| `DEV_ID` | `None` | Alias legacy/fallback |
| `GUILD_IDS` | `[]` | Guild per sync comandi |
| `YTDLP_PROXY` | `""` | Proxy SOCKS5 per yt-dlp |
| `FFMPEG_PROXY` | `""` | Proxy HTTP per FFmpeg (fallback su `YTDLP_PROXY` solo se HTTP/HTTPS) |
| `LOG_LEVEL` | `"INFO"` | Livello log: `INFO` (default, console pulita) o `DEBUG` (griglia enrichment Spotify e dettagli yt-dlp) |

#### Costanti hardcoded in `config.py`

> Queste **non si configurano dal `.env`** — per modificarle bisogna editare direttamente `config.py`.

| Attributo | Valore | Descrizione |
|---|---|---|
| `IDLE_TIMEOUT` | `600` s | Disconnect per inattività musica |
| `EMPTY_CH_TIMEOUT` | `600` s | Disconnect canale vocale vuoto |
| `MAX_QUEUE` | `200` | Tracce massime in coda |
| `DEFAULT_VOLUME` | `0.5` | Volume musica (0.0–1.0) |
| `AI_COOLDOWN_SECONDS` | `5` | Cooldown AI per utente |

#### Logica Proxy WARP + Squid

Se `YTDLP_PROXY` è impostato:
- `yt-dlp` usa `proxy=socks5://127.0.0.1:40000`
- `FFmpeg` usa `FFMPEG_PROXY` se presente; se assente fa fallback su `YTDLP_PROXY` solo se è un proxy `http://` o `https://`

Stesso IP per risoluzione e streaming → evita blocchi YouTube su VPS.

### 4.3 Runtime Config — `bot_config.json`

File in `assets/config/bot_config.json`, generato automaticamente. Persiste tra restart.

```json
{
  "status_interval": 300,
  "log_channel_id": null,
  "maintenance": false,
  "tts_volume": 1.5,
  "disabled_commands": []
}
```

Gestito dalla singleton `cfg = BotConfig()` in `core/bot_config.py`, importata nei cog che ne hanno bisogno.

| Campo | Setter | Descrizione |
|---|---|---|
| `status_interval` | `cfg.set_status_interval(s)` | Intervallo rotazione status |
| `log_channel_id` | `cfg.set_log_channel(id)` | Canale Discord per errori |
| `maintenance` | `cfg.set_maintenance(bool)` | Modalità manutenzione |
| `tts_volume` | `cfg.set_tts_volume(float)` | Volume TTS (0.1–3.0) |
| `disabled_commands` | `cfg.disable/enable_command(name)` | Lista comandi disabilitati |

---

## 5. Entrypoint — `main.py`

### 5.1 Flusso di Avvio

```
python main.py
    │
    ├── print_banner()              → banner ASCII colorato
    ├── setup_logging(INFO)         → logger "pitonazz" con ANSI
    ├── ensure_runtime_dirs()       → bootstrap centralizzato cartelle runtime
    ├── COGS = auto-discovery       → glob cogs/*.py + cogs/custom/*.py
    │
    └── asyncio.run(main())
           │
           ├── Pitonazz() init      → intents, status list
           ├── Observer (watchdog)  → sorveglia cogs/ per hot-reload
           └── bot.start(token)
                  └── setup_hook()
                         ├── check_ytdlp_update()
                         ├── _global_check registrato
                         ├── load_extension(ogni cog)
                         ├── _sync_commands()
                         ├── cycle_status.start()
                         └── on_ready()
```

### 5.2 Intents Attivi

Il bootstrap delle directory runtime è centralizzato in `main.py`; alcuni moduli di persistenza mantengono un fallback locale per uso standalone/script.

| Intent | Motivo |
|---|---|
| `voice_states` | Musica e TTS |
| `message_content` | AI (lettura contenuto messaggi) |
| `members` | Welcome, autorole, compleanni |

### 5.3 Global Interaction Check

Ogni comando slash passa per `_global_check` prima di eseguire. Se il comando è in `disabled_commands`, viene bloccato — **tranne** se chi esegue è owner/dev (`DEV_IDS` + owner app). Garantisce accesso privilegiato anche in manutenzione.

### 5.4 Hot-Reload (watchdog)

`CogReloader` — `FileSystemEventHandler` che:
- Ascolta modifiche `.py` in `cogs/`
- Cooldown 1.5s (evita reload multipli su salvataggio IDE)
- **NON ricarica** `cogs.music` / `cogs.filters` se c'è musica in riproduzione
- Ricarica via `bot.reload_extension(ext)` nel loop asyncio

### 5.5 Auto-discovery Cog

```python
_base_cogs   = [f"cogs.{f.stem}" for f in COGS_DIR.glob("*.py") if f.stem != "__init__"]
_custom_cogs = [f"cogs.custom.{f.stem}" for f in Path("cogs/custom").glob("*.py")]
```

Qualsiasi `.py` in `cogs/` o `cogs/custom/` viene caricato automaticamente.

---

## 6. Modulo Core

### 6.1 `source_resolver/` — Resolver Multi-fonte (orchestratore)

Modulo principale (~350 righe). Importa le funzioni specializzate dai tre sotto-moduli e implementa il flusso di risoluzione completo.

> **Architettura a sotto-moduli (Phase 2):**
> - `source_resolver/scoring.py` — scoring puro: Jaccard, `_dynamic_variant_penalty`, confidence
> - `source_resolver/spotify.py` — factory del client Spotify, helper selezione item
> - `source_resolver/ytdlp.py` — logger yt-dlp personalizzato, `_make_opts()`, `_strip_yt_radio()`

Tutti e tre sono moduli senza I/O propri: `source_resolver/__init__.py` li importa e li orchestra.

#### Dataclass `TrackInfo`

```python
@dataclass
class TrackInfo:
    title:        str    # Titolo traccia
    webpage_url:  str    # URL pagina YouTube
    duration:     int    # Durata in secondi
    thumbnail:    str    # URL copertina
    requester:    str    # display_name utente
    requester_id: int    # ID Discord utente
    source:       str    # "youtube" | "spotify" | "soundcloud"
    stream_url:   str    # URL stream diretto (scade)
    artist:       str    # Artista
    spotify_url:  str    # URL Spotify originale
```

#### Flusso `resolve(query)`

```
query
  ├── spotify.com/track    → _sp_track()     → Spotify API → ytsearch3
  ├── spotify.com/playlist → _sp_playlist()  → batch _sp_track()
  ├── spotify.com/album    → _sp_album()     → batch _sp_track()
  ├── spotify.com/artist   → resolve_artist_stream_by_id()
  └── altro                → _search_or_url() → yt-dlp
```

#### Flusso `resolve_choices(query, n=1)` — Spotify-first per query testuali

Per `/play <testo>` (n=1, nessun URL) il resolver usa **Spotify come primo passo**:

```
query testuale
  1. Spotify search → titolo + artista canonico (es. "Fever" → "Fever Elvis Presley")
  2. YouTube search con il titolo canonico → 3 candidati
  3. _prefer_studio(): scarta MV, preferisce versione studio se l'utente non ha chiesto live/remix
  4. _enrich_with_spotify(): arricchisce metadati con confidence scoring
```

Questo corregge typo (il motore Spotify è tollerante agli errori) e previene che YouTube restituisca versioni live o video non musicali per query generiche.

#### Scoring Dinamico — `_dynamic_variant_penalty`

Invece di una blocklist di parole chiave fissa, la penalità per varianti indesiderate usa la triangolazione per insiemi:

```
intent_words   = words(query) − words(sp_title + sp_artist)  ← cosa vuole l'utente
extra_yt_words = words(yt_title) − words(sp_title + sp_artist)  ← cosa aggiunge YT
junk_words     = extra_yt_words − words(query)  ← aggiunte non richieste
penalty        = min(len(junk_words) × 0.07, 0.30)
```

Esempi:

| Query | Titolo YT | Penalità |
|---|---|---|
| `"Shape Of You"` | `"Shape Of You Karaoke Version"` | 0.14 (karaoke non richiesto) |
| `"Shape Of You slowed"` | `"Shape Of You Slowed"` | 0.00 (slowed è nell'intent) |
| `"Fever"` | `"Fever (Live in Honolulu)"` | 0.21 (live non richiesto) |
| `"Fever live"` | `"Fever (Live in Honolulu)"` | 0.00 (live nell'intent) |

#### Logica Anti-Music-Video

Per tracce Spotify: scarica 3 candidati YouTube (`_YT_CANDIDATES = 3`), filtra quelli con parole tipo `official video`, `music video`, `vevo` (`_MV_KEYWORDS`), sceglie quello con durata più vicina a quella Spotify.

#### URL Stream e Scadenza

Gli URL stream YouTube scadono. Gestione:
- Prima riproduzione → usa `stream_url` pre-fetchato
- Se scaduto/vuoto → `resolve_fresh_url()` esegue nuovo fetch
- `_depth` counter → max 5 retry consecutivi prima di saltare traccia

#### Spotify Shuffle Intelligente

`spotify_style_shuffle(tracks)`: raggruppa per artista e distribuisce uniformemente → nessun artista consecutivo.

---

### 6.2 `player.py` — `MusicPlayer`

Una istanza per guild. Gestisce riproduzione, pausa, skip, loop, filtri, idle disconnect.

#### Attributi Chiave

| Attributo | Tipo | Descrizione |
|---|---|---|
| `queue` | `MusicQueue` | Coda tracce |
| `current` | `TrackInfo\|None` | Traccia in riproduzione |
| `filter` | `str\|None` | Stringa FFmpeg filtro attivo |
| `_loading_count` | `int` | Counter playlist in caricamento (race condition fix) |
| `_play_start` | `float` | `time.monotonic()` inizio riproduzione |
| `_seek_offset` | `float` | Offset seek accumulato |
| `_paused_total` | `float` | Tempo totale in pausa |
| `autoplay_enabled` | `bool` | Riempimento automatico coda a fine riproduzione |
| `_player_msg` | `Message\|None` | Messaggio player Discord attivo |

#### Property `position`

```
position = seek_offset + (now - play_start) - paused_total
```

#### Ciclo `play_next()`

```
play_next()
  ├── _filter_replay?  → riprende da seek_position (dopo cambio filtro)
  ├── loop=track?      → riprende dall'inizio
  ├── loop=queue?      → rimette in coda, prende prossima
  └── normale          → sposta in history, prende prossima
  │
  ├── Coda vuota?  → _arm_idle()
  ├── stream_url disponibile → usa direttamente
  ├── stream_url scaduto → resolve_fresh_url()
  └── vc.play(source, after=_after) → _after → play_next() (ricorsivo)
```

#### Idle Disconnect

`_arm_idle()` → task che aspetta `IDLE_TIMEOUT` secondi poi disconnette.  
**Non si arma** se `_loading_count > 0` (playlist ancora in caricamento).

#### Applicazione Filtri

`apply_filter(name, filter_str)`:
1. Calcola `seek_position = position - 0.5`
2. Pre-fetcha URL stream
3. `_filter_replay = True` → `vc.stop()` → `play_next()` → riprende da seek

---

### 6.3 `queue.py` — `MusicQueue`

Basata su `collections.deque` — O(1) su pop/append.

| Metodo | Descrizione |
|---|---|
| `put(track)` | Aggiunge se `len < MAX_QUEUE` |
| `put_many(tracks)` | Aggiunge lista rispettando limite |
| `get()` | Popleft — rimuove e ritorna prima traccia |
| `peek()` | Prima traccia senza rimuoverla |
| `remove(index)` | Rimuove per indice (1-based) |
| `move(from, to)` | Sposta traccia |
| `skipto(index)` | Rimuove le prime N tracce |
| `shuffle()` | Shuffle casuale |
| `spotify_shuffle()` | Shuffle intelligente per artisti |
| `add_history(track)` | Aggiunge a `deque(maxlen=50)` |
| `loop_mode` | `"off"` \| `"track"` \| `"queue"` |

---

### 6.4 `bot_config.py` — Runtime Config

Singleton `cfg = BotConfig()`. Vedi tabella completa in [sezione 4.3](#43-runtime-config--bot_configjson).

---

### 6.5 `constants.py`

- `TYPE_MAP` → stringa → `discord.ActivityType`
- `STAT_MAP` → stringa → `discord.Status`
- `TYPE_LABEL`, `STATUS_LABEL` → label UI in italiano
- `UNDISABLEABLE` → comandi protetti dal disable:

```python
UNDISABLEABLE = frozenset({
    "disablecommand", "enablecommand", "commandlist", "sync", "restart",
    "maintenance", "coglist", "help", "help-dev",
})
```

---

### 6.6 `log_colors.py`

| Funzione | Output |
|---|---|
| `tag(categoria, msg)` | `[CATEGORIA] msg` colorato ANSI |
| `b(text)` | Testo bold |
| `ms(millis)` | Latenza colorata (verde/giallo/rosso) |
| `user(text)`, `guild(text)`, `ch(text)` | Testo colorato per contesto |

---

### 6.7 `permissions.py`

`owner_check`, `dev_check`, `admin_check` sono centralizzati in `core/permissions.py`.

- `owner_check`: `OWNER_ID` (se presente) oppure owner applicazione Discord
- `dev_check`: utenti in `DEV_IDS` + owner applicazione
- `admin_check`: dev/owner oppure permesso Discord `administrator`

---

### 6.8 `ai_client.py`

Client AI centralizzato multi-provider:
- primary: Gemini (`gemini-2.5-flash`)
- fallback: Gemini (`gemini-2.0-flash`)
- emergency: Groq (`llama-3.1-8b-instant`)

Espone: `chat(messages) → (reply: str, model_used: str)` e `generate(prompt)`.

---

### 6.9 `quote_card.py`

Genera immagine PNG con citazione, avatar utente e nome server.  
Stack: `Pillow` (rendering) + `httpx` (fetch asincrono avatar).

---

### 6.10 `birthday_store.py` / `welcome_store.py`

| Store | Struttura JSON | Contenuto |
|---|---|---|
| `birthday_store` | `{guild_id: {channel_id, list_message_id, wish_messages, users}}` | Compleanni + configurazione canale/lista/messaggi auguri |
| `welcome_store` | `{guild_id: {welcome: {...}, goodbye: {...}, auto_role_id: id}}` | Config welcome per server |

---

## 7. Cogs — Funzionalità Pubbliche

### 7.1 `cogs/music.py` — Musica 🎵

Cog principale (~700 righe). Dizionario `_players: dict[int, MusicPlayer]` — una istanza per guild.

#### Comandi

| Comando | Descrizione |
|---|---|
| `/join [utente]` | Entra nel canale vocale (anche nel canale di un altro utente) |
| `/play <query>` | Riproduce musica (testo, URL YouTube, URL Spotify track/playlist/album; i link artista usano `/artistshuffle`) |
| `/search <query>` | Cerca e mostra 7 risultati con menu select |
| `/versions` | 5 versioni alternative della traccia corrente |
| `/skip` | Salta traccia corrente |
| `/seek <±sec>` | Seek relativo nella traccia corrente (es. `+10`, `-15`) |
| `/skipto <pos>` | Salta a posizione N (rimuove tracce intermedie) |
| `/pause` | Pausa |
| `/resume` | Riprendi |
| `/stop` | Ferma + svuota coda + disconnette |
| `/clearqueue` | Svuota coda (traccia corrente continua) |
| `/queue` | Coda paginata con bottoni |
| `/nowplaying` | Player con controlli (reinvia messaggio) |
| `/loop <mode>` | Loop: `off` / `track` / `queue` |
| `/autoplay` | Auto-riempie la coda quando termina (selezione ON/OFF via dropdown) |
| `/shuffle` | Toggle shuffle casuale |
| `/smartshuffle` | Shuffle stile Spotify: raggruppa per artista, nessun artista consecutivo |
| `/remove <pos>` | Rimuove traccia dalla coda |
| `/move <da> <a>` | Sposta traccia in coda |
| `/history` | Ultime 10 tracce riprodotte |
| `/disconnect` | Disconnette il bot |
| `/artistshuffle <nome> [n]` | Radio artista Spotify (top tracks + artisti simili) |

#### Race Condition Fix — `_fill_queue`

`_fill_queue` è asincrono per playlist lunghe. `player._loading_count` viene incrementato all'inizio e decrementato al termine — `_arm_idle()` non si attiva se `> 0`, evitando disconnessioni durante il caricamento.

#### Listener `on_voice_state_update`

- Bot disconnesso → ferma player, rimuove da `_players`
- Bot spostato → controlla canale vuoto
- Utente lascia → se canale vuoto, schedula `_empty_channel_disconnect`
- **NON disconnette se in pausa** (stato intenzionale)

---

### 7.2 `cogs/filters.py` — Filtri Audio 🎚️

| Filtro | Stringa FFmpeg | Effetto |
|---|---|---|
| `off` | `None` | Nessun filtro |
| `nightcore` | `aresample=48000,asetrate=48000*1.25` | +25% velocità e pitch |
| `vaporwave` | `aresample=48000,asetrate=48000*0.8` | -20% velocità e pitch |
| `8d` | `apulsator=hz=0.08` | Audio 3D rotante |
| `bassboost` | `bass=g=8:f=110:w=0.8` | Enfatizza basse frequenze |
| `trebleboost` | `treble=g=6:f=4500:w=0.8` | Enfatizza alte frequenze |
| `vocalboost` | `equalizer=f=2500:t=q:w=1.2:g=5` | Evidenzia gamma voce/presenza |
| `radio` | `highpass=f=300,lowpass=f=3200` | Effetto radio/telefono lo-fi |
| `night` | `acompressor... ,alimiter...` | Compressione+limiter leggeri (notturno) |

Accede al player tramite lookup su `bot.cogs`. Applica il filtro tramite `player.apply_filter()` (seek + re-encode FFmpeg).
Ogni filtro è esposto come slash command dedicato (`/nightcore`, `/bassboost`, ecc.) più `/filteroff` per disattivare.

---

### 7.3 `cogs/ai.py` — AI 🤖

Risponde automaticamente (no slash command) quando:
- Il bot viene menzionato (`@Pitonazz`)
- Qualcuno scrive in DM
- Qualcuno risponde direttamente a un messaggio del bot (reply)

**Rate limit:** cooldown `AI_COOLDOWN_SECONDS` (5s default, hardcoded in `config.py`) per utente.  
**Memoria:** `deque(maxlen=20)` per canale/DM. Resettabile con `/ai_reset` (owner).  
**Prompt:** `assets/prompts/ai_prompt.txt` con cache in memoria invalidabile (`/ai_reset` / reload cog).
**Contesto runtime:** prima del testo utente, il bot aggiunge al modello metadati sintetici (trigger, utente, scope DM/guild, canale e contesto reply al bot se presente) per risposte più realistiche e contestualizzate.
**Background menzioni utenti:** nei canali guild il bot conserva una finestra locale di messaggi recenti (no DM), e quando nel messaggio sono presenti menzioni (`@utente`) allega un mini-background neutro per i primi N utenti menzionati (tone/temi recenti/relazione col richiedente), con cache TTL breve e fallback “nessun background disponibile”.
**Allegati immagine:** oltre ai nomi file, il contesto esteso include metadati sintetici per immagini (nome, dimensione, risoluzione, hint da filename), con limiti di numero/peso e senza invio payload binario.
**Ricerca web ibrida (logica + override):** l’AI prova prima a rispondere col solo contesto locale; se la richiesta sembra una domanda informativa e la risposta contiene incertezza, esegue una ricerca web sintetica e ritenta automaticamente. Restano disponibili i trigger espliciti (`#web`, `search:`, `cerca web:`) come override manuale.
**Governance contesto:** il prompt runtime istruisce l’AI a usare il contesto esteso solo se rilevante, evitare inferenze sensibili e citare in modo sintetico eventuali fonti web usate.
**Ottimizzazione token (non restrittiva):** il contesto inviato al modello usa budget caratteri dinamico sulla history recente (più ampio con input utente lunghi), clipping morbido dei singoli item in memoria e `max_tokens` dinamico (più alto su DM e con input lunghi) per ridurre sprechi senza penalizzare l’utente.

---

### 7.4 `cogs/tts.py` — TTS 🔊

Usa `edge-tts` — Microsoft Edge Neural Voices, gratuito, nessuna API key.

| Voice ID | Label | Default |
|---|---|---|
| `it-IT-DiegoNeural` | Diego (ita, M) | ✅ |
| `it-IT-ElsaNeural` | Elsa (ita, F) | |
| `it-IT-IsabellaNeural` | Isabella (ita, F) | |
| `en-GB-RyanNeural` | Ryan (eng UK, M) | |
| `en-US-AriaNeural` | Aria (eng US, F) | |

Limite: 500 caratteri. Volume persistente via `/ttsvolume` (owner). Audio in memoria (`io.BytesIO`) → `FFmpegPCMAudio(buf, pipe=True)`.

---

### 7.5 `cogs/fun.py` — Divertimento 🎲

| Comando | Descrizione |
|---|---|
| `/roulette` | 1/6 di probabilità di essere mutato 5 minuti |
| `/poll <domanda> <op1> <op2> [op3] [op4]` | Sondaggio con 2–4 opzioni, aggiunge emoji reaction automaticamente |
| `/8ball <domanda>` | Oracolo: 33% sì, 33% no, 33% vago — toni cinici |
| `/citazione <testo> [utente] [autore]` | Genera card immagine PNG (max 280 caratteri) |
| Context menu **"Cita messaggio"** | Click destro su messaggio → card PNG (testo troncato a 280 car. se necessario) |

**Dettaglio roulette:** due `randint(1,6)` indipendenti (proiettile e camera) — probabilità di morte esatta 1/6. Se il bot non ha il permesso `timeout`, mostra comunque l'animazione ma non muta l'utente.  
**Dettaglio 8ball:** pool di 21 risposte (7 sì + 7 no + 7 vagi), scelta uniforme — ogni categoria ha identica probabilità.

---

### 7.6 `cogs/birthdays.py` — Compleanni 🎂

Traccia e notifica compleanni per server. Persistenza in `core/birthday_store.py`. Task schedulato per notifiche automatiche giornaliere.

---

### 7.7 `cogs/moderation.py` — Moderazione 🛡️

| Comando | Permesso | Descrizione |
|---|---|---|
| `/purge <n>` | `manage_messages` | Elimina 1-100 messaggi (bulk, salta >14 giorni) |
| `/ruolo <utente> <ruolo>` | `manage_roles` | Toggle ruolo (assegna/rimuove) con check gerarchia |

---

### 7.8 `cogs/welcome.py` — Welcome/Goodbye/AutoRole 👋

Sostitutivo di MEE6. Config indipendente per server in `core/welcome_store.py`.

#### Placeholder (`/tags`)

| Placeholder | Risultato |
|---|---|
| `{mention}` | @menzione cliccabile |
| `{name}` | Username puro |
| `{display_name}` | Nickname server |
| `{guild}` | Nome server |
| `{count}` | Numero membri |

#### Anatomia di un Embed

Schema visivo di tutte le parti configurabili tramite `/welcome set` e `/goodbye set`.

```
┌─────────────────────────────────────────────────────────┐
│▌  ← color (#RRGGBB)                                     │
│▌                                                        │
│▌  🖼️ author_name          ← + author_icon_url/upload    │  ┌──────────┐
│▌  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  │  │          │
│▌                                                        │  │ thumbnail│
│▌  title                   ← testo in grassetto          │  │  _url /   │
│▌                                                        │  │  upload   │
│▌  description             ← supporta {mention}         │  │          │
│▌  {name} {display_name}      {guild} {count}            │  └──────────┘
│▌  e markdown Discord                                    │
│▌                                                        │
│▌  ┌─────────────┐  ┌─────────────┐                     │
│▌  │ field1_name │  │ field2_name │  ← fino a 25 field   │
│▌  │ field1_value│  │ field2_value│    (4 per comando)   │
│▌  └─────────────┘  └─────────────┘                     │
│▌                                                        │
│▌  ┌──────────────────────────────────────────────────┐  │
│▌  │                                                  │  │
│▌  │           image_url / image_upload               │  │
│▌  │          (immagine grande, fondo embed)          │  │
│▌  │                                                  │  │
│▌  └──────────────────────────────────────────────────┘  │
│▌                                                        │
│▌  🖼️ footer_icon  footer text  •  timestamp            │
│▌     └─ footer_icon_url/upload   └─ footer             │
└─────────────────────────────────────────────────────────┘
```

> **Nota:** la barra colorata `▌` sul lato sinistro è controllata dal parametro `color`.  
> Per **rimuovere** un campo già impostato, passa `none` come valore (es. `footer:none`).  
> Se passi sia `*_url` che `*_upload` per la stessa immagine, l'**upload ha la precedenza**.

#### Gruppo `/welcome` (richiede `manage_guild`)

| Sotto-comando | Descrizione |
|---|---|
| `channel <#canale>` | Imposta canale |
| `toggle` | Abilita/disabilita |
| `set [plain_text] [...]` | Configura messaggio: `plain_text=True` per testo semplice, `False` per embed (default). Parametri embed: titolo, descrizione, footer, footer_icon, colore HEX, thumbnail, immagine, author, author_icon, field 1–4. |
| `field remove <n>` | Rimuove field |
| `field list` | Lista field |
| `reset` | Ripristina default |
| `preview` | Anteprima ephemeral (rispetta la modalità plain text/embed) |
| `status` | Stato configurazione (mostra la modalità attiva) |

**Gruppo `/goodbye`:** firma identica a `/welcome set`, config separata.

> ℹ️ In modalità plain text entrambi i gruppi inviano il contenuto del campo `description` come messaggio semplice (senza embed). I parametri `title`, `footer`, `color`, `thumbnail`, `image`, `author` e i field vengono ignorati finché `plain_text=True`.

#### Gruppo `/autorole` (richiede `manage_guild`)

| Sotto-comando | Descrizione |
|---|---|
| `set <ruolo>` | Ruolo automatico al join |
| `remove` | Rimuove autorole |
| `status` | Mostra autorole attivo |

---

## 8. Cogs — Funzionalità Admin/Dev

### 8.1 `cogs/dev.py` — Pannello Dev 🔧

> ⚠️ I comandi owner richiedono `owner_check`; i comandi di gestione quotidiana usano `dev_check` (owner/dev).

#### Gestione Comandi

| Comando | Descrizione |
|---|---|
| `/disablecommand <cmd>` | Disabilita comando a runtime (persiste) |
| `/enablecommand <cmd>` | Riabilita comando (con autocomplete) |
| `/commandlist` | Lista: ✅ abilitati / 🚫 disabilitati / 🔒 protetti |

#### Gestione Bot

| Comando | Descrizione |
|---|---|
| `/sync [clear_global]` | Risincronizza slash commands |
| `/restart` | Riavvia processo (`os.execv`) |
| `/maintenance <bool>` | Manutenzione on/off |
| `/setlogchannel [canale]` | Canale errori bot |

#### Gestione Status

| Comando | Descrizione |
|---|---|
| `/addstatus <tipo> <nome> [stato]` | Aggiunge a rotazione custom |
| `/removestatus <indice>` | Rimuove per indice |
| `/editstatus <indice> [...]` | Modifica esistente |
| `/liststatus` | Lista completa (base + custom) |
| `/setstatus <tipo> <nome> [stato]` | Status immediato (non persistente) |
| `/statusinterval <secondi>` | Cambia intervallo (min 10s, persiste in `bot_config.json`) |

**Tipi:** `playing` / `watching` / `listening` / `competing` / `custom`  
**Stati:** `online` / `idle` / `dnd` / `invisible`

#### Comunicazione

| Comando | Descrizione |
|---|---|
| `/say <testo> [canale]` | Bot invia messaggio |
| `/announce <titolo> <testo> [canale]` | Embed annuncio |
| `/ttsvolume <0.1–3.0>` | Volume TTS (persiste in `bot_config.json`) |

#### Backup / Restore

| Comando | Descrizione |
|---|---|
| `/backupconfig` | Esporta in ZIP: `bot_config.json`, `custom_statuses.json`, `welcome_config.json`, `birthdays.json` + cartella `welcome_images/` |
| `/restoreconfig <file.zip>` | Ripristina da ZIP → richiede `/restart` |

#### Diagnostica

| Comando | Descrizione |
|---|---|
| `/coglist` | Lista cog caricati |
| `/ai_reset [canale]` | Azzera memoria AI (tutto o per canale) |
| `/debug <on\|off>` | Attiva/disattiva il livello log `DEBUG` a runtime (senza restart). `on` mostra la griglia di enrichment Spotify e i dettagli yt-dlp in console; `off` torna a `INFO`. Equivale a impostare `LOG_LEVEL=DEBUG` nel `.env` ma agisce in tempo reale. |

---

### 8.2 `cogs/dev_audio.py` — Audio Dev 🔧🎵

Comandi audio avanzati riservati all'owner per diagnostica del player e test degli stream. Accessibili solo tramite `owner_check`.

---

## 9. Assets, Embeds, Views

### 9.1 `assets/status_messages.py`

Definisce `STATUS_CYCLE` — attività **base predefinite**:
```python
{"type": discord.ActivityType.playing, "name": "...", "status": "online"}
```
Modificare per cambiare i default. Per aggiungere status senza toccare codice → `/addstatus`.

### 9.2 `assets/prompts/ai_prompt.txt`

System prompt dell'AI. Modificabile senza restart invalidando la cache prompt (es. `/ai_reset` o reload cog).

### 9.3 Messaggi compleanno runtime (`birthdays.json`)

I messaggi di auguri compleanno sono **solo plain text** e vengono letti dalla lista
`wish_messages` configurabile via comandi `/bday messages_*`.
Placeholder supportati:
- `{mention}` → menzione membro
- `{name}` → username
- `{display_name}` → nickname server
- `{guild}` → nome server
- `{age}` / `{years}` → età calcolata se l'anno è disponibile

### 9.4 `embeds/music_embeds.py`

| Funzione | Output |
|---|---|
| `now_playing_embed(player)` | Embed traccia corrente (titolo, artista, thumbnail, durata, barra progresso, source, requester) |
| `queue_embed(player, page)` | Embed coda paginata |
| `error_embed(msg)` | Embed rosso |
| `success_embed(msg)` | Embed verde |

### 9.5 `views/player_view.py`

`PlayerView(player)` — bottoni sul messaggio Now Playing:  
⏮ Prev · ⏸/▶️ Pausa/Resume · ⏭ Skip · 🔁 Loop · 🔀 Shuffle · 📝 Coda · ⏹ Stop  
Aggiorna l'embed **in-place** senza reinviare.

### 9.6 `views/queue_view.py`

`QueueView(player, page)` — paginazione coda (◀️ ▶️), aggiorna in-place.

---

## 10. Meccanismi Trasversali

### 10.1 Sistema di Logging

```
pitonazz
├── pitonazz.music
├── pitonazz.player
├── pitonazz.ai
├── pitonazz.dev
├── pitonazz.tts
├── pitonazz.welcome
└── ... (uno per cog)
```

Log ANSI colorati via `core/log_colors.py`. Livello `INFO` configurato in `main.py`.

### 10.2 Gestione Errori

- `CheckFailure` → silenzioso (gestito dal check stesso)
- Altri errori → embed con traceback al `log_channel_id` (se configurato)
- Ogni cog ha anche `cog_app_command_error` per gestione locale

### 10.3 Metadati Cog

```python
COG_ICON  = "🎵"       # Emoji icona
COG_LABEL = "Musica"   # Nome leggibile
COG_TYPE  = "public"   # "public" | "admin" | "dev"
```

Usati da `help.py` per costruire automaticamente i menu di aiuto.

### 10.4 Compatibilità Legacy

`OWNER_ID` + `DEV_IDS` con supporto legacy `DEV_ID` per retrocompatibilità.

### 10.5 Convenzioni naming

- Repository GitHub: `Pytonazz2026`
- Nome bot lato utente/branding: `Pitonazz`
- Namespace logger tecnico: `pitonazz.*` (sempre minuscolo)

### 10.6 Script operativi: classificazione

- `scripts/deploy_commands.py` → uso **manuale/emergency** per forzare sync slash commands.
- `scripts/update_ytdlp.sh` → uso **maintenance** per aggiornamento rapido `yt-dlp`.
- `tools/audit_architecture.py` → uso **periodico/audit** per segnali di refactor (coupling cog→cog e duplicazioni logiche).

### 10.7 Governance stile/log

`tools/check_logs.py` applica policy log solo su:
- `cogs/**/*.py`
- `core/**/*.py`
- `main.py`

`views/`, `embeds/`, `scripts/`, `tools/` sono fuori scope del checker per scelta esplicita.

### 10.8 Linea guida fattorizzazione (distribuire vs centralizzare)

- **Centralizzare in startup** solo bootstrap tecnico condiviso (es. `ensure_runtime_dirs()` in `main.py`).
- **Distribuire per dominio** la logica business (cog) e persistenza (moduli `core/*_store.py`).
- **No dipendenze cog→cog**: se serve stato/funzioni condivise, estrarre in `core/` (es. `core/ai_runtime.py`).
- Mantenere fallback locali solo nei moduli eseguibili anche standalone (script/import diretti).
- **Evitare refactor massivi preventivi**: preferire interventi selettivi solo quando portano beneficio tecnico concreto.

#### Criteri di trigger per refactor a settori

Eseguire refactor solo se emerge almeno uno di questi segnali:
- file con responsabilità miste o dimensione/complessità non più gestibile;
- dipendenze incrociate non desiderate (soprattutto cog→cog);
- duplicazioni reali della stessa logica in più cogs/moduli;
- fix/test difficili da isolare senza side-effect.

Soglie minime consigliate per aprire task di refactor:
- **Volume file:** cog oltre ~900 righe o modulo core oltre ~700 righe *con responsabilità eterogenee*.
- **Coupling:** presenza di import diretti `cogs.*` dentro altri cogs.
- **Duplicazione concreta:** stesso flusso logico ripetuto in >=2 funzioni/metodi non banali (>=8 righe utili).
- **Manutenibilità:** fix ricorrenti nello stesso punto o test/fix che richiedono workaround trasversali.

Audit periodico rapido (solo rilevazione, nessuna riscrittura automatica):

```bash
python tools/audit_architecture.py
```

Per uso CI/manual gate:

```bash
python tools/audit_architecture.py --strict
```

#### Decisione operativa corrente

- **Ora:** mantenere l'assetto attuale (stabile, coerente e leggibile).
- **Quando serve:** isolare helper condivisi in `core/` (micro-refactor) e dividere solo i cogs che superano soglia di complessità reale, uno per volta.
- **Da evitare:** refactor solo estetici o non supportati da segnali tecnici.

---

## 11. Guida agli Aggiornamenti

### 11.1 Aggiungere un Nuovo Cog

1. Creare `cogs/nomecog.py`
2. Classe con `COG_ICON`, `COG_LABEL`, `COG_TYPE`
3. `async def setup(bot): await bot.add_cog(NomeCog(bot))`
4. Caricato automaticamente (hot-reload o restart)
5. Aggiornare [sezione 2](#2-architettura-e-gerarchia-dei-file) e [7](#7-cogs--funzionalità-pubbliche)/[8](#8-cogs--funzionalità-admindev)

### 11.2 Aggiungere un Comando

1. Aggiungere `@app_commands.command(...)` nel cog
2. Salva → watchdog ricarica automaticamente
3. `/sync` se i comandi non appaiono su Discord
4. Aggiornare tabella nella sezione del cog

### 11.3 Modificare Config Audio

| Parametro | File | Variabile |
|---|---|---|
| Volume default | `config.py` | `Config.DEFAULT_VOLUME` |
| Timeout inattività | `config.py` | `Config.IDLE_TIMEOUT` |
| Timeout canale vuoto | `config.py` | `Config.EMPTY_CH_TIMEOUT` |
| Max tracce coda | `config.py` | `Config.MAX_QUEUE` |
| Qualità yt-dlp | `config.py` | `Config.YDL_OPTIONS["format"]` |

### 11.4 Aggiungere un Filtro Audio

In `cogs/filters.py`:
```python
FILTERS["nomefiltro"] = ("stringa_ffmpeg_af", "🎵 Label")
```
+ aggiungere `app_commands.Choice` nel decorator.

### 11.5 Aggiungere una Voce TTS

In `cogs/tts.py`:
```python
VOICES["nome (lingua, genere)"] = "it-IT-VoiceNameNeural"
```

### 11.6 Modificare il Prompt AI

Editare `assets/prompts/ai_prompt.txt` — effettivo dopo invalidazione cache (`/ai_reset`) o reload del cog AI.

### 11.7 Aggiornare yt-dlp

```bash
pip install -U yt-dlp
```

### 11.8 Deployment su VM/VPS

```bash
# .env
YTDLP_PROXY=socks5://127.0.0.1:40000
FFMPEG_PROXY=http://127.0.0.1:3128

# Avviare WARP
warp-cli connect

# Avviare Squid (porta 3128 → WARP)
sudo systemctl start squid

# Avviare bot (screen/tmux/systemd)
screen -S pitonazz
python main.py
```

### 11.9 Cosa Aggiornare Dopo un Commit

| Tipo di modifica | Sezioni da aggiornare |
|---|---|
| Nuovo cog | [2](#2-architettura-e-gerarchia-dei-file), [7](#7-cogs--funzionalità-pubbliche) o [8](#8-cogs--funzionalità-admindev) |
| Nuovo comando | Tabella nella sezione del cog |
| Modifica `config.py` | [4.2](#42-classe-config-configpy) |
| Modifica `bot_config.json` | [4.3](#43-runtime-config--bot_configjson) |
| Modifica player | [6.2](#62-playerpy--musicplayer) |
| Modifica resolver | [6.1](#61-source_resolverpy--resolver-multi-fonte) |
| Modifica filtri | [7.2](#72-cogsfilterspy--filtri-audio-️) |
| Nuove dipendenze | [3](#3-dipendenze-e-requisiti) |
| Struttura cartelle | [2](#2-architettura-e-gerarchia-dei-file) |
| Permessi/check | [6.7](#67-permissionspy), [8.1](#81-cogsdevpy--pannello-dev-) |

---

> **Fine documento.**  
> Versione basata su commit `7c880a25c50be4b4a54b9160fcbdff2fcc41289e`  
> Per aggiornamenti: identificare la riga nella tabella [11.9](#119-cosa-aggiornare-dopo-un-commit) e intervenire nella sola sezione indicata.
