import sqlite3
import os
import logging
from flask import Flask, render_template, jsonify, request


def create_app():
    app = Flask(__name__)

    # ── Silenzia completamente werkzeug (log HTTP requests) ──────────────────
    logging.getLogger("werkzeug").setLevel(logging.ERROR)

    DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "cache.db")

    def query_db(sql, args=()):
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = [dict(r) for r in conn.execute(sql, args).fetchall()]
        conn.close()
        return rows

    @app.route("/")
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
    def delete_song(row_id):
        conn = sqlite3.connect(DB_PATH)
        conn.execute("DELETE FROM song_cache WHERE id = ?", (row_id,))
        conn.commit()
        conn.close()
        return jsonify({"ok": True})

    return app


# ── Avvio standalone (test locale senza bot) ─────────────────────────────────
if __name__ == "__main__":
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    flask_app = create_app()
    flask_app.run(host="0.0.0.0", port=5000, debug=False)