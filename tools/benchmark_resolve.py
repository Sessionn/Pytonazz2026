"""
Benchmark rapido del resolve testuale.

Uso:
    python tools/benchmark_resolve.py "Notte blu dj shokka"
"""

from __future__ import annotations

import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from core.source_resolver import SourceResolver


async def _main() -> None:
    query = " ".join(sys.argv[1:]).strip() or "Notte blu dj shokka"
    Config.CACHE_ENABLED = False
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
