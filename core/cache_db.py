"""
core/cache_db.py

Cache persistente SQLite per le query musicali.
Abilitata solo se CACHE_ENABLED=true nel .env.

API pubblica:
    init()            -> crea le tabelle se non esistono
    get(query)        -> dict | None
    put(query, track) -> None
    invalidate(query) -> None
    stats()           -> dict
    clear()           -> int  (numero righe eliminate)
"""

import hashlib
import logging
import sqlite3
import threading
import time
from contextlib import contextmanager
from typing import Optional

from config import Config

log = logging.getLogger("pitonazz.cache_db")

_DB_VERSION = 1
_lock = threading.Lock()
_conn: Optional[sqlite3.Connection] = None


# ── Connessione ──────────────────────────────────────────────────────────────

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
                log.info(f"[CACHE_DB] connesso a {Config.DB_PATH!r}")
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


# ── Schema ───────────────────────────────────────────────────────────────────

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
    created_at   INTEGER NOT NULL DEFAULT (unixepoch()),
    last_used    INTEGER NOT NULL DEFAULT (unixepoch()),
    hit_count    INTEGER NOT NULL DEFAULT 1,
    is_valid     INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS query_aliases (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    query_hash TEXT    NOT NULL UNIQUE,
    query_raw  TEXT    NOT NULL,
    cache_id   INTEGER NOT NULL REFERENCES song_cache(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_qhash  ON song_cache(query_hash);
CREATE INDEX IF NOT EXISTS idx_alias  ON query_aliases(query_hash);
CREATE INDEX IF NOT EXISTS idx_valid  ON song_cache(is_valid);
"""


def _init_schema(conn: sqlite3.Connection) -> None:
    for stmt in DDL.strip().split(";"):
        s = stmt.strip()
        if s:
            conn.execute(s)
    conn.commit()


# ── Helpers ──────────────────────────────────────────────────────────────────

def _hash(query: str) -> str:
    return hashlib.sha256(query.strip().lower().encode()).hexdigest()


def _ttl_cutoff() -> int:
    return int(time.time()) - Config.CACHE_TTL_DAYS * 86_400


# ── API pubblica ─────────────────────────────────────────────────────────────

def init() -> None:
    """Forza l'inizializzazione del DB (chiamata all'avvio se CACHE_ENABLED)."""
    _get_conn()


def get(query: str) -> Optional[dict]:
    """Restituisce la riga cachata per query, o None se assente/scaduta."""
    if not query:
        return None
    h = _hash(query)
    cutoff = _ttl_cutoff()
    with _cursor() as cur:
        # cerca prima nella tabella principale, poi negli alias
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
        if row is None:
            return None
        # aggiorna last_used e hit_count
        cur.execute(
            "UPDATE song_cache SET last_used = unixepoch(), hit_count = hit_count + 1 WHERE id = ?",
            (row["id"],),
        )
    return dict(row)


def put(query: str, track) -> None:
    """
    Salva/aggiorna una TrackInfo nel DB.
    track puo' essere un oggetto TrackInfo o un dict.
    """
    if not query:
        return
    h = _hash(query)

    def _g(attr: str, default=None):
        if isinstance(track, dict):
            return track.get(attr, default)
        return getattr(track, attr, default)

    with _cursor() as cur:
        cur.execute(
            """
            INSERT INTO song_cache
                (query_hash, query_raw, webpage_url, source, title, artist,
                 duration, thumbnail, spotify_url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(query_hash) DO UPDATE SET
                webpage_url = excluded.webpage_url,
                source      = excluded.source,
                title       = excluded.title,
                artist      = excluded.artist,
                duration    = excluded.duration,
                thumbnail   = excluded.thumbnail,
                spotify_url = excluded.spotify_url,
                last_used   = unixepoch(),
                hit_count   = hit_count + 1,
                is_valid    = 1
            """,
            (
                h,
                query.strip(),
                _g("webpage_url", ""),
                _g("source", "youtube"),
                _g("title", ""),
                _g("artist", ""),
                int(_g("duration") or 0),
                _g("thumbnail", ""),
                _g("spotify_url", ""),
            ),
        )
    _maybe_trim()


def invalidate(query: str) -> None:
    """Marca una voce come non valida senza eliminarla (per debug o re-fetch)."""
    if not query:
        return
    h = _hash(query)
    with _cursor() as cur:
        cur.execute("UPDATE song_cache SET is_valid = 0 WHERE query_hash = ?", (h,))


def stats() -> dict:
    """Ritorna statistiche rapide sul DB."""
    with _cursor() as cur:
        cur.execute("SELECT COUNT(*) AS total, SUM(hit_count) AS hits FROM song_cache WHERE is_valid = 1")
        row = cur.fetchone()
        cur.execute("SELECT COUNT(*) AS aliases FROM query_aliases")
        aliases = cur.fetchone()
    return {
        "total":   row["total"]   or 0,
        "hits":    row["hits"]    or 0,
        "aliases": aliases["aliases"] or 0,
    }


def clear() -> int:
    """Elimina tutte le voci. Ritorna il numero di righe cancellate."""
    with _cursor() as cur:
        cur.execute("DELETE FROM song_cache")
        n = cur.rowcount
        cur.execute("DELETE FROM query_aliases")
    log.info(f"[CACHE_DB] clear: {n} voci eliminate")
    return n


# ── Manutenzione automatica ───────────────────────────────────────────────────

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
    cutoff = _ttl_cutoff()
    with _cursor() as cur:
        # rimuovi scadute
        cur.execute("DELETE FROM song_cache WHERE last_used < ?", (cutoff,))
        expired = cur.rowcount
        # rimuovi eccedenze (tieni le piu' usate)
        cur.execute(
            """
            DELETE FROM song_cache
             WHERE id NOT IN (
               SELECT id FROM song_cache
                ORDER BY hit_count DESC, last_used DESC
                LIMIT ?
             )
            """,
            (Config.CACHE_MAX_ENTRIES,),
        )
        trimmed = cur.rowcount
    if expired or trimmed:
        log.debug(f"[CACHE_DB] trim: {expired} scadute + {trimmed} eccedenze rimosse")
