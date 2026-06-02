from __future__ import annotations

import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.cache_db as db


tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
tmp.close()

db.rebuild_database(tmp.name)
db.init_db(db_path=tmp.name, enabled=True)

db.put("song artist", {
    "title": "Song",
    "artist": "Artist",
    "webpage_url": "https://youtube.com/watch?v=1",
    "stream_url": "https://stream.example/first",
    "source": "youtube",
    "duration": 180,
    "thumbnail": "https://i.scdn.co/image/cover",
    "thumbnail_source": "spotify",
    "thumbnail_confidence": 0.92,
    "spotify_url": "https://open.spotify.com/track/abc123",
})

db.put("song artist", {
    "title": "Song",
    "artist": "Artist",
    "webpage_url": "https://youtube.com/watch?v=1",
    "source": "youtube",
    "duration": 180,
    "thumbnail": "https://i.ytimg.com/vi/1/hqdefault.jpg",
    "thumbnail_source": "youtube",
    "thumbnail_confidence": 0.45,
    "spotify_url": "",
})

hit = db.get("song artist")
assert hit is not None
assert hit["thumbnail"] == "https://i.scdn.co/image/cover"
assert hit["thumbnail_source"] == "spotify"
assert hit["stream_url"] == "https://stream.example/first"
assert int(hit["stream_expires_at"]) > int(time.time())

updated = db.update_stream_url("https://youtube.com/watch?v=1", "https://stream.example/fresh", ttl_seconds=120)
assert updated is True
hit = db.get("song artist")
assert hit is not None
assert hit["stream_url"] == "https://stream.example/fresh"

db._close()
try:
    os.unlink(tmp.name)
except PermissionError:
    print("(cleanup skipped: Windows file lock -- non e' un errore del codice)")

print("OK: cache preserves Spotify cover and stores temporary stream URL")
