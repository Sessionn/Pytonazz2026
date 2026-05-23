# DOCS — Pytonazz2026

Riferimento tecnico completo di tutti i comandi slash, listener e comportamenti del bot.

> **Legenda permessi** — 🟢 Tutti | 👑 Manage Guild / admin check | 🔴 Owner bot

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

Il player musicale è basato su `discord.py` voice + FFmpeg. Ogni guild ha un'istanza `MusicPlayer` indipendente gestita in `core/player.py`.

### Comandi

| Comando | Parametri | Descrizione |
|---|---|---|
| `/play` | `query` | Aggiunge alla coda o avvia la riproduzione. Accetta URL YouTube, Spotify, SoundCloud o testo libero |
| `/skip` | — | Salta la traccia corrente |
| `/stop` | — | Ferma la riproduzione e svuota la coda |
| `/pause` | — | Mette in pausa |
| `/resume` | — | Riprende dalla pausa |
| `/queue` | — | Mostra la coda con paginazione interattiva |
| `/nowplaying` | — | Mostra la traccia in riproduzione con barra di avanzamento |
| `/volume` | `livello` (1–200) | Imposta il volume |
| `/seek` | `posizione` (mm:ss o secondi) | Salta a una posizione nella traccia corrente |
| `/loop` | `modalità` | Loop: `off` / `track` / `queue` |
| `/shuffle` | — | Mescola casualmente la coda |
| `/remove` | `posizione` | Rimuove una traccia dalla coda per posizione |
| `/move` | `da` `a` | Sposta una traccia da una posizione a un'altra |
| `/clear` | — | Svuota la coda (non ferma la traccia corrente) |
| `/autoplay` | — | Attiva/disattiva autoplay: suggerisce tracce simili quando la coda finisce |
| `/disconnect` | — | Disconnette il bot dal canale vocale |
| `/join` | — | Entra nel canale vocale dell'utente |

### Sorgenti supportate

- **YouTube** — URL video, playlist (`?list=PL/OLAK/RDCLAK/UU/LL/FL/WL`), URL canale, ricerca testuale
- **Spotify** — link `track`, `playlist`, `album`, `artist` (risolti tramite YouTube)
- **SoundCloud** — URL singola traccia, `sets/` o `albums/`
- **Testo libero** — qualsiasi stringa non URL viene ricercata su YouTube

### Comportamenti

- **Playlist/album**: il bot avvia il caricamento in background con barra di avanzamento nell'embed.
- **Debounce `/play`**: i doppi click dallo stesso utente entro ~1,8 s vengono ignorati silenziosamente.
- **Autoplay**: quando la coda è vuota e autoplay è attivo, il bot carica automaticamente fino a 8 tracce simili all'ultima riprodotta.

---

## 🎛️ Filtri Audio

Filtri applicabili in tempo reale via FFmpeg, gestiti da `cogs/filters.py`.

| Comando | Descrizione |
|---|---|
| `/filter` | Applica o rimuove un filtro. Mostra la lista dei filtri disponibili se invocato senza parametri |

---

## 🗣️ TTS

Text-to-speech in canale vocale via `cogs/tts.py`.

| Comando | Parametri | Descrizione |
|---|---|---|
| `/tts` | `testo` | Legge il testo nel canale vocale corrente dell'utente |

Richiede che l'utente sia in un canale vocale. Se non c'è musica in coda, il bot si disconnette automaticamente dopo la lettura.

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
- **Contesto utenti menzionati**: se il messaggio menziona altri utenti, il bot inietta nel prompt un breve profilo del loro comportamento recente nel canale (cache 10 min).
- **Risposta multi-chunk**: le risposte lunghe (>1990 char) vengono spezzate in più messaggi Discord.
- **Rate limit**: ogni utente può interrogare il bot una volta ogni `AI_COOLDOWN_SECONDS` secondi (configurabile in `config.py`).
- **Allegati immagine**: le immagini allegate vengono riconosciute e i loro metadati iniettati nel contesto.

### Ricerca Wikipedia

