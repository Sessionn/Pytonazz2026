"""
tests/test_cache_aliases.py

Esegui dalla ROOT del progetto con:
    python tests/test_cache_aliases.py

Cosa verifica:
    - Test 2a: put() con stessa webpage_url ma query testuale diversa
               deve creare automaticamente un alias in query_aliases.
    - Test 2b: get() deve trovare HIT passando la query alias (non quella
               canonical originale).

Risultato atteso:
    Tutti i print OK: ... senza AssertionError.
"""

import sys
import os
import sqlite3

# Aggiunge la root del progetto al path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.cache_db as db

print("=" * 50)
print("TEST ALIAS - query testuali diverse stessa traccia")
print("=" * 50)

# Usa un DB temporaneo per non sporcare quello reale
import tempfile
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

# Verifica che punti alla stessa entry
result_canonical = db.get("blinding lights")
assert result["id"] == result_canonical["id"], (
    f"FAIL: id diversi - alias={result['id']} canonical={result_canonical['id']}"
)
print("OK [2b]: alias e canonical puntano alla stessa entry (id=%d)" % result["id"])

# Verifica che non ci siano duplicati
conn = sqlite3.connect(tmp.name)
count = conn.execute(
    "SELECT COUNT(*) FROM song_cache WHERE title = 'Blinding Lights'"
).fetchone()[0]
conn.close()
assert count == 1, f"FAIL: {count} entry in song_cache invece di 1"
print("OK: nessun duplicato in song_cache (count=1)")

# Pulizia
os.unlink(tmp.name)

print("\n" + "=" * 50)
print("TUTTI I TEST ALIAS PASSATI")
print("=" * 50)
