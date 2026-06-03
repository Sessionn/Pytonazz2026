"""
tests/test_resolver_spotify_artistless_fast_path.py

Esegui dalla root del progetto con:
    python tests/test_resolver_spotify_artistless_fast_path.py
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

    ytdlp_calls = []
    sp_meta = {
        "title": "They Call Me Sonic",
        "artist": "Console Allstars",
        "duration": 226,
        "thumbnail": "https://i.scdn.co/image/test-cover",
        "thumbnail_source": "spotify",
        "thumbnail_confidence": 0.92,
        "spotify_url": "https://open.spotify.com/track/test-sonic",
    }

    def fake_run_ytdlp(cls, query, requester, requester_id):
        ytdlp_calls.append(query)
        return [
            TrackInfo(
                title="They Call Me Sonic",
                webpage_url="https://www.youtube.com/watch?v=sonic",
                duration=226,
                thumbnail="https://i.ytimg.com/vi/sonic/hqdefault.jpg",
                requester=requester,
                requester_id=requester_id,
                source="youtube",
                stream_url="https://stream.test/sonic",
                artist="Console Allstars",
            )
        ]

    def fail_enrich(cls, tracks, query):
        raise AssertionError("artistless fast path should not trigger fallback enrich")

    try:
        Config.CACHE_ENABLED = False
        Config.SPOTIFY_CLIENT_ID = "test-client"
        SourceResolver._sp_search_track_meta = classmethod(lambda cls, query: sp_meta)
        SourceResolver._run_ytdlp = classmethod(fake_run_ytdlp)
        SourceResolver._enrich_with_spotify = classmethod(fail_enrich)

        tracks = await SourceResolver.resolve_choices("they call me sonic", "tester", 1, n=1)
    finally:
        Config.CACHE_ENABLED = original_cache_enabled
        Config.SPOTIFY_CLIENT_ID = original_spotify_id
        SourceResolver._sp_search_track_meta = original_sp_search
        SourceResolver._run_ytdlp = original_run_ytdlp
        SourceResolver._enrich_with_spotify = original_enrich

    assert ytdlp_calls == ["ytsearch1:They Call Me Sonic Console Allstars"], ytdlp_calls
    assert len(tracks) == 1, tracks
    assert tracks[0].thumbnail_source == "spotify", tracks[0]
    assert tracks[0].spotify_url == sp_meta["spotify_url"], tracks[0]


asyncio.run(main())
print("OK: resolver uses Spotify canonical query first for artistless search")
