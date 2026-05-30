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
    CREATE TABLE song_cache (
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

    CREATE TABLE query_aliases (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        query_hash TEXT    NOT NULL UNIQUE,
        query_raw  TEXT    NOT NULL,
        alias_type TEXT    NOT NULL DEFAULT 'text',
        cache_id   INTEGER NOT NULL REFERENCES song_cache(id) ON DELETE CASCADE
    );
    """
)
conn.execute(
    """
    INSERT INTO song_cache
        (id, query_hash, query_raw, webpage_url, source, title, artist, duration, thumbnail, spotify_url)
    VALUES
        (27, 'h27', 'q27', 'https://youtube.com/watch?v=27', 'youtube', 'Song 27', 'Artist', 100, '', ''),
        (30, 'h30', 'q30', 'https://youtube.com/watch?v=30', 'youtube', 'Song 30', 'Artist', 100, '', '')
    """
)
conn.execute(
    """
    INSERT INTO query_aliases (id, query_hash, query_raw, alias_type, cache_id)
    VALUES
        (9, 'a9', 'alias 9', 'text', 27),
        (14, 'a14', 'alias 14', 'spotify', 30)
    """
)
conn.commit()
conn.close()

dry = renumber(tmp.name, apply=False)
assert dry["song_changed"] == 2, dry
assert dry["alias_changed"] == 2, dry
assert dry["applied"] is False, dry

applied = renumber(tmp.name, apply=True)
assert applied["applied"] is True, applied

conn = sqlite3.connect(tmp.name)
song_rows = conn.execute("SELECT id, query_raw FROM song_cache ORDER BY id ASC").fetchall()
alias_rows = conn.execute("SELECT id, cache_id, query_raw FROM query_aliases ORDER BY id ASC").fetchall()
conn.close()

assert song_rows == [(1, "q27"), (2, "q30")], song_rows
assert alias_rows == [(1, 1, "alias 9"), (2, 2, "alias 14")], alias_rows

try:
    os.unlink(tmp.name)
except PermissionError:
    print("(cleanup skipped: Windows file lock -- non e' un errore del codice)")

print("OK: renumber cache IDs")
