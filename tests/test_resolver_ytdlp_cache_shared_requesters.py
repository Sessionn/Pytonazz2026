"""
tests/test_resolver_ytdlp_cache_shared_requesters.py

Esegui dalla root del progetto con:
    python tests/test_resolver_ytdlp_cache_shared_requesters.py
"""

import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yt_dlp

from core.source_resolver import SourceResolver


extract_calls = []
stream_extract_calls = []
original_youtubedl = yt_dlp.YoutubeDL


class FakeYoutubeDL:
    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def extract_info(self, query, download=False):
        extract_calls.append(query)
        return {
            "title": "Shared Cache Song",
            "webpage_url": "https://www.youtube.com/watch?v=shared",
            "duration": 123,
            "thumbnail": "https://i.ytimg.com/vi/shared/hqdefault.jpg",
            "artist": "Cache Artist",
            "url": "https://stream.test/shared",
            "formats": [
                {
                    "vcodec": "none",
                    "acodec": "mp4a.40.2",
                    "abr": 128,
                    "url": "https://stream.test/shared",
                }
            ],
        }


class SlowFakeYoutubeDL(FakeYoutubeDL):
    def extract_info(self, query, download=False):
        time.sleep(0.05)
        return super().extract_info(query, download=download)


class SlowStreamYoutubeDL(FakeYoutubeDL):
    def extract_info(self, query, download=False):
        stream_extract_calls.append(query)
        time.sleep(0.05)
        return super().extract_info(query, download=download)


try:
    yt_dlp.YoutubeDL = FakeYoutubeDL
    SourceResolver._ytdlp_query_cache.clear()

    first = SourceResolver._run_ytdlp("ytsearch1:shared cache song", "alpha", 1)
    second = SourceResolver._run_ytdlp("ytsearch1:shared cache song", "beta", 2)
finally:
    yt_dlp.YoutubeDL = original_youtubedl
    SourceResolver._ytdlp_query_cache.clear()

assert extract_calls == ["ytsearch1:shared cache song"], extract_calls
assert len(first) == 1 and len(second) == 1, (first, second)
assert first[0].requester == "alpha", first[0]
assert first[0].requester_id == 1, first[0]
assert second[0].requester == "beta", second[0]
assert second[0].requester_id == 2, second[0]
assert second[0].origin_query == "shared cache song", second[0]

extract_calls.clear()
try:
    yt_dlp.YoutubeDL = SlowFakeYoutubeDL
    SourceResolver._ytdlp_query_cache.clear()
    results = []

    def run_query(requester, requester_id):
        results.append(SourceResolver._run_ytdlp("ytsearch1:shared inflight song", requester, requester_id))

    threads = [
        threading.Thread(target=run_query, args=("alpha", 1)),
        threading.Thread(target=run_query, args=("beta", 2)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
finally:
    yt_dlp.YoutubeDL = original_youtubedl
    SourceResolver._ytdlp_query_cache.clear()

assert extract_calls.count("ytsearch1:shared inflight song") == 1, extract_calls
assert len(results) == 2, results
assert sorted(track[0].requester for track in results) == ["alpha", "beta"], results

try:
    yt_dlp.YoutubeDL = SlowStreamYoutubeDL
    SourceResolver._stream_url_cache.clear()
    stream_results = []
    url = "https://www.youtube.com/watch?v=shared-stream"

    def run_stream():
        stream_results.append(SourceResolver._fetch_stream_url(url))

    threads = [
        threading.Thread(target=run_stream),
        threading.Thread(target=run_stream),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
finally:
    yt_dlp.YoutubeDL = original_youtubedl
    SourceResolver._stream_url_cache.clear()

assert stream_extract_calls == ["https://www.youtube.com/watch?v=shared-stream"], stream_extract_calls
assert stream_results == ["https://stream.test/shared", "https://stream.test/shared"], stream_results

print("OK: resolver ytdlp cache and in-flight calls are shared across requesters")
