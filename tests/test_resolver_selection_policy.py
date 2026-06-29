"""
tests/test_resolver_selection_policy.py

Run from project root:
    python tests/test_resolver_selection_policy.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from core.source_resolver import SourceResolver
from core.source_resolver.models import TrackInfo
from core.source_resolver.selection import (
    has_unrequested_extra_variant,
    needs_quality_fallback,
    needs_wider_search,
    rank_tracks,
    select_best_track,
)


def _track(title: str, artist: str = "", duration: int = 180, url: str = "x") -> TrackInfo:
    return TrackInfo(
        title=title,
        webpage_url=f"https://www.youtube.com/watch?v={url}",
        duration=duration,
        thumbnail="",
        requester="tester",
        requester_id=1,
        source="youtube",
        stream_url=f"https://stream.test/{url}",
        artist=artist,
    )


def test_selection_prefers_query_coherent_audio() -> None:
    candidates = [
        _track("Lionel Richie - Hello (Official Video)", "Lionel Richie", 320, "wrong"),
        _track("Adele - Hello (Official Audio)", "AdeleVEVO", 295, "right"),
        _track("Hello Adele cover acoustic", "Random Channel", 250, "cover"),
    ]

    chosen = select_best_track("hello adele", candidates)
    ranked = rank_tracks("hello adele", candidates)

    assert chosen.webpage_url.endswith("right"), ranked
    assert ranked[0].score.total > ranked[1].score.total, ranked


def test_selection_keeps_requested_variant() -> None:
    candidates = [
        _track("Adele - Hello (Official Audio)", "AdeleVEVO", 295, "studio"),
        _track("Adele - Hello Live at The Royal Albert Hall", "Adele", 310, "live"),
    ]

    chosen = select_best_track("hello adele live", candidates)

    assert chosen.webpage_url.endswith("live"), chosen
    assert not needs_wider_search("hello adele live", chosen)


def test_selection_penalizes_unrequested_extra_variant() -> None:
    candidates = [
        _track("DONNE RICCHE (Acoustic Version - Slowed)", "TonyPitony", 190, "slowed"),
        _track("DONNE RICCHE - Acoustic Version", "TonyPitony", 190, "acoustic"),
    ]

    chosen = select_best_track("DONNE RICCHE - Acoustic Version TonyPitony", candidates)

    assert chosen.webpage_url.endswith("acoustic"), chosen
    assert has_unrequested_extra_variant(
        "DONNE RICCHE - Acoustic Version TonyPitony",
        candidates[0],
    )
    assert needs_quality_fallback(
        "DONNE RICCHE - Acoustic Version TonyPitony",
        candidates[0],
    )


def test_quality_fallback_keeps_weak_but_coherent_match() -> None:
    candidate = _track("SESSONLINE", "TonyPitony", 137, "sessonline")

    assert not needs_quality_fallback("sessonline tony pitony", candidate)


def test_quality_fallback_rejects_low_confidence_mismatch() -> None:
    candidate = _track("Brahms Lullaby for Babies, Hours of Soft Music", "Baby Sleep Music", 7200, "brahms")

    assert needs_quality_fallback(
        "𝘄𝗵𝗶𝘁𝗲 𝗴𝗶𝗿𝗹 𝗺𝘂𝘀𝗶𝗰 𝗳𝗼𝗿 𝘁𝗵𝗲 𝗯𝗼𝘆𝘀 | 𝗽𝗹𝗮𝘆𝗹𝗶𝘀𝘁 🗿🔥 𝕣𝕒𝕚𝕫𝕫𝕪",
        candidate,
    )


async def test_resolver_widens_only_for_suspicious_first_result() -> None:
    original_cache_enabled = Config.CACHE_ENABLED
    original_spotify_id = Config.SPOTIFY_CLIENT_ID
    original_run_ytdlp = SourceResolver._run_ytdlp
    original_enrich = SourceResolver._enrich_with_spotify

    calls = []

    def fake_ytdlp(cls, query, requester, requester_id):
        calls.append(query)
        if query == "ytsearch1:hello adele":
            return [
                TrackInfo(
                    title="Lionel Richie - Hello (Official Video)",
                    webpage_url="https://www.youtube.com/watch?v=wrong",
                    duration=320,
                    thumbnail="",
                    requester=requester,
                    requester_id=requester_id,
                    source="youtube",
                    stream_url="https://stream.test/wrong",
                    artist="Lionel Richie",
                )
            ]
        if query == "ytsearch3:hello adele":
            return [
                TrackInfo(
                    title="Lionel Richie - Hello (Official Video)",
                    webpage_url="https://www.youtube.com/watch?v=wrong",
                    duration=320,
                    thumbnail="",
                    requester=requester,
                    requester_id=requester_id,
                    source="youtube",
                    stream_url="https://stream.test/wrong",
                    artist="Lionel Richie",
                ),
                TrackInfo(
                    title="Adele - Hello (Official Audio)",
                    webpage_url="https://www.youtube.com/watch?v=right",
                    duration=295,
                    thumbnail="",
                    requester=requester,
                    requester_id=requester_id,
                    source="youtube",
                    stream_url="https://stream.test/right",
                    artist="AdeleVEVO",
                ),
            ]
        raise AssertionError(f"unexpected ytdlp query: {query}")

    def fail_enrich(cls, tracks, query):
        raise AssertionError("Spotify enrich must not run when Spotify is disabled")

    try:
        Config.CACHE_ENABLED = False
        Config.SPOTIFY_CLIENT_ID = ""
        SourceResolver._run_ytdlp = classmethod(fake_ytdlp)
        SourceResolver._enrich_with_spotify = classmethod(fail_enrich)

        tracks = await SourceResolver.resolve_choices("hello adele", "tester", 1, n=1)
    finally:
        Config.CACHE_ENABLED = original_cache_enabled
        Config.SPOTIFY_CLIENT_ID = original_spotify_id
        SourceResolver._run_ytdlp = original_run_ytdlp
        SourceResolver._enrich_with_spotify = original_enrich

    assert calls == ["ytsearch1:hello adele", "ytsearch3:hello adele"], calls
    assert len(tracks) == 1, tracks
    assert tracks[0].webpage_url == "https://www.youtube.com/watch?v=right", tracks[0]


test_selection_prefers_query_coherent_audio()
test_selection_keeps_requested_variant()
test_selection_penalizes_unrequested_extra_variant()
test_quality_fallback_keeps_weak_but_coherent_match()
test_quality_fallback_rejects_low_confidence_mismatch()
asyncio.run(test_resolver_widens_only_for_suspicious_first_result())
print("OK: resolver selection policy ranks coherent candidates and widens suspicious fast results")
