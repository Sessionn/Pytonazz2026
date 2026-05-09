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
_CLR_GRAY = "\033[90m"
_UNCONFIGURED_PROXY = "(non configurata in env)"


def _is_http_proxy_url(value: str) -> bool:
    # FFmpeg usa `-http_proxy`: accettiamo solo proxy HTTP(S).
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
    GEMINI_API_KEY:        str = os.getenv("GEMINI_API_KEY", "")

    # ── Permessi ─────────────────────────────────────────────────────────────────────────────
    # OWNER_ID  → UNA sola persona. Comandi distruttivi/irreversibili.
    # DEV_IDS   → Lista separata da virgola. Incluso sempre l'owner.
    #             Comandi di gestione e debug quotidiani.
    # DEV_ID    → Legacy alias (vecchio nome). Usato come fallback.
    #
    # Esempio .env:
    #   OWNER_ID=123456789
    #   DEV_IDS=123456789,987654321

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

    # ── Proxy (opzionale) ───────────────────────────────────────────────────────────────────
    _proxy: str = os.getenv("YTDLP_PROXY", "")
    _raw_ffmpeg_proxy: str = os.getenv("FFMPEG_PROXY", "")
    _has_http_fallback: bool = _is_http_proxy_url(_proxy)
    _ffmpeg_proxy: str = _raw_ffmpeg_proxy or (_proxy if _has_http_fallback else "")

    # ── Cookies (opzionali) ────────────────────────────────────────────────────────────────
    _cookies: str = os.getenv("COOKIE_FILE", "")

    # ── Audio ────────────────────────────────────────────────────────────────────────────────
    FFMPEG_OPTIONS = {
        "before_options": (
            (f"-http_proxy {_ffmpeg_proxy} " if _ffmpeg_proxy else "")
            + "-reconnect 1 "
            "-reconnect_streamed 1 "
            "-reconnect_delay_max 5 "
            "-protocol_whitelist file,http,https,tcp,tls,crypto,httpproxy "
            "-nostdin"
        ),
        "options": "-vn -bufsize 64k",
    }

    YDL_OPTIONS = {
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
        **({"proxy": _proxy} if _proxy else {}),
    }

    # ── Timing ──────────────────────────────────────────────────────────────────────────────
    # STATUS_INTERVAL è stato rimosso da qui perché non aveva effetto a runtime.
    # Il valore effettivo è BotConfig.status_interval (default 300),
    # persistito in assets/config/bot_config.json e modificabile via /setconfig.
    IDLE_TIMEOUT:     int = 600
    EMPTY_CH_TIMEOUT: int = 600

    # ── Limiti ─────────────────────────────────────────────────────────────────────────────
    MAX_QUEUE:        int   = 200
    MAX_RETRY_DEPTH:  int   = 5
    DEFAULT_VOLUME:   float = 0.5
    MAX_VOLUME:       float = 1.0

    # ── Logging ──────────────────────────────────────────────────────────────────────────────
    # LOG_LEVEL=DEBUG abilita i dettagli DEBUG solo per il logger di
    # enrichment Spotify (pitonazz.spotify_enrich). Il resto resta a INFO.
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()

    # ── AI ───────────────────────────────────────────────────────────────────────────────────
    AI_COOLDOWN_SECONDS: int = 5   # secondi tra una richiesta e l'altra per utente


def validate_config() -> None:
    """Logga warning per le variabili d'ambiente critiche mancanti.
    Da chiamare all'avvio (in main.py) prima di avviare il bot.
    """
    if not Config.DISCORD_TOKEN:
        raise RuntimeError(
            "DISCORD_TOKEN non trovato nel .env — impossibile avviare il bot."
        )
    if not Config.GEMINI_API_KEY and not Config.GROQ_API_KEY:
        log.warning(
            "Né GEMINI_API_KEY né GROQ_API_KEY configurate: il cog AI non funzionerà."
        )
    if not Config.SPOTIFY_CLIENT_ID or not Config.SPOTIFY_CLIENT_SECRET:
        log.warning(
            "SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET mancanti: "
            "le ricerche Spotify non funzioneranno."
        )


def start_proxy_startup_check() -> None:
    """Esegue un controllo proxy in background e logga lo stato startup."""

    ytdlp_proxy = (Config._proxy or "").strip()
    ffmpeg_proxy = (Config._ffmpeg_proxy or "").strip()
    proxy_log = logging.getLogger("pitonazz")

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
                ok = _probe_proxy(ytdlp_proxy)
                state = _status_label(ok)
                proxy_log.info(tag("PROXY", f"{state}  ytdlp  {_endpoint_label(ytdlp_proxy)}"))
            else:
                proxy_log.info(tag("PROXY", f"{_status_label(False)}  ytdlp  {_fmt(_UNCONFIGURED_PROXY, _CLR_GRAY)}"))

            if ffmpeg_proxy:
                ok = _probe_proxy(ffmpeg_proxy)
                state = _status_label(ok)
                proxy_log.info(tag("PROXY", f"{state}  ffmpeg  {_endpoint_label(ffmpeg_proxy)}"))
            else:
                proxy_log.info(tag("PROXY", f"{_status_label(False)}  ffmpeg  {_fmt(_UNCONFIGURED_PROXY, _CLR_GRAY)}"))
        except Exception:
            proxy_log.exception("Errore durante il proxy startup check in background.")

    threading.Thread(target=_check_and_log, name="proxy-startup-check", daemon=True).start()
