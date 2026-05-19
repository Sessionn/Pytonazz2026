from __future__ import annotations

import discord


_EMBED_RULER = "`" + "─" * 54 + "`"


def progress_bar(current: int, total: int, width: int = 18) -> str:
    if total > 0:
        filled = min(width, int(width * current / total))
        pct = int(100 * current / total)
        bar = "█" * filled + "░" * (width - filled)
        return f"`{bar}` {current}/{total} ({pct}%)"
    dots = "." * ((current % 3) + 1)
    return f"`caricamento{dots}` {current} tracce"


def batch_loading_embed(
    nome: str,
    requester: discord.Member,
    current: int = 0,
    total: int = 0,
) -> discord.Embed:
    return discord.Embed(
        description=(
            f"⏳ Caricamento tracce di **{nome}** in corso...\n"
            f"{progress_bar(current, total)}\n"
            f"👥 da {requester.mention}"
        ),
        color=0x5865F2,
    )


__all__ = ("_EMBED_RULER", "progress_bar", "batch_loading_embed")
