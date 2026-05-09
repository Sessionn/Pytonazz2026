"""
core/source_resolver/spotify.py
---------------------------------
Spotify client factory and item-level helpers used by SourceResolver.
Imports scoring helpers from source_resolver.scoring to avoid duplication.
"""
from __future__ import annotations

import logging
from typing import Optional

from config import Config
from core.log_colors import tag
from core.source_resolver.scoring import (
    _str_sim,
    _is_variant,
    _query_requests_variant,
)

log = logging.getLogger("pitonazz.resolver")

# ── Concurrency constants ─────────────────────────────────────────────────────

_SPOTIFY_BATCH_CONCURRENCY     = 6
_SPOTIFY_BATCH_MAX_CONCURRENCY = 10


# ── Spotify client factory ────────────────────────────────────────────────────

def _spotify_client() -> Optional[object]:
    """Return an authenticated spotipy.Spotify instance, or None if unavailable."""
    if not Config.SPOTIFY_CLIENT_ID:
        return None
    try:
        import spotipy
        from spotipy.oauth2 import SpotifyClientCredentials
        logging.getLogger("spotipy.client").setLevel(logging.CRITICAL)
        return spotipy.Spotify(auth_manager=SpotifyClientCredentials(
            client_id=Config.SPOTIFY_CLIENT_ID,
            client_secret=Config.SPOTIFY_CLIENT_SECRET,
        ))
    except ImportError:
        log.error(tag("ERR", "spotipy non installato"))
        return None


# ── Spotify item helpers ──────────────────────────────────────────────────────

def _spotify_item_name(item: dict) -> str:
    return (item or {}).get("name", "")


def _spotify_item_popularity(item: dict) -> int:
    try:
        return int((item or {}).get("popularity") or 0)
    except (TypeError, ValueError):
        return 0


def _spotify_item_artists(item: dict) -> str:
    return ", ".join(a.get("name", "") for a in (item or {}).get("artists", []) if a.get("name"))


def _spotify_item_query_similarity(query: str, item: dict) -> float:
    name    = _spotify_item_name(item)
    artists = _spotify_item_artists(item)
    if not artists:
        return _str_sim(query, name)
    sim_name = _str_sim(query, name)
    sim_full = _str_sim(query, f"{name} {artists}")
    return max(sim_name, sim_full)


def _choose_spotify_track_item(query: str, items: list[dict]) -> Optional[dict]:
    """Pick the best Spotify track item for *query* from a list of candidates.

    Returns None when items is empty. Selection uses query similarity and
    popularity, preferring non-variant tracks unless the query requests a
    variant (live, acoustic, remix, ...).

    If the user did NOT request a variant (live, acoustic, remix…) the pool is
    narrowed to non-variant tracks first, which prevents an unexpected live
    recording from being selected over a studio version.
    """
    if not items:
        return None
    wants_variant = _query_requests_variant(query)
    pool = items
    if not wants_variant:
        non_variant = [x for x in items if not _is_variant(_spotify_item_name(x))]
        if non_variant:
            pool = non_variant
    return max(
        pool,
        key=lambda x: (_spotify_item_query_similarity(query, x), _spotify_item_popularity(x)),
    )
