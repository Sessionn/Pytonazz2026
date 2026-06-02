"""
tests/test_resolver_spotify_canonical_fallback_cover.py

Esegui dalla root del progetto con:
    python tests/test_resolver_spotify_canonical_fallback_cover.py
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
    original_sp_search = SourceResolver._sp_search_track_meta
    original_run_ytdlp = SourceResolver._run_ytdlp
    original_enrich = SourceResolver._enrich_with_spotify

    calls = []
    sp_meta = {
        "title": "Trust Me",
        "artist": "Pandora",
        "duration": 230,
        "thumbnail": "https://i.scdn.co/image/pandora-trust-me",
        "thumbnail_source": "spotify",
        "thumbnail_confidence": 0.92,
        "spotify_url": "https://open.spotify.com/track/pandora-trust-me",
    }

    def fake_spotify(cls, query):
        time.sleep(0.05)
        return sp_meta

    def fake_ytdlp(cls, query, requester, requester_id):
        calls.append(query)
        if query == "ytsearch1:trust me":
            return [
                TrackInfo(
                    title="Trust Me Bro Meme",
                    webpage_url="https://www.youtube.com/watch?v=raw",
                    duration=10,
                    thumbnail="https://i.ytimg.com/vi/raw/hqdefault.jpg",
                    requester=requester,
                    requester_id=requester_id,
                    source="youtube",
                    stream_url="https://stream.test/raw",
                )
            ]
        return [
            TrackInfo(
                title="Pandora - Trust Me (HQ)",
                webpage_url="https://www.youtube.com/watch?v=canonical",
                duration=230,
                thumbnail="https://i.ytimg.com/vi/canonical/hqdefault.jpg",
                requester=requester,
                requester_id=requester_id,
                source="youtube",
                stream_url="https://stream.test/canonical",
                artist="Pandora",
            )
        ]

    def fail_enrich(cls, tracks, query):
        raise AssertionError("canonical fallback should apply Spotify metadata directly")

    try:
        Config.CACHE_ENABLED = False
        Config.SPOTIFY_CLIENT_ID = "test-client"
        Config.SPOTIFY_AMBIGUOUS_WAIT_SECONDS = 0.0
        SourceResolver._sp_search_track_meta = classmethod(fake_spotify)
        SourceResolver._run_ytdlp = classmethod(fake_ytdlp)
        SourceResolver._enrich_with_spotify = classmethod(fail_enrich)

        tracks = await SourceResolver.resolve_choices("trust me", "tester", 1, n=1)
    finally:
        Config.CACHE_ENABLED = original_cache_enabled
        Config.SPOTIFY_CLIENT_ID = original_spotify_id
        Config.SPOTIFY_AMBIGUOUS_WAIT_SECONDS = original_ambiguous_wait
        SourceResolver._sp_search_track_meta = original_sp_search
        SourceResolver._run_ytdlp = original_run_ytdlp
        SourceResolver._enrich_with_spotify = original_enrich

    assert calls == ["ytsearch1:trust me", "ytsearch1:Trust Me Pandora"], calls
    assert len(tracks) == 1, tracks
    assert tracks[0].thumbnail == sp_meta["thumbnail"], tracks[0]
    assert tracks[0].thumbnail_source == "spotify", tracks[0]
    assert tracks[0].spotify_url == sp_meta["spotify_url"], tracks[0]


asyncio.run(main())
print("OK: resolver applies Spotify cover after canonical fallback")
