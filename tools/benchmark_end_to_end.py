"""
Benchmark end-to-end del percorso di riproduzione.

Misura, per ogni query/link:
    1. cache DB lookup (con invalidazione preventiva opzionale)
    2. resolve
    3. eventuale fetch dello stream URL
    4. bootstrap FFmpeg
    5. lettura del primo frame PCM

Uso:
    python tools/benchmark_end_to_end.py "query o link 1" "query o link 2"
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from dataclasses import asdict, dataclass

import discord

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from core import cache_db
from core.music.player import compose_audio_filter
from core.source_resolver import SourceResolver


@dataclass
class BenchRow:
    query: str
    hit: bool
    resolved: bool
    title: str
    source: str
    db_lookup_ms: float
    resolve_ms: float
    fetch_ms: float
    ffmpeg_init_ms: float
    first_frame_ms: float
    total_ms: float
    first_frame_bytes: int
    error: str = ""


def _build_ffmpeg_opts() -> dict:
    chain = compose_audio_filter(None, {"low": 0.0, "mid": 0.0, "high": 0.0})
    af = f"-af {chain}" if chain else ""
    return {
        "before_options": Config.FFMPEG_OPTIONS["before_options"],
        "options": f"-vn {af} -bufsize 64k".strip(),
    }


async def _read_first_frame(source: discord.FFmpegPCMAudio) -> bytes:
    loop = asyncio.get_running_loop()
    return await asyncio.wait_for(loop.run_in_executor(None, source.read), timeout=4.0)


async def _bench_one(raw_query: str) -> BenchRow:
    query = raw_query.strip()
    cache_db.invalidate(query)

    total_t0 = time.perf_counter()

    db_t0 = time.perf_counter()
    hit = cache_db.get(query) is not None
    db_ms = (time.perf_counter() - db_t0) * 1000

    resolve_t0 = time.perf_counter()
    tracks = await SourceResolver.resolve(query, "bench", 1)
    resolve_ms = (time.perf_counter() - resolve_t0) * 1000
    if not tracks:
        total_ms = (time.perf_counter() - total_t0) * 1000
        return BenchRow(
            query=query,
            hit=hit,
            resolved=False,
            title="",
            source="",
            db_lookup_ms=db_ms,
            resolve_ms=resolve_ms,
            fetch_ms=0.0,
            ffmpeg_init_ms=0.0,
            first_frame_ms=0.0,
            total_ms=total_ms,
            first_frame_bytes=0,
            error="resolve returned no tracks",
        )

    track = tracks[0]
    stream_url = track.stream_url or ""

    fetch_ms = 0.0
    if not stream_url:
        fetch_t0 = time.perf_counter()
        stream_url = await SourceResolver.resolve_fresh_url(track)
        fetch_ms = (time.perf_counter() - fetch_t0) * 1000

    if not stream_url:
        total_ms = (time.perf_counter() - total_t0) * 1000
        return BenchRow(
            query=query,
            hit=hit,
            resolved=True,
            title=track.title,
            source=track.source,
            db_lookup_ms=db_ms,
            resolve_ms=resolve_ms,
            fetch_ms=fetch_ms,
            ffmpeg_init_ms=0.0,
            first_frame_ms=0.0,
            total_ms=total_ms,
            first_frame_bytes=0,
            error="empty stream url",
        )

    ffmpeg_opts = _build_ffmpeg_opts()
    init_t0 = time.perf_counter()
    source = discord.FFmpegPCMAudio(stream_url, **ffmpeg_opts)
    ffmpeg_init_ms = (time.perf_counter() - init_t0) * 1000

    first_frame_ms = 0.0
    first_frame_bytes = 0
    error = ""
    try:
        frame_t0 = time.perf_counter()
        frame = await _read_first_frame(source)
        first_frame_ms = (time.perf_counter() - frame_t0) * 1000
        first_frame_bytes = len(frame or b"")
        if first_frame_bytes <= 0:
            error = "ffmpeg returned empty first frame"
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    finally:
        try:
            source.cleanup()
        except Exception:
            pass

    total_ms = (time.perf_counter() - total_t0) * 1000
    return BenchRow(
        query=query,
        hit=hit,
        resolved=True,
        title=track.title,
        source=track.source,
        db_lookup_ms=db_ms,
        resolve_ms=resolve_ms,
        fetch_ms=fetch_ms,
        ffmpeg_init_ms=ffmpeg_init_ms,
        first_frame_ms=first_frame_ms,
        total_ms=total_ms,
        first_frame_bytes=first_frame_bytes,
        error=error,
    )


async def _main() -> None:
    cases = [arg.strip() for arg in sys.argv[1:] if arg.strip()]
    if not cases:
        print("usage: python tools/benchmark_end_to_end.py <query-or-url> [more cases...]")
        raise SystemExit(2)

    Config.CACHE_ENABLED = True
    cache_db.init_db(enabled=True)

    for case in cases:
        row = await _bench_one(case)
        print("---")
        for key, value in asdict(row).items():
            print(f"{key}={value}")


if __name__ == "__main__":
    asyncio.run(_main())
