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

from config import Config, validate_config, start_proxy_startup_check
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
logging.getLogger("google_genai.models").setLevel(logging.WARNING)
logging.getLogger("google_genai").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

# Valida le variabili d'ambiente critiche — solleva RuntimeError se DISCORD_TOKEN manca
validate_config()
start_proxy_startup_check()

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

class Pitonazz(commands.AutoShardedBot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.voice_states    = True
        intents.message_content = True
        intents.members         = True
        super().__init__(
            # Risponde solo se menzionato; nessun prefix text-command attivo.
            command_prefix=commands.when_mentioned_or(),
            intents=intents,
            help_command=None,
        )
        self._status_list  = self._build_status_list()
        self._status_index = random.randint(0, len(self._status_list) - 1)
        self._guild_sync_counts: dict[int, int] = {}

    def _build_status_list(self) -> list:
        base = list(STATUS_CYCLE)
        custom_path = CUSTOM_STATUSES_PATH
        if custom_path.exists():
            try:
                data = json.loads(custom_path.read_text(encoding="utf-8"))
                for entry in data:
                    t = TYPE_MAP.get(entry.get("type", "playing"), discord.ActivityType.playing)
                    base.append({"type": t, "name": entry["name"], "status": entry.get("status", "online")})
            except Exception as e:
                log.error(tag("ERR", f"Failed  {b('custom_statuses.json')}  \u2192  {e}"))
        return base

    def reload_status_list(self):
        self._status_list = self._build_status_list()
        log.info(tag("RELOAD", f"Status list  {b(len(self._status_list))} voci"))

    async def _apply_status_entry(self, entry: dict) -> None:
        act_type = entry["type"]
        if act_type == discord.ActivityType.custom:
            activity = discord.CustomActivity(name=entry["name"])
        else:
            activity = discord.Activity(type=act_type, name=entry["name"])
        status = STAT_MAP.get(entry.get("status", "online"), discord.Status.online)
        await self.change_presence(activity=activity, status=status)

    async def apply_next_status(self) -> None:
        if not self._status_list:
            return
        entry = self._status_list[self._status_index % len(self._status_list)]
        await self._apply_status_entry(entry)
        self._status_index += 1

    async def apply_maintenance_presence(self) -> None:
        await self.change_presence(
            activity=discord.CustomActivity(name="🚧 IN MANUTENZIONE 🚧"),
            status=discord.Status.dnd,
        )

    def has_active_players(self) -> bool:
        for cog in self.cogs.values():
            players = getattr(cog, "_players", {})
            if any(p.current for p in players.values()):
                return True
        return False

    async def setup_hook(self):
        await check_ytdlp_update()

        async def _is_privileged(inter: discord.Interaction) -> bool:
            if inter.user.id in Config.DEV_IDS:
                return True
            return await self.is_owner(inter.user)

        async def _global_check(inter: discord.Interaction) -> bool:
            cmd = inter.command
            if cmd is None:
                return True
            cmd_name = command_slug(getattr(cmd, "qualified_name", cmd.name))
            is_privileged = await _is_privileged(inter)
            if cfg.maintenance and not is_privileged and cmd.name != "help":
                if not inter.response.is_done():
                    await inter.response.send_message(
                        "\ud83d\udee0\ufe0f Il bot è in **manutenzione**. Riprova più tardi.",
                        ephemeral=True,
                    )
                return False
            if cfg.is_disabled(cmd_name):
                if is_privileged:
                    return True
                log.info(tag("WARN", f"Bloccato  {b(cmd_name)}  \u2192  {inter.user}"))
                if not inter.response.is_done():
                    await inter.response.send_message(
                        f"\U0001f6ab Il comando `/{cmd_name}` \u00e8 attualmente **disabilitato**.",
                        ephemeral=True,
                    )
                return False
            return True

        self.tree.interaction_check = _global_check

        for cog in COGS:
            try:
                await self.load_extension(cog)
                log.info(tag("BOOT", f"Loaded  {b(cog.split('.')[-1])}  \u2190  {cog}"))
            except Exception as e:
                log.error(tag("ERR", f"Failed  {b(cog.split('.')[-1])}  \u2192  {e}"))

        await self._sync_commands()
        self.cycle_status.change_interval(seconds=cfg.status_interval)
        self.cycle_status.start()
        log.info(tag("BOOT", f"Status interval  \u2192  {b(cfg.status_interval)}s  ({cfg.status_interval/60:.0f} min)"))
        if cfg.disabled_commands:
            formatted = "  ".join(f"\u25cf {b(n)}" for n in cfg.disabled_commands)
            log.info(tag("BOOT", f"Comandi disabilitati: {formatted}"))
        else:
            log.info(tag("BOOT", "Comandi disabilitati: nessuno"))

    async def _sync_commands(self):
        if Config.GUILD_IDS:
            self._guild_sync_counts.clear()
            for gid in Config.GUILD_IDS:
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

    async def process_commands(self, message: discord.Message) -> None:
        """Disable text-command parsing and keep the bot slash-only."""
        # Slash-only bot: no text commands should be processed.
        return

    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError) -> None:
        """Silence CommandNotFound noise while preserving other command errors."""
        if isinstance(error, commands.CommandNotFound):
            return
        await super().on_command_error(ctx, error)

    async def on_app_command_error(
        self, inter: discord.Interaction, error: app_commands.AppCommandError
    ):
        if isinstance(error, app_commands.CheckFailure):
            if not inter.response.is_done():
                await inter.response.send_message(
                    "\u274c Non hai i permessi per usare questo comando.",
                    ephemeral=True,
                )
            return

        # Log dell'errore sempre, anche se il canale log non è disponibile
        log.error(tag(
            "ERR",
            f"Comando: /{inter.command.name if inter.command else '?'} "
            f"Utente: {inter.user} — {error}"
        ))

        ch_id = cfg.log_channel_id
        if ch_id:
            ch = self.get_channel(ch_id)
            if ch:
                tb = "".join(traceback.format_exception(type(error), error, error.__traceback__))
                embed = discord.Embed(
                    title="\u274c Errore comando",
                    description=(
                        f"**Comando:** `/{inter.command.name if inter.command else '?'}`\n"
                        f"**Utente:** {inter.user} (`{inter.user.id}`)\n"
                        f"**Server:** {inter.guild}\n\n"
                        f"```py\n{tb[:1800]}\n```"
                    ),
                    color=0xe74c3c,
                )
                try:
                    await ch.send(embed=embed)
                except Exception:
                    pass
            else:
                log.warning(tag(
                    "ERR",
                    f"log_channel_id={ch_id} configurato ma canale non trovato in cache. "
                    "Verificare che il bot abbia accesso al canale e che la cache sia popolata."
                ))

    @tasks.loop(seconds=300)
    async def cycle_status(self):
        if cfg.maintenance:
            await self.apply_maintenance_presence()
            return
        await self.apply_next_status()

    @cycle_status.before_loop
    async def _before_cycle(self):
        await self.wait_until_ready()


