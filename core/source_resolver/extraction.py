"""ExtractionMixin: implementation shared by the public SourceResolver facade."""
from __future__ import annotations
from .parsing import _is_yt_channel_url, _entry_thumbnail
import logging
import re
import threading
from typing import Optional
import yt_dlp
from config import Config
from core.log_colors import tag, b
from core.source_resolver.models import TrackInfo
from core.source_resolver.ytdlp import _make_opts, _strip_yt_radio, _is_soundcloud_url, _resolve_soundcloud_short_url, _strip_soundcloud_params

log = logging.getLogger("pitonazz.resolver")

_FAST_STREAM_EXTRACT_OPTS = {
    "noplaylist": True,
    # Some authenticated YouTube sessions expose only muxed HLS streams.
    # FFmpeg discards video; prefer a small rendition to limit bandwidth.
    "format": Config.YDL_OPTIONS["format"],
}


class ExtractionMixin:
    @classmethod
    def _search_or_url(cls, query: str, requester: str, requester_id: int) -> list:
        if query.startswith("http"):
            if _is_yt_channel_url(query):
                log.debug(tag("RESOLVER", f"URL canale YouTube ignorato: {b(query)}"))
                return []
            query = _resolve_soundcloud_short_url(query)
            query = _strip_soundcloud_params(query)
            query = _strip_yt_radio(query)
        else:
            query = "ytsearch:" + query
        return cls._run_ytdlp(query, requester, requester_id)


    @classmethod
    def _run_ytdlp(cls, query: str, requester: str, requester_id: int) -> list:
        cache_key = query.strip()
        cached = cls._get_cached_ytdlp_results(cache_key, requester, requester_id)
        if cached is not None:
            log.debug(tag("RESOLVE", f"cache hit ytdlp  {b(query)}"))
            return cached
        with cls._cache_lock:
            inflight = cls._ytdlp_query_inflight.get(cache_key)
            if inflight is None:
                inflight = threading.Event()
                cls._ytdlp_query_inflight[cache_key] = inflight
                owns_inflight = True
            else:
                owns_inflight = False
        if not owns_inflight:
            inflight.wait()
            cached = cls._get_cached_ytdlp_results(cache_key, requester, requester_id)
            return cached if cached is not None else []
        normalized_query = query.strip()
        origin_query = re.sub(r"^ytsearch\d*:", "", normalized_query, count=1).strip() or normalized_query
        try:
            fast_search_results = cls._run_ytdlp_flat_first(normalized_query, requester, requester_id, origin_query)
            if fast_search_results is not None:
                cls._set_cached_ytdlp_results(cache_key, fast_search_results)
                return fast_search_results
            try:
                with yt_dlp.YoutubeDL(_make_opts()) as ydl:
                    info = ydl.extract_info(query, download=False)
            except yt_dlp.utils.ExtractorError as e:
                err_str = str(e).lower()
                # Video non disponibile (rimosso, geo-bloccato, privato, ecc.)
                if any(kw in err_str for kw in ("video unavailable", "private video",
                                                 "this video is not available",
                                                 "has been removed", "geo")):
                    log.warning(tag("WARN", f"video non disponibile, fallback search: {b(query)}"))
                    # Se era un URL diretto, proviamo una ricerca testuale con il titolo
                    if query.startswith("http"):
                        return []  # per URL diretti non c'è fallback sicuro
                    # Per query ytsearch, logghiamo e restituiamo vuoto
                    return []
                log.error(tag("ERR", f"yt-dlp ExtractorError: {e}"))
                return []
            except Exception as e:
                log.error(tag("ERR", f"yt-dlp: {e}"))
                return []
            if not info:
                return []
            results = cls._tracks_from_ytdlp_info(info, requester, requester_id, origin_query)
            cls._set_cached_ytdlp_results(cache_key, results)
            return results
        finally:
            with cls._cache_lock:
                done = cls._ytdlp_query_inflight.pop(cache_key, None)
                if done is not None:
                    done.set()


    @classmethod
    def _run_ytdlp_flat_first(
        cls,
        query: str,
        requester: str,
        requester_id: int,
        origin_query: str,
    ) -> Optional[list]:
        if not re.match(r"^ytsearch1:", query, re.IGNORECASE):
            return None
        try:
            with yt_dlp.YoutubeDL(_make_opts({"extract_flat": True, "format": "bestaudio/best"})) as ydl:
                info = ydl.extract_info(query, download=False)
            direct_url = cls._first_ytdlp_webpage_url(info or {})
            if not direct_url:
                return None
            with yt_dlp.YoutubeDL(_make_opts(_FAST_STREAM_EXTRACT_OPTS)) as ydl:
                direct_info = ydl.extract_info(direct_url, download=False)
            results = cls._tracks_from_ytdlp_info(direct_info or {}, requester, requester_id, origin_query)
            return results if results else None
        except Exception as exc:
            log.debug(tag("RESOLVE", f"flat-first ytsearch fallback  {b(query)}  {exc}"))
            return None


    @staticmethod
    def _first_ytdlp_webpage_url(info: dict) -> str:
        entries = info.get("entries") or []
        first = entries[0] if entries else info
        if not first:
            return ""
        url = (first.get("webpage_url") or first.get("url") or "").strip()
        if not url:
            return ""
        if url.startswith(("http://", "https://")):
            return url
        if re.match(r"^ytsearch\d*:", url, re.IGNORECASE):
            return ""
        if re.fullmatch(r"[A-Za-z0-9_-]{11}", url):
            return f"https://www.youtube.com/watch?v={url}"
        return ""


    @classmethod
    def _tracks_from_ytdlp_info(cls, info: dict, requester: str, requester_id: int, origin_query: str) -> list:
        raw_entries = info.get("entries")
        entries = raw_entries if raw_entries is not None else [info]
        results = []
        for e in entries:
            if not e or cls._is_drm(e):
                continue
            url = cls._best_audio_url(e)
            if not url:
                continue
            webpage_url = e.get("webpage_url", "")
            src    = "soundcloud" if _is_soundcloud_url(webpage_url) else "youtube"
            artist = e.get("artist") or e.get("creator") or e.get("uploader", "")
            thumbnail = _entry_thumbnail(e, webpage_url, src)
            results.append(TrackInfo(
                title        = e.get("title", "Senza titolo"),
                webpage_url  = webpage_url,
                duration     = int(e.get("duration") or 0),
                thumbnail    = thumbnail,
                requester    = requester,
                requester_id = requester_id,
                source       = src,
                stream_url   = url,
                artist       = artist,
                origin_query = origin_query,
                thumbnail_source = src if thumbnail else "",
                thumbnail_confidence = 0.45 if thumbnail else 0.0,
            ))
        return results


    @classmethod
    def _fetch_stream_url(cls, webpage_url: str) -> str:
        normalized_webpage_url = (webpage_url or "").strip()
        if not normalized_webpage_url:
            return ""
        cached = cls._get_cached_stream_url(normalized_webpage_url)
        if cached is not None:
            log.debug(tag("STREAM", f"cache hit stream_url  {b(normalized_webpage_url)}"))
            return cached
        with cls._cache_lock:
            inflight = cls._stream_url_inflight.get(normalized_webpage_url)
            if inflight is None:
                inflight = threading.Event()
                cls._stream_url_inflight[normalized_webpage_url] = inflight
                owns_inflight = True
            else:
                owns_inflight = False
        if not owns_inflight:
            inflight.wait()
            return cls._get_cached_stream_url(normalized_webpage_url) or ""
        try:
            try:
                with yt_dlp.YoutubeDL(_make_opts(_FAST_STREAM_EXTRACT_OPTS)) as ydl:
                    info = ydl.extract_info(normalized_webpage_url, download=False)
            except yt_dlp.utils.ExtractorError as e:
                cls.invalidate_stream_cache(normalized_webpage_url)
                err_str = str(e).lower()
                if any(kw in err_str for kw in ("video unavailable", "private video",
                                                 "this video is not available",
                                                 "has been removed")):
                    log.warning(tag("WARN", f"video non disponibile (rimosso/privato): {b(normalized_webpage_url)}"))
                else:
                    log.error(tag("ERR", f"fetch_stream_url ExtractorError: {e}"))
                return ""
            except Exception as e:
                cls.invalidate_stream_cache(normalized_webpage_url)
                log.error(tag("ERR", f"fetch_stream_url: {e}"))
                return ""
            if not info or cls._is_drm(info):
                cls.invalidate_stream_cache(normalized_webpage_url)
                return ""
            entries = info.get("entries") or []
            if entries:
                info = next((entry for entry in entries if entry and not cls._is_drm(entry)), {}) or {}
                if not info:
                    cls.invalidate_stream_cache(normalized_webpage_url)
                    return ""
            stream_url = cls._best_audio_url(info) or ""
            if stream_url:
                cls._set_cached_stream_url(normalized_webpage_url, stream_url)
            else:
                cls.invalidate_stream_cache(normalized_webpage_url)
            return stream_url
        finally:
            with cls._cache_lock:
                done = cls._stream_url_inflight.pop(normalized_webpage_url, None)
                if done is not None:
                    done.set()


    @staticmethod
    def _is_drm(info: dict) -> bool:
        if info.get("is_drm_protected"):
            return True
        formats = info.get("formats", [])
        return bool(formats) and all(f.get("has_drm") for f in formats)


    @staticmethod
    def _best_audio_url(info: dict) -> Optional[str]:
        formats = info.get("formats", [])
        audio = [
            f for f in formats
            if f.get("vcodec") == "none"
            and f.get("acodec") not in (None, "none")
            and f.get("url")
            and not f.get("has_drm")
        ]
        if not audio:
            return info.get("url")
        _DIRECT = {"https", "http", ""}
        direct  = [f for f in audio if (f.get("protocol") or "").split("+")[0] in _DIRECT]
        pool    = direct if direct else audio
        return max(pool, key=lambda f: f.get("abr") or f.get("tbr") or 0)["url"]
