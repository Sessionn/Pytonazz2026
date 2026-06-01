"""
Gestore centralizzato della configurazione runtime persistente.
"""

import asyncio
import json
import logging

from core.constants import command_slug
from core.log_colors import tag
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
        log.error(tag("ERR", f"bot_config.json corrotto: {e} — uso defaults"))
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
        self._write_lock = asyncio.Lock()
        self._data = _load()
        keys = list(self._data.keys())
        log.debug(tag("BOOT", f"bot_config  {len(keys)} chiavi"))

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

    # ── Setters asincroni ─────────────────────────────────────────────────────

    async def set_status_interval(self, seconds: int) -> None:
        self._data["status_interval"] = max(30, int(seconds))
        await self._persist()

    async def set_log_channel(self, channel_id: int | None) -> None:
        self._data["log_channel_id"] = channel_id
        await self._persist()

    async def set_maintenance(self, value: bool) -> None:
        self._data["maintenance"] = bool(value)
        await self._persist()

    async def set_tts_volume(self, value: float) -> None:
        self._data["tts_volume"] = round(float(value), 2)
        await self._persist()

    async def disable_command(self, slug: str) -> bool:
        """Disabilita un comando. Restituisce True se e' stata una novita'."""
        s = command_slug(slug)
        if s not in self._data["disabled_commands"]:
            self._data["disabled_commands"].append(s)
            await self._persist()
            return True
        return False

    async def enable_command(self, slug: str) -> bool:
        """Riabilita un comando. Restituisce True se era effettivamente disabilitato."""
        s = command_slug(slug)
        if s in self._data["disabled_commands"]:
            self._data["disabled_commands"].remove(s)
            await self._persist()
            return True
        return False

    def is_command_disabled(self, slug: str) -> bool:
        return command_slug(slug) in self._data.get("disabled_commands", [])

    # ── Snapshot ──────────────────────────────────────────────────────────────

    def snapshot(self) -> dict:
        """Restituisce una copia immutabile della configurazione attuale."""
        return dict(self._data)

    # ── Reload ────────────────────────────────────────────────────────────────

    def reload(self) -> None:
        """Ricarica la configurazione dal disco (utile per hot-reload)."""
        self._data = _load()
        keys = list(self._data.keys())
        log.debug(tag("BOOT", f"bot_config  {len(keys)} chiavi"))


cfg = BotConfig()
