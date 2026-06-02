"""
core/cache_db.py

Cache persistente SQLite per le query musicali.
Abilitata solo se CACHE_ENABLED=true nel .env.

Architettura:
    cache_tracks   - identita' logica del brano
    cache_sources  - risorsa riproducibile / mapping Spotify / metadati tecnici
    cache_queries  - query osservate e alias confermati

Per compatibilita' diagnostica vengono esposte anche due VIEW:
    song_cache
    query_aliases
"""

from __future__ import annotations

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

_SCHEMA_VERSION = 3
_STREAM_URL_DB_TTL_SECONDS = 30 * 60
_lock = threading.Lock()
_conn: Optional[sqlite3.Connection] = None
_enabled: bool = False

_RE_SPOTIFY = re.compile(
    r"https?://open\.spotify\.com/(?:intl-[a-z]{2}/)?(track|album|playlist)/([A-Za-z0-9]+)",
    re.IGNORECASE,
)


def _is_spotify_url(query: str) -> bool:
    return bool(_RE_SPOTIFY.search((query or "").strip()))


def _extract_spotify_id(url: str) -> str:
    m = _RE_SPOTIFY.search((url or "").strip())
    if not m:
        return (url or "").strip()
    return f"https://open.spotify.com/{m.group(1)}/{m.group(2)}"


def _normalize_key(value: str) -> str:
    text = (value or "").strip().lower()
    text = re.sub(r"[^\w\s:/.-]+", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def _hash(query: str) -> str:
    return hashlib.sha256(_normalize_key(query).encode()).hexdigest()


def _ttl_cutoff(ttl_days: Optional[int] = None) -> int:
    days = ttl_days if ttl_days is not None else Config.CACHE_TTL_DAYS
    return int(time.time()) - days * 86_400


def _now_ts() -> int:
    return int(time.time())


def _canonical_for_track(track) -> Optional[str]:
    def _g(attr):
        if isinstance(track, dict):
            return (track.get(attr) or "").strip()
        return (getattr(track, attr, "") or "").strip()

    title = _g("title")
    artist = _g("artist")
    if not title:
        return None
    return f"{title} {artist}".strip() if artist else title


def _title_artist_norm(title: str, artist: str) -> str:
    return _normalize_key(f"{(title or '').strip()} {(artist or '').strip()}".strip())


def _table_exists(conn: sqlite3.Connection, name: str, kind: str = "table") -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = ? AND name = ? LIMIT 1",
        (kind, name),
    ).fetchone()
    return row is not None


def _schema_is_current(conn: sqlite3.Connection) -> bool:
    version = int(conn.execute("PRAGMA user_version").fetchone()[0] or 0)
    return (
        version == _SCHEMA_VERSION
        and _table_exists(conn, "cache_tracks")
        and _table_exists(conn, "cache_sources")
        and _table_exists(conn, "cache_queries")
        and _table_exists(conn, "song_cache", "view")
        and _table_exists(conn, "query_aliases", "view")
    )


