# Cache DB Manual

Questo documento descrive il cache database musicale di Pytonazz2026: perche' esiste, come e' strutturato, come apprende query/alias, come interagisce con resolver, Spotify, yt-dlp e dashboard.

## 1. Scopo

Il cache DB serve a ridurre tempo e ambiguita' nel comando `/play`.

Obiettivi:

- riusare tracce gia' risolte;
- associare query diverse alla stessa traccia;
- salvare sorgenti riproducibili YouTube/SoundCloud;
- preservare cover Spotify quando piu' affidabile della thumbnail YouTube;
- salvare stream URL temporanei per replay rapidi;
- permettere dashboard, invalidazione e associazione manuale.

Non e' un motore ML pesante. L'apprendimento e' volutamente leggero: query osservate, alias confermati, hit count, canonicalizzazione title/artist e priorita' cover/source.

## 2. File coinvolti

- `core/cache_db.py`: schema, CRUD, alias, pruning, dashboard helpers.
- `core/source_resolver/__init__.py`: read/write cache durante resolve.
- `core/source_resolver/scoring.py`: confidence Spotify/YouTube.
- `core/source_resolver/spotify.py`: scelta candidato Spotify.
- `cogs/dev_cache.py`: comandi owner `/cache`.
- `data/database/dashboard/app.py`: API dashboard.
- `tools/rebuild_cache_db.py`: reset DB.
- `tools/dedupe_cache_db.py`: dedupe.
- `tools/renumber_cache_ids.py`: riallineamento ID.

## 3. Schema attuale

Versione schema: `PRAGMA user_version = 3`.

### `cache_tracks`

Identita' logica della traccia.

Campi principali:

- `id`: PK.
- `canonical_query_hash`: hash della query canonica.
- `canonical_query_raw`: query canonica leggibile.
- `normalized_query`: chiave normalizzata.
- `canonical_title`: titolo canonico.
- `canonical_artist`: artista canonico.
- `created_at`, `updated_at`.
- `is_active`.

Una traccia logica puo' avere piu' sorgenti e molte query/alias.

### `cache_sources`

Risorsa riproducibile e metadati tecnici.

Campi principali:

- `id`: PK.
- `track_id`: FK verso `cache_tracks`.
- `webpage_url`: URL YouTube/SoundCloud.
- `stream_url`: URL audio diretto temporaneo.
- `stream_expires_at`: scadenza stream URL.
- `last_stream_check`.
- `source`: `youtube`, `soundcloud`, ecc.
- `resolved_title`, `resolved_artist`.
- `duration`.
- `thumbnail`.
- `thumbnail_source`: `spotify`, `youtube`, `soundcloud`, `other`, vuoto.
- `thumbnail_confidence`.
- `spotify_url`.
- `source_confidence`.
- `hit_count`, `last_used`.
- `is_valid`.

Indici importanti:

- unique `webpage_url` quando non vuoto;
- unique `spotify_url` quando non vuoto;
- lookup per `track_id`, validita', hit count e last used.

### `cache_queries`

Query osservate e alias.

Campi principali:

- `id`: PK.
- `query_hash`: hash query normalizzata.
- `query_raw`: testo originale osservato.
- `query_norm`: forma normalizzata.
- `track_id`: FK verso traccia.
- `source_id`: FK verso sorgente.
- `alias_type`: `canonical`, `text`, `spotify`, ecc.
- `match_method`: `canonical`, `same_source`, `canonical_metadata`, ecc.
- `match_confidence`.
- `first_seen`, `last_seen`, `hit_count`.
- `is_confirmed`, `is_active`.

### Viste compatibili

`song_cache` espone una vista sorgente+traccia usata da dashboard/test legacy.

`query_aliases` espone query alias in forma compatibile con vecchie utility.

## 4. Normalizzazione e hash

`_normalize_key()`:

- lower-case;
- rimuove caratteri non utili;
- mantiene spazi, slash, due punti, punti e trattini;
- compatta whitespace.

`_hash()` usa SHA-256 della chiave normalizzata.

Per link Spotify viene estratto URL canonico:

```text
https://open.spotify.com/track/<id>
https://open.spotify.com/album/<id>
https://open.spotify.com/playlist/<id>
```

## 5. Flusso cache hit

Per `/play` testuale con `n==1`:

1. `SourceResolver.resolve_choices()` chiama `cache_db.get(query)`.
2. Se trova riga valida e `webpage_url`:
   - se `stream_url` e' presente e `stream_expires_at > now + 60`, lo usa subito;
   - altrimenti chiama `_fetch_stream_url(webpage_url)` e aggiorna DB con `update_stream_url()`.
3. Se stream valido: ritorna `TrackInfo`.
4. Se stream non valido: invalida URL e fa ricerca fresca.

Questo e' il percorso piu' veloce. Il bot puo' iniziare playback senza rifare search YouTube.

## 6. Flusso cache miss

1. Spotify puo' cercare metadati in parallelo o con finestra breve su query ambigue.
2. yt-dlp cerca il risultato YouTube/SoundCloud.
3. Lo scoring confronta query, title, artist, durata e penalita' varianti.
4. Il resolver decide:
   - `full`: applica title, artist, cover, Spotify URL;
   - `cover_only`: applica cover e Spotify URL, ma non sovrascrive title/artist;
   - `skip`: non arricchisce.
