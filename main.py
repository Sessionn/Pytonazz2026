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
from discord.ext import commands, tasks
from dotenv import load_dotenv

load_dotenv()

from config import Config
from core.cache_db import init_db
from core.bot_config import cfg
from core.log_colors import setup_logging
from core.banner import print_banner
from core.paths import CUSTOM_STATUSES_PATH, ensure_runtime_dirs
from assets.status_messages import STATUS_CYCLE
from core.constants import TYPE_MAP, STAT_MAP
from core.constants import command_slug

print_banner()           # <-- banner prima di qualsiasi log
log_level = getattr(logging, Config.LOG_LEVEL, logging.INFO)
setup_logging(log_level)
log = logging.getLogger("pitonazz.main")
logging.getLogger("pitonazz.spotify_enrich").setLevel(
    logging.DEBUG if Config.LOG_LEVEL == "DEBUG" else logging.INFO
)
logging.getLogger("asyncio").setLevel(logging.INFO)
ensure_runtime_dirs()

# Silenzia librerie esterne che spammano log INFO inutili
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("discord.gateway").setLevel(logging.WARNING)
logging.getLogger("discord.client").setLevel(logging.WARNING)
logging.getLogger("discord.http").setLevel(logging.WARNING)

# ── Proxy / ffmpeg / cookie ──────────────────────────────────────────────────
from core.log_colors import tag, b, hi, dim, _BGRN, _BRED, _GRY

_ytdlp_path   = os.getenv("YTDLP_PATH",   "").strip()
_ffmpeg_path  = os.getenv("FFMPEG_PATH",  "").strip()
_cookie_file  = os.getenv("COOKIE_FILE",  "").strip()

log.info(tag("PROXY",  f"ytdlp   {hi('ON', _BGRN)}  {b(_ytdlp_path)}"  if _ytdlp_path  else f"ytdlp   {hi('OFF', _BRED)}  {dim('(non configurata in env)')}"))
log.info(tag("PROXY",  f"ffmpeg  {hi('ON', _BGRN)}  {b(_ffmpeg_path)}" if _ffmpeg_path  else f"ffmpeg  {hi('OFF', _BRED)}  {dim('(non configurata in env)')}"))
log.info(tag("COOKIE", f"cookie  {hi('ON', _BGRN)}  {b(_cookie_file)}" if _cookie_file  else f"cookie  {hi('OFF', _BRED)}  {dim('(non configurata in env)')}"))

# ── Cache DB ─────────────────────────────────────────────────────────────────
init_db(enabled=Config.CACHE_ENABLED)

# ── Dashboard ────────────────────────────────────────────────────────────────
if Config.CACHE_ENABLED:
    import threading, os, sys, logging

    def _run_dashboard():
        _devnull = open(os.devnull, "w")
        sys.stderr = _devnull
        sys.stdout = _devnull          # werkzeug a volte usa stdout

        from data.database.dashboard.app import create_app
        logging.getLogger("werkzeug").setLevel(logging.ERROR)

        flask_app = create_app()
        flask_app.logger.setLevel(logging.ERROR)
        flask_app.run(
            host=Config.DASHBOARD_HOST,
            port=Config.DASHBOARD_PORT,
            debug=False,
            use_reloader=False,
        )

    t = threading.Thread(target=_run_dashboard, daemon=True)
    t.start()

    _dash_log = logging.getLogger("pitonazz.cache_db")
    _dash_log.info(tag("CACHE_DB", f"Dashboard {hi('ON', _BGRN)}  {dim(f'http://{Config.DASHBOARD_HOST}:{Config.DASHBOARD_PORT}')}"))

# ── Bot setup ────────────────────────────────────────────────────────────────
intents = discord.Intents.all()
#intents = discord.Intents.default()
#intents.message_content = True
#intents.guilds = True
#intents.members = True 
#intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents)

COGS = [
    "cogs.ai",
    "cogs.birthdays",
    "cogs.dev",
    "cogs.dev_audio",
    "cogs.dev_cache",
    "cogs.filters",
    "cogs.fun",
    "cogs.help",
    "cogs.moderation",
    "cogs.music",
    "cogs.tts",
    "cogs.welcome",
]


async def load_cogs():
    for cog in COGS:
        try:
            await bot.load_extension(cog)
            log.info(tag("COG", f"{b(cog.split('.')[-1])} caricato"))
        except Exception as e:
            log.error(tag("COG", f"{cog} ERRORE  {e}"))


# ── Watchdog hot-reload ──────────────────────────────────────────────────────
_cog_mtimes: dict[str, float] = {}


def _cog_path(cog: str) -> Path:
    return Path(*cog.split(".")).with_suffix(".py")


def _snapshot_mtimes() -> dict[str, float]:
    result = {}
    for cog in COGS:
        p = _cog_path(cog)
        if p.exists():
            result[str(p)] = p.stat().st_mtime
    return result


