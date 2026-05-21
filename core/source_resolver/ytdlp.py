"""
core/source_resolver/ytdlp.py
------------------------------
yt-dlp infrastructure helpers: custom logger, option builder, and
URL utilities.  Imported by SourceResolver in source_resolver.

Proxy handling (YTDLP_PROXY via Config.YDL_OPTIONS) is preserved
exactly — _make_opts() merges Config.YDL_OPTIONS unchanged.
"""
from __future__ import annotations

import logging
import re
import urllib.parse

from config import Config
from core.log_colors import tag

# ── Cache TTL / size constants ────────────────────────────────────────────────

_YTDLP_QUERY_CACHE_TTL  = 20.0
_YTDLP_QUERY_CACHE_MAX  = 256
_STREAM_URL_CACHE_TTL   = 45.0
_STREAM_URL_CACHE_MAX   = 256

log = logging.getLogger("pitonazz.resolver")


# ── yt-dlp logger ─────────────────────────────────────────────────────────────

class _YdlLogger:
    def debug(self, msg: str) -> None:
        if not msg.startswith("[debug]"):
            log.debug(tag("RESOLVE", f"{msg}"))

    def info(self, msg: str) -> None:
        log.debug(tag("RESOLVE", f"{msg}"))

    def warning(self, msg: str) -> None:
        if "DRM" not in msg and "JavaScript runtime" not in msg:
            log.warning(tag("WARN", f"{msg}"))

    def error(self, msg: str) -> None:
        if "DRM" not in msg:
            log.error(tag("ERR", f"{msg}"))


# ── Option builder ────────────────────────────────────────────────────────────

def _make_opts(extra: dict | None = None) -> dict:
    """Build yt-dlp options by merging Config.YDL_OPTIONS with an optional extra dict.

    Config.YDL_OPTIONS already contains the proxy key when YTDLP_PROXY is set,
    so proxy behavior is preserved automatically.

    Returns a dict with merged yt-dlp options including the custom logger.
    """
    opts = {**Config.YDL_OPTIONS, "logger": _YdlLogger()}
    if extra:
        opts.update(extra)
    return opts


# ── URL helpers ───────────────────────────────────────────────────────────────

def _strip_yt_radio(url: str) -> str:
    """Remove YouTube radio list parameters from a watch URL.

    Returns the cleaned URL, or the original URL if no radio params are present.
    """
    parsed = urllib.parse.urlparse(url)
    if parsed.netloc in ("www.youtube.com", "youtube.com"):
        params = urllib.parse.parse_qs(parsed.query)
        lst = params.get("list", [""])[0]
        if lst.startswith("RD") or "start_radio" in params:
            v = params.get("v", [""])[0]
            if v:
                return "https://www.youtube.com/watch?v=" + v
    return url


def _is_soundcloud_url(url: str) -> bool:
    """Return True if url points to SoundCloud (soundcloud.com or subdomain).

    Accepts inputs with or without a URL scheme.
    """
    raw = (url or "").strip()
    if not raw:
        return False
    parsed = urllib.parse.urlparse(raw if "://" in raw else f"https://{raw}")
    host = (parsed.hostname or "").lower()
    if not host:
        return False
    return host == "soundcloud.com" or host.endswith(".soundcloud.com")


def _is_soundcloud_short_url(url: str) -> bool:
    """Return True if url points to SoundCloud short host snd.sc."""
    raw = (url or "").strip()
    if not raw:
        return False
    parsed = urllib.parse.urlparse(raw if "://" in raw else f"https://{raw}")
    host = (parsed.hostname or "").lower()
    return host == "snd.sc" or host == "www.snd.sc"
