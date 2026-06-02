"""
Benchmark diretto yt-dlp per query di resolve.

Uso:
    python tools/benchmark_ytdlp.py "trust me" "Trust Me Pandora"
"""

from __future__ import annotations

import sys
import time
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yt_dlp

from core.source_resolver.ytdlp import _make_opts


def _bench(query: str, count: int = 1) -> None:
    ydl_query = f"ytsearch{count}:{query}"
    opts = _make_opts({"noplaylist": True})
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


def _best_audio_url(info: dict) -> str:
    formats = info.get("formats", []) if info else []
    audio = [
        f for f in formats
        if f.get("vcodec") == "none"
        and f.get("acodec") not in (None, "none")
        and f.get("url")
        and not f.get("has_drm")
    ]
    if not audio:
        return (info or {}).get("url", "")
    return max(audio, key=lambda f: f.get("abr") or f.get("tbr") or 0).get("url", "")


def _bench_flat_pipeline(query: str) -> None:
    flat_query = f"ytsearch1:{query}"
    t0 = time.perf_counter()
    with yt_dlp.YoutubeDL(_make_opts({"noplaylist": True, "extract_flat": "in_playlist"})) as ydl:
        flat_info = ydl.extract_info(flat_query, download=False)
    flat_elapsed = (time.perf_counter() - t0) * 1000
    entries = (flat_info or {}).get("entries") or []
    first = entries[0] if entries else {}
    webpage_url = (first or {}).get("webpage_url") or (first or {}).get("url") or ""
    if webpage_url and not str(webpage_url).startswith("http"):
        webpage_url = f"https://www.youtube.com/watch?v={webpage_url}"

    stream_elapsed = 0.0
    stream_ok = False
    if webpage_url:
        t1 = time.perf_counter()
        with yt_dlp.YoutubeDL(_make_opts({"noplaylist": True})) as ydl:
            info = ydl.extract_info(webpage_url, download=False)
        stream_elapsed = (time.perf_counter() - t1) * 1000
        stream_ok = bool(_best_audio_url(info or {}))

    print(
        f"flat_pipeline:{query!r} flat_ms={flat_elapsed:.0f} "
        f"stream_ms={stream_elapsed:.0f} total_ms={flat_elapsed + stream_elapsed:.0f} "
        f"title={(first or {}).get('title')!r} stream={stream_ok}"
    )


def _bench_clients(query: str) -> None:
    clients = {
        "default": {},
        "android": {"extractor_args": {"youtube": {"player_client": ["android"]}}},
        "ios": {"extractor_args": {"youtube": {"player_client": ["ios"]}}},
        "web": {"extractor_args": {"youtube": {"player_client": ["web"]}}},
    }
    for name, extra in clients.items():
        opts = _make_opts({"noplaylist": True, **extra})
        t0 = time.perf_counter()
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(f"ytsearch1:{query}", download=False)
            elapsed = (time.perf_counter() - t0) * 1000
            entries = (info or {}).get("entries") or ([info] if info else [])
            first = entries[0] if entries else {}
            print(
                f"client:{name} query={query!r} elapsed_ms={elapsed:.0f} "
                f"title={(first or {}).get('title')!r} url={bool((first or {}).get('url'))} "
                f"formats={len((first or {}).get('formats') or [])}"
            )
        except Exception as exc:
            elapsed = (time.perf_counter() - t0) * 1000
            print(f"client:{name} query={query!r} elapsed_ms={elapsed:.0f} error={type(exc).__name__}: {exc}")


def _bench_retries(query: str) -> None:
    for retry_count in (0, 1, 2):
        opts = _make_opts({
            "noplaylist": True,
            "retries": retry_count,
            "fragment_retries": retry_count,
            "extractor_retries": retry_count,
        })
        t0 = time.perf_counter()
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(f"ytsearch1:{query}", download=False)
            elapsed = (time.perf_counter() - t0) * 1000
            entries = (info or {}).get("entries") or ([info] if info else [])
            first = entries[0] if entries else {}
            print(
                f"retries:{retry_count} query={query!r} elapsed_ms={elapsed:.0f} "
                f"title={(first or {}).get('title')!r} url={bool((first or {}).get('url'))} "
                f"formats={len((first or {}).get('formats') or [])}"
            )
        except Exception as exc:
            elapsed = (time.perf_counter() - t0) * 1000
            print(f"retries:{retry_count} query={query!r} elapsed_ms={elapsed:.0f} error={type(exc).__name__}: {exc}")


def main() -> None:
    args = sys.argv[1:] or ["trust me", "Trust Me Pandora"]
    for arg in args:
        _bench(arg, 1)
        _bench(arg, 3)
        _bench_flat_pipeline(arg)
        _bench_clients(arg)
        _bench_retries(arg)


if __name__ == "__main__":
    main()
