"""
tests/test_dashboard_api.py

Esegui dalla root del progetto con:
    python tests/test_dashboard_api.py
"""

import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["DASH_USER"] = "admin"
os.environ["DASH_PASSWORD"] = "secret-pass"
os.environ["DASH_SECRET_KEY"] = "test-secret-key"

from data.database.dashboard.app import create_app

tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
tmp.close()

conn = sqlite3.connect(tmp.name)
conn.executescript(
    """
    CREATE TABLE song_cache (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        query_hash TEXT NOT NULL UNIQUE,
        query_raw TEXT NOT NULL,
        webpage_url TEXT,
        source TEXT NOT NULL DEFAULT 'youtube',
        title TEXT,
        artist TEXT,
        duration INTEGER,
        thumbnail TEXT,
        spotify_url TEXT,
        created_at INTEGER NOT NULL DEFAULT (strftime('%s','now')),
        last_used INTEGER NOT NULL DEFAULT (strftime('%s','now')),
        hit_count INTEGER NOT NULL DEFAULT 1,
        is_valid INTEGER NOT NULL DEFAULT 1
    );
    CREATE TABLE query_aliases (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        query_hash TEXT NOT NULL UNIQUE,
        query_raw TEXT NOT NULL,
        alias_type TEXT NOT NULL DEFAULT 'text',
        cache_id INTEGER NOT NULL REFERENCES song_cache(id) ON DELETE CASCADE
    );
    INSERT INTO song_cache (query_hash, query_raw, webpage_url, source, title, artist, duration, thumbnail, spotify_url)
    VALUES ('h1', 'song artist', 'https://youtube.com/watch?v=1', 'youtube', 'Song', 'Artist', 100, '', '');
    """
)
conn.commit()
conn.close()

app = create_app(db_path=tmp.name)
client = app.test_client()
with client.session_transaction() as sess:
    sess["auth"] = True

stats = client.get("/api/stats")
assert stats.status_code == 200, stats.data
assert stats.get_json()["total"] == 1

aliases = client.get("/api/aliases")
assert aliases.status_code == 200, aliases.data

assoc = client.post(
    "/api/associate",
    json={
        "spotify_url": "https://open.spotify.com/intl-it/track/abc123?si=x",
        "title": "Song",
        "artist": "Artist",
    },
)
assert assoc.status_code == 200, assoc.data
assert assoc.get_json()["action"] == "associated"

conn = sqlite3.connect(tmp.name)
row = conn.execute("SELECT alias_type FROM query_aliases LIMIT 1").fetchone()
conn.close()
assert row and row[0] == "spotify"

try:
    os.unlink(tmp.name)
except PermissionError:
    print("(cleanup skipped: Windows file lock -- non e' un errore del codice)")

print("OK: dashboard API stats/aliases/associate")
