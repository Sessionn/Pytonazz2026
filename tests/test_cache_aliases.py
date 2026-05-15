"""
tests/test_cache_aliases.py

Esegui dalla ROOT del progetto con:
    python tests/test_cache_aliases.py
"""

import sys, os, sqlite3, tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.cache_db as db

print("=" * 50)
print("TEST ALIAS - query testuali diverse stessa traccia")
print("=" * 50)

tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
tmp.close()

from config import Config
Config.DB_PATH = tmp.name
Config.CACHE_TTL_DAYS = 30
Config.CACHE_MAX_ENTRIES = 500

db.init_db(db_path=tmp.name, enabled=True)

track = {
    "title": "Blinding Lights",
    "artist": "The Weeknd",
    "webpage_url": "https://youtube.com/watch?v=TEST123",
    "source": "youtube",
    "duration": 200,
    "thumbnail": "",
    "spotify_url": "",
}

# --- Test 2a ---
print("\n[2a] Inserisco con query 'blinding lights'...")
db.put("blinding lights", track)

print("[2a] Inserisco con query 'the weeknd blinding lights' (stessa webpage_url)...")
db.put("the weeknd blinding lights", track)

stats = db.stats()
print(f"[2a] Alias nel DB: {stats['aliases']}")
assert stats["aliases"] >= 1, "FAIL: nessun alias creato dopo put() con query diversa"
print("OK [2a]: alias creato automaticamente")

# --- Test 2b ---
print("\n[2b] get() con la query alias 'the weeknd blinding lights'...")
result = db.get("the weeknd blinding lights")
print(f"[2b] Risultato: {result}")
assert result is not None, "FAIL: get() non trova via alias"
print("OK [2b]: get() trova HIT via alias")

result_canonical = db.get("blinding lights")
assert result["id"] == result_canonical["id"], (
    f"FAIL: id diversi - alias={result['id']} canonical={result_canonical['id']}"
)
print("OK [2b]: alias e canonical puntano alla stessa entry (id=%d)" % result["id"])

# --- Test 2d: no duplicati ---
conn = sqlite3.connect(tmp.name)
count = conn.execute(
    "SELECT COUNT(*) FROM song_cache WHERE title = 'Blinding Lights'"
).fetchone()[0]
conn.close()  # chiudo PRIMA di unlink
assert count == 1, f"FAIL: {count} entry in song_cache invece di 1"
print("OK: nessun duplicato in song_cache (count=1)")

# Chiudo anche la connessione interna di cache_db
if hasattr(db, "_close"):
    db._close()

try:
    os.unlink(tmp.name)
except PermissionError:
    print("(cleanup skipped: Windows file lock -- non e' un errore del codice)")

print("\n" + "=" * 50)
print("TUTTI I TEST ALIAS PASSATI")
print("=" * 50)
