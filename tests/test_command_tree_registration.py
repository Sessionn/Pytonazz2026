"""
tests/test_command_tree_registration.py

Run from project root:
    python tests/test_command_tree_registration.py
"""

import asyncio
import os
import sys

import discord
from discord import app_commands
from discord.ext import commands

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.constants import UNDISABLEABLE, command_slug
from core.runtime import DEFAULT_COGS


def _walk(item, prefix: str = ""):
    name = command_slug(f"{prefix} {item.name}".strip())
    if isinstance(item, app_commands.Command):
        yield name, item
        return
    if isinstance(item, app_commands.Group):
        for child in item.commands:
            yield from _walk(child, name)


async def main() -> None:
    intents = discord.Intents.none()
    bot = commands.Bot(command_prefix="!", intents=intents)

    loaded = []
    failures = []
    async with bot:
        for extension in DEFAULT_COGS:
            try:
                await bot.load_extension(extension)
                loaded.append(extension)
            except Exception as exc:
                failures.append((extension, repr(exc)))

        entries = []
        for item in bot.tree.get_commands():
            entries.extend(_walk(item))

    names = [name for name, _cmd in entries]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    missing_callbacks = sorted(
        name for name, cmd in entries
        if isinstance(cmd, app_commands.Command) and not callable(getattr(cmd, "callback", None))
    )
    missing_protected = sorted(name for name in UNDISABLEABLE if name not in names)

    assert not failures, failures
    assert len(loaded) == len(DEFAULT_COGS), (loaded, DEFAULT_COGS)
    assert len(entries) >= 90, len(entries)
    assert not duplicates, duplicates
    assert not missing_callbacks, missing_callbacks
    assert not missing_protected, missing_protected

    print(f"OK: command tree loads {len(loaded)} cogs and {len(entries)} slash command leaves")


asyncio.run(main())
