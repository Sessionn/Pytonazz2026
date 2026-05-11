"""Factory embed per il sistema /help."""
from __future__ import annotations

import discord

FIELD_MAX = 1024
DESC_MAX  = 4096
_BLANK    = "\u200b"


def trunc(text: str, limit: int = FIELD_MAX) -> str:
    if len(text) <= limit:
        return text
    return text[:limit - 1] + "…"


def build_command_embed(cmd, bot, cog_meta_fn, cmd_perm_fn, perm_badges, desc_prefix_markers) -> discord.Embed:
    """Embed dettaglio singolo comando."""
    from core.help_utils import cmd_full_name

    full_name   = cmd_full_name(cmd)
    cog_key     = getattr(cmd, "binding", None)
    cog_key_str = type(cog_key).__name__.lower() if cog_key else None
    icon, category = cog_meta_fn(bot, cog_key_str) if cog_key_str else ("⚙️", "Altro")

    raw_desc = cmd.description or "Nessuna descrizione disponibile."
    clean_desc = raw_desc
    for marker in desc_prefix_markers:
        if clean_desc.startswith(marker):
            clean_desc = clean_desc[len(marker):].strip()

    level = cmd_perm_fn(cmd)
    perm_label, perm_color = perm_badges.get(level, perm_badges["public"])

    embed = discord.Embed(
        title=f"`/{full_name}`",
        description=trunc(f"> {clean_desc}", DESC_MAX),
        color=perm_color,
    )
    embed.add_field(name="📂 Categoria", value=f"{icon} {category}", inline=True)
    embed.add_field(name="🔐 Permessi",  value=perm_label,           inline=True)
    embed.add_field(name=_BLANK, value=_BLANK, inline=False)

    params = [
        p for p in (cmd.parameters if hasattr(cmd, "parameters") else [])
        if p.name != "interaction"
    ]
    if params:
        lines = []
        for p in params:
            opt = " *(opzionale)*" if not p.required else ""
            lines.append(f"`{p.name}`{opt} — {p.description or '—'}")
        embed.add_field(name="📝 Parametri", value=trunc("\n".join(lines)), inline=False)

    usage = [f"/{full_name}"] + [
        f"<{p.name}>" if p.required else f"[{p.name}]" for p in params
    ]
    embed.add_field(name="⌨️ Utilizzo", value=trunc(f"`{' '.join(usage)}`"), inline=False)
    embed.set_footer(text=" [opzionale]")
    return embed


def build_category_pages(key: str, cmds: list, include_dev: bool, bot, cog_meta_fn, page_size: int = 10) -> list[discord.Embed]:
    """Lista embed paginati per una categoria."""
    from core.help_utils import cmd_full_name, clean_desc as _clean

    icon, label = cog_meta_fn(bot, key)
    color = 0x2F3136 if include_dev else 0x5865F2
    sorted_cmds = sorted(cmds, key=lambda c: c.name)
    pages = []
    for i in range(0, len(sorted_cmds), page_size):
        chunk = sorted_cmds[i: i + page_size]
        embed = discord.Embed(title=f"{icon} {label}", color=color)
        for cmd in chunk:
            embed.add_field(
                name=trunc(f"`/{cmd_full_name(cmd)}`", 256),
                value=trunc(_clean(cmd.description or "Nessuna descrizione.")),
                inline=False,
            )
        pages.append(embed)
    return pages


def build_home_embed(all_pages: dict, include_dev: bool, bot, cog_meta_fn) -> discord.Embed:
    """Embed home con riepilogo categorie."""
    color = 0x2F3136 if include_dev else 0x5865F2
    embed = discord.Embed(
        title="📚 Comandi disponibili" if not include_dev else "🔧 Comandi Dev",
        description="Usa il menu per navigare fra le categorie, oppure cerca un comando specifico con `/help`.",
        color=color,
    )
    items = list(all_pages.items())
    for i, (key, pages) in enumerate(items):
        icon, label = cog_meta_fn(bot, key)
        count = sum(len(p.fields) for p in pages)
        embed.add_field(name=f"{icon} {label}", value=f"`{count}` comandi", inline=True)
        remainder = (i + 1) % 3
        if i == len(items) - 1 and remainder != 0:
            for _ in range(3 - remainder):
                embed.add_field(name=_BLANK, value=_BLANK, inline=True)
    return embed
