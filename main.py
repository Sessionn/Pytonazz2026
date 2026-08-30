import asyncio
import json
import logging
import random

import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv

load_dotenv()

from config import Config
from core.cache_db import init_db
from core.bot_config import cfg
from core.dj_access import init_dj_access_controller
from core.log_colors import setup_logging
from core.banner import print_banner
from core.paths import CUSTOM_STATUSES_PATH, ensure_runtime_dirs
from core.runtime import (
    DEFAULT_COGS,
    ensure_ytdlp_current,
    load_extensions,
    log_runtime_paths,
    reload_modified_extensions,
    snapshot_extension_mtimes,
    start_dashboard_thread,
)
from monitoring.cookie_watchdog import start_cookie_watchdog
from assets.status_messages import STATUS_CYCLE
from core.constants import UNDISABLEABLE, command_slug

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
from core.log_colors import tag, b, hi, dim, _BGRN

log_runtime_paths(log)
ensure_ytdlp_current(log)

# ── Cache DB ─────────────────────────────────────────────────────────────────
init_db(enabled=Config.CACHE_ENABLED)

# ── Dashboard ────────────────────────────────────────────────────────────────
if Config.CACHE_ENABLED:
    start_dashboard_thread(lambda: globals().get("bot"), logging.getLogger("pitonazz.cache_db"))

# ── Bot setup ────────────────────────────────────────────────────────────────
intents = discord.Intents.all()
#intents = discord.Intents.default()
#intents.message_content = True
#intents.guilds = True
#intents.members = True 
#intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents)
init_dj_access_controller(bot)

COGS = list(DEFAULT_COGS)

_CHANNEL_CONTROL_LABELS = {
    "bot_commands_only": "solo comandi bot",
    "no_bot_commands": "comandi bot bloccati",
}


def _interaction_command_slug(inter: discord.Interaction) -> str:
    command = getattr(inter, "command", None)
    qualified_name = getattr(command, "qualified_name", None) or getattr(command, "name", "")
    if qualified_name:
        return command_slug(qualified_name)

    data = getattr(inter, "data", None) or {}
    names = [data.get("name", "")]
    options = data.get("options") or []
    while options:
        current = options[0] or {}
        # Discord option types: 1=subcommand, 2=subcommand group.
        if current.get("type") not in (1, 2):
            break
        names.append(current.get("name", ""))
        options = current.get("options") or []
    return command_slug(" ".join(name for name in names if name))


async def _is_dev_user(discord_user) -> bool:
    if discord_user.id in Config.DEV_IDS:
        return True
    return await bot.is_owner(discord_user)


@bot.tree.interaction_check
async def global_interaction_check(inter: discord.Interaction) -> bool:
    command_name = _interaction_command_slug(inter)
    if (
        command_name
        and command_name not in UNDISABLEABLE
        and cfg.is_command_disabled(command_name)
    ):
        log.warning(tag("WARN", f"comando disabilitato  {b(command_name)}  user={inter.user}"))
        if not inter.response.is_done():
            await inter.response.send_message(
                f"\u26d4 Il comando `/{command_name}` e' disabilitato al momento.",
                ephemeral=True,
            )
        raise app_commands.CheckFailure("command disabled")

    if not inter.guild_id or not inter.channel_id:
        return True
    if await _is_dev_user(inter.user):
        return True
    control = cfg.get_channel_control(inter.guild_id, inter.channel_id)
    if control != "no_bot_commands":
        return True
    label = _CHANNEL_CONTROL_LABELS.get(control, control)
    if not inter.response.is_done():
        await inter.response.send_message(
            f"\u274c Questo canale ha controllo **{label}**.",
            ephemeral=True,
        )
    raise app_commands.CheckFailure("channel blocks bot commands")


async def load_cogs():
    await load_extensions(bot, COGS, log)


# ── Watchdog hot-reload ──────────────────────────────────────────────────────
_cog_mtimes: dict[str, float] = {}


