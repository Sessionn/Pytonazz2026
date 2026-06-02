"""
Benchmark rapido del resolve testuale.

Uso:
    python tools/benchmark_resolve.py "Notte blu dj shokka"
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from core.source_resolver import SourceResolver


def _flag(value: str) -> str:
    return "yes" if (value or "").strip() else "no"


def _short_cmd(args: list[str]) -> str:
    try:
        return subprocess.check_output(args, text=True, stderr=subprocess.STDOUT, timeout=5).splitlines()[0]
    except Exception as exc:
        return f"unavailable ({type(exc).__name__})"


def _print_runtime_diagnostics() -> None:
    print(f"spotify_client_id={_flag(Config.SPOTIFY_CLIENT_ID)}")
    print(f"spotify_client_secret={_flag(Config.SPOTIFY_CLIENT_SECRET)}")
    print(f"spotify_hint_wait={Config.SPOTIFY_HINT_WAIT_SECONDS}")
    try:
        import spotipy  # noqa: F401
        print("spotipy=yes")
    except Exception:
        print("spotipy=no")
    try:
        import yt_dlp
        print(f"yt_dlp={yt_dlp.version.__version__}")
    except Exception as exc:
        print(f"yt_dlp=unavailable ({type(exc).__name__})")
    ffmpeg = shutil.which("ffmpeg") or ""
    print(f"ffmpeg={ffmpeg or 'not-found'}")
    if ffmpeg:
        print(f"ffmpeg_version={_short_cmd([ffmpeg, '-version'])}")


async def _main() -> None:
    query = " ".join(sys.argv[1:]).strip() or "Notte blu dj shokka"
    Config.CACHE_ENABLED = False
    _print_runtime_diagnostics()
    sp_t0 = time.perf_counter()
    sp_meta = await asyncio.get_running_loop().run_in_executor(
        None, SourceResolver._sp_search_track_meta, query
    )
    sp_elapsed = (time.perf_counter() - sp_t0) * 1000
    if sp_meta:
        print(
            f"spotify_probe_ms={sp_elapsed:.0f} "
            f"title={sp_meta.get('title')!r} artist={sp_meta.get('artist')!r} "
            f"cover={bool(sp_meta.get('thumbnail'))}"
        )
    else:
        print(f"spotify_probe_ms={sp_elapsed:.0f} result=None")
    t0 = time.perf_counter()
    tracks = await SourceResolver.resolve_choices(query, "bench", 1, n=1)
    elapsed = (time.perf_counter() - t0) * 1000
    print(f"elapsed_ms={elapsed:.0f}")
    for track in tracks:
        print(
            f"title={track.title!r} artist={track.artist!r} source={track.source!r} "
            f"stream={bool(track.stream_url)} cover={track.thumbnail_source!r}"
        )


if __name__ == "__main__":
    asyncio.run(_main())
