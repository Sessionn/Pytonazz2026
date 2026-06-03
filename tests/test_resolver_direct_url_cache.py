"""
tests/test_resolver_direct_url_cache.py

Esegui dalla root del progetto con:
    python tests/test_resolver_direct_url_cache.py
"""

import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
import core.cache_db as cache_db
import core.source_resolver as resolver_module
from core.source_resolver import SourceResolver


async def main() -> None:
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()

    original_cache_enabled = Config.CACHE_ENABLED
    original_db_path = Config.DB_PATH
    original_qc = resolver_module._qc_instance
    original_search_or_url = SourceResolver._search_or_url
    original_sp_track = SourceResolver._sp_track

    try:
        cache_db.rebuild_database(tmp.name)
        cache_db.init_db(db_path=tmp.name, enabled=True)
        Config.CACHE_ENABLED = True
        Config.DB_PATH = tmp.name
        resolver_module._qc_instance = None

        cache_db.put(
            "https://open.spotify.com/track/testdirectcache123",
            {
                "title": "Cached Spotify",
                "artist": "Resolver",
                "webpage_url": "https://www.youtube.com/watch?v=cached",
                "source": "youtube",
                "duration": 201,
                "thumbnail": "https://i.scdn.co/image/cached",
                "thumbnail_source": "spotify",
                "thumbnail_confidence": 0.95,
                "spotify_url": "https://open.spotify.com/track/testdirectcache123",
                "stream_url": "https://stream.test/cached",
            },
        )

        def fail_search_or_url(cls, query, requester, requester_id):
            raise AssertionError(f"direct URL cache miss inatteso via _search_or_url: {query}")

        def fail_sp_track(cls, track_id, requester, requester_id):
            raise AssertionError(f"direct Spotify URL cache miss inatteso via _sp_track: {track_id}")

        SourceResolver._search_or_url = classmethod(fail_search_or_url)
        SourceResolver._sp_track = classmethod(fail_sp_track)

        tracks = await SourceResolver.resolve(
            "https://open.spotify.com/intl-it/track/testdirectcache123?si=abc123",
            "tester",
            77,
        )
    finally:
        SourceResolver._search_or_url = original_search_or_url
        SourceResolver._sp_track = original_sp_track
        resolver_module._qc_instance = original_qc
        Config.CACHE_ENABLED = original_cache_enabled
        Config.DB_PATH = original_db_path
        try:
            os.unlink(tmp.name)
        except PermissionError:
            pass

    assert len(tracks) == 1, tracks
    track = tracks[0]
    assert track.title == "Cached Spotify", track
    assert track.requester == "tester", track
    assert track.requester_id == 77, track
    assert track.stream_url == "https://stream.test/cached", track
    assert track.spotify_url.endswith("/testdirectcache123"), track


asyncio.run(main())
print("OK: resolver direct URL cache fast path")
