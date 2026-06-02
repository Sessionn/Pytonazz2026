# Cache DB Review - 2026-06

## Stato attuale

Il progetto contiene **due implementazioni concorrenti** del cache DB:

- `core/cache_db.py`
- `cache_db/engine.py`

Il resolver reale usa oggi `core/cache_db.py` tramite l'adapter in `core/source_resolver/__init__.py`, mentre `cache_db/engine.py` contiene una seconda idea di schema e di matching non allineata con quella in produzione.

Questo e' il primo problema da risolvere: finche' esistono due cache con policy diverse, il sistema resta difficile da ragionare, testare e migrare.

## Debolezze concrete dell'implementazione attiva

### 1. Identita' della traccia troppo implicita

In `core/cache_db.py` la riga primaria di `song_cache` rappresenta insieme:

- query canonica
- risultato risolto
- sorgente web
- eventuale mapping Spotify

Questo funziona per casi semplici, ma miscela concetti distinti:

- identita' logica del brano
- osservazione della query utente
- risoluzione tecnica verso una sorgente riproducibile

Effetto collaterale: il sistema deduplica con euristiche (`webpage_url`, `title+artist`) invece di avere un'entita' stabile da referenziare.

### 2. Alias troppo poveri

`query_aliases` salva:

- `query_hash`
- `query_raw`
- `alias_type`
- `cache_id`

Mancano campi che servirebbero per una cache professionale:

- `normalized_query`
- `confidence`
- `resolution_method`
- `created_at` / `last_seen_at`
- `hit_count`
- `promoted_by`
- `is_active`

Quindi oggi non e' possibile distinguere bene:

- alias esplicito confermato
- alias derivato da stessa `webpage_url`
- alias Spotify
- alias promosso dopo dedupe
- alias potenzialmente sospetto

### 3. Invalidazione debole

La cache invalida principalmente per:

- `query_hash`
- `webpage_url`
- TTL

Manca una storia di risoluzione. Se una stessa query punta oggi a una risorsa errata o rimossa, il sistema non conserva il contesto necessario per capire:

- quale match era stato fatto
- con quale livello di affidabilita'
- da quale algoritmo o percorso

### 4. Dedupe tardivo e correttivo

La funzione `dedupe_canonical()` e' utile, ma segnala che il modello dati non previene abbastanza bene i duplicati in fase di scrittura. Un sistema piu' robusto dovrebbe rendere il dedupe un caso eccezionale, non una manutenzione ordinaria.

## Casi problematici da considerare

### Resolve errato

- query volutamente rumorosa: `dark horse katy perry pizza music`
- titolo YouTube con parole spazzatura
- canzone corretta ma versione sbagliata: `live`, `remix`, `sped up`, `slowed`
- query con artista implicito o sbagliato

### Associazione errata chiave/alias

- due brani con titolo uguale e artisti diversi
- query abbreviata che collide con piu' brani
- link Spotify che punta a un brano, ma il risultato YT memorizzato e' stato un match solo "plausibile"

### Auto-apprendimento non controllato

Se il sistema imparasse alias automaticamente da match fuzzy o enrichment borderline, rischierebbe di consolidare errori silenziosi. Su un bot musicale questa e' la failure mode piu' pericolosa: pochi falsi positivi persistenti degradano tutta la UX.

## Direzione consigliata

### Non introdurre auto-apprendimento pieno

Per questa codebase consiglio:

- **no auto-learning automatico sui fuzzy match**
- **no promozione automatica di alias da enrichment Spotify borderline**
- **si' a segnali osservabili e auditabili**

Meglio un sistema che apprende solo da conferme forti:

- stesso `webpage_url`
- stesso `spotify_url`
- conferma applicativa esplicita
- hit ripetuti coerenti nel tempo

## Schema proposto

### 1. `track_entity`

Entita' logica del brano.

Campi suggeriti:

- `id` INTEGER PK
- `canonical_title` TEXT NOT NULL
- `canonical_artist` TEXT NOT NULL DEFAULT ''
- `normalized_title_artist` TEXT NOT NULL UNIQUE
- `preferred_variant` TEXT NOT NULL DEFAULT ''
- `created_at` INTEGER NOT NULL
- `updated_at` INTEGER NOT NULL
- `confidence_state` TEXT NOT NULL DEFAULT 'confirmed'
- `is_active` INTEGER NOT NULL DEFAULT 1

