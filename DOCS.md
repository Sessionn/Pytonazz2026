# DOCS — Pytonazz2026

Riferimento tecnico completo di tutti i comandi slash, listener e comportamenti del bot.

> **Legenda permessi** — 🟢 Tutti | 🟡 Moderatori | 🔴 Owner bot

---

## Indice

1. [Musica](#-musica)
2. [Filtri Audio](#-filtri-audio)
3. [TTS](#-tts)
4. [AI](#-ai)
5. [Divertimento](#-divertimento)
6. [Moderazione](#-moderazione)
7. [Compleanni](#-compleanni)
8. [Welcome / Goodbye](#-welcome--goodbye)
9. [Help](#-help)
10. [Dev / Admin](#-dev--admin)
11. [Architettura interna](#architettura-interna)

---

## 🎵 Musica

Il player musicale è basato su `discord.py` voice + FFmpeg. Ogni guild ha un'istanza `MusicPlayer` indipendente.

### Comandi

| Comando | Parametri | Permessi | Descrizione |
|---|---|---|---|
| `/play` | `query` | 🟢 | Aggiunge alla coda o avvia la riproduzione. Accetta URL YouTube, Spotify, SoundCloud o testo libero |
| `/skip` | — | 🟢 | Salta la traccia corrente |
| `/stop` | — | 🟢 | Ferma la riproduzione e svuota la coda |
| `/pause` | — | 🟢 | Mette in pausa |
| `/resume` | — | 🟢 | Riprende dalla pausa |
| `/queue` | — | 🟢 | Mostra la coda con paginazione interattiva |
| `/nowplaying` | — | 🟢 | Mostra la traccia in riproduzione con barra di avanzamento |
| `/volume` | `livello` (1–200) | 🟢 | Imposta il volume |
| `/seek` | `posizione` (mm:ss o secondi) | 🟢 | Salta a una posizione nella traccia corrente |
| `/loop` | `modalità` | 🟢 | Modalità loop: `off` / `track` / `queue` |
| `/shuffle` | — | 🟢 | Mescola casualmente la coda |
| `/remove` | `posizione` | 🟢 | Rimuove una traccia dalla coda per posizione |
| `/move` | `da` `a` | 🟢 | Sposta una traccia da una posizione a un'altra |
| `/clear` | — | 🟢 | Svuota la coda (non ferma la traccia corrente) |
| `/autoplay` | — | 🟢 | Attiva/disattiva autoplay: suggerisce tracce simili quando la coda finisce |
| `/disconnect` | — | 🟢 | Disconnette il bot dal canale vocale |
| `/join` | — | 🟢 | Entra nel canale vocale dell'utente |

### Sorgenti supportate

- **YouTube**: URL video, URL playlist (`?list=PL/OLAK/RDCLAK/UU/LL/FL/WL`), URL canale, ricerca testuale
- **Spotify**: link `track`, `playlist`, `album`, `artist` — risolti tramite YouTube
- **SoundCloud**: URL singola traccia, `sets/` o `albums/`
- **Testo libero**: qualsiasi stringa non riconosciuta come URL viene ricercata su YouTube

### Comportamento playlist/album

Quando viene rilevata una collezione (playlist YouTube, album/playlist Spotify, set SoundCloud), il bot avvia il caricamento in background mostrando una barra di avanzamento nell'embed. Il caricamento può essere interrotto se il bot viene fermato nel frattempo.

### Debounce `/play`

Per prevenire doppi click, i comandi `/play` dallo stesso utente entro una finestra di ~1,8 secondi vengono ignorati silenziosamente.

### Autoplay

Quando la coda è esaurita e autoplay è attivo, il bot suggerisce e carica automaticamente fino a 8 tracce simili a quella appena terminata.

---

## 🎛️ Filtri Audio

Filtri applicabili in tempo reale alla riproduzione audio tramite il cog `filters.py`.

| Comando | Descrizione |
|---|---|
| `/filter` | Applica o rimuove un filtro audio. Mostra la lista dei filtri disponibili se invocato senza parametri |

I filtri vengono passati direttamente a FFmpeg come opzioni audio. L'insieme dei filtri disponibili è definito nel cog.

---

## 🗣️ TTS

Text-to-speech in canale vocale tramite il cog `tts.py`.

| Comando | Parametri | Permessi | Descrizione |
|---|---|---|---|
| `/tts` | `testo` | 🟢 | Legge il testo nel canale vocale corrente dell'utente |

Richiede che l'utente sia in un canale vocale. Il bot entra, legge il testo e, se non c'è musica in coda, si disconnette automaticamente.

---

## 🤖 AI

Il cog `ai.py` implementa un listener `on_message` — non ci sono comandi slash dedicati.

### Trigger

| Modalità | Come attivarlo |
|---|---|
| **Mention** | `@Pytonazz <messaggio>` in qualsiasi canale |
| **DM** | Qualsiasi messaggio privato al bot |
| **Reply** | Rispondere a un messaggio del bot |

### Funzionalità

- **Memoria per canale**: cronologia a finestra scorrevole (fino a 20 scambi), separata per canale/DM.
- **Contesto utenti menzionati**: se il messaggio menziona altri utenti, il bot inietta nel prompt un breve riassunto del loro comportamento recente nel canale (tono, argomenti trattati, ultimi messaggi — cache 10 min).
- **Risposta multi-chunk**: le risposte lunghe (>1990 char) vengono spezzate in più messaggi Discord.
- **Rate limit**: ogni utente può interrogare il bot una volta ogni `AI_COOLDOWN_SECONDS` secondi (configurabile in `config.py`).
- **Allegati immagine**: il bot riconosce immagini allegate e ne include metadati nel contesto (nome file, dimensioni, hint).

### Ricerca Wikipedia

Il bot attiva automaticamente una ricerca su Wikipedia italiana quando:
- il messaggio contiene i trigger espliciti `cerca web:`, `search:`, `web:` o `#web`
- oppure la risposta AI esprime incertezza (frasi come "non so", "boh", "non ricordo"…) su un messaggio che sembra una domanda

### System prompt

Caricato da `assets/prompts/ai_prompt.txt`. La cache del prompt viene invalidata automaticamente al ricaricamento del cog (`/dev reload ai`) e può essere forzata via dev tools.

### Provider AI

Il client (`core/ai_client.py`) supporta più provider con fallback automatico. Almeno un API key deve essere configurata in `.env`.

---

## 🎲 Divertimento

### Comandi slash

| Comando | Parametri | Descrizione |
|---|---|---|
| `/8ball` | `domanda` | Interroga la Magic 8-Ball. Risposta casuale tra positivo, negativo o incerto, con embed colorato |
| `/citazione` | `testo` `autore?` `utente?` `immagine_url?` | Genera una card PNG con la citazione. L'avatar viene preso dall'utente Discord se specificato, altrimenti dall'invocante o da URL custom |
| `/roulette` | — | Roulette russa: 1 possibilità su 6 di "morire". Mostra il cilindro con la camera estratta |

### Menu contestuale

| Nome | Come usarlo | Descrizione |
|---|---|---|
| **Citazione** | Tasto destro su un messaggio → Apps → "Citazione" | Genera una card PNG con il testo del messaggio selezionato |

---

## 🔨 Moderazione

Il cog `moderation.py` copre le operazioni standard di moderazione server. Tutti i comandi richiedono i permessi Discord appropriati.

| Comando | Parametri principali | Permessi | Descrizione |
|---|---|---|---|
| `/ban` | `utente` `motivo?` | 🟡 Ban Members | Banna un utente dal server |
| `/unban` | `utente_id` `motivo?` | 🟡 Ban Members | Rimuove il ban |
| `/kick` | `utente` `motivo?` | 🟡 Kick Members | Espelle un utente |
| `/mute` | `utente` `durata?` `motivo?` | 🟡 Moderate Members | Silenzia (timeout Discord) |
| `/unmute` | `utente` | 🟡 Moderate Members | Rimuove il timeout |
| `/warn` | `utente` `motivo` | 🟡 Moderate Members | Aggiunge un avvertimento al registro del membro |
| `/warnings` | `utente` | 🟡 Moderate Members | Mostra il registro degli avvertimenti |
| `/clearwarnings` | `utente` | 🟡 Moderate Members | Azzera gli avvertimenti |
| `/purge` | `quantità` `utente?` | 🟡 Manage Messages | Elimina messaggi in massa (con filtro utente opzionale) |
| `/slowmode` | `secondi` | 🟡 Manage Channels | Imposta slowmode nel canale corrente |
| `/lock` | — | 🟡 Manage Channels | Blocca il canale (impedisce l'invio messaggi a @everyone) |
| `/unlock` | — | 🟡 Manage Channels | Sblocca il canale |
| `/cases` | `utente?` | 🟡 Moderate Members | Mostra il log dei casi di moderazione |

Tutte le azioni vengono loggate internamente con ID caso progressivo.

---

## 🎂 Compleanni

Il cog `birthdays.py` gestisce la registrazione e gli auguri automatici.

| Comando | Parametri | Permessi | Descrizione |
|---|---|---|---|
| `/birthday set` | `giorno` `mese` | 🟢 | Registra il proprio compleanno |
| `/birthday remove` | — | 🟢 | Rimuove il proprio compleanno |
| `/birthday show` | `utente?` | 🟢 | Mostra il compleanno di un utente (o il proprio) |
| `/birthday list` | — | 🟢 | Lista tutti i compleanni registrati nel server |
| `/birthday next` | — | 🟢 | Mostra il prossimo compleanno in arrivo |
| `/birthday config` | `canale?` `ruolo?` | 🟡 Manage Guild | Configura canale e ruolo per gli auguri automatici |

**Auguri automatici**: ogni giorno a mezzanotte il bot controlla i compleanni del giorno e invia un messaggio nel canale configurato, assegnando temporaneamente il ruolo compleanno se configurato.

I dati sono persistiti in `data/birthdays.json`.

---

## 👋 Welcome / Goodbye

Il cog `welcome.py` gestisce messaggi di entrata/uscita e assegnazione ruoli automatica.

| Comando | Parametri | Permessi | Descrizione |
|---|---|---|---|
| `/welcome config` | — | 🟡 Manage Guild | Wizard di configurazione interattivo |
| `/welcome set channel` | `canale` | 🟡 Manage Guild | Imposta il canale per i messaggi di benvenuto |
| `/welcome set goodbye` | `canale` | 🟡 Manage Guild | Imposta il canale per i messaggi di addio |
| `/welcome set message` | `testo` | 🟡 Manage Guild | Personalizza il messaggio di benvenuto |
| `/welcome set role` | `ruolo` | 🟡 Manage Guild | Ruolo assegnato automaticamente ai nuovi membri |
| `/welcome test` | — | 🟡 Manage Guild | Simula un messaggio di benvenuto |
| `/welcome disable` | — | 🟡 Manage Guild | Disabilita welcome/goodbye |

**Comportamento automatico** (`on_member_join` / `on_member_remove`):
- invia il messaggio configurato nel canale apposito
- assegna il ruolo automatico al nuovo membro (se configurato)

La configurazione è persistita per guild in `data/`.

---

## ❓ Help

| Comando | Parametri | Descrizione |
|---|---|---|
| `/help` | `categoria?` | Mostra la lista comandi raggruppata per categoria. Se si specifica una categoria, mostra solo i comandi di quel modulo |

Il cog `help.py` costruisce dinamicamente la lista leggendo i metadati (`COG_ICON`, `COG_LABEL`, `COG_TYPE`) da ogni cog caricato.

---

## 🔧 Dev / Admin

Tutti i comandi di questo gruppo sono riservati all'**owner** del bot (ID configurato in `.env`).

### `dev.py` — Gestione bot

| Comando | Descrizione |
|---|---|
| `/dev reload <cog>` | Ricarica un cog a caldo (hot-reload) |
| `/dev load <cog>` | Carica un cog non attivo |
| `/dev unload <cog>` | Scarica un cog |
| `/dev sync` | Sincronizza i comandi slash (globale o guild) |
| `/dev eval <codice>` | Esegue codice Python inline nel contesto del bot |
| `/dev status <testo>` | Cambia lo status/activity del bot |
| `/dev cogs` | Lista tutti i cog caricati e il loro stato |

### `dev_audio.py` — Debug audio

| Comando | Descrizione |
|---|---|
| `/devaudio info` | Mostra lo stato interno del player audio per il guild corrente |
| `/devaudio reset` | Forza il reset del player (in caso di stato corrotto) |

### `dev_cache.py` — Gestione cache

| Comando | Descrizione |
|---|---|
| `/devcache stats` | Statistiche del database SQLite di cache (hit rate, dimensione, entries) |
| `/devcache clear` | Svuota la cache delle query musicali |
| `/devcache inspect <query>` | Mostra l'entry di cache per una query specifica |

---

## Architettura interna

### Stack tecnologico

| Componente | Tecnologia |
|---|---|
| Runtime | Python 3.11+ |
| Framework bot | discord.py 2.x (`app_commands`) |
| Audio | FFmpeg + `discord.py` voice client |
| Persistenza leggera | JSON in `data/` |
| Cache query musicali | SQLite in `cache_db/` |
| AI client | Multi-provider con fallback (`core/ai_client.py`) |
| Ricerca web AI | Wikipedia Search API (it.wikipedia.org) |

### Flusso avvio (`main.py`)

1. Lettura configurazione da `.env` via `config.py`
2. Caricamento di tutti i cog in `cogs/`
3. Connessione a Discord e sync comandi slash
4. Loop eventi `discord.py`

### MusicPlayer

Ogni guild ha un'istanza `MusicPlayer` separata (gestita in `core/player.py`). Il player mantiene:
- coda tracce (list)
- stato corrente (paused/playing/idle)
- modalità loop (`off` / `track` / `queue`)
- volume
- flag autoplay

La risoluzione delle sorgenti (URL → stream URL + metadati) avviene in `core/source_resolver.py` con cache SQLite per evitare lookup ripetuti.

### Stato AI in-memory

`core/ai_runtime.py` espone un oggetto `_state` singleton con:
- `conversation_memory`: dizionario `channel_id → deque` (max 20 messaggi)
- `rate_limit_map`: dizionario `user_id → timestamp` ultimo messaggio
- `channel_recent_messages`: buffer messaggi recenti per canale (per context building)
- `mention_background_cache`: cache profili utenti menzionati (TTL 10 min)
- `web_retry_metrics`: contatori metriche ricerca web

Lo stato viene resettato al ricaricamento del cog AI (`cog_unload`).

### Logging

Ogni cog usa un logger dedicato (`pitonazz.<nome_cog>`) con output colorato via `core/log_colors.py`. Il livello di log è configurabile in `config.py`.
