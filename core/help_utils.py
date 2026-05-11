"""Logica di raccolta e classificazione comandi per /help.

Non contiene embed né Views — solo dati puri.
"""
from __future__ import annotations

from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from config import Config

# ── Costanti pubbliche ──────────────────────────────────────────────────────
PAGE_SIZE = 10

PRIORITY: list[str] = [
    "music", "fun", "birthdays", "welcome", "tts",
    "moderation", "roles", "quote", "filters",
]

HIDDEN_CMDS: frozenset[str] = frozenset({
    "welcome field_remove",
    "welcome field_list",
    "goodbye field_remove",
    "goodbye field_list",
})

PERM_BADGES: dict[str, tuple[str, int]] = {
    "public": ("Tutti gli utenti",                   0x5865F2),
    "admin":  ("❔ Richiede **Gestisci server**",     0xE67E22),
    "dev":    ("🔧 Solo **dev bot**",                 0x2F3136),
    "owner":  ("👑 Solo **owner bot**",               0x2F3136),
}

DESC_PREFIX_MARKERS: tuple[str, ...] = ("❔", "🔧", "👑")


# ── Helpers identità ────────────────────────────────────────────────────────

def is_dev(user_id: int) -> bool:
    ids = Config.DEV_IDS
    return bool(ids) and user_id in ids


def is_admin(inter: discord.Interaction) -> bool:
    if inter.guild is None:
        return False
    return inter.permissions.manage_guild or inter.permissions.administrator


# ── Helpers cog ─────────────────────────────────────────────────────────────

def cog_key(cmd) -> Optional[str]:
    binding = getattr(cmd, "binding", None)
    if binding:
        return type(binding).__name__.lower()
    return None


def get_cog_meta(bot: commands.Bot, key: str) -> tuple[str, str]:
    for cog in bot.cogs.values():
        if type(cog).__name__.lower() == key:
            return (
                getattr(type(cog), "COG_ICON",  "⚙️"),
                getattr(type(cog), "COG_LABEL", key.capitalize()),
            )
    return "⚙️", key.capitalize()


def get_cog_type(bot: commands.Bot, key: str) -> str:
    for cog in bot.cogs.values():
        if type(cog).__name__.lower() == key:
            return getattr(type(cog), "COG_TYPE", "public")
    return "public"


# ── Helpers permesso per comando ─────────────────────────────────────────────

def cmd_perm(cmd) -> str:
    """
    Legge il livello di permesso del comando.
    Priorità:
    1. `_cmd_perm` sulla callback (set da @perm(...))
    2. COG_TYPE del cog
    3. 'public' default
    """
    cb = getattr(cmd, "callback", None)
    if cb and hasattr(cb, "_cmd_perm"):
        return cb._cmd_perm
    binding = getattr(cmd, "binding", None)
    if binding:
        return getattr(type(binding), "COG_TYPE", "public")
    return "public"


def cmd_full_name(cmd) -> str:
    return getattr(cmd, "qualified_name", cmd.name)


def is_hidden(cmd) -> bool:
    return cmd_full_name(cmd) in HIDDEN_CMDS


def clean_desc(text: str) -> str:
    out = text or ""
    for marker in DESC_PREFIX_MARKERS:
        if out.startswith(marker):
            out = out[len(marker):].strip()
    return out


# ── Visibilità ───────────────────────────────────────────────────────────────

def visible_for(level: str, _is_dev: bool, _is_admin: bool) -> bool:
    if level in ("dev", "owner"):
        return _is_dev
    if level == "admin":
        return _is_admin or _is_dev
    return True


# ── Iteratori ────────────────────────────────────────────────────────────────

def iter_leaf_commands(bot: commands.Bot):
    """Genera tutti i comandi foglia (no ContextMenu) dall'albero."""
    def _walk(cmd):
        if isinstance(cmd, app_commands.ContextMenu):
            return
        if isinstance(cmd, app_commands.Command):
            yield cmd
        elif isinstance(cmd, app_commands.Group):
            for sub in cmd.commands:
                yield from _walk(sub)

    for cmd in bot.tree.get_commands():
        yield from _walk(cmd)


def collect_groups(
    bot: commands.Bot,
    include_dev: bool,
    _is_dev: bool,
    _is_admin: bool,
) -> dict[str, list]:
    groups: dict[str, list] = {}
    for cmd in iter_leaf_commands(bot):
        if is_hidden(cmd):
            continue
        key = cog_key(cmd)
        if key is None:
            continue
        level   = cmd_perm(cmd)
        is_dev_ = level in ("dev", "owner")
        if is_dev_ != include_dev:
            continue
        if not visible_for(level, _is_dev, _is_admin):
            continue
        groups.setdefault(key, []).append(cmd)
    return groups


def all_commands_flat(bot: commands.Bot, _is_dev: bool, _is_admin: bool) -> list:
    result = []
    for cmd in iter_leaf_commands(bot):
        if is_hidden(cmd):
            continue
        if cog_key(cmd) is None:
            continue
        if not visible_for(cmd_perm(cmd), _is_dev, _is_admin):
            continue
        result.append(cmd)
    return result


def build_all_pages(
    bot: commands.Bot,
    include_dev: bool,
    _is_dev: bool,
    _is_admin: bool,
) -> dict[str, list]:
    """Ritorna {cog_key: [embed, ...]} ordinato per PRIORITY."""
    from embeds.help_embeds import build_category_pages

    groups = collect_groups(bot, include_dev, _is_dev, _is_admin)
    ordered = sorted(
        groups.keys(),
        key=lambda k: (PRIORITY.index(k) if k in PRIORITY else len(PRIORITY), k),
    )
    result = {}
    for key in ordered:
        pages = build_category_pages(key, groups[key], include_dev, bot, get_cog_meta, PAGE_SIZE)
        if pages:
            result[key] = pages
    return result
