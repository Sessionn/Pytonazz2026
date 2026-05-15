"""
tests/test_cache_spotify.py

Esegui dalla ROOT del progetto con:
    python tests/test_cache_spotify.py
"""

import sys, os, sqlite3, tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.cache_db as db

print("=" * 55)
print("TEST SPOTIFY - link come query, caching intelligente")
print("=" * 55)

tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
tmp.close()

from config import Config
Config.DB_PATH = tmp.name
Config.CACHE_TTL_DAYS = 30
Config.CACHE_MAX_ENTRIES = 500

db.init_db(db_path=tmp.name, enabled=True)

SPOTIFY_LINK = "https://open.spotify.com/track/0VjIjW4GlUZAMYd2vXMi3b?si=totallyrandom"
SPOTIFY_CANONICAL = "https://open.spotify.com/track/0VjIjW4GlUZAMYd2vXMi3b"

track = {
    "title": "Blinding Lights",
    "artist": "The Weeknd",
    "webpage_url": "https://youtube.com/watch?v=YOUTUBE_ID",
    "source": "youtube",
    "duration": 200,
    "thumbnail": "",
    "spotify_url": SPOTIFY_CANONICAL,
}

# --- Test 3a ---
print("\n[3a] put() con link Spotify come query...")
db.put(SPOTIFY_LINK, track)

conn = sqlite3.connect(tmp.name)
row = conn.execute("SELECT * FROM song_cache WHERE title = 'Blinding Lights'").fetchone()
print(f"[3a] query_raw salvata nel DB: {row[2] if row else 'NESSUNA RIGA'}")
assert row is not None, "FAIL: nessuna entry in song_cache"
assert "spotify.com" not in row[2], (
    f"FAIL: query_raw canonical contiene il link Spotify: {row[2]}"
)
print("OK [3a]: canonical e' testuale, non contiene spotify.com")

# --- Test 3b ---
print("\n[3b] get() con il link Spotify (con ?si= in coda)...")
result_sp = db.get(SPOTIFY_LINK)
print(f"[3b] Risultato: {result_sp}")
assert result_sp is not None, "FAIL: get() non trova via link Spotify"
print("OK [3b]: get() HIT con link Spotify")

# --- Test 3c ---
print("\n[3c] get() con query testuale 'blinding lights the weeknd'...")
result_text = db.get("blinding lights the weeknd")
if result_text is None:
    result_text = db.get("blinding lights")
print(f"[3c] Risultato: {result_text}")
assert result_text is not None, "FAIL: get() non trova via testo"
assert result_text["id"] == result_sp["id"], (
    f"FAIL: entry diverse - spotify id={result_sp['id']}, testo id={result_text['id']}"
)
print(f"OK [3c]: link Spotify e query testuale puntano alla stessa entry (id={result_text['id']})")

# --- Test 3d ---
print("\n[3d] Verifica assenza duplicati in song_cache...")
count = conn.execute(
    "SELECT COUNT(*) FROM song_cache WHERE title = 'Blinding Lights'"
).fetchone()[0]
print(f"[3d] Righe in song_cache per 'Blinding Lights': {count}")
assert count == 1, f"FAIL: {count} duplicati in song_cache"
print("OK [3d]: nessun duplicato")

# --- Test 3e ---
print("\n[3e] Verifica alias Spotify in query_aliases...")
aliases = conn.execute(
    "SELECT query_raw, cache_id FROM query_aliases"
).fetchall()
print(f"[3e] Alias presenti: {aliases}")
spotify_aliases = [a for a in aliases if "spotify.com" in (a[0] or "")]
assert len(spotify_aliases) >= 1, "FAIL: nessun alias Spotify in query_aliases"
print(f"OK [3e]: trovato alias Spotify -> cache_id={spotify_aliases[0][1]}")

conn.close()  # chiudo PRIMA di unlink

if hasattr(db, "_close"):
    db._close()

try:
    os.unlink(tmp.name)
except PermissionError:
    print("(cleanup skipped: Windows file lock -- non e' un errore del codice)")

print("\n" + "=" * 55)
print("TUTTI I TEST SPOTIFY PASSATI")
print("=" * 55)
