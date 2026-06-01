from __future__ import annotations

import logging
from typing import Optional

import discord

from core.log_colors import ch, tag

log = logging.getLogger("pitonazz.moderation_utils")


async def resolve_members(guild: discord.Guild, raw: str) -> list[discord.Member]:
    found: list[discord.Member] = []
    for token in raw.split():
        clean = token.strip("<@!>").strip()
        if not clean or not clean.isdigit():
            if clean:
                log.debug(tag("MOD", f"resolve_members: token non numerico ignorato: {clean!r}"))
            continue
        uid = int(clean)
        member = guild.get_member(uid)
        if member is None:
            try:
                member = await guild.fetch_member(uid)
            except discord.NotFound:
                log.warning(tag("MOD", f"resolve_members: utente ID {uid} non trovato nel server"))
            except discord.HTTPException as exc:
                log.warning(tag("MOD", f"resolve_members: errore fetch ID {uid}: {exc}"))
        if member and member not in found:
            found.append(member)
    return found


async def get_or_create_quarantine_channel(guild: discord.Guild, base_name: str) -> Optional[discord.VoiceChannel]:
    for channel in guild.voice_channels:
        if channel.name == base_name or channel.name.startswith(base_name + "-"):
            return channel

    existing_nums = set()
    for channel in guild.voice_channels:
        if channel.name.startswith(base_name + "-"):
            suffix = channel.name[len(base_name) + 1 :]
            if suffix.isdigit():
                existing_nums.add(int(suffix))

    if not existing_nums:
        final_name = base_name
    else:
        n = 1
        while n in existing_nums:
            n += 1
        final_name = f"{base_name}-{n}"

    try:
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(connect=False, view_channel=True),
            guild.me: discord.PermissionOverwrite(connect=True, move_members=True, view_channel=True),
        }
        channel = await guild.create_voice_channel(
            name=final_name,
            overwrites=overwrites,
            reason="Creazione canale quarantena automatica",
        )
        log.info(tag("MOD", f"quarantine channel creato {ch(channel.name)}"))
        return channel
    except (discord.Forbidden, discord.HTTPException) as exc:
        log.warning(tag("MOD", f"impossibile creare canale quarantena {base_name!r}: {exc}"))
        return None
