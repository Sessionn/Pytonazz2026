import functools
import hashlib
import json
import logging
import os
import re
import secrets
import sqlite3
import time
from urllib.parse import urlencode

import httpx
from flask import Flask, Response, jsonify, redirect, render_template, request, session, stream_with_context, url_for
from werkzeug.middleware.proxy_fix import ProxyFix

from config import Config
from core.dj_access import get_dj_access_controller, init_dj_access_controller

log = logging.getLogger(__name__)

_RE_SPOTIFY = re.compile(
    r"(open\.spotify\.com|spotify\.com)/(?:intl-[a-z]{2}/)?(track|album|playlist|artist)/([A-Za-z0-9]+)",
    re.I,
)
_DISCORD_API = "https://discord.com/api/v10"


def _extract_spotify_id(url: str) -> str:
    m = _RE_SPOTIFY.search(url)
    if m:
        return f"https://open.spotify.com/{m.group(2)}/{m.group(3)}"
    return url


def _hash(s: str) -> str:
    norm = re.sub(r"[^\w\s:/.-]+", " ", (s or "").lower().strip())
    norm = re.sub(r"\s+", " ", norm).strip()
    return hashlib.sha256(norm.encode()).hexdigest()


def create_app(db_path: str | None = None, bot=None) -> Flask:
    base_dir = os.path.dirname(os.path.abspath(__file__))
    db_path = db_path or os.path.join(base_dir, "..", "cache.db")
    db_path = os.path.abspath(db_path)
    secret_key = (os.getenv("DASH_SECRET_KEY") or os.getenv("DASHBOARD_SECRET") or "").strip()
    dashboard_user = (os.getenv("DASH_USER") or os.getenv("DASHBOARD_USER") or "").strip()
    dashboard_pw = os.getenv("DASH_PASSWORD") or os.getenv("DASHBOARD_PASSWORD") or ""
    trust_proxy = os.getenv("DASH_TRUST_PROXY", "true").strip().lower() in ("true", "1", "yes", "on")
    session_secure = os.getenv("DASH_SESSION_SECURE", "true").strip().lower() in ("true", "1", "yes", "on")
    session_samesite = (os.getenv("DASH_SESSION_SAMESITE", "Lax") or "Lax").strip().capitalize()
    login_window_seconds = max(60, int(os.getenv("DASH_LOGIN_WINDOW_SECONDS", "900")))
    login_max_attempts = max(1, int(os.getenv("DASH_LOGIN_MAX_ATTEMPTS", "5")))
    dashboard_auth_ready = bool(dashboard_user and dashboard_pw)

    if not secret_key:
        secret_key = secrets.token_hex(32)
        log.warning("DASH_SECRET_KEY non impostata: generata chiave di sessione volatile per questo avvio")
    if not dashboard_auth_ready:
        log.error("Dashboard disabilitata: imposta sia DASH_USER sia DASH_PASSWORD prima di esporla")

    app = Flask(
        __name__,
        template_folder=os.path.join(base_dir, "templates"),
        static_folder=os.path.join(base_dir, "static"),
    )
    app.secret_key = secret_key
    app.config.update(
        SESSION_COOKIE_SECURE=session_secure,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE=session_samesite if session_samesite in {"Lax", "Strict", "None"} else "Lax",
        PREFERRED_URL_SCHEME="https" if session_secure else "http",
        DJ_OAUTH_FETCH_USER=None,
    )
    if trust_proxy:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    login_attempts: dict[str, list[float]] = {}

    controller = init_dj_access_controller(bot) if bot else get_dj_access_controller()

    def get_conn():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def query_db(sql, params=None):
        conn = get_conn()
        try:
            cur = conn.execute(sql, params or [])
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    def _stats_payload() -> dict:
        row = query_db(
            """
            SELECT
                COUNT(*)                                           AS total,
                SUM(CASE WHEN is_valid=1 THEN 1 ELSE 0 END)       AS valid,
                SUM(CASE WHEN is_valid=0 THEN 1 ELSE 0 END)       AS invalid,
                COALESCE(SUM(hit_count), 0)                        AS hits
            FROM song_cache
            """
        )[0]
        aliases = query_db("SELECT COUNT(*) AS c FROM query_aliases")[0]["c"]
        return {
            "total": row["total"] or 0,
            "valid": row["valid"] or 0,
            "invalid": row["invalid"] or 0,
            "hits": row["hits"] or 0,
            "aliases": aliases,
            "ts": int(time.time()),
        }

    def login_required(f):
        @functools.wraps(f)
        def wrapped(*args, **kwargs):
            if not dashboard_auth_ready:
                if request.is_json:
                    return jsonify({"error": "dashboard_auth_not_configured"}), 503
                return render_template("login.html", error="Dashboard non configurata: imposta DASH_USER e DASH_PASSWORD."), 503
            if not session.get("auth"):
                if request.is_json:
                    return jsonify({"error": "unauthorized"}), 401
                return redirect(url_for("login"))
            return f(*args, **kwargs)

        return wrapped

    def _dj_error(error_code: str, status_code: int = 403):
        return render_template("dj_console_error.html", error_code=error_code), status_code

    def _dj_oauth_ready() -> bool:
        return bool(Config.DISCORD_CLIENT_ID and Config.DISCORD_CLIENT_SECRET and Config.DJ_CONSOLE_CALLBACK_URL)

    def _build_discord_authorize_url(guild_id: int) -> str:
        oauth_state = controller.build_oauth_state(guild_id) if controller else f"{guild_id}:{secrets.token_urlsafe(12)}"
        session["dj_oauth_state"] = oauth_state
        session["dj_oauth_guild_id"] = guild_id
        params = {
            "client_id": Config.DISCORD_CLIENT_ID,
            "redirect_uri": Config.DJ_CONSOLE_CALLBACK_URL,
            "response_type": "code",
            "scope": "identify",
            "state": oauth_state,
            "prompt": "consent",
        }
        return f"{_DISCORD_API}/oauth2/authorize?{urlencode(params)}"

    def _fetch_discord_user(code: str) -> dict:
        override = app.config.get("DJ_OAUTH_FETCH_USER")
        if override:
            return override(code)
        token_resp = httpx.post(
            f"{_DISCORD_API}/oauth2/token",
            data={
                "client_id": Config.DISCORD_CLIENT_ID,
                "client_secret": Config.DISCORD_CLIENT_SECRET,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": Config.DJ_CONSOLE_CALLBACK_URL,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=10.0,
        )
        token_resp.raise_for_status()
        token_data = token_resp.json()
        access_token = token_data.get("access_token")
        user_resp = httpx.get(
            f"{_DISCORD_API}/users/@me",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10.0,
        )
        user_resp.raise_for_status()
        return user_resp.json()

    def _require_dj_session(guild_id: int) -> tuple[bool, str | None]:
        if not controller:
            return False, "dj_controller_unavailable"
        if not _dj_oauth_ready():
            return False, "oauth_not_configured"
        discord_user_id = session.get("dj_discord_user_id")
        session_guild_id = session.get("dj_guild_id")
        if not discord_user_id or session_guild_id != guild_id:
            return False, "auth_required"
        return controller.check_access(guild_id, int(discord_user_id))

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if not dashboard_auth_ready:
            return render_template("login.html", error="Dashboard non configurata: imposta DASH_USER e DASH_PASSWORD."), 503
        error = None
        if request.method == "POST":
            now = time.time()
            client_ip = (request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or request.remote_addr or "unknown")
            attempts = [ts for ts in login_attempts.get(client_ip, []) if now - ts < login_window_seconds]
            login_attempts[client_ip] = attempts
            if len(attempts) >= login_max_attempts:
                return render_template("login.html", error="Troppi tentativi. Riprova piu tardi."), 429

            username = (request.form.get("username", "") or "").strip()
            pw = request.form.get("password", "")
            user_ok = (not dashboard_user) or secrets.compare_digest(username, dashboard_user)
            pw_ok = bool(dashboard_pw) and secrets.compare_digest(pw, dashboard_pw)
            if user_ok and pw_ok:
                session["auth"] = True
                session.permanent = True
                login_attempts.pop(client_ip, None)
                return redirect(url_for("index"))
            attempts.append(now)
            login_attempts[client_ip] = attempts[-login_max_attempts:]
            error = "Credenziali errate."
        return render_template("login.html", error=error)

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.route("/")
    @login_required
    def index():
        stats = query_db(
            """
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN is_valid=1 THEN 1 ELSE 0 END) AS valid,
                SUM(CASE WHEN is_valid=0 THEN 1 ELSE 0 END) AS invalid,
                SUM(hit_count) AS hits
            FROM song_cache
            """
        )[0]
        aliases_count = query_db("SELECT COUNT(*) as c FROM query_aliases")[0]["c"]
        return render_template("index.html", stats=stats, aliases_count=aliases_count)

    @app.route("/dj-console")
    def dj_console():
        raw_guild_id = (request.args.get("guild_id") or "").strip()
        if not raw_guild_id.isdigit():
            return _dj_error("invalid_guild", 400)
        guild_id = int(raw_guild_id)
        allowed, error = _require_dj_session(guild_id)
        if not allowed:
            if error == "auth_required":
                return redirect(url_for("dj_console_login", guild_id=guild_id))
            return _dj_error(error or "forbidden", 403)
        return render_template("dj_console.html", guild_id=guild_id)

    @app.route("/dj-console/login")
    def dj_console_login():
        raw_guild_id = (request.args.get("guild_id") or "").strip()
        if not raw_guild_id.isdigit():
            return _dj_error("invalid_guild", 400)
        if not _dj_oauth_ready():
            return _dj_error("oauth_not_configured", 503)
        return redirect(_build_discord_authorize_url(int(raw_guild_id)))

    @app.route("/dj-console/callback")
    @app.route("/dj-console/discord-callback")
    def dj_console_callback():
        if not controller:
            return _dj_error("dj_controller_unavailable", 503)
        code = (request.args.get("code") or "").strip()
        state = (request.args.get("state") or "").strip()
        if not code or not state or state != session.get("dj_oauth_state"):
            return _dj_error("invalid_oauth_state", 400)
        try:
            guild_id = int(str(state).split(":", 1)[0])
        except (TypeError, ValueError):
            return _dj_error("invalid_oauth_state", 400)
        try:
            user_payload = _fetch_discord_user(code)
        except Exception:
            log.exception("Discord OAuth callback failed")
            return _dj_error("oauth_exchange_failed", 502)
        user_id = int(user_payload["id"])
        session["dj_discord_user_id"] = user_id
        session["dj_guild_id"] = guild_id
        allowed, error = controller.check_access(guild_id, user_id)
        if not allowed:
            return _dj_error(error or "forbidden", 403)
        return redirect(url_for("dj_console", guild_id=guild_id))

    @app.route("/dj-console/state")
    def dj_console_state():
        raw_guild_id = (request.args.get("guild_id") or "").strip()
        if not raw_guild_id.isdigit():
            return jsonify({"error": "invalid_guild"}), 400
        guild_id = int(raw_guild_id)
        allowed, error = _require_dj_session(guild_id)
        if not allowed:
            return jsonify({"error": error or "forbidden"}), 403
        return jsonify(controller.get_player_snapshot(guild_id))

    @app.route("/dj-console/action", methods=["POST"])
    def dj_console_action():
        data = request.get_json(force=True, silent=True) or {}
        try:
            guild_id = int(data.get("guild_id"))
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "invalid_guild"}), 400
        allowed, error = _require_dj_session(guild_id)
        if not allowed:
            return jsonify({"ok": False, "error": error or "forbidden"}), 403
        action = str(data.get("action") or "").strip()
        result = controller.perform_action(guild_id, action, data)
        return jsonify(result), (200 if result.get("ok") else 400)

    @app.route("/dj-console/events")
    def dj_console_events():
        raw_guild_id = (request.args.get("guild_id") or "").strip()
        if not raw_guild_id.isdigit():
            return jsonify({"error": "invalid_guild"}), 400
        guild_id = int(raw_guild_id)
        allowed, error = _require_dj_session(guild_id)
        if not allowed:
            return jsonify({"error": error or "forbidden"}), 403

        @stream_with_context
        def events():
            sub = controller.subscribe(guild_id)
            try:
                initial = json.dumps(controller.get_player_snapshot(guild_id), separators=(",", ":"))
                yield f"event: dj_state\ndata: {initial}\n\n"
                while True:
                    try:
                        payload = sub.get(timeout=15.0)
                        yield f"event: dj_state\ndata: {payload}\n\n"
                    except Exception:
                        yield ": keepalive\n\n"
            finally:
                controller.unsubscribe(guild_id, sub)

        return Response(events(), mimetype="text/event-stream")

    @app.route("/api/stats")
    @login_required
    def api_stats():
        return jsonify(_stats_payload())

    @app.route("/api/events")
    @login_required
    def api_events():
        @stream_with_context
        def events():
            last = None
            while True:
                payload = _stats_payload()
                encoded = json.dumps(payload, separators=(",", ":"))
                if encoded != last:
                    yield f"event: stats\ndata: {encoded}\n\n"
                    last = encoded
                else:
                    yield ": keepalive\n\n"
                time.sleep(5)

        return Response(events(), mimetype="text/event-stream")

    @app.route("/api/songs")
    @login_required
    def api_songs():
        search = request.args.get("q", "").strip()
        source = request.args.get("source", "")
        valid = request.args.get("valid", "")
        sort = request.args.get("sort", "hit_count")
        order = request.args.get("order", "desc")

        allowed = {"hit_count", "created_at", "last_used", "title", "artist", "id"}
        if sort not in allowed:
            sort = "hit_count"
        order = "DESC" if order == "desc" else "ASC"

        filters, params = [], []
        if search:
            filters.append("(LOWER(title) LIKE ? OR LOWER(artist) LIKE ? OR LOWER(query_raw) LIKE ?)")
            params += [f"%{search.lower()}%"] * 3
        if source:
            filters.append("source = ?")
            params.append(source)
        if valid in ("1", "0"):
            filters.append("is_valid = ?")
            params.append(int(valid))

        where = ("WHERE " + " AND ".join(filters)) if filters else ""
        rows = query_db(f"SELECT * FROM song_cache {where} ORDER BY {sort} {order}", params)
        return jsonify(rows)

    @app.route("/api/aliases")
    @login_required
    def api_aliases():
        rows = query_db(
            """
            SELECT qa.id, qa.query_raw, qa.cache_id,
                   qa.alias_type, sc.title, sc.artist, sc.spotify_url, sc.webpage_url
            FROM query_aliases qa
            LEFT JOIN song_cache sc ON sc.id = qa.cache_id
            ORDER BY qa.id DESC
            """
        )
        return jsonify(rows)

    @app.route("/api/associate", methods=["POST"])
    @login_required
    def api_associate():
        data = request.get_json(force=True, silent=True) or {}
        raw_url = (data.get("spotify_url") or "").strip()
        title = (data.get("title") or "").strip().lower()
        artist = (data.get("artist") or "").strip().lower()

        if not raw_url or not _RE_SPOTIFY.search(raw_url):
            return jsonify({"ok": False, "action": "invalid_url", "cache_id": None}), 400

        spotify_url = _extract_spotify_id(raw_url)
        h_spotify = _hash(spotify_url)

        conn = get_conn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT id FROM song_cache WHERE spotify_url = ? AND is_valid = 1 LIMIT 1", (spotify_url,))
            row = cur.fetchone()
            if row:
                return jsonify({"ok": True, "action": "already_set", "cache_id": row["id"]})

            cur.execute("SELECT cache_id FROM query_aliases WHERE query_hash = ? LIMIT 1", (h_spotify,))
            alias_row = cur.fetchone()
            if alias_row:
                return jsonify({"ok": True, "action": "already_alias", "cache_id": alias_row["cache_id"]})

            target = None
            if title:
                filters, params = ["LOWER(title) LIKE ?"], [f"%{title}%"]
                if artist:
                    filters.append("LOWER(artist) LIKE ?")
                    params.append(f"%{artist}%")
                cur.execute(f"SELECT id FROM song_cache WHERE {' AND '.join(filters)} AND is_valid=1 LIMIT 1", params)
                target = cur.fetchone()

            if target is None:
                return jsonify({"ok": False, "action": "not_found", "cache_id": None})

            cache_id = target["id"]
            cur.execute(
                "UPDATE song_cache SET spotify_url = ? WHERE id = ? AND (spotify_url IS NULL OR spotify_url = '')",
                (spotify_url, cache_id),
            )
            cur.execute(
                """
                INSERT INTO query_aliases (query_hash, query_raw, alias_type, cache_id)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(query_hash) DO UPDATE SET
                    query_raw = excluded.query_raw,
                    alias_type = excluded.alias_type,
                    cache_id  = excluded.cache_id
                """,
                (h_spotify, spotify_url, "spotify", cache_id),
            )
            conn.commit()
        finally:
            conn.close()

        return jsonify({"ok": True, "action": "associated", "cache_id": cache_id})

    @app.route("/api/delete/<int:row_id>", methods=["DELETE"])
    @login_required
    def delete_song(row_id):
        conn = get_conn()
        conn.execute("DELETE FROM song_cache WHERE id = ?", (row_id,))
        conn.commit()
        conn.close()
        return jsonify({"ok": True})

    @app.route("/api/aliases/<int:alias_id>", methods=["DELETE"])
    @login_required
    def delete_alias(alias_id):
        conn = get_conn()
        conn.execute("DELETE FROM query_aliases WHERE id = ?", (alias_id,))
        conn.commit()
        conn.close()
        return jsonify({"ok": True})

    return app


if __name__ == "__main__":
    socket = os.getenv("DASHBOARD_SOCKET", "127.0.0.1:5000")
    host, port = socket.rsplit(":", 1)
    flask_app = create_app()
    flask_app.run(host=host, port=int(port), debug=False)
