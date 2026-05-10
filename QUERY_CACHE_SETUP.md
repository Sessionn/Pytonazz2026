# Query Cache — Guida Setup

Il sistema di cache salva i risultati delle ricerche musicali in un database SQLite locale.  
Alle query successive con la stessa canzone (o varianti simili), il bot bypassa yt-dlp e parte direttamente dal link salvato, riducendo i tempi di risoluzione **da ~3-5 secondi a meno di 1 secondo**.

---

## Requisiti

- Python 3.10+
- `aiosqlite>=0.20.0` (gia' incluso in `requirements.txt`)
- Nessun servizio esterno: il DB e' un semplice file `.db` sulla stessa macchina del bot

---

## Attivazione rapida

### 1. Installa la dipendenza

```bash
pip install -U aiosqlite
# oppure, se usi requirements.txt
pip install -r requirements.txt
```

### 2. Aggiungi le variabili al `.env`

```env
# Abilita il sistema
QUERY_CACHE_ENABLED=true

# Path del file SQLite (relativo alla root del bot)
QUERY_CACHE_DB_PATH=./cache.db

# Scadenza entry in giorni (default: 30)
QUERY_CACHE_TTL_DAYS=30

# Numero massimo di entry (le piu' vecchie vengono rimosse automaticamente)
QUERY_CACHE_MAX_ENTRIES=5000
```

### 3. Riavvia il bot

All'avvio vedrai nel log:

```
[CACHE] ✅  attiva  db=./cache.db  ttl=30d  max=5000  entries=0  hit_totali=0
```

Se la cache e' disabilitata:

```
[CACHE] ⏸️  disabilitata  (imposta QUERY_CACHE_ENABLED=true per attivarla)
```

---

## Toggle a runtime (senza riavvio)

I comandi `/cache` sono disponibili solo per il proprietario del bot (`OWNER_ID` nel `.env`).

| Comando | Effetto |
|---|---|
| `/cache on` | Abilita la cache. Richiede che `QUERY_CACHE_DB_PATH` sia impostato. |
| `/cache off` | Disabilita la cache. Le query tornano al fetch normale istantaneamente. Il DB non viene toccato. |
| `/cache status` | Mostra stato attuale + tutte le variabili ENV lette. |
| `/cache stats` | Entry totali, alias, hit totali, top 10 brani piu' richiesti. |
| `/cache clear` | Svuota il DB (richiede conferma via bottone, timeout 30s). |

> **Nota:** `/cache on` a runtime richiede che le variabili ENV siano gia' presenti nel `.env` al momento dell'avvio del bot. Il toggle cambia solo il flag in memoria — non modifica il file `.env`.

---

## Come funziona

### Flusso lookup

```
Utente: /play <query>
           │
           ▼
     normalize(query)
     → lowercase, rimozione stopword/noise, hash SHA-256
           │
           ▼
     lookup in DB
     (song_cache + query_aliases)
           │
     ┌─────┴─────┐
     HIT              MISS
      │                │
      ▼                ▼
  fetch solo       resolve normale
  stream_url       (yt-dlp + Spotify)
  (< 1ms DB)            │
      │                ▼
      │           store() in DB
      │                │
      └─────┬─────┘
              │
              ▼
           play()
```

### Normalizzazione query

La funzione `normalize()` in `cache_db/engine.py` rimuove:
- Differenze di maiuscolo/minuscolo
- Punteggiatura
- Stopword comuni (`the`, `a`, `an`, `official`, `video`, `lyrics`, `audio`, `hd`, `4k`, ecc.)
- Spazi multipli

Esempio:
```
"Bohemian Rhapsody - Official Video (Remastered 4K)"
  --> "bohemian rhapsody remastered"
  --> hash: a3f7c2...
```

Cio' significa che query leggermente diverse che puntano allo stesso brano trovano lo stesso risultato in cache, senza fare un fetch separato.

### Tabelle DB

```sql
song_cache      -- entry principale per ogni brano unico
query_aliases   -- query alternative che puntano alla stessa entry
```

Le entry scadute (oltre `QUERY_CACHE_TTL_DAYS`) vengono rimosse automaticamente al momento del lookup, senza bisogno di un job separato.

---

## Setup su VM Ubuntu (consigliato)

```bash
# Nella cartella del bot
echo "QUERY_CACHE_ENABLED=true" >> .env
echo "QUERY_CACHE_DB_PATH=./cache.db" >> .env

# Installa dipendenza
source venv/bin/activate   # se usi venv
pip install aiosqlite

# Riavvia il bot (systemd)
sudo systemctl restart pitonazz

# Controlla il log di avvio
sudo journalctl -u pitonazz -n 30
```

Il file `cache.db` viene creato automaticamente nella root del bot al primo avvio con la cache abilitata. Non e' necessario crearlo a mano.

> **Consiglio:** aggiungi `cache.db` al `.gitignore` se non lo e' gia', per evitare di committare il database.

---

## Backup e manutenzione

```bash
# Backup manuale
cp cache.db cache.db.bak

# Ispeziona il DB da terminale
sqlite3 cache.db "SELECT title, artist, hit_count FROM song_cache ORDER BY hit_count DESC LIMIT 20;"

# Svuota il DB via comando Discord
/cache clear

# Oppure da terminale
sqlite3 cache.db "DELETE FROM query_aliases; DELETE FROM song_cache;"
```

---

## Variabili ENV — Riferimento completo

| Variabile | Tipo | Default | Descrizione |
|---|---|---|---|
| `QUERY_CACHE_ENABLED` | `true`/`false` | `false` | Abilita/disabilita il sistema |
| `QUERY_CACHE_DB_PATH` | path | `./cache.db` | Path del file SQLite |
| `QUERY_CACHE_TTL_DAYS` | int | `30` | Giorni prima che un'entry venga considerata scaduta |
| `QUERY_CACHE_MAX_ENTRIES` | int | `5000` | Limite massimo entry nel DB |

---

## Troubleshooting

**Il DB non viene creato**  
Verifica che il percorso in `QUERY_CACHE_DB_PATH` sia scrivibile dal processo del bot:
```bash
ls -la $(dirname $QUERY_CACHE_DB_PATH)
```

**Log: `[CACHE] ⚠️ abilitata ma DB non raggiungibile`**  
Il bot ha trovato `QUERY_CACHE_ENABLED=true` ma non riesce ad aprire il file. Controlla:
1. Il percorso e' corretto e relativo alla root del bot
2. Il processo ha permessi di scrittura nella directory
3. `aiosqlite` e' installato (`pip show aiosqlite`)

**La cache e' attiva ma i tempi non migliorano**  
Normale al primo avvio: il DB e' vuoto. I benefici si vedono a partire dalla seconda richiesta dello stesso brano. Usa `/cache stats` per monitorare gli hit.

**`/cache on` risponde con errore ENV**  
Il toggle a runtime richiede che `QUERY_CACHE_DB_PATH` sia gia' nel `.env` al momento dell'avvio. Aggiungilo e riavvia il bot, poi `/cache on` funzionera'.
