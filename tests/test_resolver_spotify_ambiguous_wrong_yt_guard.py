"""
tests/test_resolver_spotify_ambiguous_wrong_yt_guard.py

Esegui dalla root del progetto con:
    python tests/test_resolver_spotify_ambiguous_wrong_yt_guard.py
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

    ytdlp_calls = []
    sp_meta = {
        "title": "18 (Eighteen) - Slowed",
        "artist": "Vic Slater",
        "duration": 260,
        "thumbnail": "https://i.scdn.co/image/eighteen",
        "thumbnail_source": "spotify",
        "thumbnail_confidence": 0.92,
        "spotify_url": "https://open.spotify.com/track/eighteen-slowed",
    }
    canonical_audio = "18 (Eighteen) - Slowed Vic Slater audio"

    def fake_run_ytdlp(cls, query, requester, requester_id):
        ytdlp_calls.append(query)
        if query == f"ytsearch1:{canonical_audio}":
            return [
                TrackInfo(
                    title="Dave - The Boy Who Played the Harp",
                    webpage_url="https://www.youtube.com/watch?v=dave-wrong",
                    duration=235,
                    thumbnail="https://i.ytimg.com/vi/dave-wrong/hqdefault.jpg",
                    requester=requester,
                    requester_id=requester_id,
                    source="youtube",
                    stream_url="https://stream.test/dave-wrong",
                    artist="Santan Dave",
                )
            ]
        if query == f"ytsearch3:{canonical_audio}":
            return [
                TrackInfo(
                    title="Dave - The Boy Who Played the Harp",
                    webpage_url="https://www.youtube.com/watch?v=dave-wrong",
                    duration=235,
                    thumbnail="https://i.ytimg.com/vi/dave-wrong/hqdefault.jpg",
                    requester=requester,
                    requester_id=requester_id,
                    source="youtube",
                    stream_url="https://stream.test/dave-wrong",
                    artist="Santan Dave",
                ),
                TrackInfo(
                    title="Eighteen (Slowed)",
                    webpage_url="https://soundcloud.com/jkmlfgh/eighteen-slowed",
                    duration=260,
                    thumbnail="https://i1.sndcdn.com/artworks-eighteen.jpg",
                    requester=requester,
                    requester_id=requester_id,
                    source="soundcloud",
                    stream_url="https://stream.test/eighteen-slowed",
                    artist="jkmlfgh",
                ),
                TrackInfo(
                    title="18 (Eighteen) - Slowed",
                    webpage_url="https://www.youtube.com/watch?v=eighteen-correct",
                    duration=260,
                    thumbnail="https://i.ytimg.com/vi/eighteen-correct/hqdefault.jpg",
                    requester=requester,
                    requester_id=requester_id,
                    source="youtube",
                    stream_url="https://stream.test/eighteen-correct",
                    artist="Vic Slater",
                ),
            ]
        raise AssertionError(f"unexpected ytdlp query: {query}")

    def fail_enrich(cls, tracks, query):
        raise AssertionError("should not need fallback enrich when spotify hint is present")

    try:
        Config.CACHE_ENABLED = False
        Config.SPOTIFY_CLIENT_ID = "test-client"
        Config.SPOTIFY_AMBIGUOUS_WAIT_SECONDS = 0.0
        SourceResolver._sp_search_track_meta = classmethod(lambda cls, query: sp_meta)
        SourceResolver._run_ytdlp = classmethod(fake_run_ytdlp)
        SourceResolver._enrich_with_spotify = classmethod(fail_enrich)

        tracks = await SourceResolver.resolve_choices("eighteen slowed", "tester", 1, n=1)
    finally:
        Config.CACHE_ENABLED = original_cache_enabled
        Config.SPOTIFY_CLIENT_ID = original_spotify_id
        Config.SPOTIFY_AMBIGUOUS_WAIT_SECONDS = original_ambiguous_wait
        SourceResolver._sp_search_track_meta = original_sp_search
        SourceResolver._run_ytdlp = original_run_ytdlp
        SourceResolver._enrich_with_spotify = original_enrich

    assert ytdlp_calls == [
        f"ytsearch1:{canonical_audio}",
        f"ytsearch3:{canonical_audio}",
    ], ytdlp_calls
    assert len(tracks) == 1, tracks
    assert tracks[0].title == "Eighteen (Slowed)", tracks[0]
    assert tracks[0].webpage_url == "https://soundcloud.com/jkmlfgh/eighteen-slowed", tracks[0]
    assert tracks[0].source == "soundcloud", tracks[0]


asyncio.run(main())
print("OK: ambiguous spotify hint rejects incoherent first yt result")
