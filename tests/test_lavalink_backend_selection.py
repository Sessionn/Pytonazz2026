"""
tests/test_lavalink_backend_selection.py

Run from project root:
    python tests/test_lavalink_backend_selection.py
"""

import os
import sys
import asyncio
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.cache_db as cache_db
import core.source_resolver as resolver_module
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
    spotify_url = "https://open.spotify.com/intl-it/track/0VjIjW4GlUZAMYd2vXMi3b?si=test"
    canonical_url = "https://open.spotify.com/track/0VjIjW4GlUZAMYd2vXMi3b"
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
    assert loaded_identifiers == [canonical_url], loaded_identifiers


async def test_lavalink_youtube_url_falls_back_to_stream_bridge() -> None:
    original_resolve = SourceResolver.resolve
    youtube_url = "https://www.youtube.com/watch?v=kX2b9l26faU"
    stream_url = "https://stream.test/montagem"
    loaded_identifiers = []

    async def fake_resolve(cls, query: str, requester: str, requester_id: int = 0) -> list:
        assert query == youtube_url
        return [
            TrackInfo(
                title="MONTAGEM ALQUIMIA",
                webpage_url=youtube_url,
                duration=97,
                thumbnail="",
                requester=requester,
                requester_id=requester_id,
                source="youtube",
                stream_url=stream_url,
                artist="h6itam",
            )
        ]

    async def fake_loadtracks(identifier: str) -> dict:
        loaded_identifiers.append(identifier)
        if identifier == youtube_url:
            return {
                "loadType": "error",
                "data": {"message": "All clients failed to load the item."},
            }
        return {
            "loadType": "track",
            "data": _track("MONTAGEM ALQUIMIA", "h6itam", 97000),
        }

    backend = LavalinkAudioBackend()
    backend._request_loadtracks = fake_loadtracks

    try:
        SourceResolver.resolve = classmethod(fake_resolve)
        result = await backend.load(youtube_url, requester="tester", requester_id=7)
    finally:
        SourceResolver.resolve = original_resolve

    assert result.ok, result
    assert result.source == "youtube+lavalink-http", result
    assert result.title == "MONTAGEM ALQUIMIA", result
    assert loaded_identifiers == [youtube_url, stream_url], loaded_identifiers


async def test_lavalink_text_search_falls_back_for_suspicious_variant() -> None:
    original_resolve_choices = SourceResolver.resolve_choices
    query = "DONNE RICCHE - Acoustic Version TonyPitony"
    stream_url = "https://stream.test/donne-ricche-acoustic"
    loaded_identifiers = []

    async def fake_resolve_choices(
        cls,
        requested_query: str,
        requester: str,
        requester_id: int,
        n: int = 1,
    ) -> list:
        assert requested_query == query
        return [
            TrackInfo(
                title="DONNE RICCHE - Acoustic Version",
                webpage_url="https://www.youtube.com/watch?v=acoustic",
                duration=190,
                thumbnail="",
                requester=requester,
                requester_id=requester_id,
                source="youtube",
                stream_url=stream_url,
                artist="TonyPitony",
            )
        ]

    async def fake_loadtracks(identifier: str) -> dict:
        loaded_identifiers.append(identifier)
        if identifier.startswith("ytmsearch:"):
            return {
                "loadType": "search",
                "data": [
                    _track("DONNE RICCHE (Acoustic Version - Slowed)", "adamxyz", 190000),
                ],
            }
        return {
            "loadType": "track",
            "data": _track("Unknown title", "Unknown artist", 190000),
        }

    backend = LavalinkAudioBackend()
    backend._request_loadtracks = fake_loadtracks

    try:
        SourceResolver.resolve_choices = classmethod(fake_resolve_choices)
        result = await backend.load(query, requester="tester", requester_id=7)
    finally:
        SourceResolver.resolve_choices = original_resolve_choices

    assert result.ok, result
    assert result.source == "quality+lavalink-http", result
    assert result.title == "DONNE RICCHE - Acoustic Version", result
    assert loaded_identifiers == [f"ytmsearch:{query}", stream_url], loaded_identifiers