def _rebuild_schema(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA foreign_keys=OFF")
    for kind, name in (
        ("view", "song_cache"),
        ("view", "query_aliases"),
        ("table", "query_aliases"),
        ("table", "song_cache"),
        ("table", "cache_queries"),
        ("table", "cache_sources"),
        ("table", "cache_tracks"),
    ):
        if _table_exists(conn, name, kind):
            conn.execute(f"DROP {kind.upper()} {name}")

    conn.executescript(
        """
        CREATE TABLE cache_tracks (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            canonical_query_hash  TEXT    NOT NULL UNIQUE,
            canonical_query_raw   TEXT    NOT NULL,
            normalized_query      TEXT    NOT NULL UNIQUE,
            canonical_title       TEXT    NOT NULL DEFAULT '',
            canonical_artist      TEXT    NOT NULL DEFAULT '',
            created_at            INTEGER NOT NULL DEFAULT (strftime('%s','now')),
            updated_at            INTEGER NOT NULL DEFAULT (strftime('%s','now')),
            is_active             INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE cache_sources (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            track_id          INTEGER NOT NULL REFERENCES cache_tracks(id) ON DELETE CASCADE,
            webpage_url       TEXT    NOT NULL DEFAULT '',
            stream_url        TEXT    NOT NULL DEFAULT '',
            stream_expires_at INTEGER NOT NULL DEFAULT 0,
            last_stream_check INTEGER NOT NULL DEFAULT 0,
            source            TEXT    NOT NULL DEFAULT 'youtube',
            resolved_title    TEXT    NOT NULL DEFAULT '',
            resolved_artist   TEXT    NOT NULL DEFAULT '',
            duration          INTEGER NOT NULL DEFAULT 0,
            thumbnail         TEXT    NOT NULL DEFAULT '',
            thumbnail_source  TEXT    NOT NULL DEFAULT '',
            thumbnail_confidence REAL NOT NULL DEFAULT 0.0,
            spotify_url       TEXT    NOT NULL DEFAULT '',
            source_confidence REAL    NOT NULL DEFAULT 1.0,
            created_at        INTEGER NOT NULL DEFAULT (strftime('%s','now')),
            last_used         INTEGER NOT NULL DEFAULT (strftime('%s','now')),
            hit_count         INTEGER NOT NULL DEFAULT 1,
            is_valid          INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE cache_queries (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            query_hash       TEXT    NOT NULL UNIQUE,
            query_raw        TEXT    NOT NULL,
            query_norm       TEXT    NOT NULL,
            track_id         INTEGER NOT NULL REFERENCES cache_tracks(id) ON DELETE CASCADE,
            source_id        INTEGER NOT NULL REFERENCES cache_sources(id) ON DELETE CASCADE,
            alias_type       TEXT    NOT NULL DEFAULT 'text',
            match_method     TEXT    NOT NULL DEFAULT 'canonical',
            match_confidence REAL    NOT NULL DEFAULT 1.0,
            first_seen       INTEGER NOT NULL DEFAULT (strftime('%s','now')),
            last_seen        INTEGER NOT NULL DEFAULT (strftime('%s','now')),
            hit_count        INTEGER NOT NULL DEFAULT 1,
            is_confirmed     INTEGER NOT NULL DEFAULT 1,
            is_active        INTEGER NOT NULL DEFAULT 1
        );

        CREATE UNIQUE INDEX idx_cache_sources_webpage
            ON cache_sources(webpage_url) WHERE webpage_url != '';
        CREATE UNIQUE INDEX idx_cache_sources_spotify
            ON cache_sources(spotify_url) WHERE spotify_url != '';
        CREATE INDEX idx_cache_sources_track
            ON cache_sources(track_id, is_valid, hit_count DESC, last_used DESC);
        CREATE INDEX idx_cache_tracks_norm
            ON cache_tracks(normalized_query);
        CREATE INDEX idx_cache_queries_track
            ON cache_queries(track_id, source_id, is_active);
        CREATE INDEX idx_cache_queries_norm
            ON cache_queries(query_norm, is_active);
        CREATE INDEX idx_cache_queries_alias
            ON cache_queries(alias_type, is_active);

        CREATE VIEW song_cache AS
        SELECT
            s.id                                  AS id,
            t.canonical_query_hash                AS query_hash,
            t.canonical_query_raw                 AS query_raw,
            s.webpage_url                         AS webpage_url,
            s.stream_url                          AS stream_url,
            s.stream_expires_at                   AS stream_expires_at,
            s.source                              AS source,
            COALESCE(NULLIF(s.resolved_title, ''),  t.canonical_title)  AS title,
            COALESCE(NULLIF(s.resolved_artist, ''), t.canonical_artist) AS artist,
            s.duration                            AS duration,
            s.thumbnail                           AS thumbnail,
            s.thumbnail_source                    AS thumbnail_source,
            s.thumbnail_confidence                AS thumbnail_confidence,
            s.spotify_url                         AS spotify_url,
            s.created_at                          AS created_at,
            s.last_used                           AS last_used,
            s.hit_count                           AS hit_count,
            s.is_valid                            AS is_valid
        FROM cache_sources s
        JOIN cache_tracks t ON t.id = s.track_id
        WHERE t.is_active = 1;

        CREATE VIEW query_aliases AS
        SELECT
            q.id          AS id,
            q.query_hash  AS query_hash,
            q.query_raw   AS query_raw,
            q.alias_type  AS alias_type,
            q.source_id   AS cache_id
        FROM cache_queries q
        WHERE q.is_active = 1;
        """
    )
    conn.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
    conn.commit()
    conn.execute("PRAGMA foreign_keys=ON")


def rebuild_database(db_path: Union[str, Path, None] = None) -> str:
    global _conn
    if db_path is not None:
        Config.DB_PATH = str(db_path)
    if _conn is not None:
        _conn.close()
        _conn = None
    Path(Config.DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(Config.DB_PATH, check_same_thread=False, timeout=10)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        _rebuild_schema(conn)
    finally:
        conn.close()
    return Config.DB_PATH


def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        with _lock:
            if _conn is None:
                Path(Config.DB_PATH).parent.mkdir(parents=True, exist_ok=True)
                _conn = sqlite3.connect(
                    Config.DB_PATH,
                    check_same_thread=False,
                    timeout=10,
                )
                _conn.row_factory = sqlite3.Row
                _conn.execute("PRAGMA journal_mode=WAL")
                _conn.execute("PRAGMA synchronous=NORMAL")
                _conn.execute("PRAGMA foreign_keys=ON")
                if not _schema_is_current(_conn):
                    log.warning(tag("CACHE_DB", "schema legacy o assente: rebuild automatico del cache DB"))
                    _rebuild_schema(_conn)
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


def _close() -> None:
    global _conn, _enabled
    with _lock:
        if _conn is not None:
            _conn.close()
            _conn = None
        _enabled = False


def _cleanup_orphans(cur: sqlite3.Cursor) -> None:
    cur.execute(
        """
        DELETE FROM cache_tracks
         WHERE id IN (
            SELECT t.id
              FROM cache_tracks t
              LEFT JOIN cache_sources s ON s.track_id = t.id
             WHERE s.id IS NULL
         )
        """
    )


def _load_ids(conn: sqlite3.Connection, table: str) -> list[int]:
    rows = conn.execute(f"SELECT id FROM {table} ORDER BY id ASC").fetchall()
    return [int(row[0]) for row in rows]


def _id_mapping(ids: list[int]) -> dict[int, int]:
    return {old_id: new_id for new_id, old_id in enumerate(ids, start=1)}


def _apply_id_map(
    conn: sqlite3.Connection,
    table: str,
    id_map: dict[int, int],
    fk_updates: list[tuple[str, str]],
) -> None:
    if not id_map:
        return
    for old_id, new_id in id_map.items():
        if old_id == new_id:
            continue
        temp_id = -new_id
        conn.execute(f"UPDATE {table} SET id = ? WHERE id = ?", (temp_id, old_id))
        for fk_table, fk_col in fk_updates:
            conn.execute(f"UPDATE {fk_table} SET {fk_col} = ? WHERE {fk_col} = ?", (temp_id, old_id))

    conn.execute(f"UPDATE {table} SET id = -id WHERE id < 0")
    for fk_table, fk_col in fk_updates:
        conn.execute(f"UPDATE {fk_table} SET {fk_col} = -{fk_col} WHERE {fk_col} < 0")


def _reset_sqlite_sequence(conn: sqlite3.Connection, table: str) -> None:
    if not _table_exists(conn, "sqlite_sequence"):
        return
    max_id = int(conn.execute(f"SELECT COALESCE(MAX(id), 0) FROM {table}").fetchone()[0] or 0)
    conn.execute("DELETE FROM sqlite_sequence WHERE name = ?", (table,))
    if max_id > 0:
        conn.execute("INSERT INTO sqlite_sequence(name, seq) VALUES(?, ?)", (table, max_id))


def _source_row(cur: sqlite3.Cursor, source_id: int) -> Optional[sqlite3.Row]:
    cur.execute("SELECT * FROM song_cache WHERE id = ? LIMIT 1", (int(source_id),))
    return cur.fetchone()


def _track_for_query(cur: sqlite3.Cursor, canonical_query: str) -> Optional[sqlite3.Row]:
    h = _hash(canonical_query)
    cur.execute(
        """
        SELECT t.*, s.id AS source_id
          FROM cache_tracks t
          JOIN cache_sources s ON s.track_id = t.id
         WHERE t.canonical_query_hash = ? AND s.is_valid = 1
         ORDER BY s.hit_count DESC, s.last_used DESC, s.id ASC
         LIMIT 1
        """,
        (h,),
    )
    row = cur.fetchone()
    if row:
        return row
    cur.execute(
        """
        SELECT t.*, s.id AS source_id
          FROM cache_queries q
          JOIN cache_tracks t ON t.id = q.track_id
          JOIN cache_sources s ON s.id = q.source_id
         WHERE q.query_hash = ? AND q.is_active = 1 AND s.is_valid = 1
         ORDER BY q.hit_count DESC, q.last_seen DESC, q.id ASC
         LIMIT 1
        """,
        (h,),
    )
    return cur.fetchone()


def _find_source_by_identifiers(
    cur: sqlite3.Cursor,
    webpage_url: str,
    spotify_url: str,
) -> Optional[sqlite3.Row]:
    if spotify_url:
        cur.execute(
            "SELECT * FROM cache_sources WHERE spotify_url = ? LIMIT 1",
            (spotify_url,),
        )
        row = cur.fetchone()
        if row:
            return row
    if webpage_url:
        cur.execute(
            "SELECT * FROM cache_sources WHERE webpage_url = ? LIMIT 1",
            (webpage_url,),
        )
        row = cur.fetchone()
        if row:
            return row
    return None


def _find_track_by_norm(cur: sqlite3.Cursor, normalized_query: str) -> Optional[sqlite3.Row]:
    cur.execute(
        "SELECT * FROM cache_tracks WHERE normalized_query = ? LIMIT 1",
        (normalized_query,),
    )
    return cur.fetchone()


def _upsert_query(
    cur: sqlite3.Cursor,
    query_raw: str,
    track_id: int,
    source_id: int,
    alias_type: str,
    match_method: str,
    match_confidence: float = 1.0,
) -> None:
    raw = (query_raw or "").strip()
    if not raw:
        return
    query_hash = _hash(raw)
    query_norm = _normalize_key(raw)
    now = _now_ts()
    cur.execute(
        """
        INSERT INTO cache_queries
            (query_hash, query_raw, query_norm, track_id, source_id,
             alias_type, match_method, match_confidence, first_seen, last_seen, hit_count, is_confirmed, is_active)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 1, 1)
        ON CONFLICT(query_hash) DO UPDATE SET
            query_raw = excluded.query_raw,
            query_norm = excluded.query_norm,
            track_id = excluded.track_id,
            source_id = excluded.source_id,
            alias_type = excluded.alias_type,
            match_method = excluded.match_method,
            match_confidence = excluded.match_confidence,
            last_seen = excluded.last_seen,
            hit_count = cache_queries.hit_count + 1,
            is_confirmed = 1,
            is_active = 1
        """,
        (
            query_hash,
            raw,
            query_norm,
            int(track_id),
            int(source_id),
            alias_type or "text",
            match_method or "canonical",
            float(match_confidence or 0.0),
            now,
            now,
        ),
    )


def _touch_hit(cur: sqlite3.Cursor, query_hash: str, source_id: int) -> None:
    now = _now_ts()
    cur.execute(
        "UPDATE cache_sources SET last_used = ?, hit_count = hit_count + 1 WHERE id = ?",
        (now, int(source_id)),
    )
    cur.execute(
        "UPDATE cache_queries SET last_seen = ?, hit_count = hit_count + 1 WHERE query_hash = ?",
        (now, query_hash),
    )


def _canonical_alias_type(raw_query: str, canonical_query: str) -> str:
    if _is_spotify_url(raw_query):
        return "spotify"
    return "canonical" if _normalize_key(raw_query) == _normalize_key(canonical_query) else "text"


def _infer_thumbnail_source(thumbnail: str, spotify_url: str, source: str) -> str:
    thumb = (thumbnail or "").lower()
    if not thumb:
        return ""
    if "i.scdn.co" in thumb:
        return "spotify"
    if "ytimg.com" in thumb or "googleusercontent.com" in thumb:
        return "youtube"
    return (source or "unknown").strip().lower() or "unknown"


def _thumbnail_priority(source: str) -> int:
    return {
        "spotify": 90,
        "apple": 80,
        "youtube": 45,
        "soundcloud": 40,
        "unknown": 10,
        "": 0,
    }.get((source or "").strip().lower(), 20)


def is_enabled() -> bool:
    return _enabled


def init() -> None:
    _get_conn()


def init_db(
    db_path: Union[str, Path, None] = None,
    enabled: bool = True,
) -> None:
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
        f"max={b(str(Config.CACHE_MAX_ENTRIES))}  "
        f"schema=v{_SCHEMA_VERSION}"
    ))


