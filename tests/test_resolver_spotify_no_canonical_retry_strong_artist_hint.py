"""
tests/test_resolver_spotify_no_canonical_retry_strong_artist_hint.py

Esegui dalla root del progetto con:
    python tests/test_resolver_spotify_no_canonical_retry_strong_artist_hint.py
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
        "title": "Splinter Cell",
        "artist": "G.Mineiro, Flatpearl, Jiz, Succo",
        "duration": 177,
        "thumbnail": "https://i.scdn.co/image/splinter",
        "thumbnail_source": "spotify",
        "thumbnail_confidence": 0.92,
        "spotify_url": "https://open.spotify.com/track/splinter",
    }

    def fake_ytdlp(cls, query, requester, requester_id):
        ytdlp_calls.append(query)
        if query != "ytsearch1:splinter cell g.mineiro":
            raise AssertionError(f"canonical retry inatteso: {query}")
        return [
            TrackInfo(
                title='G.Mineiro - "Splinter Cell" prod. Flat, Succo, Jiz (Visualizer)',
                webpage_url="https://www.youtube.com/watch?v=splinter",
                duration=177,
                thumbnail="https://i.ytimg.com/vi/splinter/hqdefault.jpg",
                requester=requester,
                requester_id=requester_id,
                source="youtube",
                stream_url="https://stream.test/splinter",
                artist="G.MINEIRO",
            )
        ]

    def fail_enrich(cls, tracks, query):
        raise AssertionError("enrich fallback non deve partire quando Spotify hint e' gia disponibile")

    try:
        Config.CACHE_ENABLED = False
        Config.SPOTIFY_CLIENT_ID = "test-client"
        SourceResolver._sp_search_track_meta = classmethod(lambda cls, query: sp_meta)
        SourceResolver._run_ytdlp = classmethod(fake_ytdlp)
        SourceResolver._enrich_with_spotify = classmethod(fail_enrich)

        tracks = await SourceResolver.resolve_choices("splinter cell g.mineiro", "tester", 1, n=1)
    finally:
        Config.CACHE_ENABLED = original_cache_enabled
        Config.SPOTIFY_CLIENT_ID = original_spotify_id
        SourceResolver._sp_search_track_meta = original_sp_search
        SourceResolver._run_ytdlp = original_run_ytdlp
        SourceResolver._enrich_with_spotify = original_enrich

    assert ytdlp_calls == ["ytsearch1:splinter cell g.mineiro"], ytdlp_calls
    assert len(tracks) == 1, tracks
    assert tracks[0].title.startswith('G.Mineiro - "Splinter Cell"'), tracks[0]
    assert tracks[0].thumbnail_source != "spotify", tracks[0]


asyncio.run(main())
print("OK: no canonical retry when artist-hinted raw result is already strong")
