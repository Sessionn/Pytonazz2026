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
import core.cache_db as cache_db

tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
tmp.close()

cache_db.rebuild_database(tmp.name)
cache_db.init_db(db_path=tmp.name, enabled=True)
cache_db.put(
    "song artist",
    {
        "title": "Song",
        "artist": "Artist",
        "webpage_url": "https://youtube.com/watch?v=1",
        "source": "youtube",
        "duration": 100,
        "thumbnail": "",
        "spotify_url": "",
    },
)

app = create_app(db_path=tmp.name)
client = app.test_client()
with client.session_transaction() as sess:
    sess["auth"] = True

stats = client.get("/api/stats")
assert stats.status_code == 200, stats.data
assert stats.get_json()["total"] == 1

aliases = client.get("/api/aliases")
assert aliases.status_code == 200, aliases.data

tracks = client.get("/api/tracks")
assert tracks.status_code == 200, tracks.data
assert tracks.get_json()[0]["canonical_title"] == "Song"

sources = client.get("/api/sources")
assert sources.status_code == 200, sources.data
assert sources.get_json()[0]["source"] == "youtube"

queries = client.get("/api/queries")
assert queries.status_code == 200, queries.data
assert queries.get_json()[0]["query_norm"] == "song artist"

schema = client.get("/api/schema")
assert schema.status_code == 200, schema.data
schema_names = {row["name"] for row in schema.get_json()}
assert {"cache_tracks", "cache_sources", "cache_queries", "song_cache", "query_aliases"} <= schema_names

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
row = conn.execute("SELECT alias_type FROM cache_queries WHERE query_raw LIKE 'https://open.spotify.com/%' LIMIT 1").fetchone()
conn.close()
assert row and row[0] == "spotify"

try:
    os.unlink(tmp.name)
except PermissionError:
    print("(cleanup skipped: Windows file lock -- non e' un errore del codice)")

print("OK: dashboard API stats/aliases/associate")