def get(query: str) -> Optional[dict]:
    if not query or not _enabled:
        return None

    query_raw = query.strip()
    query_hash = _hash(query_raw)
    cutoff = _ttl_cutoff()

    with _cursor() as cur:
        cur.execute(
            """
            SELECT q.query_hash, q.query_raw AS matched_query, q.alias_type, q.match_method,
                   s.id AS source_id, sc.*
              FROM cache_queries q
              JOIN cache_sources s ON s.id = q.source_id
              JOIN song_cache sc ON sc.id = s.id
             WHERE q.query_hash = ?
               AND q.is_active = 1
               AND s.is_valid = 1
               AND s.last_used >= ?
             LIMIT 1
            """,
            (query_hash, cutoff),
        )
        row = cur.fetchone()

        if row is None and _is_spotify_url(query_raw):
            spotify_url = _extract_spotify_id(query_raw)
            cur.execute(
                """
                SELECT s.id AS source_id, sc.*
                  FROM cache_sources s
                  JOIN song_cache sc ON sc.id = s.id
                 WHERE s.spotify_url = ?
                   AND s.is_valid = 1
                   AND s.last_used >= ?
                 LIMIT 1
                """,
                (spotify_url, cutoff),
            )
            row = cur.fetchone()
            if row:
                cur.execute(
                    "SELECT track_id FROM cache_sources WHERE id = ? LIMIT 1",
                    (row["source_id"],),
                )
                track_id = int(cur.fetchone()["track_id"])
                _upsert_query(cur, spotify_url, track_id, row["source_id"], "spotify", "spotify_url", 1.0)
                query_hash = _hash(spotify_url)

        if row is None:
            log.info(tag("CACHE_DB", f"\U0001f50d {hi('MISS', _GRY)}  {b(query_raw)}"))
            return None

        _touch_hit(cur, query_hash, int(row["source_id"]))
        result = dict(row)
        result["id"] = int(row["source_id"])

    label = f"{b(result.get('title') or query_raw)}" + (f"  {result.get('artist')}" if result.get("artist") else "")
    log.info(tag("CACHE_DB", f"\u2705 {hi('HIT', _BGRN)}  {label}"))
    return result


