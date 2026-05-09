"""
Gestore centralizzato della configurazione runtime persistente.
"""

import asyncio
import json
import logging

from core.constants import command_slug
from core.log_colors import tag, dim
from core.paths import BOT_CONFIG_PATH, ensure_runtime_dirs

log = logging.getLogger("pitonazz.bot_config")

_PATH = BOT_CONFIG_PATH
ensure_runtime_dirs()

_DEFAULTS: dict = {
    "status_interval":   300,
    "log_channel_id":    None,
    "maintenance":       False,
    "tts_volume":        1.5,
    "disabled_commands": [],
}


def _load() -> dict:
    if not _PATH.exists():
        return dict(_DEFAULTS)
    try:
        data = json.loads(_PATH.read_text(encoding="utf-8"))
        return {**_DEFAULTS, **data}
    except Exception as e:
        log.error(tag("ERR", f"bot_config.json corrotto: {e} \u2014 uso defaults"))
        return dict(_DEFAULTS)


def _save(data: dict) -> None:
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    _PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


async def _save_async(write_lock: asyncio.Lock, data: dict) -> None:
    """Salva la configurazione in modo thread-safe tramite asyncio.Lock + run_in_executor."""
    async with write_lock:
        await asyncio.get_running_loop().run_in_executor(None, _save, data)


class BotConfig:
    def __init__(self):
        # Lock creato qui (dentro il running loop) per evitare il deprecation warning
        # di asyncio.Lock() istanziato fuori da un contesto asincrono (Python 3.10+).
        self._write_lock = asyncio.Lock()
        self._data = _load()
        keys = list(self._data.keys())
        log.info(tag("BOOT", f"bot_config  {len(keys)} chiavi  {dim(str(keys))[:80]}"))

    async def _persist(self) -> None:
        """Persiste _data su disco in modo sicuro (lock + executor)."""
        await _save_async(self._write_lock, self._data)

    @property
    def status_interval(self) -> int:
        return int(self._data.get("status_interval", 300))

    @property
    def log_channel_id(self) -> int | None:
        v = self._data.get("log_channel_id")
        return int(v) if v is not None else None

    @property
    def maintenance(self) -> bool:
        return bool(self._data.get("maintenance", False))

    @property
    def tts_volume(self) -> float:
        return float(self._data.get("tts_volume", 1.5))

    @property
    def disabled_commands(self) -> list[str]:
        return list(self._data.get("disabled_commands", []))

    @staticmethod
    def _normalize_command_name(name: str) -> str:
        return command_slug(name)

    def is_disabled(self, command_name: str) -> bool:
        name = self._normalize_command_name(command_name)
        if not name:
            return False
        disabled = {
            self._normalize_command_name(n)
            for n in self._data.get("disabled_commands", [])
            if str(n).strip()
        }
        if name in disabled:
            return True
        # Retrocompatibilità: vecchi salvataggi potevano contenere solo il nome foglia.
        if "_" in name and name.split("_")[-1] in disabled:
            return True
        return False

    async def set_status_interval(self, seconds: int) -> None:
        self._data["status_interval"] = seconds
        await self._persist()

    async def set_log_channel(self, channel_id: int | None) -> None:
        self._data["log_channel_id"] = channel_id
        await self._persist()

    async def set_maintenance(self, active: bool) -> None:
        self._data["maintenance"] = active
        await self._persist()

    async def set_tts_volume(self, volume: float) -> None:
        self._data["tts_volume"] = round(volume, 2)
        await self._persist()

    async def disable_command(self, name: str) -> bool:
        name = self._normalize_command_name(name)
        if not name:
            return False
        lst = self._data.setdefault("disabled_commands", [])
        if name in lst:
            return False
        lst.append(name)
        await self._persist()
        return True

    async def enable_command(self, name: str) -> bool:
        name = self._normalize_command_name(name)
        if not name:
            return False
        lst = self._data.setdefault("disabled_commands", [])
        if name not in lst:
            return False
        lst.remove(name)
        await self._persist()
        return True

    def reload(self) -> None:
        self._data = _load()
        keys = list(self._data.keys())
        log.info(tag("BOOT", f"bot_config  {len(keys)} chiavi  {dim(str(keys))[:80]}"))


cfg = BotConfig()
