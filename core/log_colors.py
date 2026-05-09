import logging
import re

_R    = "\033[0m"
_BOLD = "\033[1m"
_DIM  = "\033[2m"

_GRN  = "\033[32m"
_YEL  = "\033[33m"
_RED  = "\033[31m"
_CYN  = "\033[36m"
_MAG  = "\033[35m"
_BLU  = "\033[34m"
_WHT  = "\033[97m"
_GRY  = "\033[90m"
_BCYN = "\033[96m"
_BGRN = "\033[92m"
_BYEL = "\033[93m"
_BRED = "\033[91m"
_BMAG = "\033[95m"
_BBLU = "\033[94m"
_ORG  = "\033[38;5;208m"
_TEAL = "\033[38;5;80m"

_LEVEL_COLOR = {
    logging.DEBUG:    _CYN,
    logging.INFO:     _GRN,
    logging.WARNING:  _YEL,
    logging.ERROR:    _RED,
    logging.CRITICAL: _MAG,
}

_SRC_PTZ = f"{_BOLD}{_BGRN}PYTONAZZ{_R}"
_SRC_DSC = f"{_BOLD}{_BBLU}DISCORD {_R}"
_SRC_EXT = f"{_BOLD}{_GRY}EXTERNAL{_R}"

TAG = {
    "SYNC"   : ("SYNC",    _BCYN),
    "BOOT"   : ("BOOT",    _BGRN),
    "PROXY"  : ("PROXY",   _ORG),
    "READY"  : ("READY",   _BGRN),
    "WATCH"  : ("WATCH",   _BLU),
    "RELOAD" : ("RELOAD",  _BLU),
    "PLAYER" : ("PLAYER",  _GRN),
    "STREAM" : ("STREAM",  _CYN),
    "FILTER" : ("FILTER",  _MAG),
    "QUEUE"  : ("QUEUE",   _YEL),
    "RESOLVE": ("RESOLVE", _BCYN),
    "SPOTIFY": ("SPOTIFY", _BGRN),
    "WARN"   : ("WARN",    _BYEL),
    "ERR"    : ("ERR",     _BRED),
    "AI"     : ("AI",      _BMAG),
    "CMD"    : ("CMD",     _WHT),
    "JOIN"   : ("JOIN",    _TEAL),
    "TTS"    : ("TTS",     _BMAG),
    "DEV"    : ("DEV",     _ORG),
    "STATUS" : ("STATUS",  _BYEL),
    "VOICE"  : ("VOICE",   _TEAL),
    "DISC"   : ("DISC",    _GRY),
    "MOD"    : ("MOD",     _BRED),
    "GATEWAY": ("GATEWAY", _BCYN),
}

_FMT  = "%(ts)s  %(levelname)s  %(source)s  %(logger_name)s  %(message)s"
_DATE = "%Y-%m-%d %H:%M:%S"


class ColorFormatter(logging.Formatter):
    _INNER = logging.Formatter(_FMT)

    @staticmethod
    def _shorten(text: str, width: int = 16) -> str:
        if len(text) <= width:
            return text.ljust(width)
        return (text[: width - 1] + "…").ljust(width)

    @classmethod
    def _source_fields(cls, logger_name: str) -> tuple[str, str]:
        name = logger_name or "root"
        if name.startswith("pitonazz"):
            mod = name.split(".", 1)[1] if "." in name else "main"
            return _SRC_PTZ, f"{_TEAL}{cls._shorten(mod)}{_R}"
        if name.startswith("discord"):
            mod = name.split(".", 1)[1] if "." in name else "core"
            return _SRC_DSC, f"{_GRY}{cls._shorten(mod)}{_R}"
        return _SRC_EXT, f"{_GRY}{cls._shorten(name)}{_R}"

    def format(self, record: logging.LogRecord) -> str:
        color  = _LEVEL_COLOR.get(record.levelno, "")
        orig   = record.levelname
        orig_ts = getattr(record, "ts", None)
        orig_source = getattr(record, "source", None)
        orig_logger_name = getattr(record, "logger_name", None)
        record.levelname = f"{color}{orig.ljust(8)}{_R}"
        record.ts = f"{_DIM}{logging.Formatter().formatTime(record, _DATE)}{_R}"
        record.source, record.logger_name = self._source_fields(record.name)
        result = self._INNER.format(record)
        record.levelname = orig
        if orig_ts is None:
            delattr(record, "ts")
        else:
            record.ts = orig_ts
        if orig_source is None:
            delattr(record, "source")
        else:
            record.source = orig_source
        if orig_logger_name is None:
            delattr(record, "logger_name")
        else:
            record.logger_name = orig_logger_name
        return result