def put(query: str, track) -> None:
    if not query or not _enabled:
        return

    query_raw = query.strip()

    def _g(attr: str, default=None):
        if isinstance(track, dict):
            return track.get(attr, default)
        return getattr(track, attr, default)

    webpage_url = (_g("webpage_url", "") or "").strip()
    if not webpage_url:
        return

    title = (_g("title", "") or "").strip() or query_raw
    artist = (_g("artist", "") or "").strip()
    source = (_g("source", "youtube") or "youtube").strip()
    duration = int(_g("duration") or 0)
    thumbnail = (_g("thumbnail", "") or "").strip()
    spotify_url = (_g("spotify_url", "") or "").strip()
    stream_url = (_g("stream_url", "") or "").strip()
    if _is_spotify_url(query_raw):
        spotify_url = spotify_url or _extract_spotify_id(query_raw)
    elif spotify_url:
        spotify_url = _extract_spotify_id(spotify_url)
    now = _now_ts()
    thumbnail_source = (_g("thumbnail_source", "") or "").strip().lower()
    if not thumbnail_source:
        thumbnail_source = _infer_thumbnail_source(thumbnail, spotify_url, source)
    thumbnail_priority = _thumbnail_priority(thumbnail_source) / 100.0
    thumbnail_confidence = float(_g("thumbnail_confidence", 0.0) or 0.0)
    if thumbnail and thumbnail_confidence <= 0:
        thumbnail_confidence = thumbnail_priority
    stream_expires_at = now + _STREAM_URL_DB_TTL_SECONDS if stream_url else 0

    canonical_query = (_canonical_for_track(track) or query_raw).strip()
    canonical_hash = _hash(canonical_query)
    normalized_query = _normalize_key(canonical_query)

    with _cursor() as cur:
        existing_source = _find_source_by_identifiers(cur, webpage_url, spotify_url)
        track_row = None

        if existing_source:
            cur.execute("SELECT * FROM cache_tracks WHERE id = ? LIMIT 1", (existing_source["track_id"],))
            track_row = cur.fetchone()
        if track_row is None:
            track_row = _find_track_by_norm(cur, normalized_query)

        if track_row is None:
            cur.execute(
                """
                INSERT INTO cache_tracks
                    (canonical_query_hash, canonical_query_raw, normalized_query,
                     canonical_title, canonical_artist, created_at, updated_at, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                """,
                (canonical_hash, canonical_query, normalized_query, title, artist, now, now),
            )
            track_id = int(cur.lastrowid)
        else:
            track_id = int(track_row["id"])
            cur.execute(
                """
                UPDATE cache_tracks
                   SET canonical_query_hash = ?,
                       canonical_query_raw = ?,
                       normalized_query = ?,
                       canonical_title = ?,
                       canonical_artist = ?,
                       updated_at = ?,
                       is_active = 1
                 WHERE id = ?
                """,
                (canonical_hash, canonical_query, normalized_query, title, artist, now, track_id),
            )

        if existing_source:
            source_id = int(existing_source["id"])
            cur.execute(
                """
                UPDATE cache_sources
                   SET track_id = ?,
                       webpage_url = CASE WHEN ? != '' THEN ? ELSE webpage_url END,
                       stream_url = CASE WHEN ? != '' THEN ? ELSE stream_url END,
                       stream_expires_at = CASE WHEN ? != '' THEN ? ELSE stream_expires_at END,
                       last_stream_check = CASE WHEN ? != '' THEN ? ELSE last_stream_check END,
                       source = ?,
                       resolved_title = ?,
                       resolved_artist = ?,
                       duration = ?,
                       thumbnail = CASE
                           WHEN ? = '' THEN thumbnail
                           WHEN thumbnail = '' THEN ?
                           WHEN ? >= thumbnail_confidence THEN ?
                           WHEN ? > thumbnail_confidence THEN ?
                           ELSE thumbnail
                       END,
                       thumbnail_source = CASE
                           WHEN ? = '' THEN thumbnail_source
                           WHEN thumbnail = '' THEN ?
                           WHEN ? >= thumbnail_confidence THEN ?
                           WHEN ? > thumbnail_confidence THEN ?
                           ELSE thumbnail_source
                       END,
                       thumbnail_confidence = CASE
                           WHEN ? = '' THEN thumbnail_confidence
                           WHEN thumbnail = '' THEN ?
                           WHEN ? >= thumbnail_confidence THEN ?
                           WHEN ? > thumbnail_confidence THEN ?
                           ELSE thumbnail_confidence
                       END,
                       spotify_url = CASE WHEN ? != '' THEN ? ELSE spotify_url END,
                       last_used = ?,
                       hit_count = hit_count + 1,
                       is_valid = 1
                 WHERE id = ?
                """,
                (
                    track_id,
                    webpage_url, webpage_url,
                    stream_url, stream_url,
                    stream_url, stream_expires_at,
                    stream_url, now,
                    source,
                    title,
                    artist,
                    duration,
                    thumbnail,
                    thumbnail,
                    thumbnail_confidence,
                    thumbnail,
                    thumbnail_priority,
                    thumbnail,
                    thumbnail,
                    thumbnail_source,
                    thumbnail_confidence,
                    thumbnail_source,
                    thumbnail_priority,
                    thumbnail_source,
                    thumbnail,
                    thumbnail_confidence,
                    thumbnail_confidence,
                    thumbnail_confidence,
                    thumbnail_priority,
                    thumbnail_confidence,
                    spotify_url, spotify_url,
                    now,
                    source_id,
                ),
            )
        else:
            cur.execute(
                """
                INSERT INTO cache_sources
                    (track_id, webpage_url, stream_url, stream_expires_at, last_stream_check,
                     source, resolved_title, resolved_artist,
                     duration, thumbnail, thumbnail_source, thumbnail_confidence,
                     spotify_url, source_confidence,
                     created_at, last_used, hit_count, is_valid)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1.0, ?, ?, 1, 1)
                """,
                (
                    track_id,
                    webpage_url,
                    stream_url,
                    stream_expires_at,
                    now if stream_url else 0,
                    source,
                    title,
                    artist,
                    duration,
                    thumbnail,
                    thumbnail_source,
                    thumbnail_confidence,
                    spotify_url,
                    now,
                    now,
                ),
            )
            source_id = int(cur.lastrowid)

        _upsert_query(cur, canonical_query, track_id, source_id, "canonical", "canonical", 1.0)
        if _normalize_key(query_raw) != _normalize_key(canonical_query):
            _upsert_query(
                cur,
                query_raw,
                track_id,
                source_id,
                _canonical_alias_type(query_raw, canonical_query),
                "same_source" if existing_source else "canonical_metadata",
                1.0,
            )
        if spotify_url and _normalize_key(spotify_url) != _normalize_key(query_raw):
            _upsert_query(cur, spotify_url, track_id, source_id, "spotify", "spotify_url", 1.0)

    _maybe_trim()


