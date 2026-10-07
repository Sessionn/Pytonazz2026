"""
tests/test_resolver_flat_multi_search.py

Esegui dalla root del progetto con:
    python tests/test_resolver_flat_multi_search.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.source_resolver import SourceResolver
from core.source_resolver.models import TrackInfo


def _track(video_id: str, stream_url: str = "") -> TrackInfo:
    return TrackInfo(
        title=f"Song {video_id}",
        webpage_url=f"https://www.youtube.com/watch?v={video_id}",
        duration=200,
        thumbnail="",
        requester="tester",
        requester_id=1,
        source="youtube",
        stream_url=stream_url,
        artist="Artist",
    )


def test_multi_candidate_search_is_flat() -> None:
    original_flat = SourceResolver._run_ytdlp_flat_candidates
    original_cached = SourceResolver._get_cached_ytdlp_results
    flat_calls = []

    def fake_flat(cls, query, requester, requester_id):
        flat_calls.append(query)
        return [_track("a"), _track("b"), _track("c")]

    try:
        SourceResolver._run_ytdlp_flat_candidates = classmethod(fake_flat)
        SourceResolver._get_cached_ytdlp_results = classmethod(lambda cls, *a: None)
        results = SourceResolver._run_ytdlp("ytsearch3:song artist", "tester", 1)
    finally:
        SourceResolver._run_ytdlp_flat_candidates = original_flat
        SourceResolver._get_cached_ytdlp_results = original_cached

    assert flat_calls == ["ytsearch3:song artist"], flat_calls
    assert [t.webpage_url[-1] for t in results] == ["a", "b", "c"], results
    assert not any(t.stream_url for t in results), "la ricerca flat non estrae stream"


async def _attach(available: set[str], candidates: list) -> tuple[TrackInfo, list]:
    original_fetch = SourceResolver._fetch_stream_url
    fetched = []

    def fake_fetch(cls, webpage_url):
        fetched.append(webpage_url[-1])
        return f"https://stream.test/{webpage_url[-1]}" if webpage_url[-1] in available else ""

    chosen = _track("a")
    chosen.title = "Titolo Spotify"
    try:
        SourceResolver._fetch_stream_url = classmethod(fake_fetch)
        await SourceResolver._attach_winner_stream(chosen, candidates)
    finally:
        SourceResolver._fetch_stream_url = original_fetch
    return chosen, fetched


async def test_attach_winner_stream() -> None:
    pool = [_track("a"), _track("b"), _track("c")]

    chosen, fetched = await _attach({"a", "b", "c"}, pool)
    assert fetched == ["a"], fetched
    assert chosen.stream_url == "https://stream.test/a", chosen

    # Il video scelto non e' disponibile: si passa al candidato successivo,
    # tenendo i metadati gia' scelti.
    chosen, fetched = await _attach({"b", "c"}, pool)
    assert fetched == ["a", "b"], fetched
    assert chosen.webpage_url.endswith("=b"), chosen
    assert chosen.stream_url == "https://stream.test/b", chosen
    assert chosen.title == "Titolo Spotify", chosen

    # Nessuno disponibile: al massimo 3 tentativi, il brano resta senza stream.
    chosen, fetched = await _attach(set(), pool + [_track("d")])
    assert fetched == ["a", "b", "c"], fetched
    assert chosen.stream_url == "" and chosen.webpage_url.endswith("=a"), chosen


test_multi_candidate_search_is_flat()
asyncio.run(test_attach_winner_stream())
print("OK: ricerche multiple flat, stream solo per il brano scelto con riserva")
