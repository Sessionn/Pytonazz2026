"""
core/cache_db.py

Cache persistente SQLite per le query musicali.
Abilitata solo se CACHE_ENABLED=true nel .env.

API pubblica:
    init_db(db_path, enabled) -> None   (alias per main.py)
    init()                    -> None   (forza init DB)
    is_enabled()              -> bool
    get(query)                -> dict | None
    put(query, track)         -> None
    add_alias(alias, query)   -> None
    invalidate(query)         -> bool
    stats()                   -> dict
    prune_lru(max_entries, ttl_days) -> int
    clear()                   -> int  (numero righe eliminate)
    clear_all()               -> int  (alias di clear())

Note sul comportamento degli alias:
    - query_aliases viene popolata automaticamente da put() ogni volta che
      la stessa traccia (stesso webpage_url) viene salvata con una query
      testuale diversa da quella originale.
    - I link Spotify usati come query vengono cachati intelligentemente:
      la traccia viene salvata sotto la canonical testuale (titolo+artista)
      e il link Spotify viene registrato come alias -> canonical, cosi'
      successive ricerche per lo stesso link o per testo trovano lo stesso
      record senza duplicati.
"""

import hashlib
import logging
import os
import re
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Optional, Union

from config import Config
from core.log_colors import tag, b, hi, dim, _BGRN, _BYEL, _BRED, _CYN, _TEAL, _GRY

log = logging.getLogger("pitonazz.cache_db")

_DB_VERSION = 1
_lock = threading.Lock()
_conn: Optional[sqlite3.Connection] = None

# Flag runtime: permette di sapere se il DB e' stato inizializzato con enabled=True
_enabled: bool = False

# Regex per riconoscere URL Spotify
_RE_SPOTIFY = re.compile(
    r"https?://open\.spotify\.com/(track|album|playlist)/([A-Za-z0-9]+)",
    re.IGNORECASE,
)


# ── Helpers query ──────────────────────────────────────────

def _is_spotify_url(query: str) -> bool:
    """Restituisce True se la query e' un link Spotify."""
    return bool(_RE_SPOTIFY.search(query.strip()))


def _extract_spotify_id(url: str) -> str:
    """Estrae l'ID Spotify (track/album/playlist) normalizzando parametri query."""
    m = _RE_SPOTIFY.search(url.strip())
    if not m:
        return url.strip()
    # Restituisce l'URL canonico senza parametri (?si=...)
    return f"https://open.spotify.com/{m.group(1)}/{m.group(2)}"


def _canonical_for_track(track) -> Optional[str]:
    """
    Costruisce una canonical key testuale (title + artist) da un oggetto traccia.
    Usata per salvare un link Spotify sotto la stessa entry testuale.
    """
    def _g(attr):
        if isinstance(track, dict):
            return (track.get(attr) or "").strip()
        return (getattr(track, attr, "") or "").strip()

    title  = _g("title")
    artist = _g("artist")
    if not title:
        return None
    canonical = f"{title} {artist}".strip().lower() if artist else title.lower()
    return canonical


# ── Connessione ────────────────────────────────────────────

def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        with _lock:
            if _conn is None:
                _conn = sqlite3.connect(
                    Config.DB_PATH,
                    check_same_thread=False,
                    timeout=10,
                )
                _conn.row_factory = sqlite3.Row
                _conn.execute("PRAGMA journal_mode=WAL")
                _conn.execute("PRAGMA synchronous=NORMAL")
                _conn.execute("PRAGMA foreign_keys=ON")
                _init_schema(_conn)
    return _conn


@contextmanager
def _cursor():
    conn = _get_conn()
    with _lock, conn:
        cur = conn.cursor()
        try:
            yield cur
        finally:
            cur.close()


# ── Schema ───────────────────────────────────────────────

