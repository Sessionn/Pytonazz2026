"""
tests/test_resolver_spotify_weak_hint_keeps_raw.py

Esegui dalla root del progetto con:
    python tests/test_resolver_spotify_weak_hint_keeps_raw.py
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
    original_wait = Config.SPOTIFY_HINT_WAIT_SECONDS
    original_sp_search = SourceResolver._sp_search_track_meta
    original_run_ytdlp = SourceResolver._run_ytdlp
    original_enrich = SourceResolver._enrich_with_spotify

    ytdlp_calls = []
    wrong_spotify_hint = {
        "title": "Calm Down",
        "artist": "Evanescence",
        "duration": 258,
        "thumbnail": "https://i.scdn.co/image/calm-down",
        "thumbnail_source": "spotify",
        "thumbnail_confidence": 0.92,
        "spotify_url": "https://open.spotify.com/track/wrong",
        "popularity": 27,
    }

    def fake_run_ytdlp(cls, query, requester, requester_id):
        ytdlp_calls.append(query)
        if query != "ytsearch1:calm des fuckdosn":
            raise AssertionError(f"canonical retry inatteso: {query}")
        return [
            TrackInfo(
                title="BUCKSHOT - CALM DES FCKDOWN (PROD. ASA NISI MASA)",
                webpage_url="https://www.youtube.com/watch?v=calm",
                duration=129,
                thumbnail="https://i.ytimg.com/vi/calm/hqdefault.jpg",
                requester=requester,
                requester_id=requester_id,
                source="youtube",
                stream_url="https://stream.test/calm",
                artist="BUCKSHOT",
            )
        ]

    def fail_enrich(cls, tracks, query):
        raise AssertionError("fallback enrich non deve partire quando Spotify hint e' presente")

    try:
        Config.CACHE_ENABLED = False
        Config.SPOTIFY_CLIENT_ID = "test-client"
        Config.SPOTIFY_HINT_WAIT_SECONDS = 0.0
        SourceResolver._sp_search_track_meta = classmethod(lambda cls, query: wrong_spotify_hint)
        SourceResolver._run_ytdlp = classmethod(fake_run_ytdlp)
        SourceResolver._enrich_with_spotify = classmethod(fail_enrich)

        tracks = await SourceResolver.resolve_choices("calm des fuckdosn", "tester", 1, n=1)
    finally:
        Config.CACHE_ENABLED = original_cache_enabled
        Config.SPOTIFY_CLIENT_ID = original_spotify_id
        Config.SPOTIFY_HINT_WAIT_SECONDS = original_wait
        SourceResolver._sp_search_track_meta = original_sp_search
        SourceResolver._run_ytdlp = original_run_ytdlp
        SourceResolver._enrich_with_spotify = original_enrich

    assert ytdlp_calls == ["ytsearch1:calm des fuckdosn"], ytdlp_calls
    assert len(tracks) == 1, tracks
    assert tracks[0].title.startswith("BUCKSHOT - CALM DES FCKDOWN"), tracks[0]
    assert tracks[0].artist == "BUCKSHOT", tracks[0]
    assert tracks[0].spotify_url == "", tracks[0]


asyncio.run(main())
print("OK: weak Spotify hint does not replace query-coherent raw result")
