"""
tests/test_lavalink_backend_selection.py

Run from project root:
    python tests/test_lavalink_backend_selection.py
"""

import os
import sys
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.audio_backends.lavalink import LavalinkAudioBackend, _payload_error, _select_track
from config import Config
from core.source_resolver import SourceResolver
from core.source_resolver.models import TrackInfo


def _track(title: str, author: str = "h6itam", length: int = 97000) -> dict:
    return {
        "encoded": "encoded",
        "info": {
            "title": title,
            "author": author,
            "length": length,
            "uri": "https://youtube.test/watch",
            "sourceName": "youtube",
        },
    }


def test_lavalink_selection_uses_resolver_ranking() -> None:
    tracks = [
        _track("MONTAGEM ALQUIMIA (SLOWED)", length=114000),
        _track("MONTAGEM ALQUIMIA", length=97000),
    ]

    selected = _select_track("montagem alquimia", tracks, apply_ranking=True)

    assert selected["info"]["title"] == "MONTAGEM ALQUIMIA", selected


def test_lavalink_selection_keeps_first_for_direct_urls() -> None:
    tracks = [
        _track("First direct result"),
        _track("Better looking title"),
    ]

    selected = _select_track("https://www.youtube.com/watch?v=abc", tracks, apply_ranking=False)

    assert selected["info"]["title"] == "First direct result", selected


def test_lavalink_payload_error_prefers_root_cause() -> None:
    payload = {
        "loadType": "error",
        "data": {
            "message": "Something went wrong while looking up the track.",
            "cause": "com.sedmelluq.discord.lavaplayer.tools.FriendlyException",
            "causeStackTrace": (
                "com.sedmelluq.discord.lavaplayer.tools.FriendlyException: wrapper\n"
                "Caused by: com.sedmelluq.discord.lavaplayer.tools.FriendlyException: "
                "Spotify generated playlists are no longer accessible via anonymous tokens.\n"
            ),
        },
    }

    assert _payload_error(payload) == (
        "Spotify generated playlists are no longer accessible via anonymous tokens."
    )


async def test_lavalink_spotify_track_uses_resolver_bridge() -> None:
    original_resolve = SourceResolver.resolve
    original_native = Config.LAVALINK_SPOTIFY_NATIVE
    spotify_url = "https://open.spotify.com/track/0VjIjW4GlUZAMYd2vXMi3b"
    loaded_identifiers = []

    async def fake_resolve(cls, query: str, requester: str, requester_id: int = 0) -> list:
        assert query == spotify_url
        return [
            TrackInfo(
                title="Blinding Lights",
                webpage_url="https://www.youtube.com/watch?v=4NRXx6U8ABQ",
                duration=200,
                thumbnail="",
                requester=requester,
                requester_id=requester_id,
                source="spotify",
                stream_url="https://stream.test/blinding",
                artist="The Weeknd",
                spotify_url=spotify_url,
            )
        ]

    async def fake_loadtracks(identifier: str) -> dict:
        loaded_identifiers.append(identifier)
        return {
            "loadType": "search",
            "data": [
                _track("Blinding Lights (Piano Karaoke Version)", "Sing2Piano", 178000),
                _track("Blinding Lights", "The Weeknd", 200000),
            ],
        }

    backend = LavalinkAudioBackend()
    backend._request_loadtracks = fake_loadtracks

    try:
        Config.LAVALINK_SPOTIFY_NATIVE = False
        SourceResolver.resolve = classmethod(fake_resolve)
        result = await backend.load(spotify_url, requester="tester", requester_id=7)
    finally:
        Config.LAVALINK_SPOTIFY_NATIVE = original_native
        SourceResolver.resolve = original_resolve

    assert result.ok, result
    assert result.source == "spotify+lavalink", result
    assert result.title == "Blinding Lights", result
    assert loaded_identifiers == ["ytmsearch:Blinding Lights The Weeknd"], loaded_identifiers


async def test_lavalink_spotify_track_prefers_native_lavasrc() -> None:
    original_native = Config.LAVALINK_SPOTIFY_NATIVE
    spotify_url = "https://open.spotify.com/track/0VjIjW4GlUZAMYd2vXMi3b"
    loaded_identifiers = []

    async def fake_loadtracks(identifier: str) -> dict:
        loaded_identifiers.append(identifier)
        return {
            "loadType": "track",
            "data": _track("Blinding Lights", "The Weeknd", 200000),
        }

    backend = LavalinkAudioBackend()
    backend._request_loadtracks = fake_loadtracks

    try:
        Config.LAVALINK_SPOTIFY_NATIVE = True
        result = await backend.load(spotify_url, requester="tester", requester_id=7)
    finally:
        Config.LAVALINK_SPOTIFY_NATIVE = original_native

    assert result.ok, result
    assert result.title == "Blinding Lights", result
    assert loaded_identifiers == [spotify_url], loaded_identifiers


test_lavalink_selection_uses_resolver_ranking()
test_lavalink_selection_keeps_first_for_direct_urls()
test_lavalink_payload_error_prefers_root_cause()
asyncio.run(test_lavalink_spotify_track_uses_resolver_bridge())
asyncio.run(test_lavalink_spotify_track_prefers_native_lavasrc())
print("OK: lavalink backend ranks search candidates and preserves direct URL order")
