"""
tests/test_cache_alias_type.py

Esegui dalla root del progetto con:
    python tests/test_cache_alias_type.py
"""

import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
import core.cache_db as db


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
        cache_id   INTEGER NOT NULL REFERENCES song_cache(id) ON DELETE CASCADE
    );
    """
)
conn.commit()
conn.close()

Config.DB_PATH = tmp.name
Config.CACHE_TTL_DAYS = 30
Config.CACHE_MAX_ENTRIES = 500

db.init_db(db_path=tmp.name, enabled=True)

conn = sqlite3.connect(tmp.name)
cols = {row[1] for row in conn.execute("PRAGMA table_info(query_aliases)")}
conn.close()
assert "alias_type" in cols, "FAIL: migrazione alias_type non applicata"

track = {
    "title": "Blinding Lights",
    "artist": "The Weeknd",
    "webpage_url": "https://youtube.com/watch?v=YOUTUBE_ID",
    "source": "youtube",
    "duration": 200,
    "thumbnail": "",
    "spotify_url": "",
}

db.put("blinding lights the weeknd", track)
db.add_alias(
    "https://open.spotify.com/track/0VjIjW4GlUZAMYd2vXMi3b",
    "blinding lights the weeknd",
    "spotify",
)

conn = sqlite3.connect(tmp.name)
row = conn.execute(
    "SELECT alias_type FROM query_aliases WHERE query_raw LIKE 'https://open.spotify.com/%'"
).fetchone()
conn.close()

assert row is not None, "FAIL: alias Spotify non inserito"
assert row[0] == "spotify", f"FAIL: alias_type={row[0]!r}, atteso 'spotify'"

db._close()
try:
    os.unlink(tmp.name)
except PermissionError:
    print("(cleanup skipped: Windows file lock -- non e' un errore del codice)")

print("OK: alias_type e migrazione query_aliases")
