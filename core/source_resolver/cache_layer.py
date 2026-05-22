"""
core/source_resolver/cache_layer.py
-------------------------------------
Two responsibilities:

1. **Module-level query-cache helpers** (`_get_query_cache`, `_cache_hit_to_track`):
   Thin adapter that bridges the functional `cache_db` API to the
   `lookup` / `store` interface used by SourceResolver.

2. **`_CacheLayerMixin`**: in-memory LRU caches for yt-dlp query results
   and stream URLs.  SourceResolver inherits this mixin.
"""
from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING, Optional

from config import Config
from core.log_colors import tag, b

if TYPE_CHECKING:
    pass  # TrackInfo imported lazily to avoid circular references

# ── Loggers ───────────────────────────────────────────────────────────────────

import logging
log = logging.getLogger("pitonazz.resolver")

# ── Query-DB cache singleton ──────────────────────────────────────────────────

_qc_instance: Optional[object] = None
_qc_lock = threading.Lock()


def _get_query_cache():
    """Return the singleton QueryCache adapter, or None if cache is disabled."""
    global _qc_instance
    if not Config.CACHE_ENABLED:
        return None
    if _qc_instance is None:
        with _qc_lock:
            if _qc_instance is None:
                try:
                    from core.cache_db import get as _cache_get, put as _cache_put

                    class _Adapter:
                        """Adapts the functional cache_db API to lookup/store."""
                        @staticmethod
                        def lookup(query: str) -> Optional[dict]:
                            return _cache_get(query)

                        @staticmethod
                        def store(query: str, track) -> None:
                            _cache_put(query, track)

                        @staticmethod
                        def link_spotify(sp_url: str, key: str, variant: str) -> None:
                            pass  # future extension

                    _qc_instance = _Adapter()
                except Exception as e:
                    log.warning(tag("CACHE", f"impossibile inizializzare QueryCache: {e}"))
                    _qc_instance = None
    return _qc_instance


def _cache_hit_to_track(
    hit: dict, requester: str, requester_id: int, stream_url: str = ""
):
    """Convert a cache DB row into a TrackInfo ready for playback."""
    # Import here to avoid circular import; TrackInfo lives in __init__.py
    from core.source_resolver import TrackInfo  # noqa: PLC0415
    return TrackInfo(
        title        = hit.get("title") or "Senza titolo",
        webpage_url  = hit.get("webpage_url") or "",
        duration     = int(hit.get("duration") or 0),
        thumbnail    = hit.get("thumbnail") or "",
        requester    = requester,
        requester_id = requester_id,
        source       = hit.get("source") or "youtube",
        stream_url   = stream_url,
        artist       = hit.get("artist") or "",
        spotify_url  = hit.get("spotify_url") or "",
    )


# ── In-memory cache mixin ─────────────────────────────────────────────────────

from core.source_resolver.ytdlp import (
    _YTDLP_QUERY_CACHE_TTL,
    _YTDLP_QUERY_CACHE_MAX,
    _STREAM_URL_CACHE_TTL,
    _STREAM_URL_CACHE_MAX,
)


class _CacheLayerMixin:
    """
    In-memory LRU caches for yt-dlp results and stream URLs.

    Class-level attributes are shared across all class-method calls, which
    is the existing behaviour preserved from the original SourceResolver.
    """

    _cache_lock: threading.Lock = threading.Lock()
    _ytdlp_query_cache: dict = {}
    _stream_url_cache:  dict = {}

    # ── Pruning ───────────────────────────────────────────────────────────────

    @classmethod
    def _cache_prune_locked(cls, cache: dict, max_size: int) -> None:
        now = time.monotonic()
        expired_keys = [k for k, (exp, _) in cache.items() if exp <= now]
        for key in expired_keys:
            cache.pop(key, None)
        while len(cache) > max_size:
            cache.pop(next(iter(cache)), None)

    # ── yt-dlp query cache ────────────────────────────────────────────────────

    @classmethod
    def _get_cached_ytdlp_results(cls, key: tuple) -> Optional[list]:
        now = time.monotonic()
        with cls._cache_lock:
            cached = cls._ytdlp_query_cache.get(key)
            if not cached:
                return None
            exp, tracks = cached
            if exp <= now:
                cls._ytdlp_query_cache.pop(key, None)
                return None
            # Touch (LRU)
            cls._ytdlp_query_cache.pop(key, None)
            cls._ytdlp_query_cache[key] = (exp, tracks)
            from core.source_resolver import _clone_track  # noqa: PLC0415
            return [_clone_track(t) for t in tracks]

    @classmethod
    def _set_cached_ytdlp_results(cls, key: tuple, tracks: list) -> None:
        with cls._cache_lock:
            from core.source_resolver import _clone_track  # noqa: PLC0415
            cls._ytdlp_query_cache.pop(key, None)
            cls._ytdlp_query_cache[key] = (
                time.monotonic() + _YTDLP_QUERY_CACHE_TTL,
                [_clone_track(t) for t in tracks],
            )
            cls._cache_prune_locked(cls._ytdlp_query_cache, _YTDLP_QUERY_CACHE_MAX)

    # ── Stream URL cache ──────────────────────────────────────────────────────

    @classmethod
    def _get_cached_stream_url(cls, webpage_url: str) -> Optional[str]:
        now = time.monotonic()
        with cls._cache_lock:
            cached = cls._stream_url_cache.get(webpage_url)
            if not cached:
                return None
            exp, url = cached
            if exp <= now:
                cls._stream_url_cache.pop(webpage_url, None)
                return None
            # Touch (LRU)
            cls._stream_url_cache.pop(webpage_url, None)
            cls._stream_url_cache[webpage_url] = (exp, url)
            return url

    @classmethod
    def _set_cached_stream_url(cls, webpage_url: str, stream_url: str) -> None:
        with cls._cache_lock:
            cls._stream_url_cache.pop(webpage_url, None)
            cls._stream_url_cache[webpage_url] = (
                time.monotonic() + _STREAM_URL_CACHE_TTL,
                stream_url,
            )
            cls._cache_prune_locked(cls._stream_url_cache, _STREAM_URL_CACHE_MAX)
