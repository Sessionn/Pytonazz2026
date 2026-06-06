"""
tests/test_resolver_spotify_lyric_phrase_guard.py

Esegui dalla root del progetto con:
    python tests/test_resolver_spotify_lyric_phrase_guard.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from core.source_resolver import SourceResolver
from core.source_resolver.models import TrackInfo


async def run_case(sp_meta: dict, expected_call: str) -> list[TrackInfo]:
    original_cache_enabled = Config.CACHE_ENABLED
    original_spotify_id = Config.SPOTIFY_CLIENT_ID
    original_sp_search = SourceResolver._sp_search_track_meta
    original_sp_search_for_track = SourceResolver._sp_search_track_meta_for_track
    original_run_ytdlp = SourceResolver._run_ytdlp
    original_enrich = SourceResolver._enrich_with_spotify
    ytdlp_calls = []

    def fake_run_ytdlp(cls, query, requester, requester_id):
        ytdlp_calls.append(query)
        if "Royal Sadness" in query and query != expected_call:
            raise AssertionError(f"unexpected canonical retry: {query}")
        if query == expected_call and "Royal Sadness" in query:
            return [
                TrackInfo(
                    title="Jane, You're Early",
                    artist="Royal Sadness",
                    webpage_url="https://www.youtube.com/watch?v=royal",
                    duration=184,
                    thumbnail="https://i.ytimg.com/vi/royal/hqdefault.jpg",
                    requester=requester,
                    requester_id=requester_id,
                    source="youtube",
                    stream_url="https://stream.test/royal",
                )
            ]
        return [
            TrackInfo(
                title="The Long Faces - Jane!",
                artist="The Long Faces",
                webpage_url="https://www.youtube.com/watch?v=jane",
                duration=218,
                thumbnail="https://i.ytimg.com/vi/jane/hqdefault.jpg",
                requester=requester,
                requester_id=requester_id,
                source="youtube",
                stream_url="https://stream.test/jane",
            )
        ]

    def fail_enrich(cls, tracks, query):
        raise AssertionError("late Spotify enrichment should not run in this fast-path test")

    def fake_sp_search_for_track(cls, original_query, track):
        meta = {
            "title": "Jane!",
            "artist": "The Long Faces",
            "duration": 218,
            "thumbnail": "https://i.scdn.co/image/jane",
            "thumbnail_source": "spotify",
            "thumbnail_confidence": 0.92,
            "spotify_url": "https://open.spotify.com/track/jane",
            "popularity": 54,
        }
        from core.source_resolver.scoring import _compute_enrich_confidence

        return meta, _compute_enrich_confidence(original_query, track, meta)

    try:
        Config.CACHE_ENABLED = False
        Config.SPOTIFY_CLIENT_ID = "test-client"
        SourceResolver._sp_search_track_meta = classmethod(lambda cls, query: sp_meta)
        SourceResolver._sp_search_track_meta_for_track = classmethod(fake_sp_search_for_track)
        SourceResolver._run_ytdlp = classmethod(fake_run_ytdlp)
        SourceResolver._enrich_with_spotify = classmethod(fail_enrich)

        tracks = await SourceResolver.resolve_choices("jane, you're early", "tester", 1, n=1)
    finally:
        Config.CACHE_ENABLED = original_cache_enabled
        Config.SPOTIFY_CLIENT_ID = original_spotify_id
        SourceResolver._sp_search_track_meta = original_sp_search
        SourceResolver._sp_search_track_meta_for_track = original_sp_search_for_track
        SourceResolver._run_ytdlp = original_run_ytdlp
        SourceResolver._enrich_with_spotify = original_enrich

    assert ytdlp_calls == [expected_call], ytdlp_calls
    return tracks


async def main() -> None:
    low_pop_spotify = {
        "title": "Jane, You're Early",
        "artist": "Royal Sadness",
        "duration": 184,
        "thumbnail": "https://i.scdn.co/image/low",
        "thumbnail_source": "spotify",
        "thumbnail_confidence": 0.92,
        "spotify_url": "https://open.spotify.com/track/low",
        "popularity": 12,
    }
    tracks = await run_case(low_pop_spotify, "ytsearch1:jane, you're early")
    assert tracks[0].title == "Jane!", tracks[0]
    assert tracks[0].artist == "The Long Faces", tracks[0]
    assert tracks[0].spotify_url == "https://open.spotify.com/track/jane", tracks[0]
    assert tracks[0].thumbnail_source == "spotify", tracks[0]

    high_pop_spotify = dict(low_pop_spotify)
    high_pop_spotify["popularity"] = 80
    tracks = await run_case(high_pop_spotify, "ytsearch1:Jane, You're Early Royal Sadness")
    assert tracks[0].spotify_url == "https://open.spotify.com/track/low", tracks[0]


asyncio.run(main())
print("OK: Spotify lyric phrase guard")
