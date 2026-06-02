"""
Rinumera gli ID del nuovo cache DB a partire da 1.

Per default:
- rinumera `cache_tracks.id`
- aggiorna `cache_sources.track_id` e `cache_queries.track_id`
- rinumera `cache_sources.id`
- aggiorna `cache_queries.source_id`
- rinumera `cache_queries.id`
- riallinea `sqlite_sequence`

Uso:
    python tools/renumber_cache_ids.py          # dry-run
    python tools/renumber_cache_ids.py --apply  # applica le modifiche
    python tools/renumber_cache_ids.py --db path/al/cache.db
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from config import Config
import core.cache_db as cache_db


def renumber(db_path: str, apply: bool) -> dict:
    conn = sqlite3.connect(db_path)
    try:
        track_ids = cache_db._load_ids(conn, "cache_tracks")
        source_ids = cache_db._load_ids(conn, "cache_sources")
        query_ids = cache_db._load_ids(conn, "cache_queries")
        track_map = cache_db._id_mapping(track_ids)
        source_map = cache_db._id_mapping(source_ids)
        query_map = cache_db._id_mapping(query_ids)

        result = {
            "track_rows": len(track_ids),
            "track_changed": sum(1 for old_id, new_id in track_map.items() if old_id != new_id),
            "source_rows": len(source_ids),
            "source_changed": sum(1 for old_id, new_id in source_map.items() if old_id != new_id),
            "query_rows": len(query_ids),
            "query_changed": sum(1 for old_id, new_id in query_map.items() if old_id != new_id),
            "applied": False,
        }

        if not apply:
            return result

        conn.execute("PRAGMA foreign_keys=OFF")
        try:
            conn.execute("BEGIN IMMEDIATE")
            cache_db._apply_id_map(conn, "cache_tracks", track_map, [("cache_sources", "track_id"), ("cache_queries", "track_id")])
            cache_db._apply_id_map(conn, "cache_sources", source_map, [("cache_queries", "source_id")])
            cache_db._apply_id_map(conn, "cache_queries", query_map, [])
            cache_db._reset_sqlite_sequence(conn, "cache_tracks")
            cache_db._reset_sqlite_sequence(conn, "cache_sources")
            cache_db._reset_sqlite_sequence(conn, "cache_queries")
            conn.commit()
            result["applied"] = True
            return result
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.execute("PRAGMA foreign_keys=ON")
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Applica la rinumerazione. Senza flag esegue solo dry-run.")
    parser.add_argument("--db", default="", help="Percorso DB SQLite alternativo.")
    args = parser.parse_args()

    if args.db:
        Config.DB_PATH = args.db
    Path(Config.DB_PATH).parent.mkdir(parents=True, exist_ok=True)

    result = renumber(Config.DB_PATH, apply=args.apply)
    mode = "APPLY" if args.apply else "DRY-RUN"
    print(
        f"{mode}: "
        f"track_rows={result['track_rows']} track_changed={result['track_changed']} "
        f"source_rows={result['source_rows']} source_changed={result['source_changed']} "
        f"query_rows={result['query_rows']} query_changed={result['query_changed']} "
        f"applied={result['applied']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
