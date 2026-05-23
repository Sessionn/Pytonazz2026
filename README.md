# Pytonazz2026

> Bot Discord per server italiani — musica multi-sorgente, AI contestuale, moderazione avanzata, compleanni e welcome/goodbye completamente personalizzabili.

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
│   ├── moderation.py        # Moderazione server (ban, kick, museruola, isolamento…)
│   ├── birthdays.py         # Gestione compleanni (/bday)
│   ├── welcome.py           # Welcome/goodbye + AutoRole (/welcome /goodbye /autorole)
│   ├── help.py              # Comando /help dinamico
│   ├── dev.py               # Comandi sviluppatore (owner-only)
│   ├── dev_audio.py         # Debug audio (owner-only)
│   └── dev_cache.py         # Gestione cache (owner-only)
├── core/
│   ├── player.py            # Logica MusicPlayer
│   ├── source_resolver.py   # Risoluzione sorgenti (YT, Spotify, SoundCloud)
│   ├── ai_client.py         # Client AI multi-provider
│   ├── ai_runtime.py        # Stato in-memory AI
│   ├── birthday_store.py    # Persistenza compleanni (JSON)
│   ├── welcome_store.py     # Persistenza config welcome/goodbye (JSON)
│   ├── permissions.py       # Decoratori permessi (admin_check, perm)
│   ├── cmd_perm.py          # Helper @perm
│   ├── paths.py             # Costanti percorsi (data/, cache_db/, assets/…)
│   ├── quote_card.py        # Generatore card citazioni
│   └── log_colors.py        # Helper log colorati
├── embeds/
│   └── music_embeds.py      # Embed riusabili per la musica
├── views/
│   └── queue_view.py        # UI paginata per la coda
├── assets/
│   └── prompts/
│       └── ai_prompt.txt    # System prompt AI (modificabile a caldo)
├── data/                    # JSON persistenti (compleanni, config welcome/goodbye…)
├── data/welcome_images/     # Immagini locali per embed welcome/goodbye
├── cache_db/                # Cache SQLite per le query musicali
└── tools/                   # Script di utilità
```

---

## Requisiti

- Python 3.11+
- FFmpeg installato e nel PATH
- Token bot Discord con intent `MESSAGE_CONTENT`, `GUILD_MEMBERS`, `GUILDS`
- Dipendenze: vedi `requirements.txt`

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
```

Vedi `.env.example` per la lista completa dei campi disponibili.

---

## Avvio

```bash
python main.py
```

Al primo avvio i comandi slash vengono sincronizzati automaticamente. Con `DEV_GUILD_ID` impostato la sync è istantanea sul guild di sviluppo; senza, la sync globale può richiedere fino a 1 ora.

---

## Moduli principali

| Cog | Tipo | Descrizione |
|---|---|---|
| `music` | pubblico | Player completo: play, queue, skip, loop, shuffle, seek, volume, autoplay |
| `filters` | pubblico | Filtri audio applicabili in tempo reale via FFmpeg |
| `tts` | pubblico | Text-to-speech in canale vocale |
| `ai` | pubblico | Risponde a mention, reply e DM con AI contestuale + Wikipedia |
| `fun` | pubblico | `/8ball`, `/citazione`, `/roulette`, menu contestuale "Citazione" |
| `moderation` | admin | Ban, kick, timeout, purge, ruolo, museruola, jenniserpi, isolamento/quarantena |
| `birthdays` | pubblico/admin | Gruppo `/bday`: registrazione compleanni, auguri automatici, messaggi personalizzabili |
| `welcome` | admin | Gruppi `/welcome` `/goodbye` `/autorole`: embed completamente configurabili con immagini, plain text, placeholder |
| `help` | pubblico | Lista comandi dinamica raggruppata per categoria |
| `dev` | owner | Reload cog, eval, status, sync (owner-only) |
| `dev_audio` | owner | Debug stato player audio (owner-only) |
| `dev_cache` | owner | Statistiche e gestione cache SQLite (owner-only) |

Per i dettagli di ogni comando vedi **[DOCS.md](DOCS.md)**.

---

## Sorgenti musicali supportate

- **YouTube** — URL video, playlist (`?list=PL…`), ricerca testuale
- **Spotify** — track, playlist, album, artista (risolti via YouTube)
- **SoundCloud** — URL traccia, set/album
- **Testo libero** — qualsiasi stringa non riconosciuta come URL viene ricercata su YouTube

---

## AI

Il bot risponde tramite AI quando:
- viene **menzionato** (`@Pytonazz`) in qualsiasi canale
- riceve un **DM**
- qualcuno **risponde** a un suo messaggio

La conversazione è mantenuta **per canale** (o per utente in DM) con una cronologia a finestra scorrevole. Il system prompt è caricato da `assets/prompts/ai_prompt.txt`.

La ricerca Wikipedia si attiva con i trigger `cerca web:`, `search:`, `web:`, `#web` oppure automaticamente quando il modello AI esprime incertezza su una domanda.

---

## Moderazione

Oltre ai comandi standard (`/ban`, `/kick`, `/timeout`, `/purge`, `/ruolo`), il bot include strumenti voce avanzati:

- **`/museruola`** — muta permanentemente il microfono di uno o più utenti, anche tra reconnessioni
- **`/jenniserpi`** / **`/jenniserpi_off`** — sordi permanenti (deafen) su singoli o gruppi
- **`/isolamento`** / **`/isolamento_off`** — sposta e blocca utenti in un canale quarantena dedicato; un watchdog riporta gli utenti nel canale se tentano di spostarsi

---

## Licenza

Uso privato / progetto personale. Nessuna licenza aperta.
