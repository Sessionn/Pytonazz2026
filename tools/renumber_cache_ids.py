"""
Rinumera gli ID del DB cache a partire da 1.

Per default:
- rinumera `song_cache.id` in ordine crescente
- aggiorna `query_aliases.cache_id`
- rinumera anche `query_aliases.id`
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


def _load_ids(conn: sqlite3.Connection, table: str) -> list[int]:
    rows = conn.execute(f"SELECT id FROM {table} ORDER BY id ASC").fetchall()
    return [int(row[0]) for row in rows]


def _mapping(ids: list[int]) -> dict[int, int]:
    return {old_id: new_id for new_id, old_id in enumerate(ids, start=1)}


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (table,),
    ).fetchone()
    return row is not None


def _apply_song_cache_mapping(conn: sqlite3.Connection, id_map: dict[int, int]) -> None:
    if not id_map:
        return
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute("BEGIN IMMEDIATE")
    try:
        for old_id, new_id in id_map.items():
            if old_id == new_id:
                continue
            temp_id = -new_id
            conn.execute("UPDATE song_cache SET id = ? WHERE id = ?", (temp_id, old_id))
            conn.execute("UPDATE query_aliases SET cache_id = ? WHERE cache_id = ?", (temp_id, old_id))

        conn.execute("UPDATE song_cache SET id = -id WHERE id < 0")
        conn.execute("UPDATE query_aliases SET cache_id = -cache_id WHERE cache_id < 0")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.execute("PRAGMA foreign_keys=ON")


def _apply_query_alias_ids(conn: sqlite3.Connection, id_map: dict[int, int]) -> None:
    if not id_map:
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        for old_id, new_id in id_map.items():
            if old_id == new_id:
                continue
            conn.execute("UPDATE query_aliases SET id = ? WHERE id = ?", (-new_id, old_id))
        conn.execute("UPDATE query_aliases SET id = -id WHERE id < 0")
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def _reset_sqlite_sequence(conn: sqlite3.Connection, table: str) -> None:
    if not _table_exists(conn, "sqlite_sequence"):
        return
    max_id = conn.execute(f"SELECT COALESCE(MAX(id), 0) FROM {table}").fetchone()[0]
    conn.execute("DELETE FROM sqlite_sequence WHERE name = ?", (table,))
    if int(max_id) > 0:
        conn.execute(
            "INSERT INTO sqlite_sequence(name, seq) VALUES(?, ?)",
            (table, int(max_id)),
        )


def renumber(db_path: str, apply: bool) -> dict:
    conn = sqlite3.connect(db_path)
    try:
        song_ids = _load_ids(conn, "song_cache")
        alias_ids = _load_ids(conn, "query_aliases")
        song_map = _mapping(song_ids)
        alias_map = _mapping(alias_ids)

        result = {
            "song_rows": len(song_ids),
            "song_changed": sum(1 for old_id, new_id in song_map.items() if old_id != new_id),
            "alias_rows": len(alias_ids),
            "alias_changed": sum(1 for old_id, new_id in alias_map.items() if old_id != new_id),
            "applied": False,
        }

        if not apply:
            return result

        _apply_song_cache_mapping(conn, song_map)
        _apply_query_alias_ids(conn, alias_map)
        conn.execute("BEGIN IMMEDIATE")
        try:
            _reset_sqlite_sequence(conn, "song_cache")
            _reset_sqlite_sequence(conn, "query_aliases")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        result["applied"] = True
        return result
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
        f"song_rows={result['song_rows']} song_changed={result['song_changed']} "
        f"alias_rows={result['alias_rows']} alias_changed={result['alias_changed']} "
        f"applied={result['applied']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
