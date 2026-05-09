import asyncio
import json
import logging
import os
import random
import threading
import time
import traceback
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands, tasks
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from config import Config, validate_config, start_proxy_startup_check, start_cookie_startup_check
from core.bot_config import cfg
from core.log_colors import setup_logging
from core.banner import print_banner
from core.paths import CUSTOM_STATUSES_PATH, ensure_runtime_dirs
from assets.status_messages import STATUS_CYCLE
from core.constants import TYPE_MAP, STAT_MAP
from core.constants import command_slug
from core.log_colors import (
    fmt_sync_guild,
    tag, b,
)

print_banner()           # <-- banner prima di qualsiasi log
setup_logging(logging.INFO)
log = logging.getLogger("pitonazz.main")
logging.getLogger("pitonazz.spotify_enrich").setLevel(
    logging.DEBUG if Config.LOG_LEVEL == "DEBUG" else logging.INFO
)
ensure_runtime_dirs()

# Silenzia librerie esterne che spammano log INFO inutili
logging.getLogger("httpx").setLevel(logging.WARNING)

# Valida le variabili d'ambiente critiche — solleva RuntimeError se DISCORD_TOKEN manca
validate_config()
start_proxy_startup_check()
start_cookie_startup_check()

COGS_DIR = Path("cogs")

_base_cogs   = [f"cogs.{f.stem}" for f in COGS_DIR.glob("*.py") if f.stem != "__init__"]
_custom_cogs = (
    [f"cogs.custom.{f.stem}" for f in Path("cogs/custom").glob("*.py") if f.stem != "__init__"]
    if Path("cogs/custom").exists() else []
)
COGS = _base_cogs + _custom_cogs

# Derivato dinamicamente dai file presenti invece di essere hardcoded
_MUSIC_COGS = {
    f"cogs.{f.stem}"
    for f in COGS_DIR.glob("*.py")
    if f.stem in {"music", "filters"}
}


# ---------------------------------------------------------------------------
# Controllo aggiornamento yt-dlp
# ---------------------------------------------------------------------------

async def check_ytdlp_update() -> None:
    import importlib.metadata
    import httpx

    try:
        installed = importlib.metadata.version("yt-dlp")
    except importlib.metadata.PackageNotFoundError:
        log.warning(tag("YT-DLP", "yt-dlp non trovato nell'ambiente!"))
        return

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get("https://pypi.org/pypi/yt-dlp/json")
            if resp.status_code != 200:
                log.warning(tag("YT-DLP", f"PyPI ha risposto con status {resp.status_code}"))
                return
            payload = resp.json()
            latest = payload["info"]["version"]
    except Exception as e:
        log.warning(tag("YT-DLP", f"Impossibile controllare PyPI: {e}"))
        return

    if installed == latest:
        log.info(tag("YT-DLP", f"\u2705 Versione aggiornata  {b(installed)}"))
    else:
        log.warning(tag(
            "YT-DLP",
            f"\u26a0\ufe0f  Aggiornamento disponibile: "
            f"installato {b(installed)}  \u2192  ultima stabile {b(latest)}\n"
            f"          \u21b3 Esegui:  pip install -U yt-dlp"
        ))


# ---------------------------------------------------------------------------
# Hot-reload watchdog
# ---------------------------------------------------------------------------

class CogReloadHandler(FileSystemEventHandler):
    def __init__(self, bot):
        self.bot = bot
        self._last: dict[str, float] = {}
        self._debounce = 0.5

    def on_modified(self, event):
        if event.is_directory or not event.src_path.endswith(".py"):
            return
        path = Path(event.src_path)
        now = time.time()
        if now - self._last.get(str(path), 0) < self._debounce:
            return
        self._last[str(path)] = now

        # Calcola il nome del modulo dal path
        try:
            rel = path.relative_to(Path.cwd())
        except ValueError:
            return
        mod_name = ".".join(rel.with_suffix("").parts)
        if mod_name not in COGS:
            return
        asyncio.run_coroutine_threadsafe(self._reload(mod_name), self.bot.loop)

    async def _reload(self, mod_name: str):
        try:
            await self.bot.reload_extension(mod_name)
            log.info(tag("HOT-RELOAD", f"{b(mod_name)} ricaricato"))
        except commands.ExtensionNotLoaded:
            try:
                await self.bot.load_extension(mod_name)
                log.info(tag("HOT-RELOAD", f"{b(mod_name)} caricato (nuovo)"))
            except Exception as exc:
                log.error(tag("HOT-RELOAD", f"Errore caricamento {b(mod_name)}: {exc}"))
        except Exception as exc:
            log.error(tag("HOT-RELOAD", f"Errore reload {b(mod_name)}: {exc}"))


# ---------------------------------------------------------------------------
# Bot
# ---------------------------------------------------------------------------

