"""
core/source_resolver/resolver_text.py
---------------------------------------
Text-query helpers extracted from ``core/source_resolver/__init__.py``.

Contains candidate-selection logic used by ``resolve_choices`` when
processing yt-dlp results for a textual search.
"""
from __future__ import annotations

from core.source_resolver.scoring import (
    _is_music_video,
    _is_variant,
    _query_requests_variant,
    _jaccard_tokens,
    _normalize_for_sim,
)


def _candidate_query_similarity(query: str, candidate) -> float:
    """Return Jaccard similarity between *query* and a yt-dlp candidate track."""
    q_norm      = _normalize_for_sim(query)
    if not q_norm:
        return 0.0
    title_norm  = _normalize_for_sim(getattr(candidate, "title",  "") or "")
    artist_norm = _normalize_for_sim(getattr(candidate, "artist", "") or "")
    full_norm   = (f"{title_norm} {artist_norm}").strip()
    return max(
        _jaccard_tokens(q_norm, title_norm),
        _jaccard_tokens(q_norm, full_norm),
    )


def _prefer_studio(candidates: list, sp_dur: float = 0, user_query: str = "") -> object:
    """
    Choose the best candidate from a yt-dlp result list.

    Prefers studio recordings over music videos and live/acoustic variants,
    unless the user explicitly asked for a variant.
    Falls back to duration proximity when a Spotify duration hint is provided.
    """
    if not candidates:
        return None
    non_mv = [c for c in candidates if not _is_music_video(c.title, getattr(c, "artist", ""))]
    pool   = non_mv if non_mv else candidates
    if not _query_requests_variant(user_query):
        studio = [c for c in pool if not _is_variant(c.title)]
        pool   = studio if studio else pool
    if len(pool) == 1:
        return pool[0]

    if (user_query or "").strip():
        if sp_dur > 0:
            return max(
                pool,
                key=lambda c: (
                    _candidate_query_similarity(user_query, c),
                    -(abs(c.duration - sp_dur) if c.duration else 9999),
                ),
            )
        return max(pool, key=lambda c: _candidate_query_similarity(user_query, c))

    if sp_dur > 0:
        pool.sort(key=lambda c: abs(c.duration - sp_dur) if c.duration else 9999)
    return pool[0]
