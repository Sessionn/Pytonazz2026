# 🗄️ Architettura del Sottosistema Query Cache Database

Il modulo `cache_db` implementa un'architettura proprietaria di caching persistente basata su **SQLite**, progettata specificamente per azzerare i tempi di latenza legati alle API di risoluzione musicale ed evitare il throttling/ban degli indirizzi IP da parte dei provider multimediali (es: YouTube rate limiting).

---

## 🛠️ Architettura e Thread-Safety

Il motore è incapsulato all'interno della classe `QueryCache` (`cache_db/engine.py`). 
* **Zero Dipendenze Esterne:** Utilizza esclusivamente la libreria standard `sqlite3` combinata con operazioni non bloccanti basate sui thread.
* **Thread-Isolation:** Utilizza un meccanismo basato su `threading.Lock()` globale integrato a istanze di connessione locali isolate per singolo thread (`threading.local()`), configurando le opzioni SQLite `check_same_thread=False`.
* **Ottimizzazione I/O:** All'apertura della connessione vengono abilitati i pragma ad alte prestazioni:
  * `PRAGMA journal_mode=WAL` (Write-Ahead Logging per letture e scritture concorrenti fulminee).
  * `PRAGMA synchronous=NORMAL` (Ottimizzazione del sync su disco senza rischio di corruzione dei dati).
  * `PRAGMA foreign_keys=ON` (Integrità referenziale).

---

## 📊 Schema Relazionale del Database

Il database è strutturato su due tabelle principali ottimizzate tramite indici B-Tree speculativi:

```sql
CREATE TABLE IF NOT EXISTS song_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_key TEXT NOT NULL,         -- Chiave normalizzata e ordinata dei token
    variant_tag TEXT NOT NULL DEFAULT '', -- Tag di variazione (es: nightcore, spedup)
    webpage_url TEXT NOT NULL,           -- URL definitivo di riproduzione (YouTube)
    title TEXT NOT NULL DEFAULT '',       -- Titolo pulito della traccia
    artist TEXT NOT NULL DEFAULT '',      -- Artista o Creatore del contenuto
    duration INTEGER NOT NULL DEFAULT 0,  -- Durata espressa in secondi
    thumbnail TEXT NOT NULL DEFAULT '',   -- URL della copertina
    source TEXT NOT NULL DEFAULT 'youtube',
    spotify_url TEXT,                     -- Traccia speculare su Spotify (se integrata)
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    last_used TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    hit_count INTEGER NOT NULL DEFAULT 1, -- Contatore di utilizzo della traccia
    is_valid INTEGER NOT NULL DEFAULT 1,  -- Flag logico di validità (0 = Scaduto/Soft Delete)
    UNIQUE(canonical_key, variant_tag)
);

CREATE TABLE IF NOT EXISTS query_alias (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alias_key TEXT NOT NULL UNIQUE,       -- Query normalizzata alternativa
    canonical_key TEXT NOT NULL,          -- Riferimento alla chiave primaria di song_cache
    variant_tag TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
```

### Indici Ottimizzati:

* `idx_sc_canonical` su `song_cache(canonical_key, variant_tag)` -> Velocizza i primi step di lookup.
* `idx_sc_spotify` su `song_cache(spotify_url)` filtrato `WHERE spotify_url != ''`.
* `idx_sc_webpage` su `song_cache(webpage_url)` -> Risoluzione diretta degli URL.
* `idx_sc_last_used` e `idx_sc_hit_count` DESC -> Utilizzati per le routine di manutenzione e statistiche.

---

## ⚡ L'Algoritmo di Lookup a 5 Step

Quando un utente inserisce una stringa di ricerca in `/play` o `/search`, la stringa subisce un processo di **Normalizzazione NFC**, rimozione della punteggiatura e delle parole di rumore (*Noise Words* come articoli e preposizioni in italiano e inglese), isolando i token in ordine alfabetico e intercettando eventuali keyword di variazione (`speed up`, `nightcore`, `slowed`, `remix`, `live`).

