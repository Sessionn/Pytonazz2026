from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import aiohttp
import discord

from core.log_colors import tag
from core.paths import WELCOME_IMAGES_DIR

log = logging.getLogger("pitonazz.welcome_assets")

LOCAL_IMAGE_SLOTS = ("image", "thumbnail", "footer_icon", "author_icon")
NONE_WORDS = {"none", "nessuno", "nessuna", "-", ""}
_ERROR_PREFIX = "\u274c"


def local_key(slot: str) -> str:
    return f"__local:{slot}__"


def local_slot(value: str | None) -> str | None:
    if value and value.startswith("__local:") and value.endswith("__"):
        return value[8:-2]
    return None


def local_path(guild_id: int, event: str, slot: str, ext: str = "png") -> Path:
    return WELCOME_IMAGES_DIR / f"{guild_id}_{event}_{slot}.{ext}"


def find_local_file(guild_id: int, event: str, slot: str) -> Path | None:
    for ext in ("png", "jpg", "jpeg", "gif", "webp"):
        path = local_path(guild_id, event, slot, ext)
        if path.exists():
            return path
    return None


def delete_local_image(guild_id: int, event: str, slot: str) -> None:
    path = find_local_file(guild_id, event, slot)
    if not path:
        return
    try:
        path.unlink()
        log.debug(tag("WEL", f"deleted local image {path.name}"))
    except Exception as exc:
        log.warning(tag("WEL", f"failed to delete {path}: {exc}"))


async def save_local_image(
    guild_id: int,
    event: str,
    slot: str,
    attachment: discord.Attachment,
) -> tuple[str | None, str | None]:
    if not attachment.content_type or not attachment.content_type.startswith("image/"):
        return None, f"{_ERROR_PREFIX} Il file allegato non \u00e8 un'immagine."

    ext = attachment.content_type.split("/")[-1].split(";")[0].strip()
    if ext not in ("png", "jpg", "jpeg", "gif", "webp"):
        ext = "png"

    delete_local_image(guild_id, event, slot)
    dest = local_path(guild_id, event, slot, ext)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(attachment.url) as resp:
                if resp.status != 200:
                    return None, f"{_ERROR_PREFIX} Download immagine fallito (HTTP {resp.status})."
                dest.write_bytes(await resp.read())
        log.debug(tag("WEL", f"saved local image {dest.name} ({dest.stat().st_size // 1024} KB)"))
        return local_key(slot), None
    except Exception as exc:
        return None, f"{_ERROR_PREFIX} Errore nel salvataggio immagine: `{exc}`"


def is_none_value(value: Optional[str]) -> bool:
    return value is not None and value.strip().lower() in NONE_WORDS


async def resolve_image_input(
    guild_id: int,
    event: str,
    slot: str,
    url: Optional[str],
    upload: Optional[discord.Attachment],
) -> tuple[str | None, str | None]:
    if upload is not None:
        return await save_local_image(guild_id, event, slot, upload)
    if url is not None:
        if is_none_value(url):
            return "__REMOVE__", None
        return url.strip(), None
    return None, None
