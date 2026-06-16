"""
Verifica che resolve_fresh_url gestisca fallback testuali ytsearch1.

Esegui dalla root del progetto con:
    python tests/test_resolver_fresh_url_search_entry.py
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yt_dlp

from core.source_resolver import SourceResolver
from core.source_resolver.models import TrackInfo


original_youtubedl = yt_dlp.YoutubeDL


class FakeYoutubeDL:
    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def extract_info(self, query, download=False):
        assert query == "ytsearch1:fallback song", query
        return {
            "entries": [
                {
                    "title": "Fallback Song",
                    "webpage_url": "https://www.youtube.com/watch?v=fallback",
                    "formats": [
                        {
                            "vcodec": "none",
                            "acodec": "mp4a.40.2",
                            "abr": 128,
                            "url": "https://stream.test/fallback",
                        }
                    ],
                }
            ]
        }


async def main() -> None:
    yt_dlp.YoutubeDL = FakeYoutubeDL
    SourceResolver._stream_url_cache.clear()
    try:
        track = TrackInfo(
            title="fallback song",
            webpage_url="ytsearch1:fallback song",
            duration=0,
            thumbnail="",
            requester="tester",
            requester_id=1,
            source="youtube",
        )
        url = await SourceResolver.resolve_fresh_url(track)
    finally:
        yt_dlp.YoutubeDL = original_youtubedl
        SourceResolver._stream_url_cache.clear()

    assert url == "https://stream.test/fallback", url


asyncio.run(main())
print("OK: resolve_fresh_url supports ytsearch1 fallback entries")