class Pitonazz(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents, help_command=None)
        self._status_list: list[dict] = []
        self._status_index: int = 0
        self._guild_sync_counts: dict[int, int] = {}

    def reload_status_list(self):
        from core.paths import CUSTOM_STATUSES_PATH
        custom = []
        if CUSTOM_STATUSES_PATH.exists():
            try:
                custom = json.loads(CUSTOM_STATUSES_PATH.read_text(encoding="utf-8"))
            except Exception:
                pass
        statuses = list(STATUS_CYCLE)
        for e in custom:
            t = e.get("type", "playing")
            if isinstance(t, str):
                e["type"] = TYPE_MAP.get(t, discord.ActivityType.playing)
            statuses.append(e)
        self._status_list = statuses

    async def setup_hook(self):
        self.reload_status_list()
        for cog in COGS:
            try:
                await self.load_extension(cog)
                log.info(tag("COG", f"{b(cog)} caricato"))
            except Exception as exc:
                log.error(tag("COG", f"Errore caricamento {b(cog)}: {exc}"))
                traceback.print_exc()

        await self._sync_commands()

        # Hot-reload watchdog
        observer = Observer()
        handler = CogReloadHandler(self)
        observer.schedule(handler, str(COGS_DIR), recursive=True)
        observer.start()
        log.info(tag("WATCHDOG", f"Hot-reload attivo su {b(str(COGS_DIR))}"))

        # yt-dlp update check
        asyncio.create_task(check_ytdlp_update())

    async def _sync_commands(self):
        if Config.GUILD_IDS:
            self._guild_sync_counts.clear()
            for gid in Config.GUILD_IDS:
                guild_obj = self.get_guild(gid)
                if guild_obj is None:
                    log.warning(tag("SYNC", f"Guild {b(str(gid))} non trovata — bot non presente, sync saltato"))
                    continue
                g      = discord.Object(id=gid)
                self.tree.clear_commands(guild=g)
                self.tree.copy_global_to(guild=g)
                synced = await self.tree.sync(guild=g)
                self._guild_sync_counts[gid] = len(synced)
        else:
            synced = await self.tree.sync()
            log.info(tag("SYNC", f"Global  \u2192  {b(len(synced))} comandi"))

    async def on_ready(self):
        log.info(tag("READY", f"{b(str(self.user))}  online  ID: {self.user.id}"))
        for gid, count in self._guild_sync_counts.items():
            guild_obj = self.get_guild(gid)
            name = guild_obj.name if guild_obj else str(gid)
            log.info(fmt_sync_guild(gid, name, count))

        self.cycle_status.start()

    @tasks.loop(seconds=300)
    async def cycle_status(self):
        await self.apply_next_status()

    @cycle_status.before_loop
    async def before_cycle(self):
        await self.wait_until_ready()

    async def apply_next_status(self):
        if not self._status_list:
            return
        maintenance = await cfg.get_maintenance()
        if maintenance:
            return
        e = self._status_list[self._status_index % len(self._status_list)]
        self._status_index += 1
        act_type = e["type"] if isinstance(e["type"], discord.ActivityType) else TYPE_MAP.get(e["type"], discord.ActivityType.playing)
        activity = (
            discord.CustomActivity(name=e["name"])
            if act_type == discord.ActivityType.custom
            else discord.Activity(type=act_type, name=e["name"])
        )
        status_str = e.get("status", "online")
        status = STAT_MAP.get(status_str, discord.Status.online)
        await self.change_presence(activity=activity, status=status)

    async def apply_maintenance_presence(self):
        await self.change_presence(
            activity=discord.Activity(type=discord.ActivityType.watching, name="🛠️ Manutenzione in corso"),
            status=discord.Status.do_not_disturb,
        )

    async def on_app_command_error(
        self, inter: discord.Interaction, error: app_commands.AppCommandError
    ):
        cause = getattr(error, "original", error)
        if isinstance(cause, app_commands.CommandOnCooldown):
            await inter.response.send_message(
                f"\u23f3 Riprova tra **{cause.retry_after:.1f}s**.", ephemeral=True
            )
            return
        if isinstance(cause, app_commands.MissingPermissions):
            await inter.response.send_message(
                "\u274c Non hai i permessi per usare questo comando.", ephemeral=True
            )
            return
        cmd_name = inter.command.qualified_name if inter.command else "sconosciuto"
        guild_name = inter.guild.name if inter.guild else "DM"
        user_str = str(inter.user)
        log.error(
            tag("ERROR",
                f"Comando /{b(cmd_name)} | {b(user_str)} | {b(guild_name)}\n"
                f"          {type(cause).__name__}: {cause}"
            )
        )
        traceback.print_exc()
        msg = (
            f"\u274c Errore nel comando `/{cmd_name}`:\n"
            f"```{type(cause).__name__}: {str(cause)[:200]}```\n"
            f"**Server:** {inter.guild}\n\n"
            "Se il problema persiste, contatta il developer."
        )
        try:
            if inter.response.is_done():
                await inter.followup.send(msg, ephemeral=True)
            else:
                await inter.response.send_message(msg, ephemeral=True)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    bot = Pitonazz()
    bot.run(Config.DISCORD_TOKEN, log_handler=None)
