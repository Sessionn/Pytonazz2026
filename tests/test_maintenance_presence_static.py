"""
tests/test_maintenance_presence_static.py

Esegui dalla root del progetto con:
    python tests/test_maintenance_presence_static.py
"""

from pathlib import Path


root = Path(__file__).resolve().parents[1]
main_py = (root / "main.py").read_text(encoding="utf-8")
dev_py = (root / "cogs" / "dev.py").read_text(encoding="utf-8")

assert "async def apply_maintenance_presence" in main_py
assert "async def restore_presence_after_maintenance" in main_py
assert "bot.apply_maintenance_presence = apply_maintenance_presence" in main_py
assert "bot.restore_presence_after_maintenance = restore_presence_after_maintenance" in main_py
assert "bot.remember_normal_presence = remember_normal_presence" in main_py
assert "await self.bot.restore_presence_after_maintenance()" in dev_py
assert "remember_normal_presence(status=status, activity=activity)" in dev_py
assert "hi(state_label, state_color)" in dev_py

print("OK: maintenance presence methods wired")
