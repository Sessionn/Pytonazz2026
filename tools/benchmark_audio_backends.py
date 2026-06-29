"""
Benchmark no-cache/no-DB per confrontare backend audio.

Uso:
    python tools/benchmark_audio_backends.py --backend current "montagem alquimia"
    python tools/benchmark_audio_backends.py --backend lavalink --jsonl results.jsonl
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from core.audio_backends import create_audio_backend
from core.source_resolver import SourceResolver


DEFAULT_CASES = [
    "montagem alquimia",
    "notte blu dj shokka",
    "hello adele",
    "boris sigla",
    "sun raude",
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "https://open.spotify.com/track/0VjIjW4GlUZAMYd2vXMi3b",
]


def _clear_runtime_caches() -> None:
    SourceResolver._ytdlp_query_cache.clear()
    SourceResolver._stream_url_cache.clear()


def _load_cases(args) -> list[str]:
    cases = list(args.cases or [])
    if args.cases_file:
        path = Path(args.cases_file)
        cases.extend(
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        )
    return cases or list(DEFAULT_CASES)


async def _bench_backend(backend_name: str, cases: list[str], repeat: int) -> list[dict]:
    backend = create_audio_backend(backend_name)
    rows: list[dict] = []
    try:
        for round_index in range(1, repeat + 1):
            for case in cases:
                _clear_runtime_caches()
                t0 = time.perf_counter()
                result = await backend.load(case, requester="bench", requester_id=1)
                total_ms = (time.perf_counter() - t0) * 1000
                row = asdict(result)
                row["round"] = round_index
                row["total_ms"] = round(total_ms, 1)
                row["load_ms"] = round(float(row["load_ms"]), 1)
                rows.append(row)
    finally:
        await backend.close()
    return rows


def _print_table(rows: list[dict]) -> None:
    for row in rows:
        status = "OK" if row["ok"] else "FAIL"
        print(
            f"{status:4} backend={row['backend']:<8} ms={row['total_ms']:>7} "
            f"tracks={row['tracks_count']:<3} title={row['title']!r} query={row['query']!r} "
            f"error={row['error']!r}"
        )


async def _main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark backend audio senza cache DB.")
    parser.add_argument("cases", nargs="*", help="Query/link da testare. Se vuoto usa casi default.")
    parser.add_argument("--cases-file", default="", help="File con una query/link per riga.")
    parser.add_argument("--backend", choices=["current", "lavalink", "both"], default="current")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--jsonl", default="", help="Path output JSONL confrontabile.")
    args = parser.parse_args()

    Config.CACHE_ENABLED = False
    cases = _load_cases(args)
    backends = ["current", "lavalink"] if args.backend == "both" else [args.backend]

    all_rows: list[dict] = []
    for backend_name in backends:
        rows = await _bench_backend(backend_name, cases, max(1, args.repeat))
        all_rows.extend(rows)

    _print_table(all_rows)
    if args.jsonl:
        path = Path(args.jsonl)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            for row in all_rows:
                fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


if __name__ == "__main__":
    asyncio.run(_main())