async def test_lavalink_resolve_track_info_uses_cache_before_lavalink() -> None:
    original_cached_track = SourceResolver._resolve_cached_track
    query = "radiance"

    async def fake_cached_track(cls, requested_query: str, requester: str, requester_id: int):
        assert requested_query == query
        return TrackInfo(
            title="Radiance",
            webpage_url="https://www.youtube.com/watch?v=cached",
            duration=180,
            thumbnail="",
            requester=requester,
            requester_id=requester_id,
            source="youtube",
            stream_url="https://stream.test/radiance",
            artist="Cached Artist",
        )

    async def fail_loadtracks(identifier: str) -> dict:
        raise AssertionError(f"Lavalink called before cache: {identifier}")

    backend = LavalinkAudioBackend()
    backend._request_loadtracks = fail_loadtracks

    try:
        SourceResolver._resolve_cached_track = classmethod(fake_cached_track)
        result = await backend.resolve_track_info(query, requester="tester", requester_id=7)
    finally:
        SourceResolver._resolve_cached_track = original_cached_track

    assert result is not None
    assert result.title == "Radiance", result
    assert result.requester == "tester", result
    assert result.requester_id == 7, result
    assert result.stream_url == "https://stream.test/radiance", result


async def test_lavalink_resolve_track_info_stores_lavalink_result_in_cache() -> None:
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()

    original_cache_enabled = Config.CACHE_ENABLED
    original_db_path = Config.DB_PATH
    original_qc = resolver_module._qc_instance
    load_count = 0

    async def fake_loadtracks(identifier: str) -> dict:
        nonlocal load_count
        load_count += 1
        assert identifier == "ytmsearch:raindance", identifier
        return {
            "loadType": "search",
            "data": [_track("Raindance", "Cached Artist", 180000)],
        }

    async def fake_fetch_stream_url(webpage_url: str) -> str:
        assert webpage_url == "https://youtube.test/watch", webpage_url
        return "https://stream.test/raindance"

    backend = LavalinkAudioBackend()
    backend._request_loadtracks = fake_loadtracks
    backend._fetch_stream_url = fake_fetch_stream_url

    try:
        cache_db.rebuild_database(tmp.name)
        cache_db.init_db(db_path=tmp.name, enabled=True)
        Config.CACHE_ENABLED = True
        Config.DB_PATH = tmp.name
        resolver_module._qc_instance = None

        first = await backend.resolve_track_info("raindance", requester="tester", requester_id=7)
        assert first is not None
        assert first.title == "Raindance", first
        assert load_count == 1, load_count

        async def fail_loadtracks(identifier: str) -> dict:
            raise AssertionError(f"Lavalink called instead of DB cache: {identifier}")

        backend._request_loadtracks = fail_loadtracks
        second = await backend.resolve_track_info("raindance", requester="tester2", requester_id=8)
    finally:
        resolver_module._qc_instance = original_qc
        Config.CACHE_ENABLED = original_cache_enabled
        Config.DB_PATH = original_db_path
        cache_db.init_db(db_path=original_db_path, enabled=original_cache_enabled)
        try:
            os.unlink(tmp.name)
        except PermissionError:
            pass

    assert second is not None
    assert second.title == "Raindance", second
    assert second.requester == "tester2", second
    assert second.requester_id == 8, second
    assert second.stream_url == "https://stream.test/raindance", second


test_lavalink_selection_uses_resolver_ranking()
test_lavalink_selection_keeps_first_for_direct_urls()
test_lavalink_payload_error_prefers_root_cause()
asyncio.run(test_lavalink_spotify_track_uses_resolver_bridge())
asyncio.run(test_lavalink_spotify_track_prefers_native_lavasrc())
asyncio.run(test_lavalink_youtube_url_falls_back_to_stream_bridge())
asyncio.run(test_lavalink_text_search_falls_back_for_suspicious_variant())
asyncio.run(test_lavalink_resolve_track_info_uses_cache_before_lavalink())
asyncio.run(test_lavalink_resolve_track_info_stores_lavalink_result_in_cache())
print("OK: lavalink backend ranks search candidates and preserves direct URL order")
