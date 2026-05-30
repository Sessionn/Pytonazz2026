"""
tests/test_dashboard_security.py

Esecuzione:
    python tests/test_dashboard_security.py
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["DASH_USER"] = "admin"
os.environ["DASH_PASSWORD"] = "secret-pass"
os.environ["DASH_SECRET_KEY"] = "test-secret-key"
os.environ["DASH_TRUST_PROXY"] = "true"
os.environ["DASH_SESSION_SECURE"] = "true"
os.environ["DASH_SESSION_SAMESITE"] = "Lax"

with tempfile.TemporaryDirectory() as td:
    db_path = Path(td) / "cache.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE song_cache (
            id INTEGER PRIMARY KEY,
            is_valid INTEGER NOT NULL DEFAULT 1,
            hit_count INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE query_aliases (
            id INTEGER PRIMARY KEY,
            query_raw TEXT,
            cache_id INTEGER
        );
        """
    )
    conn.commit()
    conn.close()

    from data.database.dashboard.app import create_app

    app = create_app(str(db_path))
    assert app.config["SESSION_COOKIE_SECURE"] is True
    assert app.config["SESSION_COOKIE_HTTPONLY"] is True
    assert app.config["SESSION_COOKIE_SAMESITE"] == "Lax"

    client = app.test_client()
    bad = client.post("/login", data={"username": "wrong", "password": "secret-pass"}, follow_redirects=False)
    assert bad.status_code == 200

    ok = client.post("/login", data={"username": "admin", "password": "secret-pass"}, follow_redirects=False)
    assert ok.status_code == 302

    print("OK: dashboard security config/login")

    os.environ.pop("DASH_SECRET_KEY", None)
    app_random_secret = create_app(str(db_path))
    assert app_random_secret.secret_key
    assert app_random_secret.secret_key != "pytonazz-dev-secret-change-me"

    print("OK: dashboard random secret fallback")

    os.environ.pop("DASH_USER", None)
    os.environ.pop("DASH_PASSWORD", None)
    app_missing_auth = create_app(str(db_path))
    client_missing_auth = app_missing_auth.test_client()
    blocked = client_missing_auth.get("/", follow_redirects=False)
    assert blocked.status_code == 503

    print("OK: dashboard fail-closed without auth config")
