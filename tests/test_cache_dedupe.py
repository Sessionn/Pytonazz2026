"""
tests/test_cache_dedupe.py

Esegui dalla root del progetto con:
    python tests/test_cache_dedupe.py
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

track_a = {
    "title": "Song",
    "artist": "Artist",
    "webpage_url": "https://youtube.com/watch?v=A",
    "source": "youtube",
    "duration": 100,
    "thumbnail": "",
    "spotify_url": "",
}
track_b = {**track_a, "webpage_url": "https://youtube.com/watch?v=B"}

db.put("song artist", track_a)

conn = sqlite3.connect(tmp.name)
conn.execute(
    """
    INSERT INTO song_cache
        (query_hash, query_raw, webpage_url, source, title, artist, duration, thumbnail, spotify_url)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    (
        "legacy-duplicate-hash",
        "song artist duplicate",
        track_b["webpage_url"],
        "youtube",
        track_b["title"],
        track_b["artist"],
        track_b["duration"],
        "",
        "",
    ),
)
conn.commit()
conn.close()

dry = db.dedupe_canonical(dry_run=True)
assert dry["duplicates"] == 1 and dry["applied"] is False, dry

applied = db.dedupe_canonical(dry_run=False)
assert applied["duplicates"] == 1 and applied["applied"] is True, applied

conn = sqlite3.connect(tmp.name)
count = conn.execute("SELECT COUNT(*) FROM song_cache WHERE is_valid = 1").fetchone()[0]
alias_count = conn.execute("SELECT COUNT(*) FROM query_aliases").fetchone()[0]
conn.close()

assert count == 1, f"FAIL: restano {count} righe valide"
assert alias_count >= 1, "FAIL: dedupe non ha promosso alias"

db._close()
try:
    os.unlink(tmp.name)
except PermissionError:
    print("(cleanup skipped: Windows file lock -- non e' un errore del codice)")

print("OK: dedupe canonicale dry-run/apply")
