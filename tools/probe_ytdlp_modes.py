"""
Probe prestazionale per confrontare modalita' yt-dlp.

Uso:
    python tools/probe_ytdlp_modes.py "A Bar Song Tipsy Shaboozey"
"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yt_dlp

from core.source_resolver.ytdlp import _make_opts


def _ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


def _first_url(info: dict) -> str:
    entries = info.get("entries") or []
    first = entries[0] if entries else info
    url = first.get("webpage_url") or first.get("url") or ""
    if url and not url.startswith(("http://", "https://")):
        url = f"https://www.youtube.com/watch?v={url}"
    return url


def _run(label: str, target: str, extra: dict | None = None) -> dict:
    t0 = time.perf_counter()
    with yt_dlp.YoutubeDL(_make_opts(extra or {})) as ydl:
        info = ydl.extract_info(target, download=False)
    elapsed = _ms(t0)
    print(f"{label}_ms={elapsed}")
    print(f"{label}_url={_first_url(info or {})}")
    return info or {}


def main() -> None:
    query = " ".join(sys.argv[1:]).strip() or "A Bar Song Tipsy Shaboozey"
    search = f"ytsearch1:{query}"
    normal = _run("normal_search", search)
    client_sets = (
        ("android",),
        ("web",),
        ("web_safari",),
        ("web_safari", "web"),
        ("mweb",),
        ("web_creator",),
    )
    for clients in client_sets:
        label = "_".join(clients)
        try:
            _run(
                f"{label}_search",
                search,
                {"extractor_args": {"youtube": {"player_client": list(clients)}}},
            )
        except Exception as exc:
            print(f"{label}_search_error={type(exc).__name__}: {exc}")
    flat = _run("flat_search", search, {"extract_flat": True, "format": "bestaudio/best"})
    flat_url = _first_url(flat)
    normal_url = _first_url(normal)
    direct_url = flat_url or normal_url
    if direct_url:
        _run("direct_fetch", direct_url, {"noplaylist": True})


if __name__ == "__main__":
    main()