def add_alias(alias: str, canonical_query: str, alias_type: str = "text") -> None:
    if not alias or not canonical_query or not _enabled:
        return
    with _cursor() as cur:
        track_row = _track_for_query(cur, canonical_query)
        if track_row is None:
            return
        _upsert_query(
            cur,
            alias.strip(),
            int(track_row["id"]),
            int(track_row["source_id"]),
            alias_type or "text",
            "manual_alias",
            1.0,
        )
    log.debug(tag("CACHE_DB", f"\U0001f517 {hi('ALIAS', _GRY)}  {alias_type or 'text'}  \u2192 {b(canonical_query)}"))


def invalidate(query: str) -> bool:
    if not query:
        return False
    query_hash = _hash(query)
    with _cursor() as cur:
        cur.execute("SELECT source_id FROM cache_queries WHERE query_hash = ? LIMIT 1", (query_hash,))
        row = cur.fetchone()
        if row is None:
            return False
        cur.execute("UPDATE cache_sources SET is_valid = 0 WHERE id = ? AND is_valid = 1", (row["source_id"],))
        found = cur.rowcount > 0
    if found:
        log.info(tag("CACHE_DB", f"\U0001f6ab {hi('INVALIDATE', _BYEL)}  {b(query)}"))
    return found


def invalidate_webpage_url(webpage_url: str) -> int:
    url = (webpage_url or "").strip()
    if not url or not _enabled:
        return 0
    with _cursor() as cur:
        cur.execute(
            "UPDATE cache_sources SET is_valid = 0 WHERE webpage_url = ? AND is_valid = 1",
            (url,),
        )
        count = cur.rowcount
    if count:
        log.info(tag("CACHE_DB", f"\U0001f6ab {hi('INVALIDATE', _BYEL)}  url  {b(str(count))} entry"))
    return count