### 2. `track_source`

Risorse concrete riproducibili o collegate a una `track_entity`.

Campi suggeriti:

- `id` INTEGER PK
- `track_id` INTEGER NOT NULL REFERENCES `track_entity(id)` ON DELETE CASCADE
- `source_type` TEXT NOT NULL
- `webpage_url` TEXT NOT NULL DEFAULT ''
- `streamable_url` TEXT NOT NULL DEFAULT ''
- `spotify_url` TEXT NOT NULL DEFAULT ''
- `duration` INTEGER NOT NULL DEFAULT 0
- `thumbnail` TEXT NOT NULL DEFAULT ''
- `source_confidence` REAL NOT NULL DEFAULT 1.0
- `is_valid` INTEGER NOT NULL DEFAULT 1
- `last_verified_at` INTEGER NOT NULL DEFAULT 0
- `created_at` INTEGER NOT NULL
- `updated_at` INTEGER NOT NULL

Vincoli suggeriti:

- indice unico parziale su `spotify_url` quando non vuoto
- indice unico parziale su `webpage_url` quando non vuoto
- indice su `(track_id, is_valid)`

### 3. `query_observation`

Storico professionale delle query viste dal sistema.

Campi suggeriti:

- `id` INTEGER PK
- `query_raw` TEXT NOT NULL
- `query_norm` TEXT NOT NULL
- `query_hash` TEXT NOT NULL UNIQUE
- `track_id` INTEGER REFERENCES `track_entity(id)` ON DELETE SET NULL
- `source_id` INTEGER REFERENCES `track_source(id)` ON DELETE SET NULL
- `match_method` TEXT NOT NULL
- `match_confidence` REAL NOT NULL DEFAULT 0
- `alias_type` TEXT NOT NULL DEFAULT 'text'
- `hit_count` INTEGER NOT NULL DEFAULT 1
- `first_seen_at` INTEGER NOT NULL
- `last_seen_at` INTEGER NOT NULL
- `is_confirmed` INTEGER NOT NULL DEFAULT 0
- `is_active` INTEGER NOT NULL DEFAULT 1

`match_method` dovrebbe distinguere almeno:

- `exact_text`
- `same_webpage`
- `spotify_url`
- `manual_alias`
- `dedupe`
- `fuzzy_candidate`

### 4. `resolution_event` opzionale ma utile

Tabella append-only per audit tecnico.

Campi:

- `id`
- `query_hash`
- `track_id`
- `source_id`
- `resolver_stage`
- `score_payload_json`
- `created_at`

Serve se vuoi analizzare in futuro i falsi positivi senza introdurre machine learning.

## Vantaggi del redesign

- separa identita' logica, sorgenti e query osservate
- rende gli alias ispezionabili e classificabili
- consente pruning per tabella e non solo per record misti
- permette di trattare Spotify come relazione tra entita', non come semplice colonna accessoria
- prepara il terreno per euristiche migliori senza dover "imparare" automaticamente

## Strategia pratica di migrazione

1. Scegliere una sola implementazione e deprecare l'altra.
2. Introdurre il nuovo schema con migrazione versionata (`PRAGMA user_version`).
3. Migrare ogni riga di `song_cache` in:
   - una `track_entity`
   - una `track_source`
   - una `query_observation`
4. Migrare `query_aliases` in `query_observation` con `alias_type` e `is_confirmed=1`.
5. Spostare ogni logica di lookup su:
   - exact query
   - spotify url
   - same webpage
   - fuzzy solo come candidate stage, mai come apprendimento automatico

## Spotify enrichment

Senza auto-apprendimento, la direzione corretta e':

- usare ranking token-aware, non solo character similarity
- penalizzare versioni non richieste
- sfruttare il segnale artista in query
- non promuovere automaticamente alias da match Spotify medi o dubbi

In breve: migliorare la selezione, non la memoria automatica.
