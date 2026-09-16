"""Schema and identifier maintenance; runtime connections stay in core.cache_db."""
from __future__ import annotations
import sqlite3

_SCHEMA_VERSION = 3


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