def update_stream_url(webpage_url: str, stream_url: str, ttl_seconds: int = _STREAM_URL_DB_TTL_SECONDS) -> bool:
    url = (webpage_url or "").strip()
    stream = (stream_url or "").strip()
    if not url or not stream or not _enabled:
        return False
    now = _now_ts()
    with _cursor() as cur:
        cur.execute(
            """
            UPDATE cache_sources
               SET stream_url = ?,
                   stream_expires_at = ?,
                   last_stream_check = ?
             WHERE webpage_url = ? AND is_valid = 1
            """,
            (stream, now + int(ttl_seconds), now, url),
        )
        return cur.rowcount > 0


def stats() -> dict:
    if not _enabled:
        return {"enabled": False, "total": 0, "valid": 0, "hits": 0, "hits_total": 0,
                "aliases": 0, "size_kb": 0, "db_path": Config.DB_PATH, "top_query": None}
    with _cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM cache_sources")
        total = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM cache_sources WHERE is_valid = 1")
        valid = cur.fetchone()[0]
        cur.execute("SELECT COALESCE(SUM(hit_count), 0) FROM cache_sources")
        hits = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM cache_queries WHERE is_active = 1")
        aliases = cur.fetchone()[0]
        cur.execute(
            """
            SELECT q.query_raw, q.hit_count
              FROM cache_queries q
             WHERE q.is_active = 1
             ORDER BY q.hit_count DESC, q.last_seen DESC
             LIMIT 1
            """
        )
        top_row = cur.fetchone()

    try:
        size_kb = round(Path(Config.DB_PATH).stat().st_size / 1024, 1)
    except OSError:
        size_kb = 0.0

    return {
        "enabled": True,
        "total": total,
        "valid": valid,
        "hits": hits,
        "hits_total": hits,
        "aliases": aliases,
        "size_kb": size_kb,
        "db_path": Config.DB_PATH,
        "top_query": dict(top_row) if top_row else None,
    }


def inspect(query: str) -> dict:
    result = {
        "query_raw": query,
        "query_hash": _hash(query),
        "query_norm": _normalize_key(query),
        "found": False,
        "row": None,
    }
    if not _enabled or not query:
        return result
    row = get(query)
    if row:
        result["found"] = True
        result["row"] = row
    return result


def dedupe_canonical(dry_run: bool = True) -> dict:
    if not _enabled:
        return {"groups": 0, "duplicates": 0, "applied": False}

    with _cursor() as cur:
        rows = cur.execute(
            """
            SELECT
                t.id AS track_id,
                t.normalized_query,
                t.canonical_title,
                t.canonical_artist,
                COALESCE(SUM(s.hit_count), 0) AS hits
            FROM cache_tracks t
            LEFT JOIN cache_sources s ON s.track_id = t.id
            GROUP BY t.id, t.normalized_query, t.canonical_title, t.canonical_artist
            ORDER BY hits DESC, t.id ASC
            """
        ).fetchall()
        groups: dict[str, list[sqlite3.Row]] = {}
        for row in rows:
            key = _title_artist_norm(row["canonical_title"], row["canonical_artist"]) or row["normalized_query"]
            groups.setdefault(key, []).append(row)
        duplicate_groups = [grp for grp in groups.values() if len(grp) > 1]

        if not dry_run:
            for grp in duplicate_groups:
                keeper = grp[0]
                keep_id = int(keeper["track_id"])
                for row in grp[1:]:
                    old_id = int(row["track_id"])
                    cur.execute("UPDATE cache_sources SET track_id = ? WHERE track_id = ?", (keep_id, old_id))
                    cur.execute("UPDATE cache_queries SET track_id = ? WHERE track_id = ?", (keep_id, old_id))
                    cur.execute("DELETE FROM cache_tracks WHERE id = ?", (old_id,))
            _cleanup_orphans(cur)

    duplicate_count = sum(len(grp) - 1 for grp in duplicate_groups)
    return {
        "groups": len(duplicate_groups),
        "duplicates": duplicate_count,
        "applied": not dry_run,
    }


def prune_lru(
    max_entries: int = 500,
    ttl_days: int = 30,
) -> int:
    cutoff = _ttl_cutoff(ttl_days)
    with _cursor() as cur:
        cur.execute("DELETE FROM cache_sources WHERE last_used < ?", (cutoff,))
        expired = cur.rowcount
        cur.execute(
            """
            DELETE FROM cache_sources
             WHERE id NOT IN (
               SELECT id FROM cache_sources
                ORDER BY hit_count DESC, last_used DESC
                LIMIT ?
             )
            """,
            (max_entries,),
        )
        trimmed = cur.rowcount
        _cleanup_orphans(cur)

    total_removed = expired + trimmed
    if total_removed:
        log.info(tag(
            "CACHE_DB",
            f"\u2702\ufe0f  {hi('PRUNE', _BYEL)}  scadute={b(str(expired))}  eccedenze={b(str(trimmed))}  "
            f"max={max_entries}  ttl={ttl_days}d"
        ))
    return total_removed


