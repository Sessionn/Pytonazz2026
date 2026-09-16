"""Read models. The facade supplies the transaction/lock owner."""

def list_song_rows(cursor_factory,
    search: str = "",
    source: str = "",
    valid: str = "",
    sort: str = "created_at",
    order: str = "DESC",
) -> list[dict]:
    allowed = {"hit_count", "created_at", "last_used", "title", "artist", "query_raw", "id"}
    sort = sort if sort in allowed else "created_at"
    order = "DESC" if str(order).upper() == "DESC" else "ASC"

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
    with cursor_factory() as cur:
        rows = cur.execute(
            f"SELECT * FROM song_cache {where} ORDER BY {sort} {order}",
            params,
        ).fetchall()
    return [dict(r) for r in rows]


def list_alias_rows(cursor_factory) -> list[dict]:
    with cursor_factory() as cur:
        return [dict(row) for row in cur.execute(SELECTS["aliases"] + " ORDER BY qa.id DESC").fetchall()]


def list_track_rows(cursor_factory) -> list[dict]:
    with cursor_factory() as cur:
        return [dict(row) for row in cur.execute(SELECTS["tracks"] + " ORDER BY t.id DESC").fetchall()]


def list_source_rows(cursor_factory) -> list[dict]:
    with cursor_factory() as cur:
        return [dict(row) for row in cur.execute(SELECTS["sources"] + " ORDER BY s.id DESC").fetchall()]


def list_query_rows(cursor_factory) -> list[dict]:
    with cursor_factory() as cur:
        return [dict(row) for row in cur.execute(SELECTS["queries"] + " ORDER BY q.id DESC").fetchall()]


SELECTS = {
    "songs": """
SELECT * FROM song_cache
    """,
    "aliases": """
SELECT qa.id, qa.query_raw, qa.cache_id,
                   qa.alias_type, sc.title, sc.artist, sc.spotify_url, sc.webpage_url
              FROM query_aliases qa
              LEFT JOIN song_cache sc ON sc.id = qa.cache_id
    """,
    "tracks": """
SELECT
                t.id,
                t.canonical_title,
                t.canonical_artist,
                t.normalized_query,
                t.created_at,
                t.updated_at,
                COALESCE(s.total, 0) AS source_count,
                COALESCE(q.total, 0) AS query_count
            FROM cache_tracks t
            LEFT JOIN (SELECT track_id, COUNT(*) AS total FROM cache_sources GROUP BY track_id) s ON s.track_id = t.id
            LEFT JOIN (SELECT track_id, COUNT(*) AS total FROM cache_queries WHERE is_active = 1 GROUP BY track_id) q ON q.track_id = t.id
    """,
    "sources": """
SELECT
                s.id,
                s.track_id,
                t.canonical_title,
                t.canonical_artist,
                s.source,
                s.resolved_title,
                s.resolved_artist,
                s.webpage_url,
                s.stream_expires_at,
                s.spotify_url,
                s.duration,
                s.thumbnail,
                s.thumbnail_source,
                s.thumbnail_confidence,
                s.is_valid,
                s.hit_count,
                s.created_at,
                s.last_used
            FROM cache_sources s
            JOIN cache_tracks t ON t.id = s.track_id
    """,
    "queries": """
SELECT
                q.id,
                q.track_id,
                q.source_id,
                q.query_raw,
                q.query_norm,
                q.alias_type,
                q.match_confidence AS confidence,
                q.is_active,
                q.hit_count,
                q.first_seen AS created_at,
                q.last_seen,
                t.canonical_title,
                t.canonical_artist,
                s.source,
                s.spotify_url,
                s.webpage_url
            FROM cache_queries q
            JOIN cache_tracks t ON t.id = q.track_id
            JOIN cache_sources s ON s.id = q.source_id
    """,
}


def list_page(cursor_factory, kind, **options):
    from .pagination import read_page

    with cursor_factory() as cur:
        return read_page(cur, SELECTS[kind], **options)