5. `cache_db.put(query, track)` salva traccia, sorgente e query/alias.

## 7. Apprendimento e alias

La cache apprende senza rallentare il resolve:

- ogni query osservata viene salvata in `cache_queries`;
- query diverse con stessa `webpage_url` vengono collegate alla stessa sorgente;
- link Spotify normalizzati diventano alias `spotify`;
- query canoniche title+artist diventano alias `canonical`;
- hit count e last used aumentano a ogni lookup;
- sorgenti invalide restano tracciabili ma non vengono usate.

Esempio:

```text
"notte blu dj shokka" -> track_id 1, source_id 1
"Notte Blu DJ Shocca, Frank Siciliano" -> track_id 1, source_id 1
"https://open.spotify.com/track/..." -> track_id 1, source_id 1
```

## 8. Cover e thumbnail

La cache conserva `thumbnail_source` e `thumbnail_confidence`.

Priorita' pratica:

1. Spotify cover: preferita quando scoring consente `full` o `cover_only`.
2. YouTube thumbnail: fallback se Spotify manca o non passa guardrail.
3. SoundCloud thumbnail: fallback per sorgenti SoundCloud.

`put()` evita di sovrascrivere una cover Spotify affidabile con una thumbnail YouTube piu' debole.

## 9. Stream URL temporaneo

Gli URL audio diretti di YouTube scadono. Per questo:

- vengono salvati in `cache_sources.stream_url`;
- hanno TTL breve, default 30 minuti;
- `stream_expires_at` decide se riusarli;
- se scaduti, il resolver ricalcola lo stream da `webpage_url`.

Questo accelera replay ravvicinati ma non pretende persistenza eterna dello stream.

## 10. Dashboard

La dashboard usa:

- `list_song_rows()`
- `list_alias_rows()`
- `list_track_rows()`
- `list_source_rows()`
- `list_query_rows()`
- `schema_overview()`
- `associate_spotify()`
- `delete_song_row()`
- `delete_alias()`

API principali:

- `/api/stats`
- `/api/songs`
- `/api/aliases`
- `/api/tracks`
- `/api/sources`
- `/api/queries`
- `/api/schema`
- `/api/associate`
- `/api/delete/<row_id>`
- `/api/aliases/<alias_id>`

## 11. Comandi owner

Gruppo `/cache` in `cogs/dev_cache.py`:

- `/cache status`: mostra se cache e' attiva.
- `/cache stats`: conteggi e hit.
- `/cache on`: abilita runtime.
- `/cache off`: disabilita runtime senza cancellare dati.
- `/cache prune`: rimuove entry vecchie/in eccesso.
- `/cache invalidate <query>`: invalida una query.
- `/cache clear <confirm>`: svuota completamente.
- `/cache export`: allega snapshot DB.

## 12. Reset DB

Reset con backup:

```bash
python tools/rebuild_cache_db.py --backup
```

DB alternativo:

```bash
python tools/rebuild_cache_db.py --db data/database/cache.db --backup
```

Non usare:

```bash
source tools/rebuild_cache_db.py --backup
```

`source` fa interpretare Python come shell e produce errori tipo `import: command not found`.

## 13. Manutenzione

Dedupe:

```bash
python tools/dedupe_cache_db.py --db data/database/cache.db --apply
```

Rinumerazione ID:

```bash
python tools/renumber_cache_ids.py --db data/database/cache.db --apply
```

Benchmark resolver:

```bash
python tools/benchmark_resolve.py "trust me"
```

Benchmark yt-dlp:

```bash
python tools/benchmark_ytdlp.py "Trust Me Pandora"
```

## 14. Troubleshooting cache

### Cache non usata

Controlla:

```env
CACHE_ENABLED=true
DB_PATH=data/database/cache.db
```

Riavvia il bot: `Config.CACHE_ENABLED` viene letto all'avvio.

### Replay lento

Possibili cause:

- stream URL scaduto;
- query non normalizzata come alias;
- DB appena ricreato;
- entry invalidata;
- YouTube anti-bot o cookie non validi.

### Cover YouTube invece di Spotify

Controlla:

```bash
python tools/benchmark_resolve.py "query"
```

Se `spotify_probe_ms` trova cover ma finale resta YouTube, controlla scoring e fallback:

```bash
python tests/test_resolver_spotify_canonical_fallback_cover.py
python tests/test_resolver_spotify_late_hint.py
```

### DB bloccato o WAL presente

SQLite puo' creare:

- `cache.db-wal`
- `cache.db-shm`

Sono file runtime normali. Non committarli. Se devi fare backup, stoppa il bot o usa `/cache export`.

## 15. Test consigliati dopo modifiche

```bash
python tests/test_cache_aliases.py
python tests/test_cache_thumbnail_stream.py
python tests/test_resolver_spotify_canonical_fallback_cover.py
python tests/test_resolver_spotify_late_hint.py
python tests/test_scoring_guardrails.py
python tests/test_dashboard_api.py
```

Se il nome del test non esiste nella copia corrente, usa:

```bash
ls tests
```

e rilancia gli equivalenti disponibili.
