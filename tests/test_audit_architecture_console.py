"""
tests/test_audit_architecture_console.py

Verifica che lo script di audit sia eseguibile anche su console Windows
con encoding legacy, dove caratteri Unicode decorativi possono rompere print().

Uso:
    python tests/test_audit_architecture_console.py
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


env = os.environ.copy()
env["PYTHONIOENCODING"] = "cp1252"

def run_tool(script_name: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / "tools" / script_name)],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
    )


result = run_tool("audit_architecture.py")
assert result.returncode == 0, (
    "audit_architecture.py deve restare portabile su console cp1252\n"
    f"stdout:\n{result.stdout}\n"
    f"stderr:\n{result.stderr}"
)
assert "Architecture Audit" in result.stdout

result = run_tool("check_logs.py")
assert result.returncode in (0, 1), (
    "check_logs.py deve completare l'audit senza crash di encoding\n"
    f"stdout:\n{result.stdout}\n"
    f"stderr:\n{result.stderr}"
)
assert "Log Audit" in result.stdout

print("OK: maintenance tool console output is portable")
