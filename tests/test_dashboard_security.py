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
    import core.cache_db as cache_db
    cache_db.rebuild_database(db_path)

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

    anonymous = app.test_client()
    assert anonymous.get("/api/songs").status_code == 401
    assert anonymous.get("/api/stats").get_json() == {"error": "unauthorized"}

    unicode_login = app.test_client().post(
        "/login", data={"username": "amministratòre", "password": "caffè"}
    )
    assert unicode_login.status_code == 200, unicode_login.data

    # The rightmost proxy hop determines identity; adding a spoofed prefix
    # must not reset the rate limit for the same client.
    limited = app.test_client()
    for index in range(5):
        response = limited.post(
            "/login", data={"username": "bad", "password": "bad"},
            headers={"X-Forwarded-For": f"198.51.100.{index}, 192.0.2.10"},
        )
        assert response.status_code == 200
    response = limited.post(
        "/login", data={"username": "bad", "password": "bad"},
        headers={"X-Forwarded-For": "203.0.113.50, 192.0.2.10"},
    )
    assert response.status_code == 429, response.data

    os.environ["DASH_TRUST_PROXY"] = "false"
    direct_app = create_app(str(db_path))
    direct_client = direct_app.test_client()
    for index in range(5):
        assert direct_client.post(
            "/login", data={"username": "bad", "password": "bad"},
            headers={"X-Forwarded-For": f"198.51.100.{index}"},
        ).status_code == 200
    assert direct_client.post(
        "/login", data={"username": "bad", "password": "bad"},
        headers={"X-Forwarded-For": "203.0.113.50"},
    ).status_code == 429
    os.environ["DASH_TRUST_PROXY"] = "true"
    print("OK: JSON auth, Unicode credentials, trusted and untrusted proxy rate limits")

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