@tasks.loop(seconds=5)
async def watchdog():
    global _cog_mtimes
    _cog_mtimes = await reload_modified_extensions(bot, COGS, _cog_mtimes, log)


# ── Status rotation ──────────────────────────────────────────────────────────
custom_statuses: list[str] = []


def _load_custom_statuses() -> list:
    """Carica le attività custom da file. Supporta sia stringhe che dizionari."""
    try:
        if CUSTOM_STATUSES_PATH.exists():
            data = json.loads(CUSTOM_STATUSES_PATH.read_text(encoding="utf-8"))
            result = []
            for s in data:
                if isinstance(s, str) and s.strip():
                    result.append(s)
                elif isinstance(s, dict) and s.get("name"):
                    result.append(s)
            return result
    except Exception:
        pass
    return []


def _build_full_status_list() -> list:
    """Costruisce la lista completa STATUS_CYCLE + custom."""
    custom = _load_custom_statuses()
    return list(STATUS_CYCLE) + custom


def reload_status_list():
    """Ricarica la lista degli status da file e aggiorna bot._status_list."""
    bot._status_list = _build_full_status_list()
    log.debug(tag("STATUS", f"reload_status_list → {len(bot._status_list)} voci"))


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


@rotate_status.before_loop
async def before_rotate_status():
    await bot.wait_until_ready()


async def apply_next_status():
    pool = getattr(bot, "_status_list", None) or _build_full_status_list()
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
        activity=discord.Game(name="⚠️MANUTENZIONE⚠️"),
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
bot._status_list = _build_full_status_list()
bot.reload_status_list = reload_status_list
bot.rotate_status_task = rotate_status   # task loop — usato da /status interval


# ── Events ───────────────────────────────────────────────────────────────────
@bot.event
async def on_ready():
    global custom_statuses
    custom_statuses = _load_custom_statuses()
    bot._status_list = _build_full_status_list()

    log.info(tag("WATCHDOG", "Hot-reload attivo su cogs"))
    if not watchdog.is_running():
        watchdog.start()
    try:
        rotate_status.change_interval(seconds=cfg.status_interval)
    except Exception as e:
        log.error(tag("STATUS", f"errore status_interval salvato  {e}"))
    if not rotate_status.is_running():
        rotate_status.start()
    start_cookie_watchdog(bot, logger=logging.getLogger("pitonazz.cookie_watchdog"))

    if cfg.maintenance:
        try:
            await bot.apply_maintenance_presence()
        except Exception as e:
            log.error(tag("STATUS", f"errore apply_maintenance_presence  {e}"))
    else:
        try:
            await asyncio.sleep(3)
            await bot.apply_next_status()
        except Exception as e:
            log.error(tag("STATUS", f"errore apply_next_status  {e}"))

    try:
        synced = await bot.tree.sync()
        if bot.guilds:
            guild_info = f"{b(str(bot.guilds[0]))}  [{dim(str(bot.guilds[0].id))}]"
        else:
            guild_info = b("global")
        log.info(tag("SYNC", f"{guild_info}  -> {b(str(len(synced)))} comandi"))
    except Exception as e:
        log.error(tag("SYNC", f"errore sync  {e}"))

    log.info(tag("READY", f"{b(str(bot.user))}  {hi('online', _BGRN)}  ID: {dim(str(bot.user.id))}"))


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    log.error(tag("CMD_ERR", f"{ctx.command}  {error}"))


# ── Entry point ─────────────────────────────────────────────────────────────
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return
    if await _is_dev_user(message.author):
        await bot.process_commands(message)
        return
    control = cfg.get_channel_control(message.guild.id, message.channel.id)
    if control != "bot_commands_only":
        await bot.process_commands(message)
        return
    try:
        await message.delete()
    except discord.Forbidden:
        log.warning(tag("CHANCTL", f"delete Forbidden #{getattr(message.channel, 'name', message.channel.id)}"))
    except discord.NotFound:
        pass


async def main():
    async with bot:
        await load_cogs()
        _cog_mtimes.update(snapshot_extension_mtimes(COGS))
        await bot.start(Config.DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
