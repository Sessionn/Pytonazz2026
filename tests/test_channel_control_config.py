"""
tests/test_channel_control_config.py

Esegui dalla root del progetto con:
    python tests/test_channel_control_config.py
"""

import asyncio
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

discord_stub = types.SimpleNamespace(
    ActivityType=types.SimpleNamespace(
        playing="playing",
        watching="watching",
        listening="listening",
        competing="competing",
        custom="custom",
    ),
    Status=types.SimpleNamespace(
        online="online",
        idle="idle",
        dnd="dnd",
        invisible="invisible",
    ),
)
sys.modules.setdefault("discord", discord_stub)

from core.bot_config import BotConfig


async def main():
    config = BotConfig()
    original = dict(config._data)
    persisted = 0

    async def fake_persist():
        nonlocal persisted
        persisted += 1

    config._persist = fake_persist
    config._data = {"channel_controls": {}}

    assert config.channel_controls_for_guild(123) == {}
    assert config.get_channel_control(123, 456) is None

    changed = await config.set_channel_control(123, 456, "bot_commands_only")
    assert changed is True
    assert config.get_channel_control(123, 456) == "bot_commands_only"
    assert config.channel_controls_for_guild(123) == {456: "bot_commands_only"}

    changed_again = await config.set_channel_control(123, 456, "bot_commands_only")
    assert changed_again is False

    changed_mode = await config.set_channel_control(123, 456, "no_bot_commands")
    assert changed_mode is True
    assert config.get_channel_control(123, 456) == "no_bot_commands"

    removed = await config.remove_channel_control(123, 456)
    assert removed is True
    assert config.get_channel_control(123, 456) is None

    missing = await config.remove_channel_control(123, 456)
    assert missing is False
    assert persisted == 3

    config._data = original


asyncio.run(main())
print("OK: channel control config")
