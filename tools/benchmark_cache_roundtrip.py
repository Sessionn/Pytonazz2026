"""
Benchmark cold/warm del resolver con cache SQLite temporanea.

Misura per ogni query:
    1. resolve cold su DB vuoto/invalidato
    2. lookup DB dopo il cold
    3. resolve warm immediatamente successivo

Uso:
    python tools/benchmark_cache_roundtrip.py "Espresso Sabrina Carpenter"
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from core import cache_db
from core.source_resolver import SourceResolver


@dataclass
class RoundtripRow:
    query: str
    cold_ms: float
    db_lookup_after_cold_ms: float
    warm_ms: float
    cold_tracks: int
    warm_tracks: int
    title: str
    artist: str
    source: str
    stream: bool


def _db_sidecar_paths(db_path: Path) -> list[Path]:
    return [db_path, db_path.with_name(db_path.name + "-wal"), db_path.with_name(db_path.name + "-shm")]


def _remove_db_files(db_path: Path) -> None:
    for path in _db_sidecar_paths(db_path):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


async def _bench_one(query: str) -> RoundtripRow:
    cache_db.invalidate(query)

    cold_t0 = time.perf_counter()
    cold_tracks = await SourceResolver.resolve(query, "bench", 1)
    cold_ms = (time.perf_counter() - cold_t0) * 1000

    db_t0 = time.perf_counter()
    cache_db.get(query)
    db_lookup_ms = (time.perf_counter() - db_t0) * 1000

    warm_t0 = time.perf_counter()
    warm_tracks = await SourceResolver.resolve(query, "bench", 1)
    warm_ms = (time.perf_counter() - warm_t0) * 1000

    track = (warm_tracks or cold_tracks or [None])[0]
    return RoundtripRow(
        query=query,
        cold_ms=cold_ms,
        db_lookup_after_cold_ms=db_lookup_ms,
        warm_ms=warm_ms,
        cold_tracks=len(cold_tracks),
        warm_tracks=len(warm_tracks),
        title=getattr(track, "title", "") if track else "",
        artist=getattr(track, "artist", "") if track else "",
        source=getattr(track, "source", "") if track else "",
        stream=bool(getattr(track, "stream_url", "")) if track else False,
    )


async def _main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark cold/warm resolver cache roundtrip.")
    parser.add_argument("queries", nargs="+", help="Query testuali da risolvere")
    parser.add_argument("--db-path", default="", help="Path DB benchmark. Default: temp dir.")
    parser.add_argument("--keep-db", action="store_true", help="Non eliminare il DB temporaneo a fine run.")
    args = parser.parse_args()

    db_path = Path(args.db_path) if args.db_path else Path(tempfile.gettempdir()) / f"pytonazz_resolve_bench_{os.getpid()}.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    _remove_db_files(db_path)

    Config.CACHE_ENABLED = True
    Config.DB_PATH = str(db_path)
    cache_db.rebuild_database(db_path)
    cache_db.init_db(enabled=True)

    try:
        for query in args.queries:
            row = await _bench_one(query.strip())
            print("---")
            for key, value in asdict(row).items():
                if isinstance(value, float):
                    value = f"{value:.0f}"
                print(f"{key}={value}")
    finally:
        cache_db._close()
        if not args.keep_db:
            _remove_db_files(db_path)


if __name__ == "__main__":
    asyncio.run(_main())