@tasks.loop(seconds=5)
async def watchdog():
    global _cog_mtimes
    current = _snapshot_mtimes()
    for path, mtime in current.items():
        if _cog_mtimes.get(path, 0) != mtime:
            cog_name = path.replace("\\", "/").replace("/", ".").removesuffix(".py")
            try:
                await bot.reload_extension(cog_name)
                log.info(tag("COG", f"hot-reload  {b(cog_name.split('.')[-1])}"))
            except Exception as e:
                log.error(tag("COG", f"hot-reload ERRORE  {cog_name}  {e}"))
    _cog_mtimes = current


# ── Status rotation ──────────────────────────────────────────────────────────
custom_statuses: list[str] = []


def _load_custom_statuses() -> list[str]:
    try:
        if CUSTOM_STATUSES_PATH.exists():
            data = json.loads(CUSTOM_STATUSES_PATH.read_text(encoding="utf-8"))
            return [s for s in data if isinstance(s, str) and s.strip()]
    except Exception:
        pass
    return []


def _build_activity(entry) -> discord.BaseActivity:
    """Costruisce un oggetto Activity da un dict o da una stringa.

    I dict in STATUS_CYCLE hanno la forma:
        {"type": discord.ActivityType.X, "name": "...", "status": "online"|"idle"|...}
    Le stringhe nei custom_statuses vengono trattate come discord.Game.
    """
    if isinstance(entry, str):
        return discord.Game(name=entry)
    activity_type = entry.get("type", discord.ActivityType.playing)
    name = entry.get("name", "")
    if activity_type == discord.ActivityType.listening:
        return discord.Activity(type=discord.ActivityType.listening, name=name)
    if activity_type == discord.ActivityType.watching:
        return discord.Activity(type=discord.ActivityType.watching, name=name)
    if activity_type == discord.ActivityType.competing:
        return discord.Activity(type=discord.ActivityType.competing, name=name)
    if activity_type == discord.ActivityType.streaming:
        return discord.Streaming(name=name, url="https://twitch.tv/placeholder")
    # playing e custom ricadono su Game
    return discord.Game(name=name)


def _build_status(entry) -> discord.Status:
    """Ricava il discord.Status dal campo 'status' dell'entry."""
    if isinstance(entry, str):
        return discord.Status.online
    raw = entry.get("status", "online")
    return getattr(discord.Status, raw, discord.Status.online)


@tasks.loop(minutes=10)
async def rotate_status():
    if cfg.maintenance:
        return
    await bot.apply_next_status()


async def apply_next_status():
    pool = STATUS_CYCLE + ([entry for entry in custom_statuses] if custom_statuses else [])
    if not pool:
        return
    chosen = random.choice(pool)
    activity = _build_activity(chosen)
    status   = _build_status(chosen)
    await bot.change_presence(status=status, activity=activity)
    bot.remember_normal_presence(status=status, activity=activity)


def remember_normal_presence(
    status: discord.Status | None = None,
    activity: discord.BaseActivity | None = None,
):
    if cfg.maintenance:
        return
    bot._last_normal_presence = {
        "activity": activity,
        "status": status or discord.Status.online,
    }


async def apply_maintenance_presence():
    prev = getattr(bot, "_last_normal_presence", None)
    if prev:
        bot._previous_presence = dict(prev)
    elif not getattr(bot, "_maintenance_presence_saved", False):
        bot._previous_presence = {"activity": bot.activity, "status": bot.status}
    bot._maintenance_presence_saved = True
    await bot.change_presence(
        status=discord.Status.dnd,
        activity=discord.Game(name="Maintenance Mode"),
    )


async def restore_presence_after_maintenance():
    prev = getattr(bot, "_previous_presence", None)
    bot._maintenance_presence_saved = False
    bot._previous_presence = None
    if prev:
        await bot.change_presence(
            status=prev.get("status") or discord.Status.online,
            activity=prev.get("activity"),
        )
        bot.remember_normal_presence(
            status=prev.get("status") or discord.Status.online,
            activity=prev.get("activity"),
        )
    else:
        await bot.apply_next_status()


bot.apply_next_status = apply_next_status
bot.remember_normal_presence = remember_normal_presence
bot.apply_maintenance_presence = apply_maintenance_presence
bot.restore_presence_after_maintenance = restore_presence_after_maintenance


# ── Events ───────────────────────────────────────────────────────────────────
@bot.event
async def on_ready():
    global custom_statuses
    custom_statuses = _load_custom_statuses()

    log.info(tag("WATCHDOG", "Hot-reload attivo su cogs"))
    if not watchdog.is_running():
        watchdog.start()
    if not rotate_status.is_running():
        rotate_status.start()

    try:
        synced = await bot.tree.sync()
        log.info(tag("SYNC", f"{b(str(bot.guilds[0]))}  [{dim(str(bot.guilds[0].id))}]  -> {b(str(len(synced)))} comandi"))
    except Exception as e:
        log.error(tag("SYNC", f"errore sync  {e}"))

    log.info(tag("READY", f"{b(str(bot.user))}  {hi('online', _BGRN)}  ID: {dim(str(bot.user.id))}"))


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    log.error(tag("CMD_ERR", f"{ctx.command}  {error}"))


# ── Entry point ─────────────────────────────────────────────────────────────
async def main():
    async with bot:
        await load_cogs()
        _cog_mtimes.update(_snapshot_mtimes())
        await bot.start(Config.DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