# ── Gateway filter ────────────────────────────────────────────────────────────
# Intercetta i log di discord.gateway e li riscrive nel tuo stile.
# Ogni pattern mappa un regex sul messaggio grezzo → una funzione che
# produce il messaggio riformattato usando tag() e i tuoi colori.

_GW_CONNECTED   = re.compile(r"Shard ID (\S+) has connected to Gateway \(Session ID: ([a-f0-9]+)\)")
_GW_RESUMED     = re.compile(r"Shard ID (\S+) has sent the RESUME payload")
_GW_RECONNECT   = re.compile(r"Shard ID (\S+) is attempting a reconnect")
_GW_DISCONNECT  = re.compile(r"Shard ID (\S+) has (disconnected|lost connection)")
_GW_HEARTBEAT   = re.compile(r"Shard ID (\S+) has sent the IDENTIFY payload")
_GW_RATELIMIT   = re.compile(r"WebSocket in shard ID (\S+) is ratelimited")


def _fmt_gateway(msg: str) -> str | None:
    """Riscrive un messaggio grezzo di discord.gateway.
    Ritorna None se il messaggio non è riconosciuto (pass-through)."""

    if m := _GW_CONNECTED.search(msg):
        shard, sid = m.group(1), m.group(2)
        shard_label = dim(f"shard {shard}") if shard != "None" else dim("single shard")
        return tag("GATEWAY", f"Connesso  {_GRY}session {sid}{_R}  {shard_label}")

    if m := _GW_RESUMED.search(msg):
        shard = m.group(1)
        return tag("GATEWAY", f"Sessione {_BGRN}ripresa{_R}  {dim(f'shard {shard}')}")

    if m := _GW_RECONNECT.search(msg):
        shard = m.group(1)
        return tag("GATEWAY", f"{_BYEL}Reconnect in corso…{_R}  {dim(f'shard {shard}')}")

    if m := _GW_DISCONNECT.search(msg):
        shard = m.group(1)
        return tag("GATEWAY", f"{_BRED}Disconnesso{_R}  {dim(f'shard {shard}')}")

    if m := _GW_HEARTBEAT.search(msg):
        shard = m.group(1)
        return tag("GATEWAY", f"IDENTIFY inviato  {dim(f'shard {shard}')}")

    if m := _GW_RATELIMIT.search(msg):
        shard = m.group(1)
        return tag("GATEWAY", f"{_BRED}Rate limit WebSocket{_R}  {dim(f'shard {shard}')}")

    return None  # messaggio non riconosciuto: lascia passare invariato


