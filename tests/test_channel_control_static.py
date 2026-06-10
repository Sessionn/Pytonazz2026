"""
tests/test_channel_control_static.py

Esegui dalla root del progetto con:
    python tests/test_channel_control_static.py
"""

from pathlib import Path


root = Path(__file__).resolve().parents[1]
runtime_py = (root / "core" / "runtime.py").read_text(encoding="utf-8")
main_py = (root / "main.py").read_text(encoding="utf-8")
cog_py = (root / "cogs" / "channel_control.py").read_text(encoding="utf-8")

assert '"cogs.channel_control"' in runtime_py
assert "@bot.tree.interaction_check" in main_py
assert "async def channel_control_interaction_check" in main_py
assert 'control != "no_bot_commands"' in main_py
assert "async def on_message" in main_py
assert 'control != "bot_commands_only"' in main_py
assert "await bot.process_commands(message)" in main_py
assert 'name="channel_control"' in cog_py
assert 'name="set"' in cog_py
assert 'name="remove"' in cog_py
assert 'name="list"' in cog_py

print("OK: channel control runtime wiring")
