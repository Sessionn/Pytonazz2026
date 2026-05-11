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
CACHE_ENABLED=true

# Path del file SQLite (relativo alla root del bot)
DB_PATH=data/database/cache.db

# Scadenza entry in giorni (default: 30)
CACHE_TTL_DAYS=30

# Numero massimo di entry (le piu' vecchie vengono rimosse automaticamente)
CACHE_MAX_ENTRIES=500
```

### 3. Riavvia il bot

All'avvio vedrai nel log:

```
[CACHE_DB] attiva  db='data/database/cache.db'  ttl=30d  max=500
```

Se la cache e' disabilitata:

```
[CACHE_DB] cache disabilitata (CACHE_ENABLED=false)
```

---

## Comandi dev (solo owner)

| Comando | Effetto |
|---|---|
| `/cache-status` | Mostra se la cache e' abilitata o meno. |
| `/cache-stats` | Entry totali, valide, alias, hit totali, dimensione DB, query top. |
| `/cache-prune` | Rimuove entry scadute o in eccesso (parametri: `max_entries`, `ttl_days`). |
| `/cache-invalidate` | Invalida una singola entry per query (per forzare un re-fetch). |
| `/cache-clear` | Svuota completamente il DB (richiede `CONFERMA` come argomento). |

> I comandi sono accessibili solo all'utente con `OWNER_ID` nel `.env`.

---

## Come funziona

### Flusso lookup

```
Utente: /play <query>
           │
           ▼
     normalize(query)
     → lowercase + hash SHA-256
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

### Tabelle DB

```sql
song_cache      -- entry principale per ogni brano unico
query_aliases   -- query alternative che puntano alla stessa entry
```

Le entry scadute (oltre `CACHE_TTL_DAYS`) vengono rimosse automaticamente ogni 5 minuti
tramite un thread in background, senza bisogno di un job separato.

---

## Setup su VM Ubuntu (consigliato)

```bash
# Nella cartella del bot
echo "CACHE_ENABLED=true" >> .env
echo "DB_PATH=data/database/cache.db" >> .env

# Installa dipendenza
source venv/bin/activate   # se usi venv
pip install aiosqlite

# Riavvia il bot (systemd)
sudo systemctl restart pitonazz

# Controlla il log di avvio
sudo journalctl -u pitonazz -n 30
```

Il file `cache.db` viene creato automaticamente nella directory `data/database/` al primo avvio
con la cache abilitata. Non e' necessario crearlo a mano.

> **Consiglio:** aggiungi `data/database/cache.db` al `.gitignore` se non lo e' gia',
> per evitare di committare il database.

---

## Backup e manutenzione

```bash
# Backup manuale
cp data/database/cache.db data/database/cache.db.bak

# Ispeziona il DB da terminale
sqlite3 data/database/cache.db "SELECT title, artist, hit_count FROM song_cache ORDER BY hit_count DESC LIMIT 20;"

# Svuota il DB via comando Discord
/cache-clear

# Oppure da terminale
sqlite3 data/database/cache.db "DELETE FROM query_aliases; DELETE FROM song_cache;"
```

---

## Variabili ENV — Riferimento completo

| Variabile | Tipo | Default | Descrizione |
|---|---|---|---|
| `CACHE_ENABLED` | `true`/`false` | `false` | Abilita/disabilita il sistema |
| `DB_PATH` | path | `data/database/cache.db` | Path del file SQLite |
| `CACHE_TTL_DAYS` | int | `30` | Giorni prima che un'entry venga considerata scaduta |
| `CACHE_MAX_ENTRIES` | int | `500` | Limite massimo entry nel DB |

---

## Troubleshooting

**Il DB non viene creato**  
Verifica che il percorso in `DB_PATH` sia scrivibile dal processo del bot:
```bash
ls -la $(dirname $DB_PATH)
```

**Log: `[CACHE_DB] cache disabilitata`**  
Il bot ha trovato `CACHE_ENABLED=false` oppure la variabile non e' impostata. Aggiornala a `true` e riavvia.

**La cache e' attiva ma i tempi non migliorano**  
Normale al primo avvio: il DB e' vuoto. I benefici si vedono a partire dalla seconda richiesta dello stesso brano. Usa `/cache-stats` per monitorare gli hit.
