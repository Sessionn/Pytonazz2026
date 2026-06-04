"""
tests/test_cache_spotify_youtube_retroactive_merge.py

Esegui dalla root del progetto con:
    python tests/test_cache_spotify_youtube_retroactive_merge.py
"""

import os
import sqlite3
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
import core.cache_db as db


tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
tmp.close()

Config.DB_PATH = tmp.name
Config.CACHE_TTL_DAYS = 30
Config.CACHE_MAX_ENTRIES = 500

db.init_db(db_path=tmp.name, enabled=True)

youtube_track = {
    "title": 'G.Mineiro - "Splinter Cell" prod. Flat, Succo, Jiz (Visualizer)',
    "artist": "G.MINEIRO",
    "webpage_url": "https://youtube.com/watch?v=TEXT_RESULT",
    "source": "youtube",
    "duration": 117,
    "thumbnail": "https://i.ytimg.com/vi/TEXT_RESULT/hqdefault.jpg",
    "spotify_url": "",
    "thumbnail_source": "youtube",
    "thumbnail_confidence": 0.45,
}

db.put('G.Mineiro - "Splinter Cell"', youtube_track)
assert db.get('G.Mineiro - "Splinter Cell"') is not None

conn = sqlite3.connect(tmp.name)
now = int(time.time())
spotify_canonical = "Splinter Cell G.Mineiro Flatpearl Jiz Succo"
spotify_hash = db._hash(spotify_canonical)
spotify_norm = db._normalize_key(spotify_canonical)

conn.execute(
    """
    INSERT INTO cache_tracks
        (canonical_query_hash, canonical_query_raw, normalized_query,
         canonical_title, canonical_artist, created_at, updated_at, is_active)
    VALUES (?, ?, ?, ?, ?, ?, ?, 1)
    """,
    (
        spotify_hash,
        spotify_canonical,
        spotify_norm,
        "Splinter Cell",
        "G.Mineiro, Flatpearl, Jiz, Succo",
        now,
        now,
    ),
)
spotify_track_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])

conn.execute(
    """
    INSERT INTO cache_sources
        (track_id, webpage_url, stream_url, stream_expires_at, last_stream_check,
         source, resolved_title, resolved_artist, duration, thumbnail,
         thumbnail_source, thumbnail_confidence, spotify_url, source_confidence,
         created_at, last_used, hit_count, is_valid)
    VALUES (?, ?, '', 0, 0, ?, ?, ?, ?, ?, ?, ?, ?, 1.0, ?, ?, 1, 1)
    """,
    (
        spotify_track_id,
        "https://youtube.com/watch?v=SPOTIFY_RESULT",
        "spotify",
        "Splinter Cell",
        "G.Mineiro, Flatpearl, Jiz, Succo",
        117,
        "https://i.scdn.co/image/splinter",
        "spotify",
        0.95,
        "https://open.spotify.com/track/3KsGBiWVuybY3Zm7LDKuqK",
        now,
        now,
    ),
)
spotify_source_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])

spotify_query = "https://open.spotify.com/track/3KsGBiWVuybY3Zm7LDKuqK"
conn.execute(
    """
    INSERT INTO cache_queries
        (query_hash, query_raw, query_norm, track_id, source_id,
         alias_type, match_method, match_confidence, first_seen, last_seen, hit_count, is_confirmed, is_active)
    VALUES (?, ?, ?, ?, ?, 'spotify', 'spotify_url', 1.0, ?, ?, 1, 1, 1)
    """,
    (
        db._hash(spotify_query),
        spotify_query,
        db._normalize_key(spotify_query),
        spotify_track_id,
        spotify_source_id,
        now,
        now,
    ),
)
conn.commit()
conn.close()

conn = sqlite3.connect(tmp.name)
before_song_count = conn.execute("SELECT COUNT(*) FROM song_cache").fetchone()[0]
before_track_count = conn.execute("SELECT COUNT(*) FROM cache_tracks").fetchone()[0]
conn.close()

assert before_song_count == 2, before_song_count
assert before_track_count == 2, before_track_count

result = db.reconcile_duplicate_sources()
assert result["merged_sources"] == 1, result

conn = sqlite3.connect(tmp.name)
after_song_rows = conn.execute(
    "SELECT id, title, artist, source, spotify_url, webpage_url FROM song_cache ORDER BY id ASC"
).fetchall()
after_aliases = conn.execute(
    "SELECT query_raw, cache_id FROM query_aliases ORDER BY id ASC"
).fetchall()
after_track_count = conn.execute("SELECT COUNT(*) FROM cache_tracks").fetchone()[0]
conn.close()

assert len(after_song_rows) == 1, after_song_rows
assert after_track_count == 1, after_track_count
assert after_song_rows[0][4] == "https://open.spotify.com/track/3KsGBiWVuybY3Zm7LDKuqK", after_song_rows
assert any("spotify.com/track/3KsGBiWVuybY3Zm7LDKuqK" in row[0] for row in after_aliases), after_aliases

text_hit = db.get('G.Mineiro - "Splinter Cell"')
spotify_hit = db.get("https://open.spotify.com/track/3KsGBiWVuybY3Zm7LDKuqK")
assert text_hit is not None and spotify_hit is not None
assert text_hit["id"] == spotify_hit["id"], (text_hit, spotify_hit)

db._close()
try:
    os.unlink(tmp.name)
except PermissionError:
    print("(cleanup skipped: Windows file lock -- non e' un errore del codice)")

print("OK: retroactive Spotify/Youtube duplicate merge")
