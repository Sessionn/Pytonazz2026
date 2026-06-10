from __future__ import annotations

import logging
import time
from pathlib import Path
from threading import Thread

from config import Config
from core.log_colors import _BGRN, _BRED, b, dim, hi, tag

DEFAULT_COGS = [
    "cogs.ai",
    "cogs.birthdays",
    "cogs.channel_control",
    "cogs.dj",
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


async def load_extensions(bot, cogs: list[str], log: logging.Logger) -> None:
    for cog in cogs:
        try:
            await bot.load_extension(cog)
            log.info(tag("COG", f"{b(cog.split('.')[-1])} caricato"))
        except Exception as exc:
            log.error(tag("COG", f"{cog} ERRORE  {exc}"))


def cog_path(cog: str) -> Path:
    return Path(*cog.split(".")).with_suffix(".py")


def snapshot_extension_mtimes(cogs: list[str]) -> dict[str, float]:
    result: dict[str, float] = {}
    for cog in cogs:
        path = cog_path(cog)
        if path.exists():
            result[str(path)] = path.stat().st_mtime
    return result


async def reload_modified_extensions(
    bot,
    cogs: list[str],
    previous_mtimes: dict[str, float],
    log: logging.Logger,
) -> dict[str, float]:
    current = snapshot_extension_mtimes(cogs)
    for path, mtime in current.items():
        if previous_mtimes.get(path, 0) == mtime:
            continue
        cog_name = path.replace("\\", "/").replace("/", ".").removesuffix(".py")
        try:
            await bot.reload_extension(cog_name)
            log.info(tag("COG", f"hot-reload  {b(cog_name.split('.')[-1])}"))
        except Exception as exc:
            log.error(tag("COG", f"hot-reload ERRORE  {cog_name}  {exc}"))
    return current


def start_dashboard_thread(bot_getter, log: logging.Logger) -> None:
    if not Config.CACHE_ENABLED:
        return

    def _run_dashboard() -> None:
        try:
            from waitress import serve
            from data.database.dashboard.app import create_app

            logging.getLogger("werkzeug").setLevel(logging.ERROR)
            while bot_getter() is None:
                time.sleep(0.05)
            flask_app = create_app(bot=bot_getter())
            flask_app.logger.setLevel(logging.ERROR)
            serve(
                flask_app,
                host=Config.DASHBOARD_HOST,
                port=Config.DASHBOARD_PORT,
                threads=8,
                clear_untrusted_proxy_headers=True,
            )
        except Exception:
            log.exception(tag("CACHE_DB", "Dashboard OFF  bootstrap fallito"))

    Thread(target=_run_dashboard, daemon=True, name="dashboard-server").start()
    log.info(
        tag(
            "CACHE_DB",
            f"Dashboard {hi('ON', _BGRN)}  {dim(f'{Config.DASHBOARD_HOST}:{Config.DASHBOARD_PORT}')}",
        )
    )


def log_runtime_paths(log: logging.Logger) -> None:
    ytdlp_path = Config.YTDLP_PATH
    ffmpeg_path = Config.FFMPEG_PATH
    cookie_file = Config.COOKIE_FILE

    log.info(
        tag(
            "PROXY",
            f"ytdlp   {hi('ON', _BGRN)}  {b(ytdlp_path)}"
            if ytdlp_path
            else f"ytdlp   {hi('OFF', _BRED)}  {dim('(non configurata in env)')}",
        )
    )
    log.info(
        tag(
            "PROXY",
            f"ffmpeg  {hi('ON', _BGRN)}  {b(ffmpeg_path)}"
            if ffmpeg_path
            else f"ffmpeg  {hi('OFF', _BRED)}  {dim('(non configurata in env)')}",
        )
    )
    log.info(
        tag(
            "COOKIE",
            f"cookie  {hi('ON', _BGRN)}  {b(cookie_file)}"
            if cookie_file
            else f"cookie  {hi('OFF', _BRED)}  {dim('(non configurata in env)')}",
        )
    )
