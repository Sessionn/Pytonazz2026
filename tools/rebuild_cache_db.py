#!/usr/bin/env python3
#
"""
Ricrea da zero il cache DB nel nuovo schema normalizzato.

Uso:
    python tools/rebuild_cache_db.py
    python tools/rebuild_cache_db.py --db data/database/cache.db
    ./tools/rebuild_cache_db.py --backup
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import time
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from config import Config
import core.cache_db as cache_db


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="", help="Percorso DB SQLite alternativo.")
    parser.add_argument("--backup", action="store_true", help="Crea una copia .bak prima di ricreare il DB.")
    args = parser.parse_args()

    if args.db:
        Config.DB_PATH = args.db

    db_path = Path(Config.DB_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if args.backup and db_path.exists():
        backup_path = db_path.with_suffix(f".{int(time.time())}.bak")
        shutil.copy2(db_path, backup_path)
        print(f"BACKUP: {backup_path}")

    rebuilt = cache_db.rebuild_database(Config.DB_PATH)
    print(f"REBUILT: {rebuilt}")
    cache_db.init_db(db_path=rebuilt, enabled=True)
    for item in cache_db.schema_overview():
        print(f"{item['kind'].upper():5} {item['name']:16} pk={item['pk']} rows={item['count']}")
    cache_db._close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
