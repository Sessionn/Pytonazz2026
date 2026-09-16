"""
tests/test_command_tree_registration.py

Run from project root:
    python tests/test_command_tree_registration.py
"""

import asyncio
import os
import sys
from types import SimpleNamespace

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

        signatures = {name: [(p.name, p.type, p.required) for p in cmd.parameters]
                      for name, cmd in entries}
        original = bot.get_cog('Music')
        player = SimpleNamespace()
        original._players[123] = player
        original._play_next_ticket[123] = 7
        moderation = bot.get_cog('Moderation')
        moderation._muted_mic[123] = {456}
        old_watchdog = moderation._quarantine_watchdog.get_task()
        for _ in range(2):
            for extension in ('cogs.music', 'cogs.moderation'):
                await bot.reload_extension(extension)
            reloaded = [entry for item in bot.tree.get_commands() for entry in _walk(item)]
            assert len(reloaded) == len(entries)
            assert signatures == {name: [(p.name, p.type, p.required) for p in cmd.parameters]
                                  for name, cmd in reloaded}
            music = bot.get_cog('Music')
            assert music is not original
            assert music._players[123] is player
            assert music._play_next_ticket[123] == 7
            assert player._on_autoplay.__self__ is music
            assert player._on_state_change.__self__ is music
            assert bot.get_cog('Moderation')._muted_mic[123] == {456}
        await asyncio.sleep(0)
        assert old_watchdog.done()
        player._on_cleanup(123)
        assert 123 not in music._players

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