Si attiva quando:
- il messaggio contiene i trigger espliciti: `cerca web:`, `search:`, `web:`, `#web`
- oppure la risposta AI esprime incertezza ("non so", "boh", "non ricordo"…) su un messaggio che sembra una domanda

### System prompt

Caricato da `assets/prompts/ai_prompt.txt`. Viene invalidato al ricaricamento del cog (`/dev reload ai`) oppure tramite dev tools.

---

## 🎲 Divertimento

### Comandi slash

| Comando | Parametri | Descrizione |
|---|---|---|
| `/8ball` | `domanda` | Interroga la Magic 8-Ball. Risposta casuale con embed colorato (positivo/negativo/incerto) |
| `/citazione` | `testo` `autore?` `utente?` `immagine_url?` | Genera una card PNG con la citazione. L'avatar viene preso dall'utente Discord se specificato, altrimenti dall'invocante o da URL custom |
| `/roulette` | — | Roulette russa: 1 su 6 di "morire". Mostra il cilindro con la camera estratta |

### Menu contestuale

| Nome | Come usarlo | Descrizione |
|---|---|---|
| **Citazione** | Tasto destro su un messaggio → Apps → "Citazione" | Genera una card PNG con il testo del messaggio selezionato e l'avatar dell'autore |

---

## 🛡️ Moderazione

Il cog `moderation.py` copre moderazione standard e strumenti voce avanzati con persistenza in-session.
Tutti i comandi richiedono i permessi Discord indicati o il check `admin` interno.

### Comandi standard

| Comando | Parametri | Permesso richiesto | Descrizione |
|---|---|---|---|
| `/purge` | `quantità` (1–100) | Manage Messages | Elimina messaggi in massa (max 14 giorni, bulk Discord) |
| `/ruolo` | `utente` `ruolo` | Manage Roles | Assegna o rimuove un ruolo (toggle) |
| `/kick` | `utente` `motivo?` | Kick Members | Espelle un utente (con check gerarchia ruoli) |
| `/ban` | `utente` `motivo?` | Ban Members | Banna un utente (con check gerarchia ruoli) |
| `/timeout` | `utente` `minuti` (1–10080) `motivo?` | Moderate Members | Timeout temporaneo |

### Strumenti voce — Museruola

| Comando | Parametri | Descrizione |
|---|---|---|
| `/museruola` | `utenti` (menzioni/ID separati da spazio) | 🔇 Muta permanentemente il microfono. Si applica subito se in VC, altrimenti al prossimo join |
| `/museruola_off` | `utenti` oppure nessuno (→ menu) | Rimuove la museruola. Senza argomenti mostra un menu a tendina con le sessioni attive |

### Strumenti voce — Jenniserpi (deafen)

| Comando | Parametri | Descrizione |
|---|---|---|
| `/jenniserpi` | `utenti` `etichetta?` | 🔕 Sordi permanenti (deafen). Supporta più utenti/gruppi. Si applica subito o al join |
| `/jenniserpi_off` | `utente/gruppo` oppure nessuno (→ menu) | Rimuove il deafen. Senza argomenti mostra menu gruppi attivi |

### Strumenti voce — Isolamento / Quarantena

| Comando | Parametri | Descrizione |
|---|---|---|
| `/isolamento` | `utenti` `nome_canale?` `etichetta?` | Sposta uno o più utenti in un canale quarantena dedicato e li blocca lì |
| `/isolamento_off` | `utente/gruppo` oppure nessuno (→ menu) | Libera gli utenti e li riporta nel canale originale. Elimina il canale quarantena se vuoto |

**Watchdog quarantena**: un task in background (ogni 60 s) riporta forzatamente gli utenti nel canale quarantena se tentano di spostarsi, e ricrea il canale se viene eliminato manualmente.

**Listener `on_voice_state_update`**: museruola e deafen vengono ri-applicati automaticamente se rimossi da altri moderatori durante una sessione attiva.

---

## 🎂 Compleanni

