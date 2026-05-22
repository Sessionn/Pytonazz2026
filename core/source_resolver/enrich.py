"""
core/source_resolver/enrich.py
---------------------------------
Spotify metadata-enrichment logic extracted from
``core/source_resolver/__init__.py``.

Contains:
- ``_should_enrich_with_spotify`` (module-level predicate)
- ``_short_log_text``             (module-level log helper)
- ``_EnrichMixin``                (class mixin inherited by SourceResolver)
"""
from __future__ import annotations

import logging
import time
from typing import Optional

from config import Config
from core.log_colors import tag, b, hi, dim, _BGRN, _BYEL, _BRED
from core.source_resolver.scoring import (
    _SPOTIFY_RETRY_BASE_DELAY_SECONDS,
    _compute_enrich_confidence,
)
from core.source_resolver.spotify import (
    _choose_spotify_track_item,
)

log        = logging.getLogger("pitonazz.resolver")
enrich_log = logging.getLogger("pitonazz.spotify_enrich")


# ── Module-level helpers ──────────────────────────────────────────────────────

def _should_enrich_with_spotify(query: str, tracks: list) -> bool:
    """Return True when Spotify enrichment should be attempted for *tracks*."""
    if not Config.SPOTIFY_CLIENT_ID:
        return False
    if not tracks:
        return False
    q = (query or "").strip()
    if not q:
        return False
    from core.source_resolver.resolver_url import _is_url_like_query  # noqa: PLC0415
    if _is_url_like_query(q):
        return False
    return True


