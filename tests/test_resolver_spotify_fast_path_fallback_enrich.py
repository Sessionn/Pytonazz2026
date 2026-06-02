"""
tests/test_resolver_spotify_fast_path_fallback_enrich.py

Esegui dalla root del progetto con:
    python tests/test_resolver_spotify_fast_path_fallback_enrich.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from core.source_resolver import SourceResolver
from core.source_resolver.models import TrackInfo


async def main() -> None:
    original_cache_enabled = Config.CACHE_ENABLED
    original_spotify_id = Config.SPOTIFY_CLIENT_ID
    original_sp_search = SourceResolver._sp_search_track_meta
    original_run_ytdlp = SourceResolver._run_ytdlp
    original_enrich = SourceResolver._enrich_with_spotify

    enrich_calls = []

    def no_hint(cls, query):
        return None

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
            )
        ]

    def fallback_enrich(cls, tracks, query):
        enrich_calls.append(query)
        tracks[0].thumbnail = "https://i.scdn.co/image/fallback-cover"
        tracks[0].thumbnail_source = "spotify"
        tracks[0].spotify_url = "https://open.spotify.com/track/fallback"
        return tracks

    try:
        Config.CACHE_ENABLED = False
        Config.SPOTIFY_CLIENT_ID = "test-client"
        SourceResolver._sp_search_track_meta = classmethod(no_hint)
        SourceResolver._run_ytdlp = classmethod(fast_ytdlp)
        SourceResolver._enrich_with_spotify = classmethod(fallback_enrich)

        tracks = await SourceResolver.resolve_choices("trust me", "tester", 1, n=1)
    finally:
        Config.CACHE_ENABLED = original_cache_enabled
        Config.SPOTIFY_CLIENT_ID = original_spotify_id
        SourceResolver._sp_search_track_meta = original_sp_search
        SourceResolver._run_ytdlp = original_run_ytdlp
        SourceResolver._enrich_with_spotify = original_enrich

    assert enrich_calls == ["trust me"], enrich_calls
    assert tracks[0].thumbnail_source == "spotify", tracks[0]
    assert tracks[0].spotify_url.endswith("/fallback"), tracks[0]


asyncio.run(main())
print("OK: resolver retries Spotify enrich on ambiguous short fast-path misses")
