"""
cache_db.py — Persistent SQLite cache per query/stream risolti.
Attivato solo se CACHE_ENABLED=true nel .env.
"""
import hashlib
import logging
import re
import sqlite3
import time
from pathlib import Path
from typing import Optional

from core.log_colors import tag, b, dim

log = logging.getLogger("pitonazz.cache_db")

# ── Costanti ─────────────────────────────────────────────────────────────────
_SCHEMA_VERSION = 1
_CLR_HIT  = "\033[92m"
_CLR_MISS = "\033[90m"
_CLR_WARN = "\033[93m"
_CLR_ERR  = "\033[91m"
_CLR_INFO = "\033[96m"


def _clr(text: str, color: str) -> str:
    return f"{color}{text}\033[0m"


# ── Stato globale ─────────────────────────────────────────────────────────────
_db_path: Optional[Path] = None
_enabled: bool = False


def init_db(db_path: Path, enabled: bool = True) -> None:
    """Crea le tabelle se non esistono. Da chiamare all'avvio del bot."""
    global _db_path, _enabled
    _db_path = db_path
    _enabled = enabled

    if not enabled:
        log.info(tag("DB", f"{_clr('OFF', _CLR_WARN)}  cache disabilitata (CACHE_ENABLED=false)"))
        return

    try:
        with _connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS song_cache (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    query_hash  TEXT NOT NULL UNIQUE,
                    query_raw   TEXT NOT NULL,
                    webpage_url TEXT NOT NULL DEFAULT '',
                    stream_url  TEXT NOT NULL DEFAULT '',
                    source      TEXT NOT NULL DEFAULT 'youtube',
                    title       TEXT NOT NULL DEFAULT '',
                    artist      TEXT NOT NULL DEFAULT '',
                    duration    INTEGER NOT NULL DEFAULT 0,
                    thumbnail   TEXT NOT NULL DEFAULT '',
                    created_at  REAL NOT NULL DEFAULT (unixepoch('now')),
                    last_used   REAL NOT NULL DEFAULT (unixepoch('now')),
                    hit_count   INTEGER NOT NULL DEFAULT 1,
                    is_valid    INTEGER NOT NULL DEFAULT 1
                );

                CREATE TABLE IF NOT EXISTS query_aliases (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    query_hash  TEXT NOT NULL,
                    query_raw   TEXT NOT NULL,
                    cache_id    INTEGER NOT NULL
                                REFERENCES song_cache(id) ON DELETE CASCADE,
                    created_at  REAL NOT NULL DEFAULT (unixepoch('now'))
                );

                CREATE TABLE IF NOT EXISTS schema_meta (
                    key   TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_song_cache_hash
                    ON song_cache(query_hash);
                CREATE INDEX IF NOT EXISTS idx_aliases_hash
                    ON query_aliases(query_hash);
                CREATE INDEX IF NOT EXISTS idx_song_cache_last_used
                    ON song_cache(last_used);
            """)
            conn.execute(
                "INSERT OR IGNORE INTO schema_meta(key, value) VALUES ('version', ?)",
                (str(_SCHEMA_VERSION),)
            )
        log.info(tag("DB", f"{_clr('ON', _CLR_HIT)}  {_clr(str(db_path), _CLR_INFO)}"))
    except Exception as exc:
        log.error(tag("DB", f"init_db fallito: {exc}"))
        _enabled = False


# ── Helpers privati ───────────────────────────────────────────────────────────
def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _hash(query: str) -> str:
    return hashlib.sha256(query.strip().lower().encode()).hexdigest()


def _normalize(query: str) -> str:
    """Lowercase, strip, rimuove parole rumore comuni."""
    q = query.strip().lower()
    q = re.sub(
        r"\b(official|video|audio|lyrics|hd|hq|4k|official music video|mv)\b",
        "", q
    )
    return re.sub(r"\s+", " ", q).strip()


# ── API pubblica ──────────────────────────────────────────────────────────────
def is_enabled() -> bool:
    return _enabled


def get(query: str) -> Optional[dict]:
    """Cerca in cache. Restituisce dict con i dati del brano o None se miss."""
    if not _enabled or not _db_path:
        return None
    norm = _normalize(query)
    h    = _hash(norm)
    try:
        with _connect() as conn:
            row = conn.execute(
                "SELECT * FROM song_cache WHERE query_hash=? AND is_valid=1", (h,)
            ).fetchone()
            if row is None:
                alias = conn.execute(
                    "SELECT cache_id FROM query_aliases WHERE query_hash=?", (h,)
                ).fetchone()
                if alias:
                    row = conn.execute(
                        "SELECT * FROM song_cache WHERE id=? AND is_valid=1",
                        (alias["cache_id"],)
                    ).fetchone()
            if row:
                conn.execute(
                    "UPDATE song_cache SET hit_count=hit_count+1, last_used=? WHERE id=?",
                    (time.time(), row["id"])
                )
                log.info(tag("DB",
                    f"{_clr('HIT', _CLR_HIT)}  {b(row['query_raw'])}  "
                    f"\u2192  {b(row['title'])}  "
                    f"hits={_clr(str(row['hit_count'] + 1), _CLR_INFO)}"
                ))
                return dict(row)
            log.debug(tag("DB", f"{_clr('MISS', _CLR_MISS)}  {dim(norm)}"))
            return None
    except Exception as exc:
        log.warning(tag("DB", f"get fallito: {exc}"))
        return None


def put(query: str, track) -> None:
    """Inserisce o aggiorna una entry. `track` e' un TrackInfo."""
    if not _enabled or not _db_path:
        return
    norm = _normalize(query)
    h    = _hash(norm)
    try:
        with _connect() as conn:
            existing = conn.execute(
                "SELECT id FROM song_cache WHERE query_hash=?", (h,)
            ).fetchone()
            if existing:
                conn.execute("""
                    UPDATE song_cache
                    SET stream_url=?, webpage_url=?, title=?, artist=?,
                        duration=?, thumbnail=?, last_used=?, is_valid=1
                    WHERE id=?
                """, (
                    getattr(track, "stream_url",  ""),
                    getattr(track, "webpage_url", ""),
                    getattr(track, "title",       ""),
                    getattr(track, "artist",      ""),
                    getattr(track, "duration",    0),
                    getattr(track, "thumbnail",   ""),
                    time.time(),
                    existing["id"],
                ))
                log.debug(tag("DB", f"UPDATE  {b(norm)}"))
            else:
                conn.execute("""
                    INSERT INTO song_cache
                        (query_hash, query_raw, webpage_url, stream_url,
                         source, title, artist, duration, thumbnail, last_used)
                    VALUES (?,?,?,?,?,?,?,?,?,?)
                """, (
                    h,
                    norm,
                    getattr(track, "webpage_url", ""),
                    getattr(track, "stream_url",  ""),
                    getattr(track, "source",      "youtube"),
                    getattr(track, "title",       ""),
                    getattr(track, "artist",      ""),
                    getattr(track, "duration",    0),
                    getattr(track, "thumbnail",   ""),
                    time.time(),
                ))
                log.info(tag("DB",
                    f"{_clr('INSERT', _CLR_INFO)}  {b(norm)}  "
                    f"=>  {b(getattr(track, 'title', '?'))}"
                ))
    except Exception as exc:
        log.warning(tag("DB", f"put fallito: {exc}"))


def add_alias(alias_query: str, canonical_query: str) -> None:
    """Associa una query alternativa allo stesso brano della query canonica."""
    if not _enabled or not _db_path:
        return
    h_alias = _hash(_normalize(alias_query))
    h_canon = _hash(_normalize(canonical_query))
    try:
        with _connect() as conn:
            row = conn.execute(
                "SELECT id FROM song_cache WHERE query_hash=?", (h_canon,)
            ).fetchone()
            if not row:
                return
            conn.execute(
                "INSERT OR IGNORE INTO query_aliases(query_hash, query_raw, cache_id) VALUES(?,?,?)",
                (h_alias, _normalize(alias_query), row["id"])
            )
    except Exception as exc:
        log.warning(tag("DB", f"add_alias fallito: {exc}"))


def invalidate(query: str) -> bool:
    """Marca una entry come non valida (soft delete)."""
    if not _enabled or not _db_path:
        return False
    h = _hash(_normalize(query))
    try:
        with _connect() as conn:
            cur = conn.execute(
                "UPDATE song_cache SET is_valid=0 WHERE query_hash=?", (h,)
            )
            return cur.rowcount > 0
    except Exception as exc:
        log.warning(tag("DB", f"invalidate fallito: {exc}"))
        return False


def prune_lru(max_entries: int = 500, ttl_days: int = 30) -> int:
    """Rimuove entry scadute o in eccesso (LRU). Restituisce righe eliminate."""
    if not _enabled or not _db_path:
        return 0
    cutoff = time.time() - ttl_days * 86400
    try:
        with _connect() as conn:
            cur     = conn.execute("DELETE FROM song_cache WHERE last_used < ?", (cutoff,))
            expired = cur.rowcount
            count   = conn.execute("SELECT COUNT(*) FROM song_cache").fetchone()[0]
            lru_removed = 0
            if count > max_entries:
                to_remove = count - max_entries
                cur = conn.execute("""
                    DELETE FROM song_cache WHERE id IN (
                        SELECT id FROM song_cache ORDER BY last_used ASC LIMIT ?
                    )
                """, (to_remove,))
                lru_removed = cur.rowcount
            total = expired + lru_removed
            if total:
                log.info(tag("DB",
                    f"prune  expired={_clr(str(expired), _CLR_WARN)}  "
                    f"lru={_clr(str(lru_removed), _CLR_WARN)}  "
                    f"tot={_clr(str(total), _CLR_ERR)}"
                ))
            return total
    except Exception as exc:
        log.warning(tag("DB", f"prune LRU fallito: {exc}"))
        return 0


def stats() -> dict:
    """Restituisce statistiche del DB come dizionario."""
    if not _enabled or not _db_path:
        return {"enabled": False}
    try:
        with _connect() as conn:
            total    = conn.execute("SELECT COUNT(*) FROM song_cache").fetchone()[0]
            valid    = conn.execute("SELECT COUNT(*) FROM song_cache WHERE is_valid=1").fetchone()[0]
            aliases  = conn.execute("SELECT COUNT(*) FROM query_aliases").fetchone()[0]
            top_row  = conn.execute(
                "SELECT query_raw, hit_count FROM song_cache ORDER BY hit_count DESC LIMIT 1"
            ).fetchone()
            hits_sum = conn.execute(
                "SELECT SUM(hit_count) FROM song_cache WHERE is_valid=1"
            ).fetchone()[0] or 0
            size_bytes = _db_path.stat().st_size if _db_path.exists() else 0
        return {
            "enabled":    True,
            "total":      total,
            "valid":      valid,
            "aliases":    aliases,
            "hits_total": hits_sum,
            "top_query":  dict(top_row) if top_row else None,
            "size_kb":    round(size_bytes / 1024, 1),
            "db_path":    str(_db_path),
        }
    except Exception as exc:
        log.warning(tag("DB", f"stats fallito: {exc}"))
        return {"enabled": True, "error": str(exc)}


def clear_all() -> int:
    """Svuota completamente song_cache e query_aliases. Restituisce righe eliminate."""
    if not _enabled or not _db_path:
        return 0
    try:
        with _connect() as conn:
            n = conn.execute("SELECT COUNT(*) FROM song_cache").fetchone()[0]
            conn.executescript("""
                DELETE FROM query_aliases;
                DELETE FROM song_cache;
            """)
            log.warning(tag("DB", f"{_clr('CLEAR ALL', _CLR_ERR)}  {n} righe eliminate"))
            return n
    except Exception as exc:
        log.warning(tag("DB", f"clear_all fallito: {exc}"))
        return 0
