from __future__ import annotations

from typing import Optional

import discord

from core.moderation.state import bot_can_moderate, can_moderate


def validate_standard_target(
    *,
    actor: discord.Member,
    bot_member: Optional[discord.Member],
    target: discord.Member,
    action_label: str,
) -> Optional[str]:
    if target.id == actor.id:
        return f"❌ Non puoi {action_label} te stesso."
    if target.id == actor.guild.owner_id:
        return f"❌ Non puoi {action_label} il proprietario del server."
    if not can_moderate(actor, target):
        return "❌ Non puoi moderare questo utente (gerarchia ruoli)."
    if not bot_can_moderate(bot_member, target):
        return "❌ Non posso moderare questo utente (gerarchia ruoli)."
    return None
