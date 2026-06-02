"""
tests/test_resolver_spotify_late_hint.py

Esegui dalla root del progetto con:
    python tests/test_resolver_spotify_late_hint.py
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
    original_hint_wait = Config.SPOTIFY_HINT_WAIT_SECONDS
    original_sp_search = SourceResolver._sp_search_track_meta
    original_run_ytdlp = SourceResolver._run_ytdlp

    sp_meta = {
        "title": "Trust Me",
        "artist": "Artist Name",
        "duration": 180,
        "thumbnail": "https://i.scdn.co/image/trust-me-cover",
        "thumbnail_source": "spotify",
        "thumbnail_confidence": 0.92,
        "spotify_url": "https://open.spotify.com/track/trustme",
    }

    def slow_spotify_hint(cls, query):
        time.sleep(0.20)
        return sp_meta

    def fast_ytdlp(cls, query, requester, requester_id):
        return [
            TrackInfo(
                title="Trust Me",
                webpage_url="https://www.youtube.com/watch?v=trustme",
                duration=180,
                thumbnail="https://i.ytimg.com/vi/trustme/hqdefault.jpg",
                requester=requester,
                requester_id=requester_id,
                source="youtube",
                stream_url="https://stream.test/trustme",
                artist="Uploader",
            )
        ]

    try:
        Config.CACHE_ENABLED = False
        Config.SPOTIFY_CLIENT_ID = "test-client"
        Config.SPOTIFY_HINT_WAIT_SECONDS = 0.01
        SourceResolver._sp_search_track_meta = classmethod(slow_spotify_hint)
        SourceResolver._run_ytdlp = classmethod(fast_ytdlp)

        tracks = await SourceResolver.resolve_choices("trust me", "tester", 1, n=1)
    finally:
        Config.CACHE_ENABLED = original_cache_enabled
        Config.SPOTIFY_CLIENT_ID = original_spotify_id
        Config.SPOTIFY_HINT_WAIT_SECONDS = original_hint_wait
        SourceResolver._sp_search_track_meta = original_sp_search
        SourceResolver._run_ytdlp = original_run_ytdlp

    assert len(tracks) == 1, tracks
    assert tracks[0].thumbnail == sp_meta["thumbnail"], tracks[0]
    assert tracks[0].thumbnail_source == "spotify", tracks[0]
    assert tracks[0].spotify_url == sp_meta["spotify_url"], tracks[0]


asyncio.run(main())
print("OK: resolver applies late Spotify hint for ambiguous short queries")
