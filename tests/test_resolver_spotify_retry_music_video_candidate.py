"""
tests/test_resolver_spotify_retry_music_video_candidate.py

Esegui dalla root del progetto con:
    python tests/test_resolver_spotify_retry_music_video_candidate.py
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
        "title": "Sua Amiga Vou Pegar",
        "artist": "MC Lan, MC WM",
        "duration": 180,
        "thumbnail": "https://i.scdn.co/image/sua-amiga",
        "thumbnail_source": "spotify",
        "thumbnail_confidence": 0.92,
        "spotify_url": "https://open.spotify.com/track/sua-amiga",
    }
    canonical_query = "Sua Amiga Vou Pegar MC Lan, MC WM"

    def fake_ytdlp(cls, query, requester, requester_id):
        calls.append(query)
        if query == f"ytsearch1:{canonical_query}":
            return [
                TrackInfo(
                    title="MC Lan e MC WM - Sua Amiga Vou Pegar (KondZilla)",
                    webpage_url="https://www.youtube.com/watch?v=video",
                    duration=180,
                    thumbnail="https://i.ytimg.com/vi/video/hqdefault.jpg",
                    requester=requester,
                    requester_id=requester_id,
                    source="youtube",
                    stream_url="https://stream.test/video",
                    artist="Canal KondZilla",
                )
            ]
        if query == f"ytsearch3:{canonical_query}":
            return [
                TrackInfo(
                    title="MC Lan e MC WM - Sua Amiga Vou Pegar (KondZilla)",
                    webpage_url="https://www.youtube.com/watch?v=video",
                    duration=180,
                    thumbnail="https://i.ytimg.com/vi/video/hqdefault.jpg",
                    requester=requester,
                    requester_id=requester_id,
                    source="youtube",
                    stream_url="https://stream.test/video",
                    artist="Canal KondZilla",
                ),
                TrackInfo(
                    title="Sua Amiga Vou Pegar",
                    webpage_url="https://www.youtube.com/watch?v=audio",
                    duration=180,
                    thumbnail="https://i.ytimg.com/vi/audio/hqdefault.jpg",
                    requester=requester,
                    requester_id=requester_id,
                    source="youtube",
                    stream_url="https://stream.test/audio",
                    artist="MC Lan, MC WM",
                ),
            ]
        raise AssertionError(f"unexpected ytdlp query: {query}")

    def fail_enrich(cls, tracks, query):
        raise AssertionError("spotify hint path should handle music-video retry directly")

    try:
        Config.CACHE_ENABLED = False
        Config.SPOTIFY_CLIENT_ID = "test-client"
        Config.SPOTIFY_AMBIGUOUS_WAIT_SECONDS = 0.0
        SourceResolver._sp_search_track_meta = classmethod(lambda cls, query: sp_meta)
        SourceResolver._run_ytdlp = classmethod(fake_ytdlp)
        SourceResolver._enrich_with_spotify = classmethod(fail_enrich)

        tracks = await SourceResolver.resolve_choices("sua amiga vou pegar", "tester", 1, n=1)
    finally:
        Config.CACHE_ENABLED = original_cache_enabled
        Config.SPOTIFY_CLIENT_ID = original_spotify_id
        Config.SPOTIFY_AMBIGUOUS_WAIT_SECONDS = original_ambiguous_wait
        SourceResolver._sp_search_track_meta = original_sp_search
        SourceResolver._run_ytdlp = original_run_ytdlp
        SourceResolver._enrich_with_spotify = original_enrich

    assert calls == [
        f"ytsearch1:{canonical_query}",
        f"ytsearch3:{canonical_query}",
    ], calls
    assert len(tracks) == 1, tracks
    assert tracks[0].webpage_url == "https://www.youtube.com/watch?v=audio", tracks[0]
    assert tracks[0].title == "Sua Amiga Vou Pegar", tracks[0]
    assert tracks[0].artist == "MC Lan, MC WM", tracks[0]
    assert tracks[0].thumbnail_source == "spotify", tracks[0]


asyncio.run(main())
print("OK: resolver retries audio candidate when Spotify hint first result is music video")
