"""ResolverCacheMixin: implementation shared by the public SourceResolver facade."""
from __future__ import annotations
import time
from typing import Optional
from core.stream_expiry import stream_ttl_seconds
from core.source_resolver.models import clone_track as _clone_track
from core.source_resolver.ytdlp import _YTDLP_QUERY_CACHE_TTL, _YTDLP_QUERY_CACHE_MAX, _STREAM_URL_CACHE_TTL, _STREAM_URL_CACHE_MAX


class ResolverCacheMixin:
    @classmethod
    def _cache_prune_locked(cls, cache: dict, max_size: int) -> None:
        now = time.monotonic()
        expired_keys = [k for k, (exp, _) in cache.items() if exp <= now]
        for key in expired_keys:
            cache.pop(key, None)
        while len(cache) > max_size:
            cache.pop(next(iter(cache)), None)


    @classmethod
    def _get_cached_ytdlp_results(
        cls, key: str, requester: str, requester_id: int
    ) -> Optional[list["TrackInfo"]]:
        now = time.monotonic()
        with cls._cache_lock:
            cached = cls._ytdlp_query_cache.get(key)
            if not cached:
                return None
            exp, tracks = cached
            if exp <= now:
                cls._ytdlp_query_cache.pop(key, None)
                return None
            cls._ytdlp_query_cache.pop(key, None)
            cls._ytdlp_query_cache[key] = (exp, tracks)
            hydrated = []
            for track in tracks:
                clone = _clone_track(track)
                clone.requester = requester
                clone.requester_id = requester_id
                hydrated.append(clone)
            return hydrated


    @classmethod
    def _set_cached_ytdlp_results(cls, key: str, tracks: list["TrackInfo"]) -> None:
        with cls._cache_lock:
            cls._ytdlp_query_cache.pop(key, None)
            cls._ytdlp_query_cache[key] = (
                time.monotonic() + _YTDLP_QUERY_CACHE_TTL,
                [_clone_track(t) for t in tracks],
            )
            cls._cache_prune_locked(cls._ytdlp_query_cache, _YTDLP_QUERY_CACHE_MAX)


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
            cls._stream_url_cache.pop(webpage_url, None)
            cls._stream_url_cache[webpage_url] = (exp, url)
            return url


    @classmethod
    def _set_cached_stream_url(cls, webpage_url: str, stream_url: str) -> None:
        if not stream_url:
            return
        ttl = stream_ttl_seconds(stream_url, fallback_ttl=int(_STREAM_URL_CACHE_TTL))
        with cls._cache_lock:
            cls._stream_url_cache.pop(webpage_url, None)
            cls._stream_url_cache[webpage_url] = (
                time.monotonic() + ttl,
                stream_url,
            )
            cls._cache_prune_locked(cls._stream_url_cache, _STREAM_URL_CACHE_MAX)


    @classmethod
    def invalidate_stream_cache(cls, webpage_url: str) -> None:
        normalized_webpage_url = (webpage_url or "").strip()
        if not normalized_webpage_url:
            return
        with cls._cache_lock:
            cls._stream_url_cache.pop(normalized_webpage_url, None)
