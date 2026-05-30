# 🐍 Pitonazz Discord Bot
![Pytonazz Gif](assets/git/demo.gif)

### Pitonazz è un'applicazione bot modulare e multifunzionale di livello enterprise per Discord, sviluppata in Python sull'architettura asincrona di `discord.py`. Progettato per coniugare l'intrattenimento multimediale ad alta fedeltà con l'automazione di community e l'intelligenza artificiale, il bot si appoggia su un motore di caching persistente SQLite custom e su una dashboard locale pubblicata correttamente dietro reverse proxy HTTPS.

---

## 📍 Indice
1. [Caratteristiche Principali](#-caratteristiche-principali)
2. [Stack Tecnologico](#%EF%B8%8F-stack-tecnologico)
3. [Prerequisiti di Sistema](#-prerequisiti-di-sistema)
4. [Guida all'Installazione Rapida](#-guida-allinstallazione-rapida)
5. [Configurazione delle Variabili d'Ambiente (`.env`)](#-configurazione-delle-variabili-dambiente-env)
6. [Struttura Essenziale della Repository](#-struttura-essenziale-della-repository)
7. [Licenza e Sviluppo](#-licenza-e-sviluppo)

---

## ✨ Caratteristiche Principali

* **🎵 Riproduzione Audio Avanzata:** Core di streaming ottimizzato via FFmpeg e `yt-dlp`. Supporta query testuali e URL da YouTube, Spotify (tracce, album, playlist) e SoundCloud. Include un sistema di code dinamico con filtri di equalizzazione in tempo reale.
* **🧠 Assistente AI Conversazionale:** Integrazione con LLM remoti dotati di memoria a lungo termine isolata per singolo canale e capacità di computer vision (analisi immagini). Implementa una modalità `#web` per il recupero del contesto live tramite Wikipedia Search API.
* **🗄️ Query Cache Proprietaria:** Sottosistema relazionale SQLite per l'indicizzazione e l'ottimizzazione delle tracce musicali con lookup predittivo, algoritmi di similarità testuale e auto-pruning.
* **🎂 Community & Automazione:** Gestione centralizzata dei compleanni degli utenti con messaggi di auguri customizzati pianificati a cron, oltre a un sistema dinamico di benvenuto/addio per i nuovi membri.
* **📊 Dashboard Amministrativa:** Dashboard Flask servita tramite `waitress`, protetta da credenziali, per ispezione cache e monitoraggio operativo.

---

## 🛠️ Stack Tecnologico

* **Linguaggio:** Python 3.10 o superiore (struttura completamente asincrona via `asyncio`).
* **Libreria Core:** `discord.py` v2.x (sfrutta nativamente gli Application Commands / Slash Commands).
* **Audio Processing:** Binari di `FFmpeg` combinati con l'estrattore di metadati dinamico `yt-dlp`.
* **Database Layer:** Modulo nativo `sqlite3` isolato tramite thread-lock e astrazioni di persistenza JSON locali.
* **Web Engine:** `Flask` + `waitress` (Dashboard) e `aiohttp` (richieste di rete asincrone verso API AI e Wikipedia).

---

## 📋 Prerequisiti di Sistema

Prima di procedere all'installazione, assicurarsi che sul sistema di hosting (locale o VPS Linux Ubuntu/Debian) siano installati i seguenti pacchetti:

```bash
# Aggiornamento dei repository ed installazione di FFmpeg e Python3 pip
sudo apt update && sudo apt install ffmpeg python3-pip python3-venv -y
```

---

## 🚀 Guida all'Installazione Rapida

### 1. Clonazione e Isolamento dell'Ambiente

Clona la repository ed accedi alla cartella radice, quindi crea un ambiente virtuale per isolare le dipendenze:

```bash
git clone https://github.com/tuo-username/Pitonazz.git
cd Pitonazz
python3 -m venv venv
```

### 2. Attivazione ed Installazione dei Pacchetti

Attiva l'ambiente virtuale ed esegui lo script di setup o installa direttamente i requisiti:

```bash
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Primo Avvio

Configura il file `.env` (vedi sezione successiva) ed esegui il punto d'ingresso dell'applicazione:

```bash
python main.py
```

---

## ⚙️ Configurazione delle Variabili d'Ambiente (`.env`)

Crea un file nominato `.env` nella directory principale del bot. Di seguito viene schematizzato il modello dei parametri richiesti:

```env
# ====== DISCORD IDENTITY ======
DISCORD_TOKEN=il_tuo_token_bot_discord

# ====== PERMESSI E SVILUPPO ======
OWNER_ID=123456789012345678      # ID Discord dell'owner principale
DEV_IDS=123456789,987654321      # ID dei collaboratori autorizzati (CSV)
DEV_ID=123456789012345678       # ID dello sviluppatore di riferimento
GUILD_IDS=000000000000000000     # ID gilda per il sync immediato dei comandi

# ====== INTEGRAZIONE AI ======
GROQ_API_KEY=gsk_la_tua_api_key_groq_qui

# ====== CREDENZIALI SPOTIFY ======
SPOTIFY_CLIENT_ID=client_id_della_dashboard_spotify
SPOTIFY_CLIENT_SECRET=client_secret_della_dashboard_spotify

# ====== SETTAGGI DELLA QUERY CACHE ======
CACHE_ENABLED=true
DB_PATH=data/database/cache.db
CACHE_TTL_DAYS=30
CACHE_MAX_ENTRIES=10000

# ====== FLASK WEB DASHBOARD ======
DASHBOARD_SOCKET=127.0.0.1:5000
DASH_USER=admin
DASH_PASSWORD=password_super_sicura_dashboard
DASH_SECRET_KEY=chiave_esadecimale_per_le_sessioni_flask
DASH_TRUST_PROXY=true
DASH_SESSION_SECURE=true
DASH_SESSION_SAMESITE=Lax
DASH_LOGIN_WINDOW_SECONDS=900
DASH_LOGIN_MAX_ATTEMPTS=5
DASH_LOG_SCANNERS=false

# ====== NETWORK PROXY & COOKIES ======
YTDLP_PROXY=http://indirizzo_proxy:porta
FFMPEG_PROXY=http://indirizzo_proxy:porta
COOKIE_FILE=data/cookies.txt
LOG_LEVEL=INFO
SHOW_BANNER=true
```

---

## 📁 Struttura Essenziale della Repository

```plaintext
Pitonazz/
│   .env                  # File delle credenziali di produzione (Ignorato da Git)
│   .env.example          # File di esempio per la configurazione dell'ambiente
│   config.py             # Parser globale centralizzato delle variabili d'ambiente
│   main.py               # Punto d'ingresso e inizializzatore asincrono del bot
│   requirements.txt      # Elenco delle dipendenze e librerie Python
│
├───assets/               # File di configurazione statica e prompt
│   ├───config/           # JSON per impostazioni interne e rotazione status
│   ├───data/             # JSON locali per la persistenza dei compleanni
│   └───prompts/          # Prompt di sistema e configurazioni per l'AI
│
├───cache_db/             # Motore relazionale di caching musicale (SQLite)
│
├───cogs/                 # Moduli funzionali del bot (Comandi Slash)
│
├───core/                 # Logica di backend (Player audio, code, permessi)
│
├───data/                 # Directory di runtime per DB e Dashboard Flask
│   ├───database/         # File di persistenza cache.db
│   └───dashboard/        # Template HTML, fogli di stile CSS e logica Flask
│
├───embeds/               # Costruttori grafici standardizzati per i messaggi Rich Embed
│
└───scripts/              # Script di utility per installazione e manutenzione
```

---

## 📜 Licenza e Sviluppo

## Dashboard in Produzione

Per un setup completo da zero su Ubuntu usa [SETUP_UBUNTU_VM.md](SETUP_UBUNTU_VM.md).

Per un deploy Internet-facing non esporre direttamente `0.0.0.0:5000`.
Schema consigliato:

```text
Internet -> 443/TLS (Caddy o Nginx) -> 127.0.0.1:5000 (dashboard Flask)
```

Passi minimi su Ubuntu:

```bash
cd /PERCORSO/DELLA/REPO
cp .env .env.backup.$(date +%F-%H%M%S)
sed -i 's/^DASHBOARD_SOCKET=.*/DASHBOARD_SOCKET=127.0.0.1:5000/' .env
sed -i 's/^DASH_LOG_SCANNERS=.*/DASH_LOG_SCANNERS=false/' .env
sudo apt update
sudo apt install -y ufw
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw deny 5000/tcp
sudo ufw --force enable
sudo ufw status verbose
```

Setup rapido con `Caddy` e DuckDNS:

```bash
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list > /dev/null
sudo apt update
sudo apt install -y caddy
sudo cp /etc/caddy/Caddyfile /etc/caddy/Caddyfile.backup.$(date +%F-%H%M%S)
sudo tee /etc/caddy/Caddyfile > /dev/null <<'EOF'
tuodominio.duckdns.org {
    encode gzip zstd
    reverse_proxy 127.0.0.1:5000
}
EOF
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl restart caddy
sudo systemctl status caddy --no-pager
```

Verifiche:

```bash
curl -I http://127.0.0.1:5000
curl -I http://tuodominio.duckdns.org
curl -I https://tuodominio.duckdns.org
```

Se `curl https://tuodominio.duckdns.org` resta appeso, controlla prima:

```bash
sudo systemctl status caddy --no-pager
sudo journalctl -u caddy -n 100 --no-pager
getent hosts tuodominio.duckdns.org
sudo ss -tulpn | grep -E ':80|:443|:5000'
```

Dopo il test positivo, chiudi definitivamente `5000/tcp` anche lato OCI e lascia pubbliche solo `80`, `443` e `22`.

---

Ho sviluppato questo progetto personale a per scopo puramente ludico e didattico. Per maggiori dettagli sull'utilizzo dei singoli comandi o sulla logica del database, consultare rispettivamente i file **[`DOCS.md`](DOCS.md)** e **[`QUERY_CACHE_SETUP.md`](QUERY_CACHE_SETUP.md)**.
