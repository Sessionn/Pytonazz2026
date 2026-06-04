"""
tests/test_cache_canonical_lookup.py

Esegui dalla root del progetto con:
    python tests/test_cache_canonical_lookup.py
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

gucci = {
    "title": "Gucci Flip Flops x Careless Whisper",
    "artist": "Moonshine",
    "webpage_url": "https://youtube.com/watch?v=GUCCI",
    "source": "youtube",
    "duration": 201,
    "thumbnail": "",
    "spotify_url": "https://open.spotify.com/track/7qxaXTeqwpdnjzmUE2NOE1",
}
db.put("Gucci Flip Flops x Careless Whisper Moonshine", gucci)

title_hit = db.get("Gucci Flip Flops x Careless Whisper")
assert title_hit is not None, "FAIL: titolo canonico senza artista non trovato"
assert title_hit["webpage_url"].endswith("GUCCI"), title_hit

typo_hit = db.get("Gucci Flips Flops x Careless Whisper")
assert typo_hit is not None, "FAIL: typo minimo sul titolo canonico non trovato"
assert typo_hit["id"] == title_hit["id"], (typo_hit, title_hit)

db.put(
    "Home Artist One",
    {
        "title": "Home",
        "artist": "Artist One",
        "webpage_url": "https://youtube.com/watch?v=HOME1",
        "source": "youtube",
        "duration": 180,
        "thumbnail": "",
        "spotify_url": "",
    },
)
db.put(
    "Home Artist Two",
    {
        "title": "Home",
        "artist": "Artist Two",
        "webpage_url": "https://youtube.com/watch?v=HOME2",
        "source": "youtube",
        "duration": 240,
        "thumbnail": "",
        "spotify_url": "",
    },
)
assert db.get("Home") is None, "FAIL: titolo ambiguo non deve produrre cache hit"
assert db.get("Careless Whisper") is None, "FAIL: query parziale non deve produrre cache hit"

conn = sqlite3.connect(tmp.name)
aliases = conn.execute(
    "SELECT query_raw, match_method FROM cache_queries WHERE source_id = ? ORDER BY id",
    (title_hit["id"],),
).fetchall()
conn.close()
assert ("Gucci Flip Flops x Careless Whisper", "canonical_title") in aliases, aliases
assert ("Gucci Flips Flops x Careless Whisper", "canonical_typo") in aliases, aliases

db._close()
try:
    os.unlink(tmp.name)
except PermissionError:
    pass

print("OK: canonical cache lookup learns strict title and typo aliases")
