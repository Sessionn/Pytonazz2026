"""
tests/test_bot_config_persistence.py

Esegui dalla root del progetto con:
    python tests/test_bot_config_persistence.py
"""

import asyncio
import os
import sys
import tempfile
import types
from pathlib import Path

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

import core.bot_config as bot_config


async def main():
    original_path = bot_config._PATH
    with tempfile.TemporaryDirectory() as tmpdir:
        test_path = Path(tmpdir) / "bot_config.json"
        bot_config._PATH = test_path
        try:
            config = bot_config.BotConfig()
            assert test_path.exists(), "BotConfig deve creare il file runtime se manca"
            assert config.maintenance is False

            await config.set_maintenance(True)
            await config.set_status_interval(12)
            await config.set_tts_volume(2.345)
            await config.set_log_channel(12345)
            await config.disable_command("Play")

            restored = bot_config.BotConfig()
            assert restored.maintenance is True
            assert restored.status_interval == 12
            assert restored.tts_volume == 2.35
            assert restored.log_channel_id == 12345
            assert restored.is_command_disabled("play") is True
        finally:
            bot_config._PATH = original_path


asyncio.run(main())
print("OK: bot config persists runtime settings")
