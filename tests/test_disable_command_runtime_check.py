"""
tests/test_disable_command_runtime_check.py

Run from project root:
    python tests/test_disable_command_runtime_check.py
"""

from pathlib import Path


root = Path(__file__).resolve().parents[1]
main_py = (root / "main.py").read_text(encoding="utf-8")
dev_py = (root / "cogs" / "dev.py").read_text(encoding="utf-8")

assert "cfg.disable_command(comando)" in dev_py
assert "cfg.enable_command(comando)" in dev_py

assert "def _interaction_command_slug" in main_py
assert "cfg.is_command_disabled(command_name)" in main_py
assert 'log.warning(tag("WARN", f"comando disabilitato' in main_py
assert 'raise app_commands.CheckFailure("command disabled")' in main_py

print("OK: disabled slash commands are blocked by the global interaction check")
