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
cache_db.put(
    "song two artist",
    {
        "title": "Song Two",
        "artist": "Artist",
        "webpage_url": "https://youtube.com/watch?v=2",
        "source": "youtube",
        "duration": 120,
        "thumbnail": "https://i.ytimg.com/vi/2/hqdefault.jpg",
        "spotify_url": "",
    },
)
cache_db.put(
    "song three artist",
    {
        "title": "Song Three",
        "artist": "Artist",
        "webpage_url": "https://youtube.com/watch?v=3",
        "source": "youtube",
        "duration": 140,
        "thumbnail": "https://i.scdn.co/image/test-cover",
        "spotify_url": "https://open.spotify.com/track/test-three",
    },
)

app = create_app(db_path=tmp.name)
client = app.test_client()
with client.session_transaction() as sess:
    sess["auth"] = True

stats = client.get("/api/stats")
assert stats.status_code == 200, stats.data
assert stats.get_json()["total"] == 3

aliases = client.get("/api/aliases")
assert aliases.status_code == 200, aliases.data

tracks = client.get("/api/tracks?sort=id&order=ASC")
assert tracks.status_code == 200, tracks.data
track_rows = tracks.get_json()
assert [row["id"] for row in track_rows] == [3, 2, 1]
assert {row["canonical_title"] for row in track_rows} == {"Song", "Song Two", "Song Three"}

sources = client.get("/api/sources")
assert sources.status_code == 200, sources.data
assert sources.get_json()[0]["source"] == "youtube"

queries = client.get("/api/queries")
assert queries.status_code == 200, queries.data
query_rows = queries.get_json()
assert {row["query_norm"] for row in query_rows} >= {"song artist", "song two artist", "song three artist"}

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

deleted = client.delete("/api/delete/2")
assert deleted.status_code == 200, deleted.data
assert deleted.get_json()["ok"] is True

tracks_after_delete = client.get("/api/tracks?sort=id&order=ASC")
assert tracks_after_delete.status_code == 200, tracks_after_delete.data
track_rows = tracks_after_delete.get_json()
assert [row["id"] for row in track_rows] == [2, 1], track_rows
assert {row["canonical_title"] for row in track_rows} == {"Song", "Song Three"}, track_rows

conn = sqlite3.connect(tmp.name)
source_rows = conn.execute(
    "SELECT id, track_id, webpage_url FROM cache_sources ORDER BY id ASC"
).fetchall()
query_rows = conn.execute(
    "SELECT id, track_id, source_id, query_raw FROM cache_queries ORDER BY id ASC"
).fetchall()
conn.close()

assert source_rows == [
    (1, 1, "https://youtube.com/watch?v=1"),
    (2, 2, "https://youtube.com/watch?v=3"),
], source_rows
assert all(track_id in (1, 2) for _, track_id, _, _ in query_rows), query_rows
assert all(source_id in (1, 2) for _, _, source_id, _ in query_rows), query_rows

cache_db.put(
    "song four artist",
    {
        "title": "Song Four",
        "artist": "Artist",
        "webpage_url": "https://youtube.com/watch?v=4",
        "source": "youtube",
        "duration": 160,
        "thumbnail": "",
        "spotify_url": "",
    },
)
tracks_after_insert = client.get("/api/tracks?sort=id&order=ASC")
assert tracks_after_insert.status_code == 200, tracks_after_insert.data
assert [row["id"] for row in tracks_after_insert.get_json()] == [3, 2, 1], tracks_after_insert.get_json()

delete_query = client.delete("/api/queries/1")
assert delete_query.status_code == 200, delete_query.data
assert delete_query.get_json()["ok"] is True

delete_source = client.delete("/api/sources/1")
assert delete_source.status_code == 200, delete_source.data
assert delete_source.get_json()["ok"] is True

delete_track = client.delete("/api/tracks/1")
assert delete_track.status_code == 200, delete_track.data
assert delete_track.get_json()["ok"] is True

conn = sqlite3.connect(tmp.name)
final_tracks = conn.execute("SELECT id, canonical_title FROM cache_tracks ORDER BY id ASC").fetchall()
final_sources = conn.execute("SELECT id, track_id FROM cache_sources ORDER BY id ASC").fetchall()
final_queries = conn.execute("SELECT id, track_id, source_id FROM cache_queries ORDER BY id ASC").fetchall()
conn.close()

assert final_tracks == [(1, "Song Four")], final_tracks
assert final_sources == [(1, 1)], final_sources
assert final_queries == [(1, 1, 1)], final_queries

try:
    os.unlink(tmp.name)
except PermissionError:
    print("(cleanup skipped: Windows file lock -- non e' un errore del codice)")

print("OK: dashboard API stats/aliases/associate")
