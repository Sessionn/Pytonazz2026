"""
tests/test_cache_spotify_youtube_fingerprint_dedup.py

Esegui dalla root del progetto con:
    python tests/test_cache_spotify_youtube_fingerprint_dedup.py
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

spotify_track = {
    "title": "Splinter Cell",
    "artist": "G.Mineiro, Flatpearl, Jiz, Succo",
    "webpage_url": "https://youtube.com/watch?v=SPOTIFY_RESULT",
    "source": "spotify",
    "duration": 117,
    "thumbnail": "https://i.scdn.co/image/splinter",
    "spotify_url": "https://open.spotify.com/track/3KsGBiWVuybY3Zm7LDKuqK",
    "thumbnail_source": "spotify",
    "thumbnail_confidence": 0.95,
}

db.put('G.Mineiro - "Splinter Cell"', youtube_track)
db.put(
    "https://open.spotify.com/intl-it/track/3KsGBiWVuybY3Zm7LDKuqK?si=a5feecf04fbd4451",
    spotify_track,
)

conn = sqlite3.connect(tmp.name)
song_rows = conn.execute("SELECT id, title, artist, spotify_url, source FROM song_cache").fetchall()
alias_rows = conn.execute("SELECT query_raw, cache_id FROM query_aliases").fetchall()
track_count = conn.execute("SELECT COUNT(*) FROM cache_tracks").fetchone()[0]
conn.close()

assert len(song_rows) == 1, f"FAIL: duplicate song_cache rows: {song_rows}"
assert track_count == 1, f"FAIL: duplicate cache_tracks rows: {track_count}"
assert song_rows[0][3] == "https://open.spotify.com/track/3KsGBiWVuybY3Zm7LDKuqK", song_rows
assert any("spotify.com/track/3KsGBiWVuybY3Zm7LDKuqK" in row[0] for row in alias_rows), alias_rows

text_hit = db.get('G.Mineiro - "Splinter Cell"')
spotify_hit = db.get("https://open.spotify.com/track/3KsGBiWVuybY3Zm7LDKuqK")

assert text_hit is not None, "FAIL: text query miss"
assert spotify_hit is not None, "FAIL: spotify query miss"
assert text_hit["id"] == spotify_hit["id"], (text_hit, spotify_hit)

same_title_other_artist = {
    "title": "Splinter Cell",
    "artist": "Different Artist",
    "webpage_url": "https://youtube.com/watch?v=OTHER_ARTIST",
    "source": "youtube",
    "duration": 117,
    "thumbnail": "",
    "spotify_url": "",
}
db.put("splinter cell different artist", same_title_other_artist)

conn = sqlite3.connect(tmp.name)
song_count_after_other_artist = conn.execute("SELECT COUNT(*) FROM song_cache").fetchone()[0]
conn.close()

assert song_count_after_other_artist == 2, (
    f"FAIL: artista diverso fuso per errore: {song_count_after_other_artist}"
)

db._close()
try:
    os.unlink(tmp.name)
except PermissionError:
    print("(cleanup skipped: Windows file lock -- non e' un errore del codice)")

print("OK: Spotify/Youtube duplicate fingerprint dedup")
