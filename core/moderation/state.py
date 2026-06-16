from __future__ import annotations

import logging
from typing import Optional

import discord

from core.moderation.isolation_registry import save_quarantine_groups
from core.log_colors import tag

log = logging.getLogger("pitonazz.state")


def save_quarantine_state(quarantine_groups: dict[int, dict[int, dict]], log: logging.Logger) -> None:
    try:
        save_quarantine_groups(quarantine_groups)
    except OSError as exc:
        log.warning(tag("MOD", f"isolation registry save failed: {exc}"))


def can_moderate(actor: discord.Member, target: discord.Member) -> bool:
    return actor.guild.owner_id == actor.id or actor.top_role > target.top_role


def bot_can_moderate(bot_member: Optional[discord.Member], target: discord.Member) -> bool:
    return bool(bot_member and bot_member.top_role > target.top_role)


def all_deafened_uids(groups: dict[int, dict]) -> set[int]:
    result = set()
    for info in groups.values():
        result |= info["members"]
    return result


def all_quarantined_uids(groups: dict[int, dict]) -> dict[int, int]:
    result = {}
    for info in groups.values():
        for uid in info["members"]:
            result[uid] = info["channel_id"]
    return result


def group_for_uid(groups: dict[int, dict], uid: int) -> Optional[int]:
    for group_key, info in groups.items():
        if uid in info["members"]:
            return group_key
    return None
