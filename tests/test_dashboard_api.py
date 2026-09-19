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

# Streaming clients cannot occupy every Waitress worker; closing frees a slot.
streams = [client.get('/api/events', buffered=False) for _ in range(4)]
assert all(response.status_code == 200 for response in streams)
assert client.get('/api/events').status_code == 503
for response in reversed(streams):
    response.close()
released = client.get('/api/events', buffered=False)
assert released.status_code == 200
released.close()

for kind in ("songs", "aliases", "tracks", "sources", "queries"):
    legacy = client.get(f"/api/{kind}").get_json()
    first = client.get(f"/api/{kind}?page=1&page_size=2&sort=id&order=asc").get_json()
    assert first["total"] == len(legacy), (kind, first)
    assert len(first["items"]) <= 2
    last = client.get(f"/api/{kind}?page=999999&page_size=2").get_json()
    assert last["page"] == last["pages"]
    empty = client.get(f"/api/{kind}?page=2&q=no-such-track-xyz").get_json()
    assert empty["items"] == [] and empty["page"] == 1 and empty["total"] == 0
    assert client.get(f"/api/{kind}?page=bad").status_code == 400
    capped = client.get(f"/api/{kind}?page_size=999999&sort=id;DROP+TABLE+cache_tracks").get_json()
    assert capped["page_size"] == 200 and capped["total"] == len(legacy)

search_page = client.get('/api/songs?page=1&q=Song+Two&source=youtube&valid=1').get_json()
assert search_page["total"] == 1 and search_page["items"][0]["title"] == "Song Two"
assert client.get('/api/songs?page=1&q=%25').get_json()["total"] == 0
tracks_page = client.get('/api/tracks?page=1').get_json()["items"]
assert all(row['source_count'] == 1 and row['query_count'] >= 1 for row in tracks_page)

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

# Deleting in one session never reassigns IDs still visible in another session.
deleted = client.delete("/api/delete/2").get_json()
assert deleted["ok"] and deleted["compact"] == {}
rows = client.get("/api/sources").get_json()
assert [row["id"] for row in rows] == [3, 1]
assert client.delete("/api/delete/2").get_json()["ok"] is False
assert client.get("/api/sources").get_json()[0]["id"] == 3
cache_db.put("song four artist", dict(title="Song Four", artist="Artist", webpage_url="https://youtube.com/watch?v=4", source="youtube", duration=160))
rows = client.get("/api/sources").get_json()
assert rows[0]["id"] == 4
assert client.delete("/api/queries/1").status_code == 200
assert client.delete("/api/sources/1").get_json()["ok"]
assert client.delete("/api/tracks/3").get_json()["ok"]
conn = sqlite3.connect(tmp.name)
assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
assert conn.execute("SELECT id, canonical_title FROM cache_tracks").fetchall() == [(4, "Song Four")]
conn.close()

try:
    os.unlink(tmp.name)
except PermissionError:
    print("(cleanup skipped: Windows file lock -- non e' un errore del codice)")

print("OK: dashboard API stats/aliases/associate")
