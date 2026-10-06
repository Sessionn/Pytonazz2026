"""
Il controllo globale degli slash command deve girare davvero: comandi
disabilitati, manutenzione e canali "no_bot_commands" vanno bloccati
dall'albero dei comandi del bot, i dev restano esenti.

Esegui dalla root del progetto con:
    python tests/test_global_interaction_check.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ["CACHE_ENABLED"] = "false"
os.environ["SHOW_BANNER"] = "false"

import core.runtime

core.runtime.ensure_ytdlp_current = lambda logger: None  # niente rete nei test

from discord import app_commands

import main
from config import Config

DEV_ID = 111
USER_ID = 222


class FakeResponse:
    def __init__(self):
        self.sent: list[str] = []

    def is_done(self) -> bool:
        return bool(self.sent)

    async def send_message(self, message, ephemeral=False):
        self.sent.append(message)


def interaction(name: str, user_id: int, channel_id: int = 10):
    return SimpleNamespace(
        command=None,  # non ancora risolto quando discord.py esegue il check
        data={"name": name, "options": []},
        user=SimpleNamespace(id=user_id),
        guild_id=1,
        channel_id=channel_id,
        response=FakeResponse(),
    )


async def run_check(inter) -> bool:
    try:
        return await main.bot.tree.interaction_check(inter)
    except app_commands.CheckFailure:
        return False


async def main_test() -> None:
    assert isinstance(main.bot.tree, main.PytonazzCommandTree)
    Config.DEV_IDS = [DEV_ID]

    async def not_owner(user):
        return False
    main.bot.is_owner = not_owner

    data = main.cfg._data
    saved = {key: data.get(key) for key in ("disabled_commands", "maintenance", "channel_controls")}
    main.cfg._persist = lambda: asyncio.sleep(0)  # non scrivere bot_config.json
    try:
        data.update(disabled_commands=[], maintenance=False, channel_controls={})
        assert await run_check(interaction("play", USER_ID))

        data["disabled_commands"] = ["play"]
        blocked = interaction("play", USER_ID)
        assert not await run_check(blocked)
        assert "disabilitato" in blocked.response.sent[0]
        assert not await run_check(interaction("play", DEV_ID)), "disabilitato vale anche per i dev"
        data["disabled_commands"] = []

        data["maintenance"] = True
        blocked = interaction("play", USER_ID)
        assert not await run_check(blocked)
        assert "manutenzione" in blocked.response.sent[0]
        assert await run_check(interaction("help", USER_ID))
        assert await run_check(interaction("play", DEV_ID))
        data["maintenance"] = False

        data["channel_controls"] = {"1": {"10": "no_bot_commands"}}
        assert not await run_check(interaction("play", USER_ID, channel_id=10))
        assert await run_check(interaction("play", USER_ID, channel_id=11))
        assert await run_check(interaction("play", DEV_ID, channel_id=10))
    finally:
        data.update(saved)


asyncio.run(main_test())
print("OK: controllo globale attivo (disabilitati, manutenzione, canali)")
