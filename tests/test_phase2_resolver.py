"""
Esegui dalla ROOT del progetto con:
    python tests/test_phase2_resolver.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cogs.music as music
import core.source_resolver as resolver
import core.source_resolver.scoring as scoring
from core.source_resolver import SourceResolver, TrackInfo
from yt_dlp.utils import DownloadError

print("=" * 60)
print("TEST PHASE 2 - resolver cache / fallback / snd.sc")
print("=" * 60)


def _track(title: str = "Song", artist: str = "Artist", stream_url: str = "") -> TrackInfo:
    return TrackInfo(
        title=title,
        webpage_url="https://example.com/watch?v=test",
        duration=123,
        thumbnail="",
        requester="tester",
        requester_id=1,
        source="youtube",
        stream_url=stream_url,
        artist=artist,
    )


print("\n[1] Cache helpers: guard su title non vuoto...")
resolver_calls = []
music_calls = []
orig_get_query_cache = resolver._get_query_cache
orig_music_put = music.cache_db.put


class _DummyCache:
    @staticmethod
    def store(query, track):
        resolver_calls.append((query, track.title))


resolver._get_query_cache = lambda: _DummyCache()
music.cache_db.put = lambda query, track: music_calls.append((query, track.title))

resolver._cache_query_track("https://youtube.com/watch?v=abc", _track("Cached"))
resolver._cache_query_track("https://youtube.com/watch?v=empty", _track(""))
music._cache_selected_track("blinding lights", _track("Chosen"))
music._cache_selected_track("empty query", _track(""))

assert resolver_calls == [("https://youtube.com/watch?v=abc", "Cached")], resolver_calls
assert music_calls == [("blinding lights", "Chosen")], music_calls
print("OK: cache helper applica la guard su title")

resolver._get_query_cache = orig_get_query_cache
music.cache_db.put = orig_music_put


print("\n[2] Redirect short SoundCloud (snd.sc)...")
orig_client_session = resolver.aiohttp.ClientSession


class _FakeHeadResponse:
    def __init__(self, url: str):
        self.url = url

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeSession:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def head(self, url, allow_redirects=True):
        assert allow_redirects is True
        assert url == "https://snd.sc/demo"
        return _FakeHeadResponse("https://soundcloud.com/artist/track")


resolver.aiohttp.ClientSession = _FakeSession

resolved = asyncio.run(resolver._resolve_soundcloud_short_url("https://snd.sc/demo"))
unchanged = asyncio.run(resolver._resolve_soundcloud_short_url("https://soundcloud.com/artist/track"))

assert resolved == "https://soundcloud.com/artist/track", resolved
assert unchanged == "https://soundcloud.com/artist/track", unchanged
print("OK: snd.sc viene risolto prima di yt-dlp")

resolver.aiohttp.ClientSession = orig_client_session


print("\n[3] Fallback per video non disponibile...")
orig_youtubedl = resolver.yt_dlp.YoutubeDL
orig_run_ytdlp = SourceResolver._run_ytdlp
fallback_calls = []


class _FailingYoutubeDL:
    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def extract_info(self, query, download=False):
        raise DownloadError("This video is not available")


def _fake_run_ytdlp(cls, query, requester, requester_id):
    fallback_calls.append((query, requester, requester_id))
    return [_track("Recovered", "Artist", "https://stream.example/audio")]


resolver.yt_dlp.YoutubeDL = _FailingYoutubeDL
SourceResolver._run_ytdlp = classmethod(_fake_run_ytdlp)

fallback_url = SourceResolver._fetch_stream_url(
    "https://youtube.com/watch?v=deadbeef",
    "Recovered Artist",
)

assert fallback_url == "https://stream.example/audio", fallback_url
assert fallback_calls == [("ytsearch1:Recovered Artist", "", 0)], fallback_calls
print("OK: fallback testuale attivato sul caso video unavailable")

resolver.yt_dlp.YoutubeDL = orig_youtubedl
SourceResolver._run_ytdlp = orig_run_ytdlp


print("\n[4] Soglia enrich più conservativa...")
assert scoring._ENRICH_CONFIDENCE_MEDIUM >= 0.85, scoring._ENRICH_CONFIDENCE_MEDIUM
assert scoring._ENRICH_CONFIDENCE_HIGH > scoring._ENRICH_CONFIDENCE_MEDIUM, (
    scoring._ENRICH_CONFIDENCE_HIGH,
    scoring._ENRICH_CONFIDENCE_MEDIUM,
)
print("OK: threshold Spotify enrich alzata a >= 85%")

print("\n" + "=" * 60)
print("TUTTI I TEST PHASE 2 PASSATI")
print("=" * 60)