DDL = """
CREATE TABLE IF NOT EXISTS song_cache (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    query_hash   TEXT    NOT NULL UNIQUE,
    query_raw    TEXT    NOT NULL,
    webpage_url  TEXT,
    source       TEXT    NOT NULL DEFAULT 'youtube',
    title        TEXT,
    artist       TEXT,
    duration     INTEGER,
    thumbnail    TEXT,
    spotify_url  TEXT,
    created_at   INTEGER NOT NULL DEFAULT (strftime('%s','now')),
    last_used    INTEGER NOT NULL DEFAULT (strftime('%s','now')),
    hit_count    INTEGER NOT NULL DEFAULT 1,
    is_valid     INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS query_aliases (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    query_hash TEXT    NOT NULL UNIQUE,
    query_raw  TEXT    NOT NULL,
    cache_id   INTEGER NOT NULL REFERENCES song_cache(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_qhash      ON song_cache(query_hash);
CREATE INDEX IF NOT EXISTS idx_spotify    ON song_cache(spotify_url);
CREATE INDEX IF NOT EXISTS idx_webpage    ON song_cache(webpage_url);
CREATE INDEX IF NOT EXISTS idx_alias      ON query_aliases(query_hash);
CREATE INDEX IF NOT EXISTS idx_alias_cid  ON query_aliases(cache_id);
CREATE INDEX IF NOT EXISTS idx_valid      ON song_cache(is_valid);
"""


def _init_schema(conn: sqlite3.Connection) -> None:
    for stmt in DDL.strip().split(";"):
        s = stmt.strip()
        if s:
            conn.execute(s)
    conn.commit()


# ── Helpers ──────────────────────────────────────────────

def _hash(query: str) -> str:
    return hashlib.sha256(query.strip().lower().encode()).hexdigest()


def _ttl_cutoff(ttl_days: Optional[int] = None) -> int:
    days = ttl_days if ttl_days is not None else Config.CACHE_TTL_DAYS
    return int(time.time()) - days * 86_400


# ── API pubblica ───────────────────────────────────────────

def is_enabled() -> bool:
    """Restituisce True se la cache e' attiva (init_db chiamata con enabled=True)."""
    return _enabled


def init() -> None:
    """Forza l'inizializzazione del DB (chiamata all'avvio se CACHE_ENABLED)."""
    _get_conn()


def init_db(
    db_path: Union[str, Path, None] = None,
    enabled: bool = True,
) -> None:
    """
    Entry-point chiamato da main.py all'avvio.

    Parametri
    ---------
    db_path : percorso opzionale al file SQLite; se fornito sovrascrive
              Config.DB_PATH prima di aprire la connessione.
    enabled : se False la cache e' disabilitata e la funzione e' un no-op.
    """
    global _enabled
    if not enabled:
        log.info(tag("CACHE_DB", f"{hi('disabilitata', _BRED)}  {dim('(imposta CACHE_ENABLED=true per attivarla)')}"))
        _enabled = False
        return
    if db_path is not None:
        Config.DB_PATH = str(db_path)
    init()
    _enabled = True
    log.info(tag(
        "CACHE_DB",
        f"{hi('attiva', _BGRN)}  "
        f"{b(Config.DB_PATH)}  "
        f"ttl={b(str(Config.CACHE_TTL_DAYS) + 'd')}  "
        f"max={b(str(Config.CACHE_MAX_ENTRIES))}"
    ))


def get(query: str) -> Optional[dict]:
    """
    Cerca la query nel DB in 4 step:
      1. Exact hash hit (query testuale identica)
      2. Alias hash hit (query registrata come alias)
      3. Spotify URL hit (query e' un link Spotify gia' salvato)
      4. Lookup diretto su spotify_url nel DB (se query e' URL Spotify)
    """
    if not query or not _enabled:
        return None

    query_stripped = query.strip()
    h = _hash(query_stripped)
    cutoff = _ttl_cutoff()

    with _cursor() as cur:
        # Step 1 + 2: exact hash oppure alias
        cur.execute(
            """
            SELECT sc.*
              FROM song_cache sc
             WHERE sc.query_hash = ? AND sc.is_valid = 1 AND sc.last_used >= ?
            UNION ALL
            SELECT sc.*
              FROM song_cache sc
              JOIN query_aliases qa ON qa.cache_id = sc.id
             WHERE qa.query_hash = ? AND sc.is_valid = 1 AND sc.last_used >= ?
             LIMIT 1
            """,
            (h, cutoff, h, cutoff),
        )
        row = cur.fetchone()

        # Step 3 + 4: se la query e' un link Spotify, cerca per spotify_url
        if row is None and _is_spotify_url(query_stripped):
            spotify_id = _extract_spotify_id(query_stripped)
            cur.execute(
                """
                SELECT * FROM song_cache
                 WHERE spotify_url = ? AND is_valid = 1 AND last_used >= ?
                 LIMIT 1
                """,
                (spotify_id, cutoff),
            )
            row = cur.fetchone()
            if row:
                # Promuovi anche il link come alias per evitare ricerche future
                _promote_alias_inner(cur, query_stripped, row["id"])

        if row is None:
            log.info(tag("CACHE_DB", f"\U0001f50d {hi('MISS', _GRY)}  {b(query_stripped)}"))
            return None

        cur.execute(
            "UPDATE song_cache SET last_used = strftime('%s','now'), hit_count = hit_count + 1 WHERE id = ?",
            (row["id"],),
        )

    title  = row["title"]  or query_stripped
    artist = row["artist"] or ""
    label  = f"{b(title)}" + (f"  {artist}" if artist else "")
    log.info(tag("CACHE_DB", f"\u2705 {hi('HIT', _BGRN)}  {label}  hits={row['hit_count'] + 1}"))
    return dict(row)


