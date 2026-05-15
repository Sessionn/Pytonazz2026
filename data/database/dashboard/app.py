import sqlite3
import os
import logging
import functools
from flask import (
    Flask, render_template, jsonify, request,
    session, redirect, url_for
)
from dotenv import load_dotenv

# Carica .env dalla root del progetto
_ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", ".env")
load_dotenv(_ENV_PATH)

# Importa tag() se disponibile, altrimenti fallback semplice
try:
    from core.log_colors import tag as _lc_tag
except ImportError:
    def _lc_tag(label: str, msg: str) -> str:  # type: ignore
        return f"{label}  {msg}"


# ── Logger dedicato per connessioni anomale (scanner TLS/bot) ────────────
_net_log = logging.getLogger("NET_SCAN")

_SCANNER_SIGNATURES = (
    "Bad request version",
    "Bad HTTP/0.9 request",
    "Invalid HTTP version",
)

_LOG_SCANNERS = os.getenv("DASH_LOG_SCANNERS", "true").lower() == "true"


class _WerkzeugScannerFilter(logging.Filter):
    """Intercetta i messaggi werkzeug da scanner/bot e li reinvia a NET_SCAN."""
    def filter(self, record):
        msg = record.getMessage()
        if any(s in msg for s in _SCANNER_SIGNATURES):
            if _LOG_SCANNERS:
                _net_log.warning(_lc_tag("NET_SCAN", msg))
            return False
        return True


_wz = logging.getLogger("werkzeug")
_wz.setLevel(logging.ERROR)
_wz.addFilter(_WerkzeugScannerFilter())


def create_app():
    app = Flask(__name__)

    app.secret_key = os.getenv("DASH_SECRET_KEY") or os.urandom(24)

    DASH_USER     = os.getenv("DASH_USER", "admin")
    DASH_PASSWORD = os.getenv("DASH_PASSWORD", "changeme")

    DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "cache.db")

    # ── Helper ─────────────────────────────────────────────────────────
    def login_required(f):
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            if not session.get("logged_in"):
                return redirect(url_for("login"))
            return f(*args, **kwargs)
        return wrapper

    def query_db(sql, args=()):
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = [dict(r) for r in conn.execute(sql, args).fetchall()]
        conn.close()
        return rows

    # ── Login / Logout ────────────────────────────────────────────
    @app.route("/login", methods=["GET", "POST"])
    def login():
        error = None
        if request.method == "POST":
            user = request.form.get("username", "").strip()
            pwd  = request.form.get("password", "")
            if user == DASH_USER and pwd == DASH_PASSWORD:
                session["logged_in"] = True
                return redirect(url_for("index"))
            error = "Credenziali errate."
        return render_template("login.html", error=error)

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    # ── Route protette ─────────────────────────────────────────────
    @app.route("/")
    @login_required
    def index():
        stats = query_db("""
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN is_valid=1 THEN 1 ELSE 0 END) AS valid,
                SUM(CASE WHEN is_valid=0 THEN 1 ELSE 0 END) AS invalid,
                SUM(hit_count) AS hits
            FROM song_cache
        """)[0]
        aliases_count = query_db("SELECT COUNT(*) as c FROM query_aliases")[0]["c"]
        return render_template("index.html", stats=stats, aliases_count=aliases_count)

    @app.route("/api/songs")
    @login_required
    def api_songs():
        search = request.args.get("q", "").strip()
        source = request.args.get("source", "")
        valid  = request.args.get("valid", "")
        sort   = request.args.get("sort", "hit_count")
        order  = request.args.get("order", "desc")

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
        rows = query_db(
            f"SELECT * FROM song_cache {where} ORDER BY {sort} {order}", params
        )
        return jsonify(rows)

    @app.route("/api/aliases")
    @login_required
    def api_aliases():
        rows = query_db("""
            SELECT qa.id, qa.query_raw, qa.cache_id,
                   sc.title, sc.artist
            FROM query_aliases qa
            LEFT JOIN song_cache sc ON sc.id = qa.cache_id
            ORDER BY qa.id DESC
        """)
        return jsonify(rows)

    @app.route("/api/delete/<int:row_id>", methods=["DELETE"])
    @login_required
    def delete_song(row_id):
        conn = sqlite3.connect(DB_PATH)
        conn.execute("DELETE FROM song_cache WHERE id = ?", (row_id,))
        conn.commit()
        conn.close()
        return jsonify({"ok": True})

    return app


# ── Avvio standalone ──────────────────────────────────────────────────────
if __name__ == "__main__":
    socket  = os.getenv("DASHBOARD_SOCKET", "0.0.0.0:5000")
    host, port = socket.rsplit(":", 1)
    flask_app = create_app()
    flask_app.run(host=host, port=int(port), debug=False)