def clear() -> int:
    with _cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM cache_sources")
        n = int(cur.fetchone()[0])
        cur.execute("DELETE FROM cache_queries")
        cur.execute("DELETE FROM cache_sources")
        cur.execute("DELETE FROM cache_tracks")
    log.info(tag("CACHE_DB", f"\U0001f5d1\ufe0f  {hi('CLEAR', _BRED)}  {b(str(n))} entry eliminate"))
    return n


def clear_all() -> int:
    return clear()


def list_song_rows(
    search: str = "",
    source: str = "",
    valid: str = "",
    sort: str = "hit_count",
    order: str = "DESC",
) -> list[dict]:
    allowed = {"hit_count", "created_at", "last_used", "title", "artist", "id"}
    sort = sort if sort in allowed else "hit_count"
    order = "DESC" if str(order).upper() == "DESC" else "ASC"

    filters, params = [], []
    if search:
        filters.append("(LOWER(title) LIKE ? OR LOWER(artist) LIKE ? OR LOWER(query_raw) LIKE ?)")
        params += [f"%{search.lower()}%"] * 3
    if source:
        filters.append("source = ?")
        params.append(source)
    if valid in ("1", "0"):
        filters.append("is_valid = ?")
        params.append(int(valid))

    where = ("WHERE " + " AND ".join(filters)) if filters else ""
    with _cursor() as cur:
        rows = cur.execute(
            f"SELECT * FROM song_cache {where} ORDER BY {sort} {order}",
            params,
        ).fetchall()
    return [dict(r) for r in rows]


def list_alias_rows() -> list[dict]:
    with _cursor() as cur:
        rows = cur.execute(
            """
            SELECT qa.id, qa.query_raw, qa.cache_id,
                   qa.alias_type, sc.title, sc.artist, sc.spotify_url, sc.webpage_url
              FROM query_aliases qa
              LEFT JOIN song_cache sc ON sc.id = qa.cache_id
             ORDER BY qa.id DESC
            """
        ).fetchall()
    return [dict(r) for r in rows]


def list_track_rows() -> list[dict]:
    with _cursor() as cur:
        rows = cur.execute(
            """
            SELECT
                t.id,
                t.canonical_title,
                t.canonical_artist,
                t.normalized_query,
                t.created_at,
                t.updated_at,
                COUNT(DISTINCT s.id) AS source_count,
                COUNT(DISTINCT q.id) AS query_count
            FROM cache_tracks t
            LEFT JOIN cache_sources s ON s.track_id = t.id
            LEFT JOIN cache_queries q ON q.track_id = t.id AND q.is_active = 1
            GROUP BY t.id, t.canonical_title, t.canonical_artist, t.normalized_query, t.created_at, t.updated_at
            ORDER BY t.id DESC
            """
        ).fetchall()
    return [dict(r) for r in rows]


def list_source_rows() -> list[dict]:
    with _cursor() as cur:
        rows = cur.execute(
            """
            SELECT
                s.id,
                s.track_id,
                t.canonical_title,
                t.canonical_artist,
                s.source,
                s.resolved_title,
                s.resolved_artist,
                s.webpage_url,
                s.stream_expires_at,
                s.spotify_url,
                s.duration,
                s.thumbnail,
                s.thumbnail_source,
                s.thumbnail_confidence,
                s.is_valid,
                s.hit_count,
                s.created_at,
                s.last_used
            FROM cache_sources s
            JOIN cache_tracks t ON t.id = s.track_id
            ORDER BY s.id DESC
            """
        ).fetchall()
    return [dict(r) for r in rows]


def list_query_rows() -> list[dict]:
    with _cursor() as cur:
        rows = cur.execute(
            """
            SELECT
                q.id,
                q.track_id,
                q.source_id,
                q.query_raw,
                q.query_norm,
                q.alias_type,
                q.match_confidence AS confidence,
                q.is_active,
                q.hit_count,
                q.first_seen AS created_at,
                q.last_seen,
                t.canonical_title,
                t.canonical_artist,
                s.source,
                s.spotify_url,
                s.webpage_url
            FROM cache_queries q
            JOIN cache_tracks t ON t.id = q.track_id
            JOIN cache_sources s ON s.id = q.source_id
            ORDER BY q.id DESC
            """
        ).fetchall()
    return [dict(r) for r in rows]


def schema_overview() -> list[dict]:
    counts = stats()
    with _cursor() as cur:
        track_count = int(cur.execute("SELECT COUNT(*) FROM cache_tracks").fetchone()[0])
        source_count = int(cur.execute("SELECT COUNT(*) FROM cache_sources").fetchone()[0])
        query_count = int(cur.execute("SELECT COUNT(*) FROM cache_queries").fetchone()[0])

    return [
        {
            "name": "cache_tracks",
            "kind": "table",
            "pk": "id",
            "count": track_count,
            "purpose": "Identita canonica del brano: titolo, artista e chiave normalizzata.",
        },
        {
            "name": "cache_sources",
            "kind": "table",
            "pk": "id",
            "count": source_count,
            "purpose": "Sorgente risolta e riproducibile: URL, durata, validita, hit e mapping Spotify.",
        },
        {
            "name": "cache_queries",
            "kind": "table",
            "pk": "id",
            "count": query_count,
            "purpose": "Query osservate, alias confermati, confidence e collegamento a track/source.",
        },
        {
            "name": "song_cache",
            "kind": "view",
            "pk": "id (source_id)",
            "count": counts["total"],
            "purpose": "Vista operativa compatibile per dashboard e resolver: una riga per sorgente valida o storica.",
        },
        {
            "name": "query_aliases",
            "kind": "view",
            "pk": "id (query_id)",
            "count": counts["aliases"],
            "purpose": "Vista compatibile delle associazioni query/alias senza esporre tutta la tabella tecnica.",
        },
    ]


