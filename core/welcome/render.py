from __future__ import annotations

import logging
from typing import Optional

import discord

from core.log_colors import tag
from core.welcome.assets import find_local_file, local_slot

log = logging.getLogger("pitonazz.welcome_render")


class SafeFormatMap(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def resolve_text(text: Optional[str], member: discord.Member | discord.User) -> Optional[str]:
    if text is None:
        return None
    guild = getattr(member, "guild", None)
    mapping = {
        "mention": member.mention,
        "name": member.name,
        "display_name": member.display_name,
        "guild": guild.name if guild else "Server",
        "count": guild.member_count if guild else 0,
    }
    try:
        return text.format_map(SafeFormatMap(mapping))
    except Exception as exc:
        log.warning(tag("WEL", f"placeholder format error: {exc}"))
        return text


def build_embed_and_files(
    cfg: dict,
    member: discord.Member | discord.User,
    guild_id: int,
    event: str,
) -> tuple[discord.Embed, list[discord.File]]:
    files: list[discord.File] = []

    def resolve_url(field: str) -> str | None:
        value = cfg.get(field)
        if not value:
            return None
        slot = local_slot(value)
        if slot:
            path = find_local_file(guild_id, event, slot)
            if path:
                files.append(discord.File(str(path), filename=path.name))
                return f"attachment://{path.name}"
            log.warning(tag("WEL", f"local image missing: {guild_id}/{event}/{slot}"))
            return None
        return value

    embed = discord.Embed(
        title=resolve_text(cfg.get("title"), member),
        description=resolve_text(cfg.get("description"), member),
        color=cfg.get("color", 0x5865F2),
    )

    if cfg.get("footer"):
        embed.set_footer(
            text=resolve_text(cfg["footer"], member),
            icon_url=resolve_url("footer_icon_url"),
        )

    thumb_url = resolve_url("thumbnail_url")
    if thumb_url:
        embed.set_thumbnail(url=thumb_url)

    image_url = resolve_url("image_url")
    if image_url:
        embed.set_image(url=image_url)

    if cfg.get("author_name"):
        embed.set_author(
            name=resolve_text(cfg["author_name"], member),
            icon_url=resolve_url("author_icon_url"),
        )

    for field in cfg.get("fields", []):
        embed.add_field(
            name=resolve_text(field.get("name", "\u200b"), member),
            value=resolve_text(field.get("value", "\u200b"), member),
            inline=field.get("inline", False),
        )

    return embed, files


def build_config_summary(cfg: dict, event: str) -> discord.Embed:
    fields_text = (
        "\n".join(
            f"**{i + 1}.** `{field['name']}` \u2014 {field['value'][:50]}"
            f"{'...' if len(field['value']) > 50 else ''}"
            f"{' *(inline)*' if field.get('inline') else ''}"
            for i, field in enumerate(cfg.get("fields", []))
        )
        or "*nessuno*"
    )
    enabled = cfg.get("enabled", True)
    enabled_mark = "\u2705" if enabled else "\u274c"
    enabled_icon = "\U0001f7e2" if enabled else "\U0001f534"
    channel_id = cfg.get("channel_id")
    channel_line = f"**Canale:** <#{channel_id}>" if channel_id else "**Canale:** *non impostato*"
    plain_text = cfg.get("plain_text", False)
    mode_line = "**Modo:** messaggio semplice (plain text)" if plain_text else "**Modo:** embed"

    def display_url(value: str | None) -> str:
        if not value:
            return "*nessuna*"
        slot = local_slot(value)
        return f"*locale ({slot})*" if slot else value

    lines = [
        channel_line,
        f"**Abilitato:** {enabled_mark}",
        mode_line,
        f"**Titolo:** {cfg.get('title') or '*vuoto*'}",
        f"**Descrizione:** {(cfg.get('description') or '')[:80] or '*vuota*'}",
        f"**Footer:** {cfg.get('footer') or '*nessuno*'}",
        f"**Footer icon:** {display_url(cfg.get('footer_icon_url'))}",
        f"**Colore:** `#{cfg.get('color', 0):06X}`",
        f"**Thumbnail:** {display_url(cfg.get('thumbnail_url'))}",
        f"**Immagine:** {display_url(cfg.get('image_url'))}",
        f"**Author:** {cfg.get('author_name') or '*nessuno*'}",
        f"**Author icon:** {display_url(cfg.get('author_icon_url'))}",
        f"**Fields ({len(cfg.get('fields', []))}):**\n{fields_text}",
    ]
    return discord.Embed(
        title=f"{enabled_icon} Config {event.capitalize()}",
        description="\n".join(lines),
        color=0x5865F2,
    )


def parse_hex_color(value: str) -> Optional[int]:
    normalized = value.strip().lstrip("#")
    if len(normalized) != 6:
        return None
    try:
        return int(normalized, 16)
    except ValueError:
        return None
