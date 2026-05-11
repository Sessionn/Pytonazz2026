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
ensure_runtime_dirs()

# Silenzia librerie esterne che spammano log INFO inutili
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("discord.gateway").setLevel(logging.WARNING)
logging.getLogger("discord.client").setLevel(logging.WARNING)
logging.getLogger("discord.http").setLevel(logging.WARNING)

# ── Proxy / ffmpeg / cookie ──────────────────────────────────────────────────
from core.log_colors import tag, b

def _log_proxy_flag(label: str, env_key: str) -> None:
    val = os.getenv(env_key, "").strip()
    status = b("ON") if val else "OFF"
    reason = f"  ({val})" if val else f"  (non configurata in env)"
    log.info(tag("PROXY", f"{label}{reason}") if not val else tag("PROXY", f"{label}{reason}"))
    log.info(tag("PROXY", f"{label}  {status}{reason}"))

_ytdlp_path  = os.getenv("YTDLP_PATH",  "").strip()
_ffmpeg_path = os.getenv("FFMPEG_PATH", "").strip()
_cookie_path = os.getenv("COOKIE_PATH", "").strip()

log.info(tag("PROXY",  f"ytdlp   {'ON  ' + b(_ytdlp_path)  if _ytdlp_path  else 'OFF  (non configurata in env)'}"))
log.info(tag("PROXY",  f"ffmpeg  {'ON  ' + b(_ffmpeg_path) if _ffmpeg_path else 'OFF  (non configurata in env)'}"))
log.info(tag("COOKIE", f"{'ON  ' + b(_cookie_path) if _cookie_path else 'OFF  (non configurata in env)'}"))

# ── Cache DB ─────────────────────────────────────────────────────────────────
init_db(enabled=Config.CACHE_ENABLED)

# ── Bot setup ────────────────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.voice_states = True

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


@tasks.loop(minutes=10)
async def rotate_status():
    pool = custom_statuses + STATUS_CYCLE
    if not pool:
        return
    chosen = random.choice(pool)
    await bot.change_presence(activity=discord.Game(name=chosen))


# ── Events ───────────────────────────────────────────────────────────────────
@bot.event
async def on_ready():
    global custom_statuses
    custom_statuses = _load_custom_statuses()

    log.info(tag("WATCHDOG", f"Hot-reload attivo su cogs"))
    watchdog.start()
    rotate_status.start()

    try:
        synced = await bot.tree.sync()
        log.info(tag("SYNC", f"{b(str(bot.guilds[0]))}  [{bot.guilds[0].id}]  -> {b(str(len(synced)))} comandi"))
    except Exception as e:
        log.error(tag("SYNC", f"errore sync  {e}"))

    log.info(tag("READY", f"{b(str(bot.user))} online  ID: {b(str(bot.user.id))}"))


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    log.error(tag("CMD_ERR", f"{ctx.command}  {error}"))


# ── Entry point ──────────────────────────────────────────────────────────────
async def main():
    async with bot:
        await load_cogs()
        _cog_mtimes.update(_snapshot_mtimes())
        await bot.start(Config.DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
