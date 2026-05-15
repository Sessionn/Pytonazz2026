import sqlite3
import os
import logging
import functools
import re
from flask import (
    Flask, render_template, jsonify, request,
    session, redirect, url_for
)
from dotenv import load_dotenv

# Carica .env dalla root del progetto
_ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", ".env")
load_dotenv(_ENV_PATH)

try:
    from core.log_colors import tag as _lc_tag
except ImportError:
    def _lc_tag(label: str, msg: str) -> str:  # type: ignore
        return f"{label}  {msg}"


_net_log = logging.getLogger("NET_SCAN")

_SCANNER_SIGNATURES = (
    "Bad request version",
    "Bad HTTP/0.9 request",
    "Invalid HTTP version",
)

_LOG_SCANNERS = os.getenv("DASH_LOG_SCANNERS", "true").lower() == "true"

_RE_SPOTIFY = re.compile(
    r"https?://open\.spotify\.com/(track|album|playlist)/([A-Za-z0-9]+)",
    re.IGNORECASE,
)


def _extract_spotify_id(url: str) -> str:
    """Normalizza un link Spotify rimuovendo i parametri query (?si=...)."""
    m = _RE_SPOTIFY.search(url.strip())
    if not m:
        return url.strip()
    return f"https://open.spotify.com/{m.group(1)}/{m.group(2)}"


class _WerkzeugScannerFilter(logging.Filter):
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


import hashlib

def _hash(query: str) -> str:
    return hashlib.sha256(query.strip().lower().encode()).hexdigest()


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

    def get_conn():
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def query_db(sql, args=()):
        conn = get_conn()
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
        # Valori iniziali per il template (poi aggiornati in real-time via /api/stats)
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

    # ── API: statistiche live ──────────────────────────────────────
    @app.route("/api/stats")
    @login_required
    def api_stats():
        """
        Ritorna le stat card in JSON per aggiornamento real-time lato JS.
        Leggero: una sola query aggregata + una COUNT su query_aliases.
        """
        row = query_db("""
            SELECT
                COUNT(*)                                           AS total,
                SUM(CASE WHEN is_valid=1 THEN 1 ELSE 0 END)       AS valid,
                SUM(CASE WHEN is_valid=0 THEN 1 ELSE 0 END)       AS invalid,
                COALESCE(SUM(hit_count), 0)                        AS hits
            FROM song_cache
        """)[0]
        aliases = query_db("SELECT COUNT(*) AS c FROM query_aliases")[0]["c"]
        return jsonify({
            "total":   row["total"]   or 0,
            "valid":   row["valid"]   or 0,
            "invalid": row["invalid"] or 0,
            "hits":    row["hits"]    or 0,
            "aliases": aliases,
        })

    # ── API: songs ─────────────────────────────────────────────────
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

    # ── API: aliases ───────────────────────────────────────────────
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

    # ── API: associa link Spotify a entry esistente ────────────────
    @app.route("/api/associate", methods=["POST"])
    @login_required
    def api_associate():
        """
        Riceve un link Spotify (spotify_url) e cerca nel DB una entry
        compatibile per titolo+artista o webpage_url.

        Comportamento (in ordine di priorita'):
          1. Se spotify_url e' gia' presente in song_cache -> no-op, ritorna
             {action: 'already_set', cache_id}.
          2. Cerca entry con titolo+artista simili (LIKE normalizzato).
          3. In ogni caso aggiorna spotify_url sulla entry trovata e
             inserisce/aggiorna il link come alias in query_aliases.

        Body JSON atteso:
            { "spotify_url": "https://open.spotify.com/track/...",
              "title": "...",       # opzionale, migliora il match
              "artist": "..." }     # opzionale

        Risposta:
            { "ok": true/false, "action": "...", "cache_id": int|null }
        """
        data = request.get_json(force=True, silent=True) or {}
        raw_url = (data.get("spotify_url") or "").strip()
        title   = (data.get("title")  or "").strip().lower()
        artist  = (data.get("artist") or "").strip().lower()

        if not raw_url or not _RE_SPOTIFY.search(raw_url):
            return jsonify({"ok": False, "action": "invalid_url", "cache_id": None}), 400

        spotify_url = _extract_spotify_id(raw_url)
        h_spotify   = _hash(spotify_url)

        conn = get_conn()
        try:
            cur = conn.cursor()

            # 1. Gia' presente come spotify_url nella song_cache?
            cur.execute(
                "SELECT id FROM song_cache WHERE spotify_url = ? AND is_valid = 1 LIMIT 1",
                (spotify_url,)
            )
            row = cur.fetchone()
            if row:
                conn.close()
                return jsonify({"ok": True, "action": "already_set", "cache_id": row["id"]})

            # 2. Gia' presente come alias?
            cur.execute(
                "SELECT cache_id FROM query_aliases WHERE query_hash = ? LIMIT 1",
                (h_spotify,)
            )
            alias_row = cur.fetchone()
            if alias_row:
                conn.close()
                return jsonify({"ok": True, "action": "already_alias", "cache_id": alias_row["cache_id"]})

            # 3. Cerca per titolo+artista (match LIKE normalizzato)
            target = None
            if title:
                filters, params = [], []
                filters.append("LOWER(title) LIKE ?")
                params.append(f"%{title}%")
                if artist:
                    filters.append("LOWER(artist) LIKE ?")
                    params.append(f"%{artist}%")
                cur.execute(
                    f"SELECT id FROM song_cache WHERE {' AND '.join(filters)} AND is_valid=1 LIMIT 1",
                    params
                )
                target = cur.fetchone()

            if target is None:
                conn.close()
                return jsonify({"ok": False, "action": "not_found", "cache_id": None})

            cache_id = target["id"]

            # Aggiorna spotify_url sulla entry canonical (solo se mancava)
            cur.execute(
                "UPDATE song_cache SET spotify_url = ? WHERE id = ? AND (spotify_url IS NULL OR spotify_url = '')",
                (spotify_url, cache_id)
            )

            # Registra il link Spotify come alias
            cur.execute(
                """
                INSERT INTO query_aliases (query_hash, query_raw, cache_id)
                VALUES (?, ?, ?)
                ON CONFLICT(query_hash) DO UPDATE SET
                    query_raw = excluded.query_raw,
                    cache_id  = excluded.cache_id
                """,
                (h_spotify, spotify_url, cache_id)
            )
            conn.commit()
        finally:
            conn.close()

        return jsonify({"ok": True, "action": "associated", "cache_id": cache_id})

    # ── API: delete ────────────────────────────────────────────────
    @app.route("/api/delete/<int:row_id>", methods=["DELETE"])
    @login_required
    def delete_song(row_id):
        conn = get_conn()
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
