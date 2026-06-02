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
    _normalize_for_sim,
    _jaccard_tokens,
    _query_artist_signal,
)

log = logging.getLogger("pitonazz.resolver")

# ── Concurrency constants ─────────────────────────────────────────────────────

_SPOTIFY_BATCH_CONCURRENCY     = 6
_SPOTIFY_BATCH_MAX_CONCURRENCY = 10


# ── Spotify client factory ────────────────────────────────────────────────────

def _spotify_client() -> Optional[object]:
    """Return an authenticated spotipy.Spotify instance, or None if unavailable."""
    if not Config.SPOTIFY_CLIENT_ID or not Config.SPOTIFY_CLIENT_SECRET:
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
    """Rank Spotify search items with token-aware scoring plus soft typo fallback.

    Pure character similarity is too permissive for short or noisy queries and
    can overvalue strings that merely "look similar". Here we keep a small
    character component for typo tolerance, but base the ranking primarily on
    token overlap and artist signal.
    """
    q_norm = _normalize_for_sim(query)
    name = _spotify_item_name(item)
    artists = _spotify_item_artists(item)
    name_norm = _normalize_for_sim(name)
    full_norm = _normalize_for_sim(f"{name} {artists}".strip())

    if not q_norm:
        return 0.0
    if not full_norm:
        return _str_sim(q_norm, name_norm)

    title_jaccard = _jaccard_tokens(q_norm, name_norm)
    full_jaccard = _jaccard_tokens(q_norm, full_norm)
    title_str = _str_sim(q_norm, name_norm)
    full_str = _str_sim(q_norm, full_norm)
    artist_sim, artist_hint_present = _query_artist_signal(query, artists)

    score = max(
        (title_jaccard * 0.70) + (title_str * 0.30),
        (full_jaccard * 0.62) + (full_str * 0.23) + ((artist_sim * 0.15) if artist_hint_present else 0.0),
    )

    if q_norm == name_norm or q_norm == full_norm:
        score += 0.05

    if not _query_requests_variant(query) and _is_variant(name):
        score -= 0.12

    return max(0.0, min(1.0, score))


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