Il cog `birthdays.py` gestisce la registrazione e gli auguri automatici tramite il gruppo `/bday`.
I dati sono persistiti in `data/` tramite `core/birthday_store.py`.

### Comandi pubblici

| Comando | Parametri | Descrizione |
|---|---|---|
| `/bday set` | `giorno` `mese` (lista) `anno?` | Registra il proprio compleanno. L'anno è opzionale (mostra l'età negli auguri se presente) |
| `/bday remove` | — | Rimuove il proprio compleanno |
| `/bday check` | `utente?` | Mostra il compleanno di un utente (default: se stessi) |
| `/bday list` | — | Lista prossimi compleanni del server, ordinata per data, con embed paginato |

### Comandi admin (👑 Manage Guild)

| Comando | Parametri | Descrizione |
|---|---|---|
| `/bday adminset` | `utente` `giorno` `mese` `anno?` | Imposta il compleanno di un altro utente |
| `/bday adminremove` | `utente` | Rimuove il compleanno di un altro utente |
| `/bday channel` | `canale?` | Imposta il canale per gli auguri automatici. Senza canale disabilita gli auguri |
| `/bday test` | — | Simula un messaggio di auguri (anteprima ephemeral, usa i messaggi configurati) |
| `/bday tags` | — | Mostra i placeholder disponibili per i messaggi personalizzati |
| `/bday messages_set` | `messaggi` | Sostituisce la lista messaggi auguri (una riga = un messaggio) |
| `/bday messages_add` | `messaggio` | Aggiunge un messaggio alla lista |
| `/bday messages_remove` | `indice` | Rimuove un messaggio dalla lista per indice |
| `/bday messages_list` | — | Mostra tutti i messaggi configurati con indice |

### Placeholder messaggi auguri

