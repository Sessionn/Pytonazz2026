"""
Benchmark diretto yt-dlp per query di resolve.

Uso:
    python tools/benchmark_ytdlp.py "trust me" "Trust Me Pandora"
"""

from __future__ import annotations

import sys
import time

import yt_dlp


def _bench(query: str, count: int = 1) -> None:
    ydl_query = f"ytsearch{count}:{query}"
    opts = {
        "format": "bestaudio[ext=mp3]/bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio/best",
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": True,
        "skip_download": True,
        "noplaylist": True,
        "socket_timeout": 8,
        "retries": 2,
        "fragment_retries": 2,
        "extractor_retries": 2,
    }
    t0 = time.perf_counter()
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(ydl_query, download=False)
    elapsed = (time.perf_counter() - t0) * 1000
    entries = (info or {}).get("entries") or ([info] if info else [])
    first = entries[0] if entries else {}
    print(
        f"{ydl_query} elapsed_ms={elapsed:.0f} entries={len(entries)} "
        f"title={(first or {}).get('title')!r} url={bool((first or {}).get('url'))} "
        f"formats={len((first or {}).get('formats') or [])}"
    )


def main() -> None:
    args = sys.argv[1:] or ["trust me", "Trust Me Pandora"]
    for arg in args:
        _bench(arg, 1)
        _bench(arg, 3)


if __name__ == "__main__":
    main()
