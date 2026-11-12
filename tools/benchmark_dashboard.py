"""Measure dashboard endpoints on a disposable synthetic cache, without HTTP sockets."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import statistics
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=500)
    parser.add_argument("--requests", type=int, default=30)
    parser.add_argument("--output", type=Path, help="Optional JSON report path")
    args = parser.parse_args()
    if args.rows < 1 or args.requests < 1:
        parser.error("--rows and --requests must be positive")

    # Set before importing Config, so the real cache is never initialized.
    with tempfile.TemporaryDirectory(prefix="pytonazz-dashboard-bench-") as work:
        db_path = Path(work) / "cache.db"
        os.environ["DB_PATH"] = str(db_path)
        os.environ["DASH_USER"] = "benchmark"
        os.environ["DASH_PASSWORD"] = "benchmark-local-only"
        os.environ["DASH_SECRET_KEY"] = "benchmark-local-only"
        from config import Config
        from core import cache_db
        from data.database.dashboard.app import create_app

        Config.CACHE_MAX_ENTRIES = max(args.rows + 1, Config.CACHE_MAX_ENTRIES)
        cache_db.rebuild_database(db_path)
        cache_db.init_db(db_path, enabled=True)
        try:
            seed_started = time.perf_counter()
            for index in range(args.rows):
                identity = hashlib.sha256(str(index).encode()).hexdigest().translate(
                    str.maketrans("0123456789", "ghijklmnop")
                )
                cache_db.put(f"benchmark song {identity}", {
                    "title": identity,
                    "artist": f"performer{identity}",
                    "webpage_url": f"https://www.youtube.com/watch?v=bench{index:06d}",
                    "source": "youtube",
                    "duration": 180,
                })
            seeded = cache_db.list_song_rows()
            if len(seeded) != args.rows:
                raise RuntimeError(f"Expected {args.rows} rows, found {len(seeded)}")
            report = {
                "python": platform.python_version(),
                "platform": platform.platform(),
                "rows": args.rows,
                "requests_per_endpoint": args.requests,
                "seed_ms": round((time.perf_counter() - seed_started) * 1000, 3),
                "endpoints": [],
            }
            app = create_app(db_path=str(db_path))
            client = app.test_client()
            with client.session_transaction() as session:
                session["auth"] = True
            for endpoint in ("/api/stats", "/api/songs", "/api/tracks", "/api/aliases", "/api/schema"):
                warmup = client.get(endpoint)
                if warmup.status_code != 200:
                    raise RuntimeError(f"{endpoint}: HTTP {warmup.status_code}")
                durations = []
                payload_bytes = 0
                for _ in range(args.requests):
                    started = time.perf_counter()
                    response = client.get(endpoint)
                    payload = response.get_data()
                    durations.append((time.perf_counter() - started) * 1000)
                    if response.status_code != 200 or response.get_json() is None:
                        raise RuntimeError(f"{endpoint}: invalid response")
                    payload_bytes = len(payload)
                durations.sort()
                report["endpoints"].append({
                    "endpoint": endpoint,
                    "median_ms": round(statistics.median(durations), 3),
                    "p95_ms": round(durations[math.ceil(len(durations) * .95) - 1], 3),
                    "max_ms": round(max(durations), 3),
                    "response_bytes": payload_bytes,
                })
        finally:
            # cache_db owns a process-global connection; close before temp cleanup
            # so this benchmark also works on Windows.
            if cache_db._conn is not None:
                cache_db._conn.close()
                cache_db._conn = None

    encoded = json.dumps(report, indent=2)
    print(encoded)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
