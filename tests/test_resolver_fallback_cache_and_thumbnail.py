"""
tests/test_resolver_fallback_cache_and_thumbnail.py

Run from project root:
    python tests/test_resolver_fallback_cache_and_thumbnail.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
import core.source_resolver as resolver_module
from core.source_resolver import SourceResolver
from core.source_resolver.models import TrackInfo


def test_youtube_thumbnail_is_derived_when_ytdlp_omits_it() -> None:
    info = {
        "id": "abc123xyz89",
        "title": "Korbe - ALL' ITALIANA (Official Video)",
        "webpage_url": "https://www.youtube.com/watch?v=abc123xyz89",
        "duration": 138,
        "uploader": "Korbe",
        "formats": [{"vcodec": "none", "acodec": "mp4a.40.2", "url": "https://stream.test/audio"}],
    }

    tracks = SourceResolver._tracks_from_ytdlp_info(info, "tester", 1, "all'italiana")

    assert len(tracks) == 1, tracks
    assert tracks[0].thumbnail == "https://i.ytimg.com/vi/abc123xyz89/hqdefault.jpg", tracks[0]
    assert tracks[0].thumbnail_source == "youtube", tracks[0]


async def test_timeout_fallback_is_stored_when_it_has_a_real_url() -> None:
    original_timeout = Config.RESOLVE_HARD_TIMEOUT_SECONDS
    original_get_cache = resolver_module._get_query_cache
    original_impl = SourceResolver._resolve_choices_impl
    original_fallback = SourceResolver._resolve_fallback_track
    stored = []

    class FakeCache:
        def store(self, query, track):
            stored.append((query, track.webpage_url, track.thumbnail))

    fallback_track = TrackInfo(
        title="Korbe - ALL' ITALIANA (Official Video)",
        webpage_url="https://www.youtube.com/watch?v=abc123xyz89",
        duration=138,
        thumbnail="https://i.ytimg.com/vi/abc123xyz89/hqdefault.jpg",
        requester="tester",
        requester_id=1,
        source="youtube",
        artist="Korbe",
        origin_query="all'italiana",
        thumbnail_source="youtube",
        thumbnail_confidence=0.45,
    )

    async def slow_impl(cls, query, requester, requester_id, n=7):
        await asyncio.sleep(1)
        return []

    async def immediate_fallback(cls, query, requester, requester_id):
        return fallback_track

    try:
        Config.RESOLVE_HARD_TIMEOUT_SECONDS = 0.5
        resolver_module._get_query_cache = lambda: FakeCache()
        SourceResolver._resolve_choices_impl = classmethod(slow_impl)
        SourceResolver._resolve_fallback_track = classmethod(immediate_fallback)

        tracks = await SourceResolver.resolve_choices("all'italiana", "tester", 1, n=1)
    finally:
        Config.RESOLVE_HARD_TIMEOUT_SECONDS = original_timeout
        resolver_module._get_query_cache = original_get_cache
        SourceResolver._resolve_choices_impl = original_impl
        SourceResolver._resolve_fallback_track = original_fallback

    assert tracks == [fallback_track], tracks
    assert stored == [
        ("all'italiana", "https://www.youtube.com/watch?v=abc123xyz89", "https://i.ytimg.com/vi/abc123xyz89/hqdefault.jpg")
    ], stored


async def test_fresh_stream_updates_persisted_source() -> None:
    original_get_cache = resolver_module._get_query_cache
    original_fetch = SourceResolver._fetch_stream_url
    updated = []

    class FakeCache:
        def update_stream_url(self, webpage_url, stream_url):
            updated.append((webpage_url, stream_url))

    track = TrackInfo(
        title="Korbe - ALL' ITALIANA (Official Video)",
        webpage_url="https://www.youtube.com/watch?v=abc123xyz89",
        duration=138,
        thumbnail="https://i.ytimg.com/vi/abc123xyz89/hqdefault.jpg",
        requester="tester",
        requester_id=1,
        source="youtube",
    )

    try:
        resolver_module._get_query_cache = lambda: FakeCache()
        SourceResolver._fetch_stream_url = classmethod(
            lambda cls, _webpage_url: "https://stream.test/audio"
        )
        url = await SourceResolver.resolve_fresh_url(track)
    finally:
        resolver_module._get_query_cache = original_get_cache
        SourceResolver._fetch_stream_url = original_fetch

    assert url == "https://stream.test/audio", url
    assert updated == [
        ("https://www.youtube.com/watch?v=abc123xyz89", "https://stream.test/audio")
    ], updated


def test_spotify_timeout_fallback_uses_youtube_mirror() -> None:
    original_sp_client = SourceResolver._sp_client
    original_flat_fallback = SourceResolver._fallback_from_flat_ytdlp
    spotify_url = "https://open.spotify.com/intl-it/track/55SQ7OsKtNX274q3dyZQsQ?si=test"

    class FakeSpotify:
        def track(self, track_id):
            assert track_id == "55SQ7OsKtNX274q3dyZQsQ", track_id
            return {
                "name": "It Can't Come Quickly Enough",
                "duration_ms": 237000,
                "artists": [{"name": "Scissor Sisters"}],
                "album": {"images": [{"url": "https://i.scdn.co/image/cover"}]},
                "external_urls": {"spotify": "https://open.spotify.com/track/55SQ7OsKtNX274q3dyZQsQ"},
            }

    def fake_flat_fallback(cls, query, requester, requester_id):
        assert query == "It Can't Come Quickly Enough Scissor Sisters", query
        return TrackInfo(
            title="YouTube title",
            webpage_url="https://www.youtube.com/watch?v=mirror123",
            duration=240,
            thumbnail="https://i.ytimg.com/vi/mirror123/hqdefault.jpg",
            requester=requester,
            requester_id=requester_id,
            source="youtube",
            artist="YouTube artist",
        )

    try:
        SourceResolver._sp_client = classmethod(lambda cls: FakeSpotify())
        SourceResolver._fallback_from_flat_ytdlp = classmethod(fake_flat_fallback)
        track = SourceResolver._fallback_track_sync(spotify_url, "tester", 1)
    finally:
        SourceResolver._sp_client = original_sp_client
        SourceResolver._fallback_from_flat_ytdlp = original_flat_fallback

    assert track.webpage_url == "https://www.youtube.com/watch?v=mirror123", track
    assert track.title == "It Can't Come Quickly Enough", track
    assert track.artist == "Scissor Sisters", track
    assert track.thumbnail == "https://i.scdn.co/image/cover", track
    assert track.source == "spotify", track
    assert track.spotify_url == "https://open.spotify.com/track/55SQ7OsKtNX274q3dyZQsQ", track


def test_spotify_url_is_never_cached_as_fallback() -> None:
    original_get_cache = resolver_module._get_query_cache
    stored = []
    spotify_url = "https://open.spotify.com/track/55SQ7OsKtNX274q3dyZQsQ"

    class FakeCache:
        def store(self, query, track):
            stored.append((query, track.webpage_url))

    try:
        resolver_module._get_query_cache = lambda: FakeCache()
        SourceResolver._store_resolved_fallback(
            spotify_url,
            TrackInfo(
                title=spotify_url,
                webpage_url=spotify_url,
                duration=0,
                thumbnail="",
                requester="tester",
                requester_id=1,
                source="spotify",
            ),
        )
    finally:
        resolver_module._get_query_cache = original_get_cache

    assert not stored, stored


def test_spotify_emergency_fallback_is_not_queued_as_a_stream() -> None:
    spotify_url = "https://open.spotify.com/track/55SQ7OsKtNX274q3dyZQsQ"
    assert SourceResolver._emergency_fallback_track(spotify_url, "tester", 1) is None


test_youtube_thumbnail_is_derived_when_ytdlp_omits_it()
asyncio.run(test_timeout_fallback_is_stored_when_it_has_a_real_url())
asyncio.run(test_fresh_stream_updates_persisted_source())
test_spotify_timeout_fallback_uses_youtube_mirror()
test_spotify_url_is_never_cached_as_fallback()
test_spotify_emergency_fallback_is_not_queued_as_a_stream()
print("OK: timeout fallbacks are cached and YouTube thumbnails are derived")
