from __future__ import annotations

import os
import queue
import sqlite3
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["DASH_USER"] = "admin"
os.environ["DASH_PASSWORD"] = "secret-pass"
os.environ["DASH_SECRET_KEY"] = "test-secret-key"
os.environ["DISCORD_CLIENT_ID"] = "cid"
os.environ["DISCORD_CLIENT_SECRET"] = "csecret"
os.environ["DASHBOARD_PUBLIC_BASE_URL"] = "http://127.0.0.1:5000"
os.environ["DJ_CONSOLE_CALLBACK_URL"] = "http://127.0.0.1:5000/dj-console/callback"

from data.database.dashboard.app import create_app
from core.dj_access import get_dj_access_controller


def make_db() -> str:
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "cache.db"
        conn = sqlite3.connect(db_path)
        conn.executescript(
            """
            CREATE TABLE song_cache (
                id INTEGER PRIMARY KEY,
                query_hash TEXT,
                query_raw TEXT,
                is_valid INTEGER NOT NULL DEFAULT 1,
                hit_count INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE query_aliases (
                id INTEGER PRIMARY KEY,
                query_hash TEXT,
                query_raw TEXT,
                cache_id INTEGER
            );
            """
        )
        conn.commit()
        conn.close()
        copy_path = Path(tempfile.gettempdir()) / "pytonazz_dj_console_test.db"
        copy_path.write_bytes(db_path.read_bytes())
        return str(copy_path)


db_path = make_db()
app = create_app(db_path=db_path, bot=SimpleNamespace(loop=None))
controller = get_dj_access_controller()
controller.build_oauth_state = lambda guild_id: f"{guild_id}:state"
controller.check_access = lambda guild_id, user_id, timeout=8.0: (user_id == 42, None if user_id == 42 else "missing_dj_role")
controller.get_player_snapshot = lambda guild_id: {
    "guild_id": guild_id,
    "connected": True,
    "voice_channel_name": "DJ Booth",
    "is_paused": False,
    "position": 12.0,
    "duration": 180,
    "volume": 0.5,
    "loop_mode": "off",
    "shuffle_mode": False,
    "autoplay_enabled": False,
    "filter_name": "off",
    "eq": {"low": 0.0, "mid": 0.0, "high": 0.0},
    "current_track": None,
    "queue": [],
}
controller.perform_action = lambda guild_id, action, payload, timeout=10.0: {"ok": True}
controller.subscribe = lambda guild_id: queue.Queue()
controller.unsubscribe = lambda guild_id, q: None
app.config["DJ_OAUTH_FETCH_USER"] = lambda code: {"id": "42"}

client = app.test_client()

missing = client.get("/dj-console", follow_redirects=False)
assert missing.status_code == 400

redirected = client.get("/dj-console?guild_id=123", follow_redirects=False)
assert redirected.status_code == 302
assert "/dj-console/login?guild_id=123" in redirected.headers["Location"]

oauth_start = client.get("/dj-console/login?guild_id=123", follow_redirects=False)
assert oauth_start.status_code == 302
assert "discord.com/api/v10/oauth2/authorize" in oauth_start.headers["Location"]

callback = client.get("/dj-console/callback?code=abc&state=123:state", follow_redirects=False)
assert callback.status_code == 302
assert "/dj-console?guild_id=123" in callback.headers["Location"]

allowed = client.get("/dj-console?guild_id=123", follow_redirects=False)
assert allowed.status_code == 200

state_resp = client.get("/dj-console/state?guild_id=123")
assert state_resp.status_code == 200
assert state_resp.get_json()["voice_channel_name"] == "DJ Booth"

action_resp = client.post("/dj-console/action", json={"guild_id": 123, "action": "skip"})
assert action_resp.status_code == 200
assert action_resp.get_json()["ok"] is True

events_resp = client.get("/dj-console/events?guild_id=123")
assert events_resp.status_code == 200
assert b"event: dj_state" in events_resp.data

with client.session_transaction() as sess:
    sess["dj_discord_user_id"] = 77
    sess["dj_guild_id"] = 123

denied = client.get("/dj-console?guild_id=123", follow_redirects=False)
assert denied.status_code == 403

print("OK: dj console oauth/access/routes")