def associate_spotify(spotify_url: str, title: str = "", artist: str = "") -> dict:
    raw_url = (spotify_url or "").strip()
    title = (title or "").strip().lower()
    artist = (artist or "").strip().lower()
    if not raw_url or not _RE_SPOTIFY.search(raw_url):
        return {"ok": False, "action": "invalid_url", "cache_id": None}

    normalized_spotify = _extract_spotify_id(raw_url)
    h_spotify = _hash(normalized_spotify)

    with _cursor() as cur:
        cur.execute(
            "SELECT id FROM cache_sources WHERE spotify_url = ? AND is_valid = 1 LIMIT 1",
            (normalized_spotify,),
        )
        row = cur.fetchone()
        if row:
            return {"ok": True, "action": "already_set", "cache_id": int(row["id"])}

        cur.execute("SELECT source_id FROM cache_queries WHERE query_hash = ? LIMIT 1", (h_spotify,))
        alias_row = cur.fetchone()
        if alias_row:
            return {"ok": True, "action": "already_alias", "cache_id": int(alias_row["source_id"])}

        target = None
        if title:
            filters, params = ["LOWER(COALESCE(NULLIF(resolved_title, ''), '')) LIKE ?"], [f"%{title}%"]
            if artist:
                filters.append("LOWER(COALESCE(NULLIF(resolved_artist, ''), '')) LIKE ?")
                params.append(f"%{artist}%")
            cur.execute(
                f"SELECT * FROM cache_sources WHERE {' AND '.join(filters)} AND is_valid = 1 LIMIT 1",
                params,
            )
            target = cur.fetchone()

        if target is None:
            return {"ok": False, "action": "not_found", "cache_id": None}

        source_id = int(target["id"])
        track_id = int(target["track_id"])
        cur.execute(
            "UPDATE cache_sources SET spotify_url = ? WHERE id = ? AND (spotify_url IS NULL OR spotify_url = '')",
            (normalized_spotify, source_id),
        )
        _upsert_query(cur, normalized_spotify, track_id, source_id, "spotify", "manual_spotify", 1.0)

    return {"ok": True, "action": "associated", "cache_id": source_id}


def compact_ids() -> dict:
    conn = _get_conn()
    with _lock:
        conn.execute("PRAGMA foreign_keys=OFF")
        try:
            conn.execute("BEGIN IMMEDIATE")

            track_map = _id_mapping(_load_ids(conn, "cache_tracks"))
            source_map = _id_mapping(_load_ids(conn, "cache_sources"))
            query_map = _id_mapping(_load_ids(conn, "cache_queries"))
            result = {
                "track_rows": len(track_map),
                "track_changed": sum(1 for old_id, new_id in track_map.items() if old_id != new_id),
                "source_rows": len(source_map),
                "source_changed": sum(1 for old_id, new_id in source_map.items() if old_id != new_id),
                "query_rows": len(query_map),
                "query_changed": sum(1 for old_id, new_id in query_map.items() if old_id != new_id),
                "applied": False,
            }

            _apply_id_map(conn, "cache_tracks", track_map, [("cache_sources", "track_id"), ("cache_queries", "track_id")])
            _apply_id_map(conn, "cache_sources", source_map, [("cache_queries", "source_id")])
            _apply_id_map(conn, "cache_queries", query_map, [])

            _reset_sqlite_sequence(conn, "cache_tracks")
            _reset_sqlite_sequence(conn, "cache_sources")
            _reset_sqlite_sequence(conn, "cache_queries")
            conn.commit()

            result["applied"] = True
            return result
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.execute("PRAGMA foreign_keys=ON")


def delete_song_row(row_id: int) -> bool:
    with _cursor() as cur:
        cur.execute("SELECT track_id FROM cache_sources WHERE id = ? LIMIT 1", (int(row_id),))
        row = cur.fetchone()
        if row is None:
            return False
        cur.execute("DELETE FROM cache_sources WHERE id = ?", (int(row_id),))
        _cleanup_orphans(cur)
    compact_ids()
    return True


def delete_alias(alias_id: int) -> bool:
    with _cursor() as cur:
        cur.execute("DELETE FROM cache_queries WHERE id = ?", (int(alias_id),))
        deleted = cur.rowcount > 0
    if deleted:
        compact_ids()
    return deleted


_last_trim = 0.0
_TRIM_INTERVAL = 300


def _maybe_trim() -> None:
    global _last_trim
    now = time.time()
    if now - _last_trim < _TRIM_INTERVAL:
        return
    _last_trim = now
    threading.Thread(target=_trim, daemon=True).start()


def _trim() -> None:
    prune_lru(
        max_entries=Config.CACHE_MAX_ENTRIES,
        ttl_days=Config.CACHE_TTL_DAYS,
    )
