import functools
import hashlib
import json
import logging
import os
import re
import secrets
import sqlite3
import sys
import time
from urllib.parse import urlencode

import httpx
from flask import Flask, Response, jsonify, redirect, render_template, request, session, stream_with_context, url_for
from werkzeug.middleware.proxy_fix import ProxyFix

from config import Config
import core.cache_db as cache_db
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
    Config.DB_PATH = db_path
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

    def _dj_log(message: str, level: int = logging.INFO, **fields) -> None:
        payload = ", ".join(f"{key}={value}" for key, value in fields.items())
        if payload:
            log.log(level, "DJ console %s [%s]", message, payload)
        else:
            log.log(level, "DJ console %s", message)

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

    def _dj_error(error_code: str, status_code: int = 403, guild_id: int | None = None):
        message_map = {
            "missing_dj_role": "L'account Discord collegato a questa sessione non ha il ruolo DJ richiesto nel server.",
            "auth_required": "Serve una nuova autenticazione Discord per identificare correttamente l'account che sta aprendo la console.",
            "invalid_guild": "Il server richiesto non e` valido o non e` stato passato correttamente alla console.",
            "oauth_not_configured": "OAuth Discord non e` configurato sul bot, quindi la console remota non puo` autenticare l'utente.",
        }
        effective_guild_id = guild_id or int(session.get("dj_guild_id") or session.get("dj_oauth_guild_id") or 0) or None
        reconnect_url = (
            url_for("dj_console", guild_id=effective_guild_id, force_reauth=1)
            if effective_guild_id and _dj_oauth_ready()
            else None
        )
        return render_template(
            "dj_console_error.html",
            error_code=error_code,
            error_message=message_map.get(error_code, "Verifica autenticazione Discord, ruolo DJ configurato e membership del server."),
            guild_id=effective_guild_id,
            reconnect_url=reconnect_url,
        ), status_code

    def _dj_oauth_ready() -> bool:
        return bool(Config.DISCORD_CLIENT_ID and Config.DISCORD_CLIENT_SECRET and Config.DJ_CONSOLE_CALLBACK_URL)

    def _build_discord_authorize_url(guild_id: int) -> str:
        oauth_state = controller.build_oauth_state(guild_id) if controller else f"{guild_id}:{secrets.token_urlsafe(12)}"
        session["dj_oauth_state"] = oauth_state
        session["dj_oauth_guild_id"] = guild_id
        session["dj_auth_requested_at"] = int(time.time())
        params = {
            "client_id": Config.DISCORD_CLIENT_ID,
            "redirect_uri": Config.DJ_CONSOLE_CALLBACK_URL,
            "response_type": "code",
            "scope": "identify",
            "state": oauth_state,
            "prompt": "consent",
        }
        _dj_log("oauth_authorize_url_built", guild_id=guild_id, state=oauth_state)
        return f"{_DISCORD_API}/oauth2/authorize?{urlencode(params)}"

    def _exchange_discord_code(code: str) -> dict:
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
        return token_resp.json()

    def _refresh_discord_token(refresh_token: str) -> dict:
        override = app.config.get("DJ_OAUTH_REFRESH_TOKEN")
        if override:
            return override(refresh_token)
        token_resp = httpx.post(
            f"{_DISCORD_API}/oauth2/token",
            data={
                "client_id": Config.DISCORD_CLIENT_ID,
                "client_secret": Config.DISCORD_CLIENT_SECRET,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=10.0,
        )
        token_resp.raise_for_status()
        return token_resp.json()

    def _refresh_and_store_dj_tokens() -> tuple[bool, str]:
        refresh_token = str(session.get("dj_refresh_token") or "")
        if not refresh_token:
            _clear_dj_session("missing_refresh_token")
            return False, ""
        try:
            token_data = _refresh_discord_token(refresh_token)
        except Exception:
            log.exception("Discord token refresh failed")
            _clear_dj_session("token_refresh_failed")
            return False, ""
        _store_dj_tokens(
            int(session.get("dj_guild_id") or 0),
            int(session.get("dj_discord_user_id") or 0),
            token_data,
        )
        _dj_log(
            "auth_link_refreshed",
            guild_id=session.get("dj_guild_id"),
            user_id=session.get("dj_discord_user_id"),
            expires_at=session.get("dj_token_expires_at"),
        )
        return True, str(session.get("dj_access_token") or "")

    def _fetch_discord_user(access_token: str) -> dict:
        override = app.config.get("DJ_OAUTH_FETCH_USER")
        if override:
            return override(access_token)
        user_resp = httpx.get(
            f"{_DISCORD_API}/users/@me",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10.0,
        )
        user_resp.raise_for_status()
        return user_resp.json()

    def _store_dj_tokens(guild_id: int, user_id: int, token_data: dict) -> None:
        session["dj_discord_user_id"] = user_id
        session["dj_guild_id"] = guild_id
        session["dj_access_token"] = token_data.get("access_token", "")
        session["dj_refresh_token"] = token_data.get("refresh_token", "")
        session["dj_token_expires_at"] = int(time.time()) + int(token_data.get("expires_in", 0) or 0)
        session["dj_identity_checked_at"] = 0
        _dj_log(
            "oauth_tokens_stored",
            level=logging.DEBUG,
            guild_id=guild_id,
            user_id=user_id,
            has_access_token=bool(session["dj_access_token"]),
            has_refresh_token=bool(session["dj_refresh_token"]),
            expires_at=session["dj_token_expires_at"],
        )

    def _clear_dj_session(reason: str | None = None) -> None:
        if reason:
            _dj_log(
                "session_cleared",
                level=logging.INFO,
                reason=reason,
                guild_id=session.get("dj_guild_id"),
                user_id=session.get("dj_discord_user_id"),
            )
        for key in (
            "dj_oauth_state",
            "dj_oauth_guild_id",
            "dj_discord_user_id",
            "dj_guild_id",
            "dj_auth_requested_at",
            "dj_access_token",
            "dj_refresh_token",
            "dj_token_expires_at",
            "dj_identity_checked_at",
        ):
            session.pop(key, None)

    def _ensure_discord_auth_link(force_validate: bool = False) -> tuple[bool, str | None]:
        access_token = str(session.get("dj_access_token") or "")
        refresh_token = str(session.get("dj_refresh_token") or "")
        expires_at = int(session.get("dj_token_expires_at") or 0)
        now = int(time.time())
        if not access_token:
            _dj_log("auth_link_missing_access_token", guild_id=session.get("dj_guild_id"), user_id=session.get("dj_discord_user_id"))
            return False, "auth_required"

        if expires_at and now >= max(0, expires_at - 30):
            refreshed, access_token = _refresh_and_store_dj_tokens()
            if not refreshed:
                return False, "auth_required"

        last_checked = int(session.get("dj_identity_checked_at") or 0)
        if force_validate or (now - last_checked) >= 60:
            try:
                user_payload = _fetch_discord_user(access_token)
            except httpx.HTTPStatusError as exc:
                if exc.response is not None and exc.response.status_code == 401:
                    _dj_log(
                        "auth_link_identity_unauthorized",
                        level=logging.WARNING,
                        guild_id=session.get("dj_guild_id"),
                        user_id=session.get("dj_discord_user_id"),
                    )
                    refreshed, access_token = _refresh_and_store_dj_tokens()
                    if not refreshed:
                        return False, "auth_required"
                    try:
                        user_payload = _fetch_discord_user(access_token)
                    except Exception:
                        log.exception("Discord identity validation failed after token refresh")
                        _clear_dj_session("identity_validation_failed")
                        return False, "auth_required"
                else:
                    log.exception("Discord identity validation failed")
                    _clear_dj_session("identity_validation_failed")
                    return False, "auth_required"
            except Exception:
                log.exception("Discord identity validation failed")
                _clear_dj_session("identity_validation_failed")
                return False, "auth_required"
            expected_user_id = int(session.get("dj_discord_user_id") or 0)
            if int(user_payload.get("id") or 0) != expected_user_id:
                _dj_log(
                    "auth_link_identity_mismatch",
                    level=logging.WARNING,
                    expected_user_id=expected_user_id,
                    actual_user_id=user_payload.get("id"),
                )
                _clear_dj_session("identity_mismatch")
                return False, "auth_required"
            session["dj_identity_checked_at"] = now
            _dj_log(
                "auth_link_validated",
                level=logging.DEBUG,
                guild_id=session.get("dj_guild_id"),
                user_id=expected_user_id,
                checked_at=now,
            )
        return True, None

    def _require_dj_session(guild_id: int, force_identity_validation: bool = False) -> tuple[bool, str | None]:
        if not controller:
            _dj_log("session_rejected", level=logging.WARNING, guild_id=guild_id, error="dj_controller_unavailable")
            return False, "dj_controller_unavailable"
        if not _dj_oauth_ready():
            _dj_log("session_rejected", level=logging.WARNING, guild_id=guild_id, error="oauth_not_configured")
            return False, "oauth_not_configured"
        discord_user_id = session.get("dj_discord_user_id")
        session_guild_id = session.get("dj_guild_id")
        if not discord_user_id or session_guild_id != guild_id:
            _dj_log(
                "session_rejected",
                level=logging.INFO,
                guild_id=guild_id,
                error="auth_required",
                session_guild_id=session_guild_id,
                session_user_id=discord_user_id,
            )
            return False, "auth_required"
        linked, auth_error = _ensure_discord_auth_link(force_validate=force_identity_validation)
        if not linked:
            _dj_log(
                "session_rejected",
                level=logging.INFO,
                guild_id=guild_id,
                error=auth_error or "auth_required",
                session_user_id=discord_user_id,
            )
            return False, auth_error or "auth_required"
        allowed, error = controller.check_access(guild_id, int(discord_user_id))
        if allowed:
            _dj_log("session_authorized", level=logging.DEBUG, guild_id=guild_id, user_id=discord_user_id)
            return True, None
        _dj_log(
            "session_rejected",
            level=logging.INFO,
            guild_id=guild_id,
            user_id=discord_user_id,
            error=error or "forbidden",
        )
        return False, error

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
        runtime_label = f"Python {sys.version_info.major}.{sys.version_info.minor}"
        runtime_stack = "Flask + SQLite"
        db_name = os.path.basename(db_path)
        bot_avatar_url = None
        if bot and getattr(bot, "user", None):
            try:
                bot_avatar_url = str(bot.user.display_avatar.url)
            except Exception:
                bot_avatar_url = None
        return render_template(
            "index.html",
            stats=stats,
            aliases_count=aliases_count,
            runtime_label=runtime_label,
            runtime_stack=runtime_stack,
            db_name=db_name,
            bot_avatar_url=bot_avatar_url,
        )

    @app.route("/dj-console")
    def dj_console():
        raw_guild_id = (request.args.get("guild_id") or "").strip()
        if not raw_guild_id.isdigit():
            return _dj_error("invalid_guild", 400)
        guild_id = int(raw_guild_id)
        if (request.args.get("force_reauth") or "").strip() == "1":
            _clear_dj_session("manual_reauth")
            _dj_log("console_force_reauth", guild_id=guild_id)
            return redirect(url_for("dj_console_login", guild_id=guild_id))
        _dj_log("console_entry", guild_id=guild_id, session_guild_id=session.get("dj_guild_id"), session_user_id=session.get("dj_discord_user_id"))
        allowed, error = _require_dj_session(guild_id, force_identity_validation=True)
        if not allowed:
            if error == "auth_required":
                _dj_log("console_redirect_login", guild_id=guild_id)
                return redirect(url_for("dj_console_login", guild_id=guild_id))
            return _dj_error(error or "forbidden", 403, guild_id=guild_id)
        return render_template("dj_console.html", guild_id=guild_id)

    @app.route("/dj-console/login")
    def dj_console_login():
        raw_guild_id = (request.args.get("guild_id") or "").strip()
        if not raw_guild_id.isdigit():
            return _dj_error("invalid_guild", 400)
        if not _dj_oauth_ready():
            return _dj_error("oauth_not_configured", 503)
        _dj_log("console_login_start", guild_id=raw_guild_id)
        return redirect(_build_discord_authorize_url(int(raw_guild_id)))

    @app.route("/dj-console/callback")
    @app.route("/dj-console/discord-callback")
    def dj_console_callback():
        if not controller:
            return _dj_error("dj_controller_unavailable", 503)
        code = (request.args.get("code") or "").strip()
        state = (request.args.get("state") or "").strip()
        _dj_log(
            "console_callback_received",
            level=logging.DEBUG,
            state=state,
            session_state=session.get("dj_oauth_state"),
            session_oauth_guild_id=session.get("dj_oauth_guild_id"),
        )
        if not code or not state or state != session.get("dj_oauth_state"):
            return _dj_error("invalid_oauth_state", 400)
        try:
            guild_id = int(str(state).split(":", 1)[0])
        except (TypeError, ValueError):
            return _dj_error("invalid_oauth_state", 400)
        expected_guild_id = int(session.get("dj_oauth_guild_id") or 0)
        if expected_guild_id and expected_guild_id != guild_id:
            _dj_log(
                "console_callback_guild_mismatch",
                level=logging.WARNING,
                state_guild_id=guild_id,
                session_oauth_guild_id=expected_guild_id,
            )
            return _dj_error("invalid_oauth_state", 400)
        try:
            oauth_user_override = app.config.get("DJ_OAUTH_FETCH_USER")
            if oauth_user_override:
                token_data = {
                    "access_token": "test-access-token",
                    "refresh_token": "",
                    "expires_in": 3600,
                }
                user_payload = oauth_user_override(code)
            else:
                token_data = _exchange_discord_code(code)
                user_payload = _fetch_discord_user(str(token_data.get("access_token") or ""))
        except Exception:
            log.exception("Discord OAuth callback failed")
            return _dj_error("oauth_exchange_failed", 502)
        user_id = int(user_payload["id"])
        _clear_dj_session()
        _store_dj_tokens(guild_id, user_id, token_data)
        allowed, error = controller.check_access(guild_id, user_id)
        if not allowed:
            _dj_log("console_callback_access_denied", level=logging.INFO, guild_id=guild_id, user_id=user_id, error=error)
            return _dj_error(error or "forbidden", 403)
        _dj_log("console_callback_access_granted", guild_id=guild_id, user_id=user_id)
        return redirect(url_for("dj_console", guild_id=guild_id))

    @app.route("/dj-console/state")
    def dj_console_state():
        raw_guild_id = (request.args.get("guild_id") or "").strip()
        if not raw_guild_id.isdigit():
            return jsonify({"error": "invalid_guild"}), 400
        guild_id = int(raw_guild_id)
        allowed, error = _require_dj_session(guild_id)
        if not allowed:
            status = 401 if error == "auth_required" else 403
            _dj_log("state_denied", level=logging.INFO, guild_id=guild_id, error=error or "forbidden", status=status)
            return jsonify({"error": error or "forbidden"}), status
        snapshot = controller.get_player_snapshot(guild_id)
        current = snapshot.get("current_track") or {}
        _dj_log(
            "state_ready",
            level=logging.DEBUG,
            guild_id=guild_id,
            connected=snapshot.get("connected"),
            title=current.get("title"),
        )
        return jsonify(snapshot)

    @app.route("/dj-console/action", methods=["POST"])
    def dj_console_action():
        data = request.get_json(force=True, silent=True) or {}
        try:
            guild_id = int(data.get("guild_id"))
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "invalid_guild"}), 400
        allowed, error = _require_dj_session(guild_id)
        if not allowed:
            status = 401 if error == "auth_required" else 403
            _dj_log("action_denied", level=logging.INFO, guild_id=guild_id, action=data.get("action"), error=error or "forbidden", status=status)
            return jsonify({"ok": False, "error": error or "forbidden"}), status
        action = str(data.get("action") or "").strip()
        _dj_log("action_start", level=logging.DEBUG, guild_id=guild_id, action=action)
        result = controller.perform_action(guild_id, action, data)
        _dj_log("action_result", level=logging.INFO if result.get("ok") else logging.WARNING, guild_id=guild_id, action=action, result=result)
        return jsonify(result), (200 if result.get("ok") else 400)

    @app.route("/dj-console/events")
    def dj_console_events():
        raw_guild_id = (request.args.get("guild_id") or "").strip()
        if not raw_guild_id.isdigit():
            return jsonify({"error": "invalid_guild"}), 400
        guild_id = int(raw_guild_id)
        allowed, error = _require_dj_session(guild_id)
        if not allowed:
            status = 401 if error == "auth_required" else 403
            _dj_log("events_denied", level=logging.INFO, guild_id=guild_id, error=error or "forbidden", status=status)
            return jsonify({"error": error or "forbidden"}), status

        @stream_with_context
        def events():
            sub = controller.subscribe(guild_id)
            _dj_log("events_subscribed", level=logging.DEBUG, guild_id=guild_id)
            try:
                initial = json.dumps(controller.get_player_snapshot(guild_id), separators=(",", ":"))
                yield f"event: dj_state\ndata: {initial}\n\n"
                if app.config.get("DJ_OAUTH_FETCH_USER"):
                    return
                while True:
                    try:
                        payload = sub.get(timeout=15.0)
                        yield f"event: dj_state\ndata: {payload}\n\n"
                    except Exception:
                        yield ": keepalive\n\n"
            finally:
                controller.unsubscribe(guild_id, sub)
                _dj_log("events_unsubscribed", level=logging.DEBUG, guild_id=guild_id)

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
        sort = request.args.get("sort", "created_at")
        order = request.args.get("order", "desc")

        allowed = {"hit_count", "created_at", "last_used", "title", "artist", "query_raw", "id"}
        if sort not in allowed:
            sort = "created_at"
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
        rows = cache_db.list_song_rows(search=search, source=source, valid=valid, sort=sort, order=order)
        return jsonify(rows)

    @app.route("/api/aliases")
    @login_required
    def api_aliases():
        rows = cache_db.list_alias_rows()
        return jsonify(rows)

    @app.route("/api/tracks")
    @login_required
    def api_tracks():
        return jsonify(cache_db.list_track_rows())

    @app.route("/api/sources")
    @login_required
    def api_sources():
        return jsonify(cache_db.list_source_rows())

    @app.route("/api/queries")
    @login_required
    def api_queries():
        return jsonify(cache_db.list_query_rows())

    @app.route("/api/schema")
    @login_required
    def api_schema():
        return jsonify(cache_db.schema_overview())

    @app.route("/api/associate", methods=["POST"])
    @login_required
    def api_associate():
        data = request.get_json(force=True, silent=True) or {}
        result = cache_db.associate_spotify(
            spotify_url=(data.get("spotify_url") or "").strip(),
            title=(data.get("title") or "").strip(),
            artist=(data.get("artist") or "").strip(),
        )
        status = 200 if result.get("ok") else 400
        return jsonify(result), status

    @app.route("/api/delete/<int:row_id>", methods=["DELETE"])
    @login_required
    def delete_song(row_id):
        return jsonify({"ok": cache_db.delete_song_row(row_id)})

    @app.route("/api/tracks/<int:track_id>", methods=["DELETE"])
    @login_required
    def delete_track(track_id):
        return jsonify({"ok": cache_db.delete_track_row(track_id)})

    @app.route("/api/sources/<int:source_id>", methods=["DELETE"])
    @login_required
    def delete_source(source_id):
        return jsonify({"ok": cache_db.delete_source_row(source_id)})

    @app.route("/api/queries/<int:query_id>", methods=["DELETE"])
    @login_required
    def delete_query(query_id):
        return jsonify({"ok": cache_db.delete_alias(query_id)})

    @app.route("/api/aliases/<int:alias_id>", methods=["DELETE"])
    @login_required
    def delete_alias(alias_id):
        return jsonify({"ok": cache_db.delete_alias(alias_id)})

    return app


if __name__ == "__main__":
    socket = os.getenv("DASHBOARD_SOCKET", "127.0.0.1:5000")
    host, port = socket.rsplit(":", 1)
    flask_app = create_app()
    flask_app.run(host=host, port=int(port), debug=False)
