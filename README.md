# 🐍 Pitonazz Discord Bot

Pitonazz è un bot multiproporzione avanzato per Discord sviluppato in Python con la libreria `discord.py`. È progettato per offrire un sistema di streaming musicale ad altissime prestazioni dotato di architettura di caching persistente, un assistente AI conversazionale con memoria a lungo termine e recupero di contesto (Web Search), moduli automatizzati per la gestione di compleanni/benvenuti e una comoda Dashboard Web di amministrazione integrata in Flask.

---

## 🚀 Caratteristiche Principali

| Modulo | Descrizione | Funzionalità Chiave |
| :--- | :--- | :--- |
| **🎵 Musica Avanzata** | Streaming audio ad alta fedeltà con supporto multi-provider. | Coda fino a 200 tracce, Smart Shuffle (no artisti consecutivi), filtri audio (Nightcore, Vaporwave, 8D), riproduzione da YouTube, Spotify (Tracce/Playlist/Album) e SoundCloud. |
| **🧠 Intelligenza Artificiale** | Assistente integrato basato su LLM (con fallback automatico). | Memoria contestuale per canale (fino a 20 messaggi), lettura allegati immagine, e attivazione automatica o esplicita di **Web Search** tramite Wikipedia API. |
| **🗄️ Query Cache System** | Sottosistema proprietario di indicizzazione e caching delle tracce. | lookup a 5 livelli, normalizzazione delle query, Jaccard Fuzzy Scan e auto-pruning LRU/TTL basato su SQLite. |
| **🎂 Compleanni & Community** | Automazione delle ricorrenze e gestione degli ingressi nel server. | Auguri automatici pianificati a mezzanotte (ora UTC), messaggi custom in plain-text con placeholder dinamici (`{mention}`, `{age}`) e immagini di benvenuto dinamiche. |
| **📊 Web Dashboard** | Pannello di controllo web per il monitoraggio del backend. | Sviluppato in Flask, protetto da credenziali personalizzabili, monitoraggio dei log e sicurezza avanzata contro scanner di rete anomali (`[NET_SCAN]`). |

---

## 🛠️ Stack Tecnologico e Dipendenze

* **Core Runtime:** Python 3.10+
* **Discord API Wrapper:** `discord.py` v2.7.1
* **Audio Layer:** FFmpeg (con supporto proxy indipendente) & `yt-dlp`
* **Database Layer:** SQLite (`aiosqlite` per operazioni asincrone e modulo nativo `sqlite3`)
* **Dashboard Server:** Flask WSGI Environment
* **AI Engine:** Integrazione multi-provider via HTTP client asincrono (`aiohttp`)

---

## ⚙️ Configurazione dell'Ambiente (`.env`)

Crea un file chiamato `.env` nella root del progetto prendendo come riferimento il file `.env.example`:

```env
# Credenziali Discord obbligatorie
DISCORD_TOKEN=il_tuo_token_discord_qui

# Permessi e Identificazione Sviluppatori
OWNER_ID=id_proprietario_principale
DEV_IDS=id1,id2,id3
DEV_ID=id_dev_primario

# Provider AI (Richiesta almeno una chiave valida, es: Groq)
GROQ_API_KEY=la_tua_api_key_groq

# Spotify API (Opzionale, abilita il recupero traccia/playlist avanzato)
SPOTIFY_CLIENT_ID=client_id_spotify
SPOTIFY_CLIENT_SECRET=client_secret_spotify

# Configurazione del Sottosistema di Cache Musicale
CACHE_ENABLED=true
DB_PATH=data/database/cache.db
CACHE_TTL_DAYS=30
CACHE_MAX_ENTRIES=10000

# Web Dashboard Flask
DASHBOARD_SOCKET=0.0.0.0:5000
DASH_USER=admin
DASH_PASSWORD=inserisci_una_password_sicura
DASH_SECRET_KEY=genera_un_hex_casuale_sicuro
DASH_LOG_SCANNERS=true

# Opzioni di Network e Fallback Audio
GUILD_IDS=id_server_per_sync_rapido
YTDLP_PROXY=http://tuoproxy:porta
FFMPEG_PROXY=http://tuoproxy:porta
COOKIE_FILE=data/cookies.txt
LOG_LEVEL=INFO
SHOW_BANNER=true
```

---

## 📦 Installazione e Avvio

### 1. Prerequisiti di Sistema (Linux/Ubuntu)

Assicurati che `ffmpeg` sia installato sul sistema ospitante:

```bash
sudo apt update && sudo apt install ffmpeg -y
```

### 2. Configurazione Automatica (Script di Setup)

Il progetto include uno script di installazione automatica dei pacchetti che isola l'ambiente e aggiorna i binari critici:

```bash
chmod +x scripts/setup.sh scripts/update_ytdlp.sh
./scripts/setup.sh
```

### 3. Esecuzione del Bot

Dopo aver configurato correttamente il file `.env`, avvia l'applicazione:

```bash
python main.py
```

---

## 📁 Struttura della Repository

```text
C:.
├── assets/                 # Configuraizoni locali statiche e prompt AI
│   ├── config/             # bot_config.json e custom_statuses.json
│   ├── data/               # database compleanni birthdays.json
│   └── prompts/            # prompt di sistema dell'AI (ai_prompt.txt)
├── cache_db/               # Logica di Engine del Query Cache Database
├── cogs/                   # Estensioni modulari di discord.py (Comandi Slash)
├── core/                   # Architettura software core (Player, Resolver, Queue)
├── data/                   # File di runtime del DB SQLite e Dashboard Web
│   ├── database/
│   │   ├── cache.db
│   │   └── dashboard/      # Server Flask (App, Static CSS/JS, Templates HTML)
├── embeds/                 # Template grafici Rich Embeds per Discord
├── scripts/                # Script di automazione, deploy e aggiornamento yt-dlp
├── tests/                  # Suite di Unit Testing automatizzata per la cache
└── tools/                  # Script diagnostici di audit strutturale dei log
```