Il motore esegue quindi una ricerca sequenziale basata su 5 livelli di costo computazionale crescente:

```text
[ Query Utente ]
       │
       ▼
 ┌───────────┐      HIT      ┌───────────────────────┐
 │  Step 1   ├──────────────>│ Exact Match (O(log n))│ ──> [ Restituisce Traccia ]
 └─────┬─────┘               └───────────────────────┘
       │ MISS
       ▼
 ┌───────────┐      HIT      ┌───────────────────────┐
 │  Step 2   ├──────────────>│   Alias Cache Match   │ ──> [ Restituisce Traccia ]
 └─────┬─────┘               └───────────────────────┘
       │ MISS
       ▼
 ┌───────────┐      HIT      ┌───────────────────────┐
 │  Step 3   ├──────────────>│   Spotify URL Match   │ ──> [ Restituisce Traccia ]
 └─────┬─────┘               └───────────────────────┘
       │ MISS
       ▼
 ┌───────────┐      HIT      ┌───────────────────────┐
 │  Step 4   ├──────────────>│  Webpage URL Match    │ ──> [ Restituisce Traccia ]
 └─────┬─────┘               └───────────────────────┘
       │ MISS
       ▼
 ┌───────────┐    Score >=   ┌───────────────────────┐
 │  Step 5   ├──────────────>│ Jaccard Fuzzy Scan    │ ──> [ Restituisce Traccia come Candidato ]
 └─────┬─────┘      0.82     └───────────────────────┘
       │ MISS
       ▼
[ Esegui Network Fetch (yt-dlp) ] ──> [ Memorizza via store() ]
```

1. **Step 1: Exact Hit (`song_cache`):** Cerca una corrispondenza esatta dell'indice combinato delle chiavi normalizzate. Tempo di risposta stimato: `~0.1 ms`.
2. **Step 2: Alias Hit (`query_alias`):** Controlla se la query corrisponde a un sinonimo precedentemente associato o promosso.
3. **Step 3: Spotify URL Hit:** Se l'input contiene un link Spotify, esegue un match istantaneo sull'indice della colonna `spotify_url`.
4. **Step 4: Webpage URL Hit:** Se l'input è un link di riproduzione diretto (YouTube), esegue un match sulla colonna `webpage_url`.
5. **Step 5: Fuzzy Scan (Top-300):** Estrae le 300 tracce con il più alto indice di gradimento (`hit_count`) ed esegue un calcolo di similarità testuale combinando l'indice di **Jaccard** con una ponderazione di stringa pura (peso del 35%). Se lo score supera la **soglia di tolleranza di 0.82**, la traccia viene restituita come candidato.

> ⚠️ **Policy di Promozione degli Alias:** Il meccanismo di Fuzzy Match (Step 5) **NON** memorizza l'alias in modo automatico per prevenire l'inquinamento del database. L'alias viene promosso e scritto in tabella `query_alias` solo in seguito, quando il metodo `store()` conferma esplicitamente la correttezza della traccia riprodotta.

---

## 🧹 Routine Automatizzate di Manutenzione e Pruning

Il database gestisce in autonomia la propria occupazione di memoria per evitare saturazione disco su server VPS:

* **Pruning LRU (Least Recently Used):** Ogni volta che viene inserita una nuova traccia tramite `store()`, il bot verifica il volume di righe. Se le righe superano la costante `CACHE_MAX_ENTRIES` (configurabile da `.env`), viene istanziato un **Thread Demone in background** che elimina le vecchie entry ordinate per la data `last_used` più remota, rimuovendo a cascata gli alias orfani.
* **Pruning Stale (Invalidazione TTL):** Eseguibile anche tramite i comandi sviluppatore, invalida in modalità soft (`is_valid = 0`) tutte le tracce la cui data di ultimo utilizzo supera il tempo massimo stabilito in `CACHE_TTL_DAYS` (Default: 30 giorni).
