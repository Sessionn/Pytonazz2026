"""
tests/test_cache_canonical_dedup.py

Esegui dalla root del progetto con:
    python tests/test_cache_canonical_dedup.py
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

track = {
    "title": "La Casa Di Topolino",
    "artist": "Disney Junior",
    "webpage_url": "https://youtube.com/watch?v=GOOD_ID",
    "source": "youtube",
    "duration": 145,
    "thumbnail": "",
    "spotify_url": "",
}

db.put("la casa di topolino", track)
db.put("casa topolino sigla cartone", track)

result_clean = db.get("la casa di topolino")
result_dirty = db.get("casa topolino sigla cartone")

assert result_clean is not None, "FAIL: query pulita non trovata"
assert result_dirty is not None, "FAIL: query distorta non trovata via alias"
assert result_clean["id"] == result_dirty["id"], "FAIL: query distorta ha creato entry separata"

conn = sqlite3.connect(tmp.name)
song_count = conn.execute("SELECT COUNT(*) FROM song_cache").fetchone()[0]
alias_count = conn.execute("SELECT COUNT(*) FROM query_aliases").fetchone()[0]
conn.close()

assert song_count == 1, f"FAIL: song_cache contiene {song_count} righe invece di 1"
assert alias_count >= 2, f"FAIL: alias insufficienti ({alias_count})"

invalidated = db.invalidate_webpage_url("https://youtube.com/watch?v=GOOD_ID")
assert invalidated == 1, f"FAIL: invalidate_webpage_url ha invalidato {invalidated} righe"
assert db.get("la casa di topolino") is None, "FAIL: entry invalidata ancora visibile"

db._close()
try:
    os.unlink(tmp.name)
except PermissionError:
    print("(cleanup skipped: Windows file lock -- non e' un errore del codice)")

print("OK: dedup canonicale e invalidazione URL")