def _promote_alias_inner(cur: sqlite3.Cursor, query_raw: str, cache_id: int) -> None:
    """
    Registra query_raw come alias per cache_id.
    Usato internamente (dentro un _cursor() gia' aperto).
    """
    h = _hash(query_raw)
    try:
        cur.execute(
            """
            INSERT INTO query_aliases (query_hash, query_raw, cache_id)
            VALUES (?, ?, ?)
            ON CONFLICT(query_hash) DO UPDATE SET
                query_raw = excluded.query_raw,
                cache_id  = excluded.cache_id
            """,
            (h, query_raw.strip(), cache_id),
        )
    except Exception:
        pass


def put(query: str, track) -> None:
    """
    Salva/aggiorna una TrackInfo nel DB.
    track puo' essere un oggetto TrackInfo o un dict.

    Logica alias automatica:
    - Se query e' un link Spotify:
        * La traccia viene salvata sotto la canonical testuale (titolo+artista).
        * Il link Spotify viene registrato come alias -> canonical entry.
    - Se query e' testuale e webpage_url e' gia' in DB sotto un hash diverso:
        * La nuova query viene registrata come alias -> entry esistente.
    - In entrambi i casi lo spotify_url viene scritto sulla entry canonical
      cosi' i lookup futuri per URL Spotify trovano hit immediato.
    """
    if not query or not _enabled:
        return

    query_stripped = query.strip()
    is_spotify = _is_spotify_url(query_stripped)

    def _g(attr: str, default=None):
        if isinstance(track, dict):
            return track.get(attr, default)
        return getattr(track, attr, default)

    title       = (_g("title",  "") or "").strip() or query_stripped
    artist      = (_g("artist", "") or "").strip()
    webpage_url = (_g("webpage_url", "") or "").strip()
    source      = (_g("source", "youtube") or "youtube").strip()
    duration    = int(_g("duration") or 0)
    thumbnail   = (_g("thumbnail", "") or "").strip()
    spotify_url = (_g("spotify_url", "") or "").strip()

    # Se la query e' un link Spotify, normalizza il suo ID
    if is_spotify:
        spotify_url = spotify_url or _extract_spotify_id(query_stripped)

    # Determina la query canonical da usare come chiave principale nel DB:
    # - se la query e' un link Spotify, usa titolo+artista come canonical
    # - altrimenti usa la query stessa
    if is_spotify:
        canonical_query = _canonical_for_track(track) or title.lower()
    else:
        canonical_query = query_stripped

    h_canonical = _hash(canonical_query)
    h_original  = _hash(query_stripped)

    with _cursor() as cur:
        # Controlla se esiste gia' una entry per questa webpage_url
        # (traccia stessa, query diversa -> promuovi alias)
        row_by_url = None
        if webpage_url:
            cur.execute(
                "SELECT id, query_hash FROM song_cache WHERE webpage_url = ? AND is_valid = 1 LIMIT 1",
                (webpage_url,),
            )
            row_by_url = cur.fetchone()

        if row_by_url and row_by_url["query_hash"] != h_canonical:
            # Traccia gia' in cache sotto un hash diverso: promuovi alias
            existing_id = row_by_url["id"]
            _promote_alias_inner(cur, canonical_query, existing_id)
            if is_spotify and h_original != h_canonical:
                _promote_alias_inner(cur, query_stripped, existing_id)
            # Aggiorna spotify_url se mancava
            if spotify_url:
                cur.execute(
                    "UPDATE song_cache SET spotify_url = ?, last_used = strftime('%s','now'), hit_count = hit_count + 1 "
                    "WHERE id = ? AND (spotify_url IS NULL OR spotify_url = '')",
                    (spotify_url, existing_id),
                )
            log.info(tag("CACHE_DB", f"\U0001f517 {hi('ALIAS', _CYN)}  {b(query_stripped)}  \u2192  {b(title)}"))
            return

        # Inserisci o aggiorna la entry canonical
        cur.execute("SELECT id FROM song_cache WHERE query_hash = ?", (h_canonical,))
        existing = cur.fetchone()

        cur.execute(
            """
            INSERT INTO song_cache
                (query_hash, query_raw, webpage_url, source, title, artist,
                 duration, thumbnail, spotify_url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(query_hash) DO UPDATE SET
                webpage_url = CASE WHEN excluded.webpage_url != '' THEN excluded.webpage_url ELSE webpage_url END,
                source      = excluded.source,
                title       = excluded.title,
                artist      = excluded.artist,
                duration    = excluded.duration,
                thumbnail   = excluded.thumbnail,
                spotify_url = CASE WHEN excluded.spotify_url != '' THEN excluded.spotify_url ELSE spotify_url END,
                last_used   = strftime('%s','now'),
                hit_count   = hit_count + 1,
                is_valid    = 1
            """,
            (
                h_canonical,
                canonical_query,
                webpage_url,
                source,
                title,
                artist,
                duration,
                thumbnail,
                spotify_url,
            ),
        )

        # Recupera l'id della entry canonical (appena inserita o gia' esistente)
        cur.execute("SELECT id FROM song_cache WHERE query_hash = ?", (h_canonical,))
        entry_row = cur.fetchone()
        if entry_row:
            entry_id = entry_row["id"]
            # Se la query originale era un link Spotify, registrala come alias
            if is_spotify and h_original != h_canonical:
                _promote_alias_inner(cur, query_stripped, entry_id)
                # Registra anche il link Spotify normalizzato come alias
                if spotify_url and _hash(spotify_url) != h_canonical:
                    _promote_alias_inner(cur, spotify_url, entry_id)

    label = f"{b(title)}" + (f"  {artist}" if artist else "")
    if existing:
        log.info(tag("CACHE_DB", f"\u267b\ufe0f  {hi('UPDATE', _CYN)}  {label}"))
    else:
        log.info(tag("CACHE_DB", f"\U0001f4be {hi('STORE', _TEAL)}  {label}"))

    _maybe_trim()


