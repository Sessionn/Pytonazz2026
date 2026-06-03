"""
tests/test_resolver_spotify_direct_track_fallback.py

Esegui dalla root del progetto con:
    python tests/test_resolver_spotify_direct_track_fallback.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.source_resolver import SourceResolver
from core.source_resolver.models import TrackInfo


def main() -> None:
    original_run_ytdlp = SourceResolver._run_ytdlp
    calls = []

    sp_track = {
        "name": "Jump All",
        "duration_ms": 155000,
        "popularity": 42,
        "artists": [{"name": "prodbykenny"}],
        "album": {"images": [{"url": "https://i.scdn.co/image/jump-all"}]},
        "external_urls": {"spotify": "https://open.spotify.com/track/jump-all"},
    }

    def fake_run_ytdlp(cls, query, requester, requester_id):
        calls.append(query)
        if query == "ytsearch1:Jump All prodbykenny":
            return [
                TrackInfo(
                    title="Jump Around Meme Remix",
                    webpage_url="https://www.youtube.com/watch?v=wrong",
                    duration=24,
                    thumbnail="https://i.ytimg.com/vi/wrong/hqdefault.jpg",
                    requester=requester,
                    requester_id=requester_id,
                    source="youtube",
                    stream_url="https://stream.test/wrong",
                    artist="Meme Factory",
                )
            ]
        if query == "ytsearch3:Jump All prodbykenny audio":
            return [
                TrackInfo(
                    title="prodbykenny - JUMP ALL",
                    webpage_url="https://soundcloud.com/prodbykenny/jump-all",
                    duration=155,
                    thumbnail="https://i1.sndcdn.com/artworks-jump-all.jpg",
                    requester=requester,
                    requester_id=requester_id,
                    source="soundcloud",
                    stream_url="https://stream.test/jump-all",
                    artist="prodbykenny",
                )
            ]
        raise AssertionError(f"unexpected query: {query}")

    try:
        SourceResolver._run_ytdlp = classmethod(fake_run_ytdlp)
        resolved = SourceResolver._sp_track_from_obj(sp_track, "prodbykenny", "tester", 1)
    finally:
        SourceResolver._run_ytdlp = original_run_ytdlp

    assert calls == [
        "ytsearch1:Jump All prodbykenny",
        "ytsearch3:Jump All prodbykenny audio",
    ], calls
    assert resolved is not None
    assert resolved.title == "Jump All", resolved
    assert resolved.source == "spotify", resolved
    assert resolved.webpage_url == "https://soundcloud.com/prodbykenny/jump-all", resolved


main()
print("OK: spotify direct track falls back when fast ytsearch1 match is weak")