class GatewayFilter(logging.Filter):
    """Filtra discord.gateway riscrivendo i messaggi nel tuo stile.
    Restituisce sempre True (il record passa comunque),
    ma ne modifica il msg prima che il formatter lo veda."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.name != "discord.gateway":
            return True
        formatted = _fmt_gateway(record.getMessage())
        if formatted is not None:
            record.msg  = formatted
            record.args = ()  # evita double-format
            # rimappa il nome logger su "pitonazz.gateway" per coerenza visiva
            record.name = "pitonazz.gateway"
        return True


# ── Helpers base ─────────────────────────────────────────────────────

def b(text) -> str:
    """Grassetto."""
    return f"{_BOLD}{text}{_R}"

def hi(text, color: str = _CYN) -> str:
    """Testo colorato."""
    return f"{color}{text}{_R}"

def ms(val: float) -> str:
    """Millisecondi in giallo grassetto."""
    return f"{_BOLD}{_BYEL}{val:.0f}ms{_R}"

def title(text: str) -> str:
    """Titolo traccia in grassetto bianco."""
    return f"{_BOLD}{_WHT}{text}{_R}"

def guild(text: str) -> str:
    """Nome server in teal."""
    return f"{_TEAL}{text}{_R}"

def user(text: str) -> str:
    """Nome utente in grigio."""
    return f"{_GRY}{text}{_R}"

def ch(text: str) -> str:
    """Nome canale in cyan."""
    return f"{_BCYN}#{text}{_R}"

def dim(text: str) -> str:
    """Testo attenuato."""
    return f"{_DIM}{text}{_R}"

def tag(label: str, msg: str) -> str:
    """Tag colorato + messaggio."""
    t, c = TAG.get(label, (label, _GRY))
    return f"{_BOLD}{c}{t:<8}{_R} {msg}"


# ── Messaggi di sistema centralizzati ──────────────────────────────────

def fmt_cog_loaded(cog_name: str) -> str:
    short = cog_name.split(".")[-1]
    return tag("BOOT", f"Loaded  {b(short)}{_GRY}  ←  {cog_name}{_R}")

def fmt_cog_failed(cog_name: str, error: Exception) -> str:
    short = cog_name.split(".")[-1]
    return tag("ERR", f"Failed  {b(short)}  →  {_BRED}{error}{_R}")

def fmt_sync_guild(guild_id: int, guild_name: str, count: int) -> str:
    return tag("SYNC", f"{_TEAL}{guild_name}{_R}  {_GRY}[{guild_id}]{_R}  →  {b(count)} comandi")

def fmt_sync_global(count: int) -> str:
    return tag("SYNC", f"Global  →  {b(count)} comandi")

def fmt_ready(bot_name: str, bot_id: int) -> str:
    return tag("READY", f"{_BOLD}{_BGRN}{bot_name}{_R}  online  {_GRY}ID: {bot_id}{_R}")

def fmt_status_interval(seconds: int) -> str:
    mins = seconds / 60
    return tag("BOOT", f"Status interval  →  {b(seconds)}s  {_GRY}({mins:.0f} min){_R}")

def fmt_disabled_commands(names: list[str]) -> str:
    if not names:
        return tag("BOOT", f"Comandi disabilitati: {_GRY}nessuno{_R}")
    formatted = "  ".join(f"{_BRED}●{_R} {_BOLD}{n}{_R}" for n in names)
    return tag("BOOT", f"Comandi disabilitati: {formatted}")

def fmt_maintenance(active: bool) -> str:
    if active:
        return tag("WARN", f"Modalità {_BOLD}{_BYEL}MANUTENZIONE{_R} attiva")
    return tag("BOOT", f"Manutenzione {_GRN}disattivata{_R}")

def fmt_reload(cog_name: str) -> str:
    short = cog_name.split(".")[-1]
    return tag("RELOAD", f"{b(short)}  {_GRY}← {cog_name}{_R}")

def fmt_reload_failed(cog_name: str, error: Exception) -> str:
    return tag("ERR", f"Reload fallito  {b(cog_name)}  →  {_BRED}{error}{_R}")

def fmt_watch_modified(cog_name: str) -> str:
    return tag("WATCH", f"Modifica rilevata  →  {b(cog_name)}")

def fmt_watch_skipped(cog_name: str) -> str:
    return tag("WATCH", f"{_YEL}Reload posticipato{_R}  {b(cog_name)}  {_GRY}(player attivo){_R}")

def fmt_interaction_disabled(cmd_name: str, user_name: str) -> str:
    return tag("WARN", f"Bloccato  {b(cmd_name)}  {_GRY}→ {user_name}{_R}")

def fmt_botconfig_loaded(data: dict) -> str:
    keys = list(data.keys())
    return tag("BOOT", f"bot_config  {_GRY}{len(keys)} chiavi{_R}  {dim(str(keys))[:80]}")


# ── Setup ────────────────────────────────────────────────────────────────────
def setup_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(ColorFormatter())
    handler.addFilter(GatewayFilter())      # riformatta discord.gateway
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(handler)
    logging.getLogger("yt_dlp").setLevel(logging.ERROR)
