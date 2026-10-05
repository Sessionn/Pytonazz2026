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

    headers = ok.headers
    assert headers.get("X-Frame-Options") == "DENY"
    assert headers.get("X-Content-Type-Options") == "nosniff"
    assert "script-src 'self'" in headers.get("Content-Security-Policy", "")

    blocked_cross_origin = client.delete(
        "/api/delete/1",
        headers={"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"},
    )
    assert blocked_cross_origin.status_code == 403, blocked_cross_origin.status_code
    same_origin = client.delete("/api/delete/999999", headers={"Origin": "http://localhost"})
    assert same_origin.status_code == 200, same_origin.status_code

    print("OK: dashboard security headers/csrf")

    # Il rate limit deve usare l'IP aggiunto dal proxy (ultimo hop), non il
    # primo valore di X-Forwarded-For che il client puo' inventare a piacere.
    limited = create_app(str(db_path)).test_client()
    statuses = []
    for attempt in range(7):
        resp = limited.post(
            "/login",
            data={"username": "admin", "password": "wrong"},
            headers={"X-Forwarded-For": f"10.0.0.{attempt}, 203.0.113.7"},
        )
        statuses.append(resp.status_code)
    assert statuses[-1] == 429, statuses

    print("OK: dashboard login rate limit not bypassable via X-Forwarded-For")

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
