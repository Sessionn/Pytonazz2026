"""
Verifica che seek e filtri riusino il link audio gia' noto invece di rifare
yt-dlp, anche quando il link arriva dall'abbinamento lazy o da un DB hit.

Esegui dalla root del progetto con:
    python tests/test_resolver_seek_reuses_stream.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yt_dlp

import core.source_resolver as resolver_module
from core.source_resolver import SourceResolver
from core.source_resolver.models import TrackInfo


PAGE = "https://www.youtube.com/watch?v=seektest"
STREAM = f"https://rr1.googlevideo.com/videoplayback?expire={int(time.time()) + 6 * 3600}&id=x"

original_youtubedl = yt_dlp.YoutubeDL
original_query_cache = resolver_module._get_query_cache


class NoYoutubeDL:
    def __init__(self, opts):
        raise AssertionError("seek non deve rifare yt-dlp con un link ancora valido")


class FakeQueryCache:
    def lookup(self, query):
        return {"webpage_url": PAGE, "stream_url": STREAM,
                "stream_expires_at": int(time.time()) + 6 * 3600,
                "title": "Seek Test", "duration": 200}

    def update_stream_url(self, webpage_url, stream_url):
        pass


def track() -> TrackInfo:
    return TrackInfo(title="Seek Test", webpage_url=PAGE, duration=200, thumbnail="",
                     requester="tester", requester_id=1, source="youtube")


async def lazy_match_then_seek() -> None:
    SourceResolver._stream_url_cache.clear()
    current = track()
    current.stream_url = STREAM  # appena arrivato dall'abbinamento lazy
    assert await SourceResolver.resolve_fresh_url(current) == STREAM
    # seek: lo stream del brano e' gia' stato consumato da play_next
    assert await SourceResolver.resolve_fresh_url(current) == STREAM


async def db_hit_then_seek() -> None:
    SourceResolver._stream_url_cache.clear()
    hit = await SourceResolver._resolve_cached_track("seek test", "tester", 1)
    assert hit is not None and hit.stream_url == STREAM
    assert await SourceResolver.resolve_fresh_url(track()) == STREAM


async def main() -> None:
    yt_dlp.YoutubeDL = NoYoutubeDL
    resolver_module._get_query_cache = lambda: FakeQueryCache()
    try:
        await lazy_match_then_seek()
        await db_hit_then_seek()
    finally:
        yt_dlp.YoutubeDL = original_youtubedl
        resolver_module._get_query_cache = original_query_cache
        SourceResolver._stream_url_cache.clear()


asyncio.run(main())
print("OK: seek riusa il link audio da abbinamento lazy e da DB hit")
