"""
tests/test_resolver_spotify_direct_track_soft_fast_path.py

Esegui dalla root del progetto con:
    python tests/test_resolver_spotify_direct_track_soft_fast_path.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.source_resolver import SourceResolver
from core.source_resolver.models import TrackInfo


def _run_case(sp_track: dict, first_candidate: TrackInfo) -> None:
    original_run_ytdlp = SourceResolver._run_ytdlp
    calls = []
    query_with_artist = f"{sp_track['name']} {', '.join(a['name'] for a in sp_track['artists'])}"

    def fake_run_ytdlp(cls, query, requester, requester_id):
        calls.append(query)
        if query != f"ytsearch1:{query_with_artist}":
            raise AssertionError(f"unexpected fallback query: {query}")
        return [first_candidate]

    try:
        SourceResolver._run_ytdlp = classmethod(fake_run_ytdlp)
        resolved = SourceResolver._sp_track_from_obj(sp_track, sp_track["artists"][0]["name"], "tester", 1)
    finally:
        SourceResolver._run_ytdlp = original_run_ytdlp

    assert calls == [f"ytsearch1:{query_with_artist}"], calls
    assert resolved is not None
    assert resolved.title == sp_track["name"], resolved
    assert resolved.source == "spotify", resolved


def main() -> None:
    _run_case(
        {
            "name": "Go Your Own Way - 2004 Remaster",
            "duration_ms": 223000,
            "popularity": 42,
            "artists": [{"name": "Fleetwood Mac"}],
            "album": {"images": [{"url": "https://i.scdn.co/image/go-your-own-way"}]},
            "external_urls": {"spotify": "https://open.spotify.com/track/go-your-own-way"},
        },
        TrackInfo(
            title="Go Your Own Way (2004 Remaster)",
            webpage_url="https://www.youtube.com/watch?v=go-your-own-way",
            duration=223,
            thumbnail="https://i.ytimg.com/vi/go-your-own-way/hqdefault.jpg",
            requester="tester",
            requester_id=1,
            source="youtube",
            stream_url="https://stream.test/go-your-own-way",
            artist="",
        ),
    )

    _run_case(
        {
            "name": "You Are My Sunshine",
            "duration_ms": 177000,
            "popularity": 42,
            "artists": [{"name": "Zach Bryan"}],
            "album": {"images": [{"url": "https://i.scdn.co/image/you-are-my-sunshine"}]},
            "external_urls": {"spotify": "https://open.spotify.com/track/you-are-my-sunshine"},
        },
        TrackInfo(
            title="Zach Bryan - You Are My Sunshine",
            webpage_url="https://www.youtube.com/watch?v=you-are-my-sunshine",
            duration=177,
            thumbnail="https://i.ytimg.com/vi/you-are-my-sunshine/hqdefault.jpg",
            requester="tester",
            requester_id=1,
            source="youtube",
            stream_url="https://stream.test/you-are-my-sunshine",
            artist="",
        ),
    )

    _run_case(
        {
            "name": "SIR BAUDELAIRE (feat. DJ Drama)",
            "duration_ms": 88000,
            "popularity": 42,
            "artists": [{"name": "Tyler, The Creator"}, {"name": "DJ Drama"}],
            "album": {"images": [{"url": "https://i.scdn.co/image/sir-baudelaire"}]},
            "external_urls": {"spotify": "https://open.spotify.com/track/sir-baudelaire"},
        },
        TrackInfo(
            title="SIR BAUDELAIRE (Audio)",
            webpage_url="https://www.youtube.com/watch?v=sir-baudelaire",
            duration=88,
            thumbnail="https://i.ytimg.com/vi/sir-baudelaire/hqdefault.jpg",
            requester="tester",
            requester_id=1,
            source="youtube",
            stream_url="https://stream.test/sir-baudelaire",
            artist="",
        ),
    )


main()
print("OK: spotify direct track accepts coherent first ytsearch1 matches without fallback")