def add_alias(alias: str, canonical_query: str) -> None:
    """
    Registra `alias` come query alternativa che punta alla stessa entry
    di `canonical_query`. Se canonical_query non esiste nel DB, la funzione
    e' un no-op silenzioso.
    """
    if not alias or not canonical_query or not _enabled:
        return
    h_alias     = _hash(alias)
    h_canonical = _hash(canonical_query)
    with _cursor() as cur:
        cur.execute(
            "SELECT id FROM song_cache WHERE query_hash = ? AND is_valid = 1",
            (h_canonical,),
        )
        row = cur.fetchone()
        if row is None:
            return
        cur.execute(
            """
            INSERT INTO query_aliases (query_hash, query_raw, cache_id)
            VALUES (?, ?, ?)
            ON CONFLICT(query_hash) DO UPDATE SET
                query_raw = excluded.query_raw,
                cache_id  = excluded.cache_id
            """,
            (h_alias, alias.strip(), row["id"]),
        )
    log.debug(tag("CACHE_DB", f"\U0001f517 {hi('ALIAS', _GRY)}  {b(alias)}  \u2192 {b(canonical_query)}"))


def invalidate(query: str) -> bool:
    """
    Marca una voce come non valida senza eliminarla (per debug o re-fetch).
    Restituisce True se la voce esisteva ed e' stata invalidata, False altrimenti.
    """
    if not query:
        return False
    h = _hash(query)
    with _cursor() as cur:
        cur.execute(
            "UPDATE song_cache SET is_valid = 0 WHERE query_hash = ? AND is_valid = 1",
            (h,),
        )
        found = cur.rowcount > 0
    if found:
        log.info(tag("CACHE_DB", f"\U0001f6ab {hi('INVALIDATE', _BYEL)}  {b(query)}"))
    else:
        log.debug(tag("CACHE_DB", f"\U0001f6ab {hi('INVALIDATE', _GRY)}  {b(query)}  (non trovata)"))
    return found


