"""
Deduplica il DB cache musicale.

Uso:
    python tools/dedupe_cache_db.py          # dry-run
    python tools/dedupe_cache_db.py --apply  # applica merge
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from config import Config
import core.cache_db as cache_db


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Applica la deduplica. Senza flag fa solo dry-run.")
    parser.add_argument("--db", default="", help="Percorso DB SQLite alternativo.")
    args = parser.parse_args()

    if args.db:
        Config.DB_PATH = args.db
    Path(Config.DB_PATH).parent.mkdir(parents=True, exist_ok=True)

    cache_db.init_db(db_path=Config.DB_PATH, enabled=True)
    result = cache_db.dedupe_canonical(dry_run=not args.apply)
    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"{mode}: groups={result['groups']} duplicates={result['duplicates']} applied={result['applied']}")
    cache_db._close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
