"""
tests/test_resolver_spotify_retry_unrequested_variant.py

Esegui dalla root del progetto con:
    python tests/test_resolver_spotify_retry_unrequested_variant.py
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
    original_ambiguous_wait = Config.SPOTIFY_AMBIGUOUS_WAIT_SECONDS
    original_sp_search = SourceResolver._sp_search_track_meta
    original_run_ytdlp = SourceResolver._run_ytdlp
    original_enrich = SourceResolver._enrich_with_spotify

    calls = []
    sp_meta = {
        "title": "DONNE RICCHE",
        "artist": "TonyPitony",
        "duration": 172,
        "thumbnail": "https://i.scdn.co/image/donne-ricche",
        "thumbnail_source": "spotify",
        "thumbnail_confidence": 0.92,
        "spotify_url": "https://open.spotify.com/track/donne-ricche",
    }

    def fake_spotify(cls, query):
        return sp_meta

    def fake_ytdlp(cls, query, requester, requester_id):
        calls.append(query)
        if query == "ytsearch1:DONNE RICCHE TonyPitony audio":
            return [
                TrackInfo(
                    title="DONNE RICCHE - TonyPitony | ACOUSTIC VERSION",
                    webpage_url="https://www.youtube.com/watch?v=acoustic",
                    duration=172,
                    thumbnail="https://i.ytimg.com/vi/acoustic/hqdefault.jpg",
                    requester=requester,
                    requester_id=requester_id,
                    source="youtube",
                    stream_url="https://stream.test/acoustic",
                    artist="TonyPitony",
                )
            ]
        if query == "ytsearch3:DONNE RICCHE TonyPitony audio":
            return [
                TrackInfo(
                    title="DONNE RICCHE - TonyPitony",
                    webpage_url="https://www.youtube.com/watch?v=studio",
                    duration=172,
                    thumbnail="https://i.ytimg.com/vi/studio/hqdefault.jpg",
                    requester=requester,
                    requester_id=requester_id,
                    source="youtube",
                    stream_url="https://stream.test/studio",
                    artist="TonyPitony",
                )
            ]
        raise AssertionError(f"unexpected query: {query}")

    def fail_enrich(cls, tracks, query):
        raise AssertionError("spotify hint path should handle the retry directly")

    try:
        Config.CACHE_ENABLED = False
        Config.SPOTIFY_CLIENT_ID = "test-client"
        Config.SPOTIFY_AMBIGUOUS_WAIT_SECONDS = 0.0
        SourceResolver._sp_search_track_meta = classmethod(fake_spotify)
        SourceResolver._run_ytdlp = classmethod(fake_ytdlp)
        SourceResolver._enrich_with_spotify = classmethod(fail_enrich)

        tracks = await SourceResolver.resolve_choices("Donne ricche", "tester", 1, n=1)
    finally:
        Config.CACHE_ENABLED = original_cache_enabled
        Config.SPOTIFY_CLIENT_ID = original_spotify_id
        Config.SPOTIFY_AMBIGUOUS_WAIT_SECONDS = original_ambiguous_wait
        SourceResolver._sp_search_track_meta = original_sp_search
        SourceResolver._run_ytdlp = original_run_ytdlp
        SourceResolver._enrich_with_spotify = original_enrich

    assert calls == [
        "ytsearch1:DONNE RICCHE TonyPitony audio",
        "ytsearch3:DONNE RICCHE TonyPitony audio",
    ], calls
    assert len(tracks) == 1, tracks
    assert tracks[0].webpage_url == "https://www.youtube.com/watch?v=studio", tracks[0]


asyncio.run(main())
print("OK: resolver retries canonical search for unrequested official variant")
