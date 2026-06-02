"""
tests/test_cache_renumber_ids.py

Esegui dalla root del progetto con:
    python tests/test_cache_renumber_ids.py
"""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.renumber_cache_ids import renumber


tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
tmp.close()

conn = sqlite3.connect(tmp.name)
conn.executescript(
    """
    CREATE TABLE cache_tracks (
        id                   INTEGER PRIMARY KEY AUTOINCREMENT,
        canonical_query_hash TEXT NOT NULL UNIQUE,
        canonical_query_raw  TEXT NOT NULL,
        normalized_query     TEXT NOT NULL UNIQUE,
        canonical_title      TEXT NOT NULL DEFAULT '',
        canonical_artist     TEXT NOT NULL DEFAULT '',
        created_at           INTEGER NOT NULL DEFAULT (strftime('%s','now')),
        updated_at           INTEGER NOT NULL DEFAULT (strftime('%s','now')),
        is_active            INTEGER NOT NULL DEFAULT 1
    );

    CREATE TABLE cache_sources (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        track_id        INTEGER NOT NULL REFERENCES cache_tracks(id) ON DELETE CASCADE,
        webpage_url     TEXT NOT NULL DEFAULT '',
        source          TEXT NOT NULL DEFAULT 'youtube',
        resolved_title  TEXT NOT NULL DEFAULT '',
        resolved_artist TEXT NOT NULL DEFAULT '',
        duration        INTEGER NOT NULL DEFAULT 0,
        thumbnail       TEXT NOT NULL DEFAULT '',
        spotify_url     TEXT NOT NULL DEFAULT '',
        source_confidence REAL NOT NULL DEFAULT 1.0,
        created_at      INTEGER NOT NULL DEFAULT (strftime('%s','now')),
        last_used       INTEGER NOT NULL DEFAULT (strftime('%s','now')),
        hit_count       INTEGER NOT NULL DEFAULT 1,
        is_valid        INTEGER NOT NULL DEFAULT 1
    );

    CREATE TABLE cache_queries (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        query_hash       TEXT NOT NULL UNIQUE,
        query_raw        TEXT NOT NULL,
        query_norm       TEXT NOT NULL,
        track_id         INTEGER NOT NULL REFERENCES cache_tracks(id) ON DELETE CASCADE,
        source_id        INTEGER NOT NULL REFERENCES cache_sources(id) ON DELETE CASCADE,
        alias_type       TEXT NOT NULL DEFAULT 'text',
        match_method     TEXT NOT NULL DEFAULT 'canonical',
        match_confidence REAL NOT NULL DEFAULT 1.0,
        first_seen       INTEGER NOT NULL DEFAULT (strftime('%s','now')),
        last_seen        INTEGER NOT NULL DEFAULT (strftime('%s','now')),
        hit_count        INTEGER NOT NULL DEFAULT 1,
        is_confirmed     INTEGER NOT NULL DEFAULT 1,
        is_active        INTEGER NOT NULL DEFAULT 1
    );
    """
)
conn.execute(
    """
    INSERT INTO cache_tracks
        (id, canonical_query_hash, canonical_query_raw, normalized_query, canonical_title, canonical_artist)
    VALUES
        (27, 'h27', 'q27', 'q27', 'Song 27', 'Artist'),
        (30, 'h30', 'q30', 'q30', 'Song 30', 'Artist')
    """
)
conn.execute(
    """
    INSERT INTO cache_sources
        (id, track_id, webpage_url, source, resolved_title, resolved_artist, duration, thumbnail, spotify_url)
    VALUES
        (11, 27, 'https://youtube.com/watch?v=27', 'youtube', 'Song 27', 'Artist', 100, '', ''),
        (18, 30, 'https://youtube.com/watch?v=30', 'youtube', 'Song 30', 'Artist', 100, '', '')
    """
)
conn.execute(
    """
    INSERT INTO cache_queries
        (id, query_hash, query_raw, query_norm, track_id, source_id, alias_type)
    VALUES
        (9, 'a9', 'alias 9', 'alias 9', 27, 11, 'text'),
        (14, 'a14', 'alias 14', 'alias 14', 30, 18, 'spotify')
    """
)
conn.commit()
conn.close()

dry = renumber(tmp.name, apply=False)
assert dry["track_changed"] == 2, dry
assert dry["source_changed"] == 2, dry
assert dry["query_changed"] == 2, dry
assert dry["applied"] is False, dry

applied = renumber(tmp.name, apply=True)
assert applied["applied"] is True, applied

conn = sqlite3.connect(tmp.name)
track_rows = conn.execute("SELECT id, canonical_query_raw FROM cache_tracks ORDER BY id ASC").fetchall()
source_rows = conn.execute("SELECT id, track_id, webpage_url FROM cache_sources ORDER BY id ASC").fetchall()
query_rows = conn.execute("SELECT id, track_id, source_id, query_raw FROM cache_queries ORDER BY id ASC").fetchall()
conn.close()

assert track_rows == [(1, "q27"), (2, "q30")], track_rows
assert source_rows == [(1, 1, "https://youtube.com/watch?v=27"), (2, 2, "https://youtube.com/watch?v=30")], source_rows
assert query_rows == [(1, 1, 1, "alias 9"), (2, 2, 2, "alias 14")], query_rows

try:
    os.unlink(tmp.name)
except PermissionError:
    print("(cleanup skipped: Windows file lock -- non e' un errore del codice)")

print("OK: renumber cache IDs")