| Placeholder | Valore |
|---|---|
| `{mention}` | Menzione cliccabile dell'utente |
| `{name}` | Username Discord |
| `{display_name}` | Nickname sul server |
| `{age}` / `{years}` | Età (solo se l'anno è stato registrato) |
| `{guild}` | Nome del server |

### Auguri automatici

Ogni giorno a mezzanotte UTC il bot controlla i compleanni del giorno e invia un messaggio plain text nel canale configurato. Il messaggio viene scelto casualmente dalla lista configurata per il server (o da un default se la lista è vuota). La lista compleanni nel canale viene aggiornata automaticamente dopo ogni auguri.

---

## 👋 Welcome / Goodbye

Il cog `welcome.py` gestisce messaggi di entrata/uscita e assegnazione ruolo automatica.
La configurazione è persistita per guild in `data/` tramite `core/welcome_store.py`.

### Standalone

| Comando | Descrizione |
|---|---|
| `/wg_tags` | 👑 Mostra i placeholder e la sintassi Markdown disponibili per welcome/goodbye |

### Placeholder

| Placeholder | Valore |
|---|---|
| `{mention}` | Menzione cliccabile |
| `{name}` | Username Discord |
| `{display_name}` | Nickname sul server |
| `{guild}` | Nome del server |
| `{count}` | Numero di membri attuali |

### Gruppo `/welcome` (👑 Manage Guild)

| Comando | Parametri | Descrizione |
|---|---|---|
| `/welcome channel` | `canale` | Imposta il canale di destinazione |
| `/welcome toggle` | — | Abilita/disabilita con menu a tendina (ON/OFF) |
| `/welcome set` | vedi sotto | Modifica title, description, footer, colore, thumbnail, immagine, author, fino a 4 field inline |
| `/welcome field remove` | `indice` | Rimuove un field dall'embed per numero |
| `/welcome field list` | — | Elenca i field configurati con indice |
| `/welcome reset` | — | Ripristina la configurazione ai valori predefiniti ed elimina le immagini locali |
| `/welcome preview` | — | Anteprima ephemeral del messaggio (con te stesso come "nuovo membro") |
| `/welcome status` | — | Mostra tutta la configurazione attuale in un embed riepilogativo |

### Gruppo `/goodbye` (👑 Manage Guild)

Stessi sotto-comandi di `/welcome` (`channel`, `toggle`, `set`, `field remove/list`, `reset`, `preview`, `status`).

### `/welcome set` e `/goodbye set` — parametri

| Parametro | Descrizione |
|---|---|
| `plain_text` | `True` = messaggio semplice; `False` = embed (default) |
| `title` | Titolo embed (`none` per rimuovere) |
| `description` | Testo principale (supporta placeholder) |
| `footer` | Testo footer (`none` per rimuovere) |
| `footer_icon_url` | URL icona footer |
| `footer_icon_upload` | Upload icona footer come attachment |
| `color` | Colore bordo in HEX es. `#FF0000` |
| `thumbnail_url` | URL thumbnail |
| `thumbnail_upload` | Upload thumbnail come attachment |
| `image_url` | URL immagine grande |
| `image_upload` | Upload immagine grande come attachment |
| `author_name` | Nome author (`none` per rimuovere) |
| `author_icon_url` | URL icona author |
| `author_icon_upload` | Upload icona author come attachment |
| `field1_name` / `field1_value` | Field 1 (nome + valore obbligatori insieme) |
| `field2_name` / `field2_value` | Field 2 |
| `field3_name` / `field3_value` | Field 3 |
| `field4_name` / `field4_value` | Field 4 |

**Immagini locali**: gli attachment vengono scaricati subito su disco in `data/welcome_images/<guild_id>_<event>_<slot>.<ext>` per evitare la scadenza degli URL Discord (~1–2h). Nel JSON viene salvato un sentinel `__local:<slot>__` al posto dell'URL.

### Gruppo `/autorole` (👑 Manage Guild)

| Comando | Parametri | Descrizione |
|---|---|---|
| `/autorole set` | `ruolo` | Imposta il ruolo da assegnare automaticamente a ogni nuovo membro al join |
| `/autorole remove` | — | Rimuove il ruolo automatico |
| `/autorole status` | — | Mostra il ruolo automatico attivo |

### Comportamento automatico

- **`on_member_join`**: assegna l'AutoRole (se configurato), poi invia il messaggio welcome nel canale impostato.
- **`on_member_remove`**: invia il messaggio goodbye nel canale impostato.
- Se `plain_text=True`, usa solo il campo `description` come testo semplice (con placeholder risolti).

---

## ❓ Help

| Comando | Parametri | Descrizione |
|---|---|---|
| `/help` | `categoria?` | Lista comandi raggruppata per categoria. Con categoria mostra solo i comandi di quel modulo |

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
| `/devaudio info` | Stato interno del player audio per il guild corrente |
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
| Immagini welcome locali | File su disco in `data/welcome_images/` |
| Cache query musicali | SQLite in `cache_db/` |
| AI client | Multi-provider con fallback (`core/ai_client.py`) |
| Ricerca web AI | Wikipedia Search API (it.wikipedia.org) |

### Flusso avvio (`main.py`)

1. Lettura configurazione da `.env` via `config.py`
2. Caricamento di tutti i cog in `cogs/`
3. Connessione a Discord e sync comandi slash
4. Loop eventi `discord.py`

### MusicPlayer

Ogni guild ha un'istanza `MusicPlayer` separata (gestita in `core/player.py`). Il player mantiene coda tracce, stato corrente (paused/playing/idle), modalità loop (`off` / `track` / `queue`), volume e flag autoplay. La risoluzione delle sorgenti avviene in `core/source_resolver.py` con cache SQLite.

### Stato AI in-memory

`core/ai_runtime.py` espone un singleton `_state` con:
- `conversation_memory`: `channel_id → deque` (max 20 messaggi)
- `rate_limit_map`: `user_id → timestamp` ultimo messaggio
- `channel_recent_messages`: buffer messaggi recenti per canale (context building)
- `mention_background_cache`: cache profili utenti menzionati (TTL 10 min)

Lo stato viene resettato al ricaricamento del cog AI (`cog_unload`).

### Logging

Ogni cog usa un logger dedicato (`pitonazz.<nome_cog>`) con output colorato via `core/log_colors.py`.
