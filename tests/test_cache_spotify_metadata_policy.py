"""
tests/test_cache_spotify_metadata_policy.py

Esegui dalla root del progetto con:
    python tests/test_cache_spotify_metadata_policy.py
"""

import os
import sqlite3
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
import core.cache_db as db


def _insert_spotify_duplicate(conn: sqlite3.Connection, canonical_query: str, title: str, artist: str, spotify_url: str) -> None:
    now = int(time.time())
    conn.execute(
        """
        INSERT INTO cache_tracks
            (canonical_query_hash, canonical_query_raw, normalized_query,
             canonical_title, canonical_artist, created_at, updated_at, is_active)
        VALUES (?, ?, ?, ?, ?, ?, ?, 1)
        """,
        (
            db._hash(canonical_query),
            canonical_query,
            db._normalize_key(canonical_query),
            title,
            artist,
            now,
            now,
        ),
    )
    track_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    conn.execute(
        """
        INSERT INTO cache_sources
            (track_id, webpage_url, stream_url, stream_expires_at, last_stream_check,
             source, resolved_title, resolved_artist, duration, thumbnail,
             thumbnail_source, thumbnail_confidence, spotify_url, source_confidence,
             created_at, last_used, hit_count, is_valid)
        VALUES (?, ?, '', 0, 0, ?, ?, ?, ?, ?, ?, ?, ?, 1.0, ?, ?, 1, 1)
        """,
        (
            track_id,
            "https://youtube.com/watch?v=SPOTIFY_RESULT",
            "spotify",
            title,
            artist,
            117,
            "https://i.scdn.co/image/example",
            "spotify",
            0.95,
            spotify_url,
            now,
            now,
        ),
    )
    source_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    conn.execute(
        """
        INSERT INTO cache_queries
            (query_hash, query_raw, query_norm, track_id, source_id,
             alias_type, match_method, match_confidence, first_seen, last_seen, hit_count, is_confirmed, is_active)
        VALUES (?, ?, ?, ?, ?, 'spotify', 'spotify_url', 1.0, ?, ?, 1, 1, 1)
        """,
        (
            db._hash(spotify_url),
            spotify_url,
            db._normalize_key(spotify_url),
            track_id,
            source_id,
            now,
            now,
        ),
    )


def _run_case(youtube_title: str, expected_title: str, expected_artist: str) -> None:
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()

    Config.DB_PATH = tmp.name
    Config.CACHE_TTL_DAYS = 30
    Config.CACHE_MAX_ENTRIES = 500
    db.init_db(db_path=tmp.name, enabled=True)

    youtube_track = {
        "title": youtube_title,
        "artist": "G.MINEIRO",
        "webpage_url": "https://youtube.com/watch?v=TEXT_RESULT",
        "source": "youtube",
        "duration": 117,
        "thumbnail": "https://i.ytimg.com/vi/TEXT_RESULT/hqdefault.jpg",
        "spotify_url": "",
        "thumbnail_source": "youtube",
        "thumbnail_confidence": 0.45,
    }
    db.put('G.Mineiro - "Splinter Cell"', youtube_track)

    conn = sqlite3.connect(tmp.name)
    _insert_spotify_duplicate(
        conn,
        "Splinter Cell G.Mineiro Flatpearl Jiz Succo",
        "Splinter Cell",
        "G.Mineiro, Flatpearl, Jiz, Succo",
        "https://open.spotify.com/track/3KsGBiWVuybY3Zm7LDKuqK",
    )
    conn.commit()
    conn.close()

    result = db.reconcile_duplicate_sources()
    assert result["merged_sources"] == 1, result

    row = db.get('G.Mineiro - "Splinter Cell"')
    assert row is not None
    assert row["title"] == expected_title, row
    assert row["artist"] == expected_artist, row

    db._close()
    try:
        os.unlink(tmp.name)
    except PermissionError:
        pass


_run_case(
    'G.Mineiro - "Splinter Cell" prod. Flat, Succo, Jiz (Visualizer)',
    'G.Mineiro - "Splinter Cell" prod. Flat, Succo, Jiz (Visualizer)',
    "G.MINEIRO",
)
_run_case(
    'Splinter Cell slowed + reverb',
    "Splinter Cell",
    "G.Mineiro, Flatpearl, Jiz, Succo",
)

print("OK: spotify metadata policy for youtube variants")
