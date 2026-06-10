"""
tests/test_dev_permissions_static.py

Esegui dalla root del progetto con:
    python tests/test_dev_permissions_static.py
"""

from pathlib import Path


root = Path(__file__).resolve().parents[1]
dev_py = (root / "cogs" / "dev.py").read_text(encoding="utf-8")

restart_idx = dev_py.index('async def restart(')
maintenance_idx = dev_py.index('async def maintenance(')

restart_block = dev_py[dev_py.rfind("@app_commands.command", 0, restart_idx):restart_idx]
maintenance_block = dev_py[dev_py.rfind("@app_commands.command", 0, maintenance_idx):maintenance_idx]

assert "@dev_check" in restart_block, restart_block
assert "@owner_check" not in restart_block, restart_block
assert "@dev_check" in maintenance_block, maintenance_block
assert "@owner_check" not in maintenance_block, maintenance_block
assert "solo dev" in dev_py.lower()

print("OK: restart and maintenance are dev commands")
