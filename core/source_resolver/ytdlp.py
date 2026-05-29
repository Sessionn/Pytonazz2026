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
import urllib.request

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


# Parametri query SoundCloud che interferiscono con yt-dlp (sort, client_id, ecc.)
# Includiamo anche i parametri di tracking/sharing che non servono alla risoluzione
_SC_STRIP_PARAMS = frozenset({
    "sort", "client_id", "offset", "limit", "linked_partitioning",
    "app_version", "app_locale", "cursor",
    "si",                          # SoundCloud share ID (sharing link)
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "ref", "fbclid", "igshid",
})


def _strip_soundcloud_params(url: str) -> str:
    """Rimuove parametri query non necessari dai link SoundCloud prima di passarli a yt-dlp.

    Link del tipo soundcloud.com/user/sets/playlist?sort=latest o ?si=...&utm_source=...
    non vengono risolti correttamente da yt-dlp se mantengono i query param di navigazione.
    """
    raw = (url or "").strip()
    if not _is_soundcloud_url(raw):
        return raw
    target = raw if "://" in raw else f"https://{raw}"
    parsed = urllib.parse.urlparse(target)
    if not parsed.query:
        return raw
    params = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    cleaned = {k: v for k, v in params.items() if k.lower() not in _SC_STRIP_PARAMS}
    new_query = urllib.parse.urlencode(cleaned, doseq=True)
    cleaned_url = urllib.parse.urlunparse(parsed._replace(query=new_query))
    if cleaned_url != target:
        log.debug(tag("RESOLVE", f"SoundCloud params stripped: {cleaned_url}"))
    return cleaned_url


def _is_soundcloud_short_url(url: str) -> bool:
    raw = (url or "").strip()
    if not raw:
        return False
    parsed = urllib.parse.urlparse(raw if "://" in raw else f"https://{raw}")
    return (parsed.hostname or "").lower() == "on.soundcloud.com"


def _resolve_soundcloud_short_url(url: str, timeout: float = 8.0) -> str:
    """Resolve on.soundcloud.com short links prima che yt-dlp li veda.

    Usa GET invece di HEAD perché alcuni server SoundCloud non restituiscono
    il Location header correttamente con HEAD. Legge solo pochi byte del body
    per seguire i redirect, poi applica _strip_soundcloud_params per pulire
    i parametri di tracking (?si=, ?utm_*) dall'URL finale.
    """
    raw = (url or "").strip()
    if not _is_soundcloud_short_url(raw):
        return _strip_soundcloud_params(raw) if _is_soundcloud_url(raw) else raw
    target = raw if "://" in raw else f"https://{raw}"
    req = urllib.request.Request(
        target,
        method="GET",
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            final_url = resp.geturl() or target
        # Pulisci i param di tracking dall'URL risolto
        final_url = _strip_soundcloud_params(final_url)
        if final_url != target:
            log.debug(tag("RESOLVE", f"SoundCloud short resolved: {final_url}"))
        return final_url
    except Exception as exc:
        log.warning(tag("RESOLVE", f"SoundCloud short resolve failed ({exc}), uso URL originale"))
        return target
