"""
tests/test_resolver_spotify_cover_link_mode.py

Esegui dalla root del progetto con:
    python tests/test_resolver_spotify_cover_link_mode.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
import core.source_resolver as resolver_mod
from core.source_resolver import SourceResolver
from core.source_resolver.models import TrackInfo


async def main() -> None:
    original_cache_enabled = Config.CACHE_ENABLED
    original_spotify_id = Config.SPOTIFY_CLIENT_ID
    original_sp_search = SourceResolver._sp_search_track_meta
    original_run_ytdlp = SourceResolver._run_ytdlp
    original_compute = resolver_mod._compute_enrich_confidence

    calls = []
    sp_meta = {
        "title": "Gucci Flip Flops x Careless Whisper",
        "artist": "Moonshine",
        "duration": 182,
        "thumbnail": "https://i.scdn.co/image/gucci-flips-flops",
        "thumbnail_source": "spotify",
        "thumbnail_confidence": 0.92,
        "spotify_url": "https://open.spotify.com/track/7qxaXTeqwpdnjzmUE2NOE1",
    }

    def fake_sp_search(cls, query):
        return sp_meta

    def fake_ytdlp(cls, query, requester, requester_id):
        calls.append(query)
        return [
            TrackInfo(
                title="Gucci Flip Flops x Careless Whisper",
                webpage_url="https://www.youtube.com/watch?v=gucci-careless",
                duration=181,
                thumbnail="https://i.ytimg.com/vi/gucci-careless/hqdefault.jpg",
                requester=requester,
                requester_id=requester_id,
                source="youtube",
                stream_url="https://stream.test/gucci-careless",
            )
        ]

    def fake_score(original_query, yt_track, meta):
        return {
            "decision": "skip",
            "confidence": 0.44,
            "query_sim": 1.0,
            "yt_sim": 0.91,
            "artist_sim": 0.0,
            "artist_hint_present": False,
            "duration_sim": 0.92,
            "variant_penalty": 0.0,
            "non_music_penalty": 0.0,
            "reason": "low_confidence",
        }

    try:
        Config.CACHE_ENABLED = False
        Config.SPOTIFY_CLIENT_ID = "test-client"
        SourceResolver._sp_search_track_meta = classmethod(fake_sp_search)
        SourceResolver._run_ytdlp = classmethod(fake_ytdlp)
        resolver_mod._compute_enrich_confidence = fake_score

        tracks = await SourceResolver.resolve_choices(
            "gucci flips flops x Careless Whisper", "tester", 1, n=1
        )
    finally:
        Config.CACHE_ENABLED = original_cache_enabled
        Config.SPOTIFY_CLIENT_ID = original_spotify_id
        SourceResolver._sp_search_track_meta = original_sp_search
        SourceResolver._run_ytdlp = original_run_ytdlp
        resolver_mod._compute_enrich_confidence = original_compute

    assert calls == ["ytsearch1:gucci flips flops x Careless Whisper"], calls
    assert tracks[0].spotify_url == sp_meta["spotify_url"], tracks[0]
    assert tracks[0].thumbnail == sp_meta["thumbnail"], tracks[0]
    assert tracks[0].thumbnail_source == "spotify", tracks[0]
    assert tracks[0].title == "Gucci Flip Flops x Careless Whisper", tracks[0]


asyncio.run(main())
print("OK: resolver attaches Spotify link and cover on coherent medium-confidence matches")