def _short_log_text(value: str, limit: int = 48) -> str:
    """Truncate *value* to *limit* chars for compact log output."""
    text = (value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


# ── Enrich mixin ──────────────────────────────────────────────────────────────

class _EnrichMixin:
    """
    Mixin providing Spotify metadata-enrichment class methods.

    Inherited by ``SourceResolver``.  Methods use ``cls._sp_client()`` which
    is also defined on ``SourceResolver`` (via ``_sp_client`` in __init__.py).
    """

    @classmethod
    def _sp_search_track_meta(cls, query: str) -> Optional[dict]:
        """Search Spotify for *query* and return track metadata, or None."""
        for attempt in range(3):
            sp = cls._sp_client()
            if not sp:
                return None
            try:
                res   = sp.search(q=query, type="track", limit=5)
                items = res.get("tracks", {}).get("items", [])
                if not items:
                    return None
                t = _choose_spotify_track_item(query, items)
                if not t:
                    return None
                images = t.get("album", {}).get("images", [])
                return {
                    "title":       t.get("name", ""),
                    "thumbnail":   images[0]["url"] if images else "",
                    "duration":    int((t.get("duration_ms") or 0) / 1000),
                    "artist":      ", ".join(a["name"] for a in t.get("artists", [])),
                    "spotify_url": t.get("external_urls", {}).get("spotify", ""),
                }
            except Exception as e:
                cls._sp = None  # type: ignore[attr-defined]
                if attempt < 2:
                    time.sleep(0.4 * (attempt + 1))
                    continue
                log.debug(tag("SPOTIFY", f"{b(query)}  fallito dopo 3 tentativi: {e}"))
        return None

    @classmethod
    def _sp_search_track_meta_for_track(
        cls, original_query: str, track
    ) -> tuple[Optional[dict], Optional[dict]]:
        """
        Search Spotify for the best match for *track* and return
        ``(meta_dict, score_dict)`` or ``(None, None)`` on failure.
        """
        search_parts = [original_query]
        if track.title:
            search_parts.append(track.title)
        if track.artist:
            search_parts.append(track.artist)
        search_query = " ".join(x.strip() for x in search_parts if x and x.strip())

        for attempt in range(3):
            sp = cls._sp_client()
            if not sp:
                return None, None
            try:
                res   = sp.search(q=search_query, type="track", limit=5)
                items = res.get("tracks", {}).get("items", [])
                if not items:
                    return None, None

                best_meta  = None
                best_score = None
                for item in items:
                    images = item.get("album", {}).get("images", [])
                    meta = {
                        "title":       item.get("name", ""),
                        "thumbnail":   images[0]["url"] if images else "",
                        "duration":    int((item.get("duration_ms") or 0) / 1000),
                        "artist":      ", ".join(a["name"] for a in item.get("artists", [])),
                        "spotify_url": item.get("external_urls", {}).get("spotify", ""),
                    }
                    score = _compute_enrich_confidence(original_query, track, meta)
                    if best_score is None or score["confidence"] > best_score["confidence"]:
                        best_meta  = meta
                        best_score = score

                return best_meta, best_score
            except Exception as e:
                cls._sp = None  # type: ignore[attr-defined]
                if attempt < 2:
                    time.sleep(_SPOTIFY_RETRY_BASE_DELAY_SECONDS * (attempt + 1))
                    continue
                enrich_log.debug(tag("SPOTIFY", f"{b(search_query)}  fallito dopo 3 tentativi: {e}"))
        return None, None

    @classmethod
    def _enrich_with_spotify(cls, tracks: list, original_query: str) -> list:
        """Enrich *tracks* in-place with Spotify metadata when confidence is high."""
        if not Config.SPOTIFY_CLIENT_ID:
            return tracks
        for idx, track in enumerate(tracks, start=1):
            try:
                meta, score = cls._sp_search_track_meta_for_track(original_query, track)
            except Exception as e:
                enrich_log.debug(tag("SPOTIFY", f"enrich skip: {e}"))
                continue

            if not meta or not score:
                enrich_log.info(tag("SPOTIFY", f"enrich[{idx}]  {b(track.title)}  skip  reason=no_meta"))
                continue
            if not any(meta.get(k) for k in ("thumbnail", "title", "artist", "spotify_url")):
                enrich_log.info(tag("SPOTIFY", f"enrich[{idx}]  {b(track.title)}  skip  reason=empty_meta"))
                continue

            decision              = score["decision"]
            sp_title              = meta.get("title", "")
            sp_artist             = meta.get("artist", "")
            yt_title_before       = track.title
            apply_cover_and_spotify = decision in ("full", "cover_only")

            if apply_cover_and_spotify and meta.get("spotify_url"):
                track.spotify_url = meta["spotify_url"]
            if apply_cover_and_spotify and meta.get("thumbnail"):
                track.thumbnail = meta["thumbnail"]
            if decision == "full":
                if sp_title:
                    track.title = sp_title
                if sp_artist:
                    track.artist = sp_artist

            _dc      = _BGRN if decision == "full" else (_BYEL if decision == "cover_only" else _BRED)
            conf_pct = int(score["confidence"]       * 100)
            q_pct    = int(score["query_sim"]         * 100)
            yt_pct   = int(score["yt_sim"]            * 100)
            art_pct  = int(score["artist_sim"]        * 100)
            dur_pct  = int(score["duration_sim"]      * 100)
            junk_pct = int(score["variant_penalty"]   * 100)
            nm_pct   = int(score["non_music_penalty"] * 100)

            _sp_label = b(_short_log_text(sp_title)) + (
                f"  {_short_log_text(sp_artist, 24)}" if sp_artist else ""
            )
            _yt_label = (
                dim(_short_log_text(yt_title_before))
                if decision == "full"
                else b(_short_log_text(yt_title_before))
            )
            enrich_log.info(tag(
                "SPOTIFY",
                f"enrich[{idx}]  {hi(decision, _dc)}  {hi(f'{conf_pct}%', _dc)}"
                f"  {_yt_label}  →  {_sp_label}",
            ))
            enrich_log.debug(tag(
                "SPOTIFY",
                f"  scores  q={q_pct}%  yt={yt_pct}%  art={art_pct}%"
                f"  dur={dur_pct}%  junk={junk_pct}%  nm={nm_pct}%"
                f"  reason={dim(score['reason'])}",
            ))
        return tracks