def stats() -> dict:
    """
    Ritorna statistiche estese sul DB.

    Campi restituiti:
        total       - numero totale di entry (valide + invalide)
        valid       - entry valide e non scadute
        hits        - somma totale dei hit_count
        aliases     - numero di alias registrati
        size_kb     - dimensione approssimativa del file SQLite in KB
        db_path     - percorso del file DB
        top_query   - dict della query con piu' hit (o None)
    """
    if not _enabled:
        return {"total": 0, "valid": 0, "hits": 0, "aliases": 0,
                "size_kb": 0, "db_path": Config.DB_PATH, "top_query": None}
    cutoff = _ttl_cutoff()
    with _cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM song_cache")
        total = cur.fetchone()[0]

        cur.execute(
            "SELECT COUNT(*) FROM song_cache WHERE is_valid = 1 AND last_used >= ?",
            (cutoff,),
        )
        valid = cur.fetchone()[0]

        cur.execute("SELECT COALESCE(SUM(hit_count), 0) FROM song_cache")
        hits = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM query_aliases")
        aliases = cur.fetchone()[0]

        cur.execute(
            "SELECT * FROM song_cache ORDER BY hit_count DESC LIMIT 1"
        )
        top_row = cur.fetchone()

    try:
        size_kb = round(Path(Config.DB_PATH).stat().st_size / 1024, 1)
    except OSError:
        size_kb = 0.0

    return {
        "total":    total,
        "valid":    valid,
        "hits":     hits,
        "aliases":  aliases,
        "size_kb":  size_kb,
        "db_path":  Config.DB_PATH,
        "top_query": dict(top_row) if top_row else None,
    }


def prune_lru(
    max_entries: int = 500,
    ttl_days: int = 30,
) -> int:
    """
    Rimuove le entry scadute e quelle in eccesso rispetto a max_entries
    (tenendo le piu' usate di recente).

    Restituisce il numero totale di righe eliminate.
    """
    cutoff = _ttl_cutoff(ttl_days)
    with _cursor() as cur:
        cur.execute("DELETE FROM song_cache WHERE last_used < ?", (cutoff,))
        expired = cur.rowcount
        cur.execute(
            """
            DELETE FROM song_cache
             WHERE id NOT IN (
               SELECT id FROM song_cache
                ORDER BY hit_count DESC, last_used DESC
                LIMIT ?
             )
            """,
            (max_entries,),
        )
        trimmed = cur.rowcount

    total_removed = expired + trimmed
    if total_removed:
        log.info(tag(
            "CACHE_DB",
            f"\u2702\ufe0f  {hi('PRUNE', _BYEL)}  scadute={b(str(expired))}  eccedenze={b(str(trimmed))}  "
            f"max={max_entries}  ttl={ttl_days}d"
        ))
    else:
        log.debug(tag("CACHE_DB", f"\u2702\ufe0f  {hi('PRUNE', _GRY)}  nulla da rimuovere"))
    return total_removed


def clear() -> int:
    """Elimina tutte le voci. Ritorna il numero di righe cancellate."""
    with _cursor() as cur:
        cur.execute("DELETE FROM song_cache")
        n = cur.rowcount
        cur.execute("DELETE FROM query_aliases")
    log.info(tag("CACHE_DB", f"\U0001f5d1\ufe0f  {hi('CLEAR', _BRED)}  {b(str(n))} entry eliminate"))
    return n


def clear_all() -> int:
    """Alias di clear() — compatibile con dev_cache.py."""
    return clear()


# ── Manutenzione automatica ───────────────────────────────────────────

_last_trim = 0.0
_TRIM_INTERVAL = 300  # secondi tra un trim e l'altro


def _maybe_trim() -> None:
    global _last_trim
    now = time.time()
    if now - _last_trim < _TRIM_INTERVAL:
        return
    _last_trim = now
    threading.Thread(target=_trim, daemon=True).start()


def _trim() -> None:
    """Esegue pulizia automatica usando i valori correnti di Config."""
    prune_lru(
        max_entries=Config.CACHE_MAX_ENTRIES,
        ttl_days=Config.CACHE_TTL_DAYS,
    )
