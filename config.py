import logging
import os
import socket
import threading
from pathlib import Path
from urllib.parse import urlsplit
from dotenv import load_dotenv
from core.log_colors import tag, b, hi

load_dotenv()

log = logging.getLogger("pitonazz.config")

_CLR_ON   = "\033[92m"
_CLR_OFF  = "\033[91m"
_CLR_WARN = "\033[93m"
_CLR_GRAY = "\033[90m"
_UNCONFIGURED_PROXY  = "(non configurata in env)"
_UNCONFIGURED_COOKIE = "(non configurato in env)"

_DB_PATH_DEFAULT = "data/database/cache.db"
_PROJECT_ROOT = Path(__file__).resolve().parent


def _is_http_proxy_url(value: str) -> bool:
    normalized_url = (value or "").strip().lower()
    return normalized_url.startswith("http://") or normalized_url.startswith("https://")


def _default_port_for_scheme(scheme: str) -> int | None:
    scheme = (scheme or "").lower()
    defaults = {
        "http":   80,
        "https":  443,
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


def _resolve_db_path(raw: str) -> str:
    """
    Restituisce il path del DB SQLite.
    Se raw e' vuoto usa il default. Crea le directory intermedie se necessario.
    """
    path = Path(raw.strip() if raw.strip() else _DB_PATH_DEFAULT)
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


def _resolve_optional_file_path(raw: str) -> str:
    """
    Normalizza un path opzionale proveniente da .env.
    I path relativi vengono risolti dalla root progetto, non dalla cwd del processo.
    """
    value = (raw or "").strip()
    if not value:
        return ""
    path = Path(os.path.expandvars(os.path.expanduser(value)))
    if not path.is_absolute():
        path = _PROJECT_ROOT / path
    return str(path)


class Config:
    DISCORD_TOKEN:         str = os.getenv("DISCORD_TOKEN", "")
    DISCORD_CLIENT_ID:     str = os.getenv("DISCORD_CLIENT_ID", "").strip()
    DISCORD_CLIENT_SECRET: str = os.getenv("DISCORD_CLIENT_SECRET", "").strip()
    SPOTIFY_CLIENT_ID:     str = os.getenv("SPOTIFY_CLIENT_ID", "")
    SPOTIFY_CLIENT_SECRET: str = os.getenv("SPOTIFY_CLIENT_SECRET", "")
    SPOTIFY_HINT_WAIT_SECONDS: float = float(os.getenv("SPOTIFY_HINT_WAIT_SECONDS", "0.25"))
    SPOTIFY_AMBIGUOUS_WAIT_SECONDS: float = float(os.getenv("SPOTIFY_AMBIGUOUS_WAIT_SECONDS", "0.75"))
    RESOLVE_HARD_TIMEOUT_SECONDS: float = float(os.getenv("RESOLVE_HARD_TIMEOUT_SECONDS", "4.75"))
    RESOLVE_MAX_WAIT_SECONDS: float = float(os.getenv("RESOLVE_MAX_WAIT_SECONDS", "20.0"))
    RESOLVE_FALLBACK_DELAY_SECONDS: float = float(os.getenv("RESOLVE_FALLBACK_DELAY_SECONDS", "2.0"))
    AUDIO_BACKEND: str = os.getenv("AUDIO_BACKEND", "current").strip().lower()
    LAVALINK_URI: str = os.getenv("LAVALINK_URI", "http://127.0.0.1:2333").strip()
    LAVALINK_PASSWORD: str = os.getenv("LAVALINK_PASSWORD", "youshallnotpass").strip()
    LAVALINK_SEARCH_SOURCE: str = os.getenv("LAVALINK_SEARCH_SOURCE", "youtube_music").strip().lower()
    LAVALINK_SPOTIFY_NATIVE: bool = os.getenv("LAVALINK_SPOTIFY_NATIVE", "true").strip().lower() in ("true", "1", "yes", "on")
    GROQ_API_KEY:          str = os.getenv("GROQ_API_KEY", "")
    YTDLP_PATH:            str = os.getenv("YTDLP_PATH", "").strip()
    FFMPEG_PATH:           str = os.getenv("FFMPEG_PATH", "").strip()

    # ── Permessi ─────────────────────────────────────────────────────────────────────────────────────
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

    # ── Proxy (opzionale) ─────────────────────────────────────────────────────────────────────
    _proxy: str             = os.getenv("YTDLP_PROXY", "")
    _raw_ffmpeg_proxy: str  = os.getenv("FFMPEG_PROXY", "")
    _has_http_fallback: bool = _is_http_proxy_url(_proxy)
    _ffmpeg_proxy: str      = _raw_ffmpeg_proxy or (_proxy if _has_http_fallback else "")

    # ── Cookies ────────────────────────────────────────────────────────────────────────────────
    _cookies_raw: str          = os.getenv("COOKIE_FILE", "")
    _cookies_enabled_raw: str  = os.getenv("COOKIES_ENABLED", "").strip().lower()
    COOKIES_ENABLED: bool = (
        (_cookies_enabled_raw not in ("false", "0", "no", "off"))
        if _cookies_enabled_raw
        else bool(_cookies_raw)
    )
    COOKIE_FILE: str           = _resolve_optional_file_path(_cookies_raw)
    EFFECTIVE_COOKIE_FILE: str = COOKIE_FILE if COOKIES_ENABLED else ""
    _cookies: str              = EFFECTIVE_COOKIE_FILE

    # ── Audio ──────────────────────────────────────────────────────────────────────────────────
    FFMPEG_OPTIONS: dict = {
        "before_options": (
            (f"-http_proxy {_ffmpeg_proxy} " if _ffmpeg_proxy else "")
            + "-reconnect 1 "
              "-reconnect_streamed 1 "
              "-reconnect_at_eof 1 "
              "-reconnect_on_network_error 1 "
              "-reconnect_on_http_error 4xx,5xx "
              "-reconnect_max_retries 8 "
              "-reconnect_delay_max 5 "
              "-reconnect_delay_total_max 30 "
              "-rw_timeout 15000000 "
              "-analyzeduration 0 "
              "-probesize 32k "
              "-protocol_whitelist file,http,https,tcp,tls,crypto,httpproxy "
              "-nostdin"
        ),
        "options": "-vn -bufsize 64k",
    }

    YDL_OPTIONS: dict = {
        "format": "bestaudio[ext=mp3]/bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio/best",
        "cookiefile": _cookies if _cookies else None,
        "noplaylist": False,
        "nocheckcertificate": True,
        "ignoreerrors": True,
        "logtostderr": False,
        "quiet": True,
        "no_warnings": True,
        "default_search": "ytsearch",
        "source_address": "0.0.0.0",
        "skip_download": True,
        "extract_flat": False,
        "socket_timeout": 8,
        "retries": 1,
        "fragment_retries": 1,
        "extractor_retries": 1,
        **({
            "proxy": _proxy} if _proxy else {}),
    }

    # ── Timing ───────────────────────────────────────────────────────────────────────────────
    IDLE_TIMEOUT: int     = 600
    EMPTY_CH_TIMEOUT: int = 600

    # ── Limiti ───────────────────────────────────────────────────────────────────────────────
    MAX_QUEUE: int        = 200
    MAX_RETRY_DEPTH: int  = 5
    DEFAULT_VOLUME: float = 0.5
    MAX_VOLUME: float     = 1.0

    # ── Log / misc ─────────────────────────────────────────────────────────────────────────
    LOG_LEVEL: str  = os.getenv("LOG_LEVEL", "INFO").upper().strip()
    SHOW_BANNER: bool = os.getenv("SHOW_BANNER", "true").strip().lower() not in ("false", "0", "no", "off")

    # ── AI ────────────────────────────────────────────────────────────────────────────────────
    AI_COOLDOWN_SECONDS: int = 5

    # ── Song Cache DB ───────────────────────────────────────────────────────────
    _cache_enabled_raw: str     = os.getenv("CACHE_ENABLED", "false").strip().lower()
    CACHE_ENABLED: bool         = _cache_enabled_raw in ("true", "1", "yes", "on")
    DB_PATH: str                = _resolve_db_path(os.getenv("DB_PATH", ""))
    CACHE_TTL_DAYS: int         = int(os.getenv("CACHE_TTL_DAYS",    "30"))
    CACHE_MAX_ENTRIES: int      = int(os.getenv("CACHE_MAX_ENTRIES", "500"))

    _dashboard_socket_raw: str  = os.getenv("DASHBOARD_SOCKET", "").strip()
    DASHBOARD_ENABLED: bool     = bool(_dashboard_socket_raw)
    DASHBOARD_HOST: str         = _dashboard_socket_raw.rsplit(":", 1)[0] if _dashboard_socket_raw else "0.0.0.0"
    DASHBOARD_PORT: int         = int(_dashboard_socket_raw.rsplit(":", 1)[1]) if _dashboard_socket_raw else 5000
    DASHBOARD_PUBLIC_BASE_URL: str = os.getenv("DASHBOARD_PUBLIC_BASE_URL", "").strip().rstrip("/")
    DJ_CONSOLE_CALLBACK_URL: str = os.getenv("DJ_CONSOLE_CALLBACK_URL", "").strip()

# ────────────────────────────────────────────────────────────────────────────────────────

def validate_config() -> None:
    if not Config.DISCORD_TOKEN:
        raise RuntimeError(
            "DISCORD_TOKEN non trovato nel .env — impossibile avviare il bot."
        )
    if not Config.GROQ_API_KEY:
        log.warning(
            "GROQ_API_KEY non configurata: il cog AI non funzioner\u00e0."
        )
    if not Config.SPOTIFY_CLIENT_ID or not Config.SPOTIFY_CLIENT_SECRET:
        log.warning(
            "SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET mancanti: "
            "le ricerche Spotify non funzioneranno."
        )


def _validate_cookie_file(path: str) -> tuple[bool, str]:
    """Verifica esistenza, leggibilita' e formato Netscape del file cookie.

    Returns
    -------
    (ok: bool, messaggio: str)
    """
    import os as _os
    if not path:
        return False, "nessun path specificato"
    if not _os.path.exists(path):
        return False, f"file non trovato: {path}"
    if not _os.access(path, _os.R_OK):
        return False, f"file non leggibile (permessi): {path}"
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            first_line = f.readline().strip()
            if not first_line.startswith("# Netscape HTTP Cookie File") and \
               not first_line.startswith("# HTTP Cookie File"):
                return False, f"header Netscape mancante (prima riga: {first_line[:60]!r})"
            data_lines = sum(1 for line in f if line.strip() and not line.startswith("#"))
        return True, f"OK \u2014 {data_lines} righe dati"
    except Exception as e:
        return False, f"errore lettura: {e}"


def start_proxy_startup_check() -> None:
    """Esegue un controllo proxy in background e logga lo stato startup."""
    ytdlp_proxy  = (Config._proxy or "").strip()
    ffmpeg_proxy = (Config._ffmpeg_proxy or "").strip()
    proxy_log    = logging.getLogger("pitonazz")

    def _fmt(text: str, color: str, *, bolded: bool = False) -> str:
        value = hi(text, color)
        return b(value) if bolded else value

    def _status_label(enabled: bool) -> str:
        return _fmt("ON", _CLR_ON, bolded=True) if enabled else _fmt("OFF", _CLR_OFF, bolded=True)

    def _endpoint_label(proxy_url: str) -> str:
        endpoint = _proxy_endpoint(proxy_url)
        if endpoint is None:
            return _fmt("(URL non valida)", _CLR_GRAY)
        host, port = endpoint
        return _fmt(f"({host}:{port})", _CLR_GRAY)

    def _check_and_log() -> None:
        try:
            if ytdlp_proxy:
                ok    = _probe_proxy(ytdlp_proxy)
                state = _status_label(ok)
                proxy_log.info(tag("PROXY", f"{state} ytdlp {_endpoint_label(ytdlp_proxy)}"))
            else:
                proxy_log.info(tag("PROXY", f"{_status_label(False)} ytdlp {_fmt(_UNCONFIGURED_PROXY, _CLR_GRAY)}"))

            if ffmpeg_proxy:
                ok    = _probe_proxy(ffmpeg_proxy)
                state = _status_label(ok)
                proxy_log.info(tag("PROXY", f"{state} ffmpeg {_endpoint_label(ffmpeg_proxy)}"))
            else:
                proxy_log.info(tag("PROXY", f"{_status_label(False)} ffmpeg {_fmt(_UNCONFIGURED_PROXY, _CLR_GRAY)}"))
        except Exception:
            proxy_log.exception("Errore durante il proxy startup check in background.")

    threading.Thread(target=_check_and_log, name="proxy-startup-check", daemon=True).start()


def start_cookie_startup_check() -> None:
    """Verifica il file cookie in background e logga lo stato startup."""
    cookie_log = logging.getLogger("pitonazz")
    enabled    = Config.COOKIES_ENABLED
    path       = (Config.EFFECTIVE_COOKIE_FILE or "").strip()

    def _fmt(text: str, color: str, *, bolded: bool = False) -> str:
        value = hi(text, color)
        return b(value) if bolded else value

    def _status_label(on: bool) -> str:
        return _fmt("ON", _CLR_ON, bolded=True) if on else _fmt("OFF", _CLR_OFF, bolded=True)

    def _check_and_log() -> None:
        try:
            state = _status_label(enabled)
            if not enabled:
                cookie_log.info(tag("COOKIE", f"{state} {_fmt(_UNCONFIGURED_COOKIE, _CLR_GRAY)}"))
                return
            ok, msg = _validate_cookie_file(path)
            detail  = _fmt(msg, _CLR_ON if ok else _CLR_OFF)
            icon    = "\u2705" if ok else "\u26a0\ufe0f"
            cookie_log.info(tag("COOKIE", f"{state} {icon} {detail}"))
            if not ok:
                cookie_log.warning(tag("COOKIE", f"Cookie disabilitati di fatto \u2014 {msg}"))
        except Exception:
            cookie_log.exception("Errore durante il cookie startup check in background.")

    threading.Thread(target=_check_and_log, name="cookie-startup-check", daemon=True).start()