class CogReloader(FileSystemEventHandler):
    def __init__(self, bot: Pitonazz, loop: asyncio.AbstractEventLoop):
        self.bot       = bot
        self.loop      = loop
        self._cooldown: dict = {}
        self._lock = threading.Lock()

    def on_modified(self, event):
        if event.is_directory:
            return
        path = Path(event.src_path)
        if path.suffix != ".py" or "cogs" not in path.parts:
            return
        # Usa time.monotonic() invece di self.loop.time() per thread-safety garantita
        now = time.monotonic()
        with self._lock:
            if now - self._cooldown.get(path, 0.0) < 1.5:
                return
            self._cooldown[path] = now
        parts = path.parts
        idx   = parts.index("cogs")
        ext   = ".".join(parts[idx:]).removesuffix(".py")
        log.info(tag("WATCH", f"Modifica rilevata  \u2192  {b(ext)}"))
        asyncio.run_coroutine_threadsafe(self._reload(ext), self.loop)

    async def _reload(self, ext: str):
        if ext in _MUSIC_COGS and self.bot.has_active_players():
            log.warning(tag("WATCH", f"Reload posticipato  {b(ext)}  (player attivo)"))
            return
        try:
            await self.bot.reload_extension(ext)
            log.info(tag("RELOAD", f"{b(ext.split('.')[-1])}  \u2190 {ext}"))
        except Exception as e:
            log.error(tag("ERR", f"Reload fallito  {b(ext)}  \u2192  {e}"))


async def main():
    bot      = Pitonazz()
    loop     = asyncio.get_running_loop()
    observer = Observer()
    observer.schedule(CogReloader(bot, loop), path="cogs", recursive=True)
    observer.start()
    try:
        async with bot:
            await bot.start(Config.DISCORD_TOKEN)
    finally:
        observer.stop()
        observer.join()


if __name__ == "__main__":
    asyncio.run(main())
