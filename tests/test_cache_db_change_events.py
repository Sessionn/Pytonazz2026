"""
tests/test_cache_db_change_events.py

Run from project root:
    python tests/test_cache_db_change_events.py
"""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
import core.cache_db as cache_db
from core.source_resolver.models import TrackInfo


tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
tmp.close()

original_cache_enabled = Config.CACHE_ENABLED
original_db_path = Config.DB_PATH
sub = cache_db.subscribe_changes()

try:
    cache_db.rebuild_database(tmp.name)
    cache_db.init_db(db_path=tmp.name, enabled=True)
    Config.CACHE_ENABLED = True
    Config.DB_PATH = tmp.name

    cache_db.put(
        "realtime query",
        TrackInfo(
            title="Realtime Track",
            webpage_url="https://www.youtube.com/watch?v=realtime",
            duration=180,
            thumbnail="",
            requester="tester",
            requester_id=1,
            source="youtube",
            stream_url="https://stream.test/realtime",
            artist="Tester",
        ),
    )
    event = sub.get(timeout=1.0)
finally:
    cache_db.unsubscribe_changes(sub)
    Config.CACHE_ENABLED = original_cache_enabled
    Config.DB_PATH = original_db_path
    cache_db.init_db(db_path=original_db_path, enabled=original_cache_enabled)
    try:
        os.unlink(tmp.name)
    except PermissionError:
        pass

assert event["action"] == "put", event
assert event["source_id"] >= 1, event
assert event["track_id"] >= 1, event
assert event["seq"] >= 1, event

print("OK: cache DB emits realtime change events")
