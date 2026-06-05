"""
tests/test_resolver_spotify_no_duplicate_enrich_on_pending_hint.py

Esegui dalla root del progetto con:
    python tests/test_resolver_spotify_no_duplicate_enrich_on_pending_hint.py
"""

import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from core.source_resolver import SourceResolver
from core.source_resolver.models import TrackInfo


async def main() -> None:
    original_cache_enabled = Config.CACHE_ENABLED
    original_spotify_id = Config.SPOTIFY_CLIENT_ID
    original_ambiguous_wait = Config.SPOTIFY_AMBIGUOUS_WAIT_SECONDS
    original_hint_wait = Config.SPOTIFY_HINT_WAIT_SECONDS
    original_sp_search = SourceResolver._sp_search_track_meta
    original_run_ytdlp = SourceResolver._run_ytdlp
    original_enrich = SourceResolver._enrich_with_spotify

    enrich_calls = []

    def slow_spotify(cls, query):
        time.sleep(0.6)
        return {
            "title": "Cinderella",
            "artist": "Future, Metro Boomin, Travis Scott",
            "duration": 154,
            "thumbnail": "https://i.scdn.co/image/cinderella",
            "spotify_url": "https://open.spotify.com/track/cinderella",
        }

    def fake_ytdlp(cls, query, requester, requester_id):
        return [
            TrackInfo(
                title="Future, Metro Boomin, Travis Scott - Cinderella (Official Audio)",
                webpage_url="https://www.youtube.com/watch?v=cinderella",
                duration=154,
                thumbnail="https://i.ytimg.com/vi/cinderella/hqdefault.jpg",
                requester=requester,
                requester_id=requester_id,
                source="youtube",
                stream_url="https://stream.test/cinderella",
                artist="",
            )
        ]

    def fail_duplicate_enrich(cls, tracks, query):
        enrich_calls.append(query)
        raise AssertionError("pending Spotify hint must not trigger a duplicate synchronous enrich")

    try:
        Config.CACHE_ENABLED = False
        Config.SPOTIFY_CLIENT_ID = "test-client"
        Config.SPOTIFY_AMBIGUOUS_WAIT_SECONDS = 0.0
        Config.SPOTIFY_HINT_WAIT_SECONDS = 0.0
        SourceResolver._sp_search_track_meta = classmethod(slow_spotify)
        SourceResolver._run_ytdlp = classmethod(fake_ytdlp)
        SourceResolver._enrich_with_spotify = classmethod(fail_duplicate_enrich)

        started = time.perf_counter()
        tracks = await SourceResolver.resolve_choices("cindirellla", "tester", 1, n=1)
        elapsed = time.perf_counter() - started
    finally:
        Config.CACHE_ENABLED = original_cache_enabled
        Config.SPOTIFY_CLIENT_ID = original_spotify_id
        Config.SPOTIFY_AMBIGUOUS_WAIT_SECONDS = original_ambiguous_wait
        Config.SPOTIFY_HINT_WAIT_SECONDS = original_hint_wait
        SourceResolver._sp_search_track_meta = original_sp_search
        SourceResolver._run_ytdlp = original_run_ytdlp
        SourceResolver._enrich_with_spotify = original_enrich

    assert enrich_calls == [], enrich_calls
    assert len(tracks) == 1, tracks
    assert tracks[0].webpage_url == "https://www.youtube.com/watch?v=cinderella", tracks[0]
    assert elapsed < 0.45, elapsed


asyncio.run(main())
print("OK: pending Spotify hint does not duplicate synchronous enrich")
