"""
tests/test_cache_spotify_text_alias_repeated_tokens.py

Esegui dalla root del progetto con:
    python tests/test_cache_spotify_text_alias_repeated_tokens.py
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

Config.DB_PATH = tmp.name
Config.CACHE_TTL_DAYS = 30
Config.CACHE_MAX_ENTRIES = 500

db.init_db(db_path=tmp.name, enabled=True)

spotify_link = "https://open.spotify.com/intl-it/track/1tMm6HuHYo6yR0L0m1CfAk?si=602f325cdf604740"
spotify_canonical = "https://open.spotify.com/track/1tMm6HuHYo6yR0L0m1CfAk"
webpage_url = "https://www.youtube.com/watch?v=wWv-O4BMFZA"

spotify_track = {
    "title": "Miguel Miguel Phonk",
    "artist": "prodbymiri",
    "webpage_url": webpage_url,
    "source": "spotify",
    "duration": 101,
    "thumbnail": "https://i.scdn.co/image/miguel",
    "thumbnail_source": "spotify",
    "thumbnail_confidence": 0.95,
    "spotify_url": spotify_canonical,
}

youtube_track = {
    "title": "Miguel Phonk - (Official 4K Video)",
    "artist": "nugabar",
    "webpage_url": webpage_url,
    "source": "youtube",
    "duration": 300,
    "thumbnail": "https://i.ytimg.com/vi/wWv-O4BMFZA/hqdefault.jpg",
    "thumbnail_source": "youtube",
    "thumbnail_confidence": 0.45,
    "spotify_url": "",
}

db.put(spotify_link, spotify_track)

text_hit = db.get("miguel phonk")
spotify_hit = db.get(spotify_link)

assert text_hit is not None, "FAIL: query testuale non trovata via metadata Spotify"
assert spotify_hit is not None, "FAIL: link Spotify non trovato"
assert text_hit["id"] == spotify_hit["id"], (text_hit, spotify_hit)
assert text_hit["title"] == "Miguel Miguel Phonk", text_hit
assert text_hit["source"] == "spotify", text_hit

conn = sqlite3.connect(tmp.name)
method_row = conn.execute(
    "SELECT match_method FROM cache_queries WHERE query_raw = 'miguel phonk' LIMIT 1"
).fetchone()
conn.close()
assert method_row == ("canonical_title_tokens",), method_row

db.put("miguel phonk", youtube_track)

conn = sqlite3.connect(tmp.name)
rows = conn.execute(
    "SELECT title, artist, source, duration, spotify_url FROM song_cache ORDER BY id"
).fetchall()
aliases = conn.execute(
    "SELECT query_raw, match_method FROM cache_queries ORDER BY id"
).fetchall()
conn.close()

assert rows == [("Miguel Miguel Phonk", "prodbymiri", "spotify", 101, spotify_canonical)], rows
assert any(row[0] == "miguel phonk" for row in aliases), aliases

db._close()
try:
    os.unlink(tmp.name)
except PermissionError:
    pass

print("OK: Spotify cache hit da query testuale con token ripetuti e metadata preservati")
