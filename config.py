import logging
import os
import socket
import threading
from urllib.parse import urlsplit
from dotenv import load_dotenv
from core.log_colors import tag, b, hi

load_dotenv()

log = logging.getLogger("pitonazz.config")

_CLR_ON = "\033[92m"
_CLR_OFF = "\033[91m"
_CLR_WARN = "\033[93m"
_CLR_GRAY = "\033[90m"
_UNCONFIGURED_PROXY = "(non configurata in env)"
_UNCONFIGURED_COOKIE = "(non configurato in env)"


def _is_http_proxy_url(value: str) -> bool:
    normalized_url = (value or "").strip().lower()
    return normalized_url.startswith("http://") or normalized_url.startswith("https://")


def _default_port_for_scheme(scheme: str) -> int | None:
    scheme = (scheme or "").lower()
    defaults = {
        "http": 80,
        "https": 443,
        "socks5": 1080,
        "socks5h": 1080,
        "socks4": 1080,
    }
    return defaults.get(scheme)


def _proxy_endpoint(proxy_url: str) -> tuple[str, int] | None:
    raw = (proxy_url or "").strip()
    if not raw:
        return None
    parsed = urlsplit(raw)
    host = parsed.hostname
    if not host:
        return None
    port = parsed.port or _default_port_for_scheme(parsed.scheme)
    if not port:
        return None
    return host, port


def _probe_proxy(proxy_url: str, timeout: float = 2.0) -> bool:
    endpoint = _proxy_endpoint(proxy_url)
    if endpoint is None:
        return False
    host, port = endpoint
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


class Config:
    DISCORD_TOKEN:         str = os.getenv("DISCORD_TOKEN", "")
    SPOTIFY_CLIENT_ID:     str = os.getenv("SPOTIFY_CLIENT_ID", "")
    SPOTIFY_CLIENT_SECRET: str = os.getenv("SPOTIFY_CLIENT_SECRET", "")
    GROQ_API_KEY:          str = os.getenv("GROQ_API_KEY", "")

    # ── Permessi ───────────────────────────────────────────────────────────────────────────────────
    _owner_raw: str = os.getenv("OWNER_ID") or os.getenv("DEV_ID") or ""
    OWNER_ID: int | None = int(_owner_raw) if _owner_raw.strip().isdigit() else None

    _dev_raw: str = os.getenv("DEV_IDS") or os.getenv("DEV_ID") or ""
    _dev_list: list[int] = [int(x.strip()) for x in _dev_raw.split(",") if x.strip().isdigit()]
    DEV_IDS: list[int] = list(dict.fromkeys(
        ([OWNER_ID] if OWNER_ID else []) + _dev_list
    ))
    DEV_ID: int | None = DEV_IDS[0] if DEV_IDS else None

    _gids = os.getenv("GUILD_IDS", "")
    GUILD_IDS: list[int] = [int(g.strip()) for g in _gids.split(",") if g.strip().isdigit()]

    # ── Proxy (opzionale) ───────────────────────────────────────────────────────────────────────
    _proxy: str = os.getenv("YTDLP_PROXY", "")
    _raw_ffmpeg_proxy: str = os.getenv("FFMPEG_PROXY", "")
    _has_http_fallback: bool = _is_http_proxy_url(_proxy)
    _ffmpeg_proxy: str = _raw_ffmpeg_proxy or (_proxy if _has_http_fallback else "")

    # ── Cookies ────────────────────────────────────────────────────────────────────────────
    _cookies_raw: str = os.getenv("COOKIE_FILE", "")
    _cookies_enabled_raw: str = os.getenv("COOKIES_ENABLED", "").strip().lower()
    COOKIES_ENABLED: bool = (
        (_cookies_enabled_raw not in ("false", "0", "no", "off"))
        if _cookies_enabled_raw
        else bool(_cookies_raw)
    )
    COOKIE_FILE: str = _cookies_raw

    # ── Log / misc ───────────────────────────────────────────────────────────────────────────
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper().strip()
    SHOW_BANNER: bool = os.getenv("SHOW_BANNER", "true").strip().lower() not in ("false", "0", "no", "off")

    # ── Song Cache DB ────────────────────────────────────────────────────────────────────────
    _cache_enabled_raw: str = os.getenv("CACHE_ENABLED", "false").strip().lower()
    CACHE_ENABLED: bool      = _cache_enabled_raw in ("true", "1", "yes", "on")
    DB_PATH: str             = os.getenv("DB_PATH", "cache.db")
    CACHE_TTL_DAYS: int      = int(os.getenv("CACHE_TTL_DAYS",    "30"))
    CACHE_MAX_ENTRIES: int   = int(os.getenv("CACHE_MAX_ENTRIES", "500"))


def validate_config() -> None:
    if not Config.DISCORD_TOKEN:
        raise RuntimeError("DISCORD_TOKEN non configurato nel .env")


def start_proxy_startup_check() -> None:
    proxy = Config._proxy
    if not proxy:
        return
    def _check():
        ok = _probe_proxy(proxy)
        if ok:
            log.info(tag("PROXY", f"{_CLR_ON}OK{_CLR_GRAY[0:]}  {proxy}\033[0m"))
        else:
            log.warning(tag("PROXY", f"{_CLR_WARN}IRRAGGIUNGIBILE{_CLR_GRAY[0:]}  {proxy}\033[0m"))
    threading.Thread(target=_check, daemon=True).start()


def start_cookie_startup_check() -> None:
    if not Config.COOKIES_ENABLED:
        return
    cookie_file = Config.COOKIE_FILE
    def _check():
        import os as _os
        if cookie_file and _os.path.isfile(cookie_file):
            log.info(tag("COOKIE", f"{_CLR_ON}OK{_CLR_GRAY[0:]}  {cookie_file}\033[0m"))
        else:
            log.warning(tag("COOKIE", f"{_CLR_WARN}FILE NON TROVATO{_CLR_GRAY[0:]}  {cookie_file or _UNCONFIGURED_COOKIE}\033[0m"))
    threading.Thread(target=_check, daemon=True).start()
