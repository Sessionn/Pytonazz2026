# Pytonazz2026

> Bot Discord per server italiani — musica multi-sorgente, AI contestuale, moderazione, compleanni e molto altro.

---

## Panoramica

Pytonazz2026 è un bot Discord scritto in Python con `discord.py` (slash commands via `app_commands`). Ogni funzionalità è incapsulata in un **cog** separato e il bot si avvia tramite `main.py`. La configurazione avviene interamente via variabili d'ambiente (`.env`).

---

## Struttura del progetto

```
Pytonazz2026/
├── main.py                  # Avvio bot, caricamento cog, sync comandi
├── config.py                # Lettura env + costanti globali
├── requirements.txt
├── .env.example
├── cogs/
│   ├── music.py             # Player musicale completo
│   ├── filters.py           # Filtri audio (EQ, effetti)
│   ├── tts.py               # Text-to-speech in voce
│   ├── ai.py                # AI conversazionale (mention / DM / reply)
│   ├── fun.py               # Comandi divertimento
│   ├── moderation.py        # Moderazione server
│   ├── birthdays.py         # Gestione compleanni
│   ├── welcome.py           # Welcome/goodbye + ruoli automatici
│   ├── help.py              # Comando /help dinamico
│   ├── dev.py               # Comandi sviluppatore (owner-only)
│   ├── dev_audio.py         # Debug audio (owner-only)
│   └── dev_cache.py         # Gestione cache (owner-only)
├── core/
│   ├── player.py            # Logica MusicPlayer
│   ├── source_resolver.py   # Risoluzione sorgenti (YT, Spotify, SoundCloud)
│   ├── ai_client.py         # Client AI multi-provider
│   ├── ai_runtime.py        # Stato in-memory AI
│   ├── quote_card.py        # Generatore card citazioni
│   └── log_colors.py        # Helper log colorati
├── embeds/
│   └── music_embeds.py      # Embed riusabili per la musica
├── views/
│   └── queue_view.py        # UI paginata per la coda
├── assets/
│   └── prompts/
│       └── ai_prompt.txt    # System prompt AI (modificabile a caldo)
├── data/                    # JSON persistenti (compleanni, config welcome…)
├── cache_db/                # Cache SQLite per le query musicali
└── tools/                   # Script di utilità
```

---

## 📦 Installazione e Avvio

### 1. Prerequisiti di Sistema (Linux/Ubuntu)

Assicurati che `ffmpeg` sia installato sul sistema ospitante:

```bash
pip install -r requirements.txt
```

---

## Configurazione

Copia `.env.example` in `.env` e compila tutti i campi:

```env
DISCORD_TOKEN=...
OWNER_ID=...
# Provider AI (almeno uno)
OPENAI_API_KEY=...
# Spotify (opzionale, per link Spotify)
SPOTIFY_CLIENT_ID=...
SPOTIFY_CLIENT_SECRET=...
# Canali/ruoli del server
BIRTHDAY_CHANNEL_ID=...
WELCOME_CHANNEL_ID=...
# ecc. — vedi .env.example per la lista completa
```

---

## Avvio

```bash
python main.py
```

Al primo avvio i comandi slash vengono sincronizzati automaticamente. Con `DEV_GUILD_ID` impostato la sync è istantanea sul guild di sviluppo; senza, la sync globale può richiedere fino a 1 ora.

---

## Moduli principali

| Cog | Descrizione |
|---|---|
| `music` | Player completo: play, queue, skip, loop, shuffle, seek, volume, autoplay |
| `filters` | Filtri audio applicabili in tempo reale |
| `tts` | Text-to-speech in canale vocale |
| `ai` | Risponde a mention, reply e DM con AI contestuale + ricerca Wikipedia |
| `fun` | `/8ball`, `/citazione`, `/roulette`, menu contestuale "Citazione" |
| `moderation` | Ban, kick, mute, timeout, purge, warn, case log |
| `birthdays` | Registra compleanni e invia auguri automatici |
| `welcome` | Messaggio benvenuto/addio, assegnazione ruoli automatica |
| `help` | Lista comandi dinamica per categoria |
| `dev` | Reload cog, eval, status, sync (owner-only) |

Per i dettagli di ogni comando vedi **[DOCS.md](DOCS.md)**.

---

## Sorgenti musicali supportate

- **YouTube** — URL video, playlist (`?list=PL…`), canale, ricerca testuale
- **Spotify** — track, playlist, album, artista (risolti via YouTube)
- **SoundCloud** — URL traccia, set/album
- **Ricerca testuale** — query generica risolta su YouTube

---

## AI

Il bot risponde tramite AI quando:
- viene **menzionato** (`@Pytonazz`)
- riceve un **DM**
- qualcuno **risponde** a un suo messaggio

La conversazione è mantenuta **per canale** (o per utente in DM) con una cronologia a finestra scorrevole. Il system prompt è caricato da `assets/prompts/ai_prompt.txt` e invalidabile a caldo tramite `/dev reload ai`.

La ricerca Wikipedia viene attivata aggiungendo `cerca web:`, `search:`, `web:` o `#web` prima della query, oppure automaticamente quando il modello AI esprime incertezza.

---

## Licenza

Uso privato / progetto personale. Nessuna licenza aperta.
