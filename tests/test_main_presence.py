"""
Esegui dalla ROOT del progetto con:
    python tests/test_main_presence.py
"""

import asyncio
import os
import sys

os.environ.setdefault("SHOW_BANNER", "false")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import discord
import main
from core.bot_config import cfg

print("=" * 55)
print("TEST MAIN - intents members + maintenance presence")
print("=" * 55)

assert main.intents.members is True, "FAIL: intents.members deve essere True"
print("OK: intents.members = True")


async def run_checks():
    calls = []
    original_maintenance = cfg._data.get("maintenance", False)

    async def fake_change_presence(*, status=None, activity=None):
        calls.append((status, activity))

    main.bot.change_presence = fake_change_presence
    main.bot._current_presence_status = discord.Status.idle
    main.bot._current_presence_activity = discord.Game(name="Prima")
    main.bot._maintenance_presence_status = None
    main.bot._maintenance_presence_activity = None

    try:
        cfg._data["maintenance"] = True
        await main.bot.apply_maintenance_presence()

        status, activity = calls[-1]
        assert status == discord.Status.dnd, "FAIL: maintenance deve impostare status dnd"
        assert getattr(activity, "name", "") == "🚧 Manutenzione", "FAIL: activity manutenzione errata"
        assert main.bot._maintenance_presence_status == discord.Status.idle, "FAIL: status precedente non salvato"
        assert getattr(main.bot._maintenance_presence_activity, "name", "") == "Prima", "FAIL: activity precedente non salvata"
        print("OK: maintenance salva e applica la presence")

        cfg._data["maintenance"] = False
        await main.bot.restore_presence_after_maintenance()

        status, activity = calls[-1]
        assert status == discord.Status.idle, "FAIL: restore deve ripristinare lo status precedente"
        assert getattr(activity, "name", "") == "Prima", "FAIL: restore deve ripristinare l'activity precedente"
        assert main.bot._maintenance_presence_status is None, "FAIL: stato maintenance non pulito"
        assert main.bot._maintenance_presence_activity is None, "FAIL: activity maintenance non pulita"
        print("OK: maintenance ripristina la presence precedente")
    finally:
        cfg._data["maintenance"] = original_maintenance


asyncio.run(run_checks())

print("\n" + "=" * 55)
print("TUTTI I TEST MAIN PASSATI")
print("=" * 55)
