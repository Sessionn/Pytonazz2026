"""
tests/test_resolver_spotify_direct_track_unknown_duration_fast_path.py

Esegui dalla root del progetto con:
    python tests/test_resolver_spotify_direct_track_unknown_duration_fast_path.py
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
        "name": "CALM DES FCKDOWN",
        "duration_ms": 154000,
        "popularity": 42,
        "artists": [{"name": "Ski Mask the Slump God"}],
        "album": {"images": [{"url": "https://i.scdn.co/image/calm"}]},
        "external_urls": {"spotify": "https://open.spotify.com/track/calm"},
    }
    query_with_artist = "CALM DES FCKDOWN Ski Mask the Slump God"

    def fake_run_ytdlp(cls, query, requester, requester_id):
        calls.append(query)
        if query != f"ytsearch1:{query_with_artist}":
            raise AssertionError(f"unexpected fallback query: {query}")
        return [
            TrackInfo(
                title="CALM DES FCKDOWN",
                webpage_url="https://www.youtube.com/watch?v=calm",
                duration=0,
                thumbnail="https://i.ytimg.com/vi/calm/hqdefault.jpg",
                requester=requester,
                requester_id=requester_id,
                source="youtube",
                stream_url="https://stream.test/calm",
                artist="",
            )
        ]

    try:
        SourceResolver._run_ytdlp = classmethod(fake_run_ytdlp)
        resolved = SourceResolver._sp_track_from_obj(sp_track, "Ski Mask the Slump God", "tester", 1)
    finally:
        SourceResolver._run_ytdlp = original_run_ytdlp

    assert calls == [f"ytsearch1:{query_with_artist}"], calls
    assert resolved is not None
    assert resolved.title == "CALM DES FCKDOWN", resolved
    assert resolved.duration == 154, resolved
    assert resolved.spotify_url == "https://open.spotify.com/track/calm", resolved
    assert resolved.thumbnail_source == "spotify", resolved


main()
print("OK: spotify direct track accepts strong first result even with missing YT duration")
