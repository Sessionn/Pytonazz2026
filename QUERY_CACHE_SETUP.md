# 🗄️ Specifica Tecnica del Sottosistema Query Cache Database

Il modulo `cache_db` sovrintende alla persistenza e all'ottimizzazione delle richieste di riproduzione musicale all'interno di **Pitonazz**. Questo documento descrive nel dettaglio l'architettura relazionale, l'algoritmo di corrispondenza delle stringhe ed i meccanismi di protezione del database implementati in SQLite.

---

## 📍 Indice
1. [Infrastruttura di Concorrenza e Thread-Safety](#-infrastruttura-di-concorrenza-e-thread-safety)
2. [Dizionario dei Dati e Schema Relazionale](#-dizionario-dei-dati-e-schema-relazionale)
3. [Analisi Dettagliata del Lookup a 5 Step](#-analisi-dettagliata-del-lookup-a-5-step)
4. [Ottimizzazioni I/O delle Performance (Pragma)](#-ottimizzazioni-io-delle-performance-pragma)
5. [Routine di Sfratamento e Gestione dello Spazio (Pruning)](#-routine-di-sfratamento-e-gestione-dello-spazio-pruning)

---

## 🛠️ Infrastruttura di Concorrenza e Thread-Safety

Poiché `discord.py` opera all'interno di un ciclo di eventi asincrono (`asyncio`), e le librerie standard di SQLite in Python soffrono di limitazioni intrinseche nel passaggio di connessioni tra thread diversi, l'architettura di `cache_db/engine.py` è stata progettata seguendo il pattern del **Thread-Isolation Lock**:

1. **Lock Globale del Thread:** Tutte le operazioni di scrittura (`INSERT`, `UPDATE`, `DELETE`) sono regolate da un'istanza di `threading.Lock()`. Questo impedisce che due gilde differenti tentino di modificare simultaneamente lo stesso settore del database sul disco, scongiurando l'errore `sqlite3.OperationalError: database is locked`.
2. **Archiviazione Locale del Thread:** Il bot istanzia le connessioni al database sfruttando l'oggetto `threading.local()`. Ciascun thread operativo mantiene una propria connessione univoca e isolata. Le connessioni vengono inizializzate impostando il flag `check_same_thread=False` per permettere l'interscambio controllato dei cursori all'interno dei task asincroni del bot.

---

## 📊 Dizionario dei Dati e Schema Relazionale

Il database (`cache.db`) è composto da due tabelle interconnesse da vincoli di integrità referenziale. Di seguito viene riportata l'analisi meticolosa dei campi e degli indici.

### 1. Tabella `song_cache`
Contiene i metadati reali e definitivi delle tracce musicali risolte e riproducibili.

| Campo | Tipo SQL | Vincoli / Default | Descrizione Tecnica |
| :--- | :--- | :--- | :--- |
| `id` | `INTEGER` | `PRIMARY KEY AUTOINCREMENT` | Identificatore univoco progressivo della traccia cache. |
| `canonical_key` | `TEXT` | `NOT NULL` | Chiave testuale generata ordinando alfabeticamente i token estratti dalla stringa di ricerca originaria, interamente normalizzata. |
| `variant_tag` | `TEXT` | `NOT NULL DEFAULT ''` | Identifica l'applicazione di filtri o manipolazioni acustiche stabili (es: `nightcore`, `slowed`). |
| `webpage_url` | `TEXT` | `NOT NULL` | L'URL assoluto della sorgente multimediale definitiva di riproduzione (tipicamente il link video standard di YouTube). |
| `title` | `TEXT` | `NOT NULL DEFAULT ''` | Titolo pulito della traccia estratto dai metadati ufficiali dell'estrattore. |
| `artist` | `TEXT` | `NOT NULL DEFAULT ''` | Nome dell'autore, interprete o creatore del contenuto multimediale. |
| `duration` | `INTEGER` | `NOT NULL DEFAULT 0` | Durata complessiva del file audio espressa rigorosamente in secondi. |
| `thumbnail` | `TEXT` | `NOT NULL DEFAULT ''` | URL HTTP/HTTPS diretto alla copertina o miniatura del brano. |
| `source` | `TEXT` | `NOT NULL DEFAULT 'youtube'`| Stringa identificativa del provider di origine (`youtube`, `spotify`, `soundcloud`). |
| `spotify_url` | `TEXT` | `NULL` | Mappatura dell'URL Spotify speculare del brano (se risolto tramite l'algoritmo di enrichment). |
| `created_at` | `TEXT` | `DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ'))` | Timestamp ISO 8601 di inserimento della riga. |
| `last_used` | `TEXT` | `DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ'))` | Timestamp ISO 8601 dell'ultima volta che il brano è stato richiamato da una query. |
| `hit_count` | `INTEGER` | `NOT NULL DEFAULT 1` | Contatore cumulativo degli utilizzi della traccia all'interno dell'ecosistema del bot. |
| `is_valid` | `INTEGER` | `NOT NULL DEFAULT 1` | Flag logico booleano (`1`=Attivo, `0`=Scaduto/In attesa di cancellazione fisica). |

* **Vincolo di Unicità Composita:** `UNIQUE(canonical_key, variant_tag)`. Impedisce la duplicazione di una medesima traccia canonica per la stessa variante audio.

### 2. Tabella `query_alias`
Mappa le query alternative digitate dagli utenti riconducendole a record canonici esistenti.

| Campo | Tipo SQL | Vincoli / Default | Descrizione Tecnica |
| :--- | :--- | :--- | :--- |
| `id` | `INTEGER` | `PRIMARY KEY AUTOINCREMENT` | Identificatore univoco progressivo dell'alias. |
| `alias_key` | `TEXT` | `NOT NULL UNIQUE` | Stringa di ricerca testuale normalizzata utilizzata dall'utente (es: typo o abbreviazione). |
| `canonical_key` | `TEXT` | `NOT NULL` | Riferimento testuale che punta alla colonna `canonical_key` della tabella `song_cache`. |
| `variant_tag` | `TEXT` | `NOT NULL DEFAULT ''` | Tag di variazione audio associato a questo specifico alias. |
| `created_at` | `TEXT` | `DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ'))` | Timestamp di creazione dell'alias. |

---

### 🔥 Albero degli Indici B-Tree Strutturati
Per minimizzare i tempi di scansione sequenziale (`O(n)`), sono stati implementati quattro indici selettivi:
1. `idx_sc_canonical`: Ottimizza le letture basate sulla combinazione di chiave canonica e variante nello Step 1 del lookup (`CREATE INDEX idx_sc_canonical ON song_cache(canonical_key, variant_tag);`).
2. `idx_sc_spotify`: Indice parziale specializzato per i link Spotify. Esclude i record vuoti riducendo le dimensioni dell'indice sul disco (`CREATE INDEX idx_sc_spotify ON song_cache(spotify_url) WHERE spotify_url IS NOT NULL AND spotify_url != '';`).
3. `idx_sc_webpage`: Indicizza gli URL diretti per velocizzare i controlli di Step 4 (`CREATE INDEX idx_sc_webpage ON song_cache(webpage_url);`).
4. `idx_sc_metrics`: Indice composito orientato all'ordinamento per le operazioni di pruning e diagnostica dei log (`CREATE INDEX idx_sc_metrics ON song_cache(last_used, hit_count DESC);`).

---

## ⚡ Analisi Dettagliata del Lookup a 5 Step

Quando un comando musicale riceve un input stringa, quest'ultimo viene normalizzato: rimozione dei caratteri speciali, conversione in lowercase, rimozione di *noise words* (articoli, preposizioni) e ordinamento dei token residui in ordine alfabetico. Successivamente viene avviata la pipeline di ricerca sequenziale a costo controllato:

```text
[ Input Stringa ] ──> Normalizzazione dei Token ──> Estrazione Variant Tag
│
▼
┌────────────────────────────────────────────────────────────────────────┐
│ STEP 1: MATCH DIRETTO CANONICO (Fascia di Costo: ~0.1ms)             │
│ Query: SELECT * FROM song_cache WHERE canonical_key = ? AND variant = ?│
└──────────────────────────────┬─────────────────────────────────────────┘
│ MISS
▼
┌────────────────────────────────────────────────────────────────────────┐
│ STEP 2: RICERCA NEGLI ALIAS DI QUERY (Fascia di Costo: ~0.3ms)       │
│ Query: SELECT canonical_key FROM query_alias WHERE alias_key = ?     │
└──────────────────────────────┬─────────────────────────────────────────┘
│ MISS
▼
┌────────────────────────────────────────────────────────────────────────┐
│ STEP 3: MATCH PARZIALE INDEXED URL SPOTIFY (Fascia di Costo: ~0.2ms) │
│ Query: SELECT * FROM song_cache WHERE spotify_url = ?                │
└──────────────────────────────┬─────────────────────────────────────────┘
│ MISS
▼
┌────────────────────────────────────────────────────────────────────────┐
│ STEP 4: MATCH DIRETTO URL SORGENTE WEBPAGE (Fascia di Costo: ~0.2ms) │
│ Query: SELECT * FROM song_cache WHERE webpage_url = ?                │
└──────────────────────────────┬─────────────────────────────────────────┘
│ MISS
▼
┌────────────────────────────────────────────────────────────────────────┐
│ STEP 5: CORRISPONDENZA SFUMATA "JACCARD FUZZY SCAN"                 │
│ Estrarre TOP-300 record per hit_count. Computazione algoritmica:     │
│ Score = (0.65 * Jaccard_Distance) + (0.35 * Levenshtein_Ratio)       │
│ Soglia di Accettazione Sottosistema: Score >= 0.82                   │
└──────────────────────────────┬─────────────────────────────────────────┘
│ MISS (Sotto la soglia)
▼
[ ESEGUI NETWORK FETCH VIA YT-DLP ]
│
▼
Store() dei Risultati e Scrittura DB
```

### Regola di Promozione degli Alias nello Step 5
Se una ricerca produce un *MISS* nei primi 4 step ma viene risolta positivamente dallo Step 5 (Fuzzy Scan), il bot **NON** inserisce immediatamente la query d'origine nella tabella degli alias. Questo previene la corruzione del DB causata da errori casuali di digitazione degli utenti. L'alias viene scritto stabilmente in `query_alias` solo nel momento in cui la traccia viene avviata con successo nel player vocale, confermando la bontà della selezione.

---

## 📈 Ottimizzazioni I/O delle Performance (Pragma)

All'atto della prima inizializzazione delle connessioni, il modulo forza l'esecuzione di una serie di direttive PRAGMA volte a superare i colli di bottiglia del file system:

```sql
PRAGMA journal_mode = WAL;
```

Write-Ahead Logging: Sostituisce il meccanismo tradizionale di rollback journal. I processi di lettura non vengono bloccati dalle operazioni di scrittura concorrenti. Le letture avvengono in parallelo mentre le scritture vengono accumulate in un file ausiliario `.wal`, riducendo drasticamente le chiamate di sistema alla CPU per il lock del file.

```sql
PRAGMA synchronous = NORMAL;
```

Sincronizzazione Ottimizzata: In modalità NORMAL, il motore SQLite esegue il flush dei dati sul disco rigido nei momenti critici ma non si arresta ad aspettare il feedback fisico del controller del disco per ogni singola transazione non critica. Questo garantisce un incremento delle performance di scrittura fino a 4 volte superiore, mantenendo l'integrità del database intatta in caso di crash dell'applicazione bot.

```sql
PRAGMA cache_size = -4000;
```

Allocazione della Cache di Memoria: Il valore negativo alloca un quantitativo fisso espresso in Kibibyte anziché in pagine. In questo scenario, vengono riservati esattamente 4 MB di memoria RAM ad uso esclusivo dei fogli B-Tree degli indici di SQLite, azzerando le letture sul disco meccanico o SSD per le query ripetitive.

---

## 🧹 Routine di Sfratamento e Gestione dello Spazio (Pruning)

Per preservare l'integrità dello spazio disco del server ed evitare l'accumulo di record obsoleti o inutilizzati, l'engine implementa due logiche automatiche di pulizia e sfratamento:

### 1. Pruning LRU (Least Recently Used) ad Alta Densità
Attivato internamente dal metodo `store()` ogni volta che il numero di righe inserite all'interno della tabella `song_cache` supera la costante numerica `CACHE_MAX_ENTRIES` configurata nel file `.env`.

**Meccanismo:** Viene istanziato un thread demone parallelo che seleziona ed elimina il 10% dei record complessivi aventi il valore di `last_used` più datato nel tempo e un basso tasso di `hit_count`. Grazie ai vincoli di integrità relazionale ed alle regole di eliminazione a cascata, la rimozione di un record da `song_cache` epura in automatico tutti i sinonimi orfani associati all'interno della tabella `query_alias`.

### 2. Invalidazione Temporale TTL (Time-To-Live)
Eseguibile automaticamente all'avvio del bot o invocabile manualmente tramite i comandi sviluppatore della cache (`/dev_cache prune`).

**Meccanismo:** Il motore esegue una scansione calcolando la differenza di giorni tra il timestamp corrente e la colonna `last_used`:

```sql
UPDATE song_cache SET is_valid = 0 WHERE JULIANDAY('now') - JULIANDAY(last_used) > ?;
```

I record che superano il valore della variabile `CACHE_TTL_DAYS` vengono marcati come non validi (`is_valid = 0`), escludendoli istantaneamente dai flussi di lookup degli utenti. Una routine notturna provvede alla successiva cancellazione fisica (`VACUUM`) per ricompattare le dimensioni del file sul disco.
