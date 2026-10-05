"""
tests/run_all.py

Esegue ogni test script-style di `tests/` in un processo separato (i test
modificano Config/env a livello di modulo, quindi non vanno caricati tutti
nello stesso interprete) e stampa un riepilogo.

Uso dalla root del progetto:
    python tests/run_all.py            # tutti i test
    python tests/run_all.py dashboard  # solo i file che contengono "dashboard"
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = ROOT / "tests"
TIMEOUT_SECONDS = 180


def main(argv: list[str]) -> int:
    pattern = argv[1] if len(argv) > 1 else ""
    files = sorted(
        path for path in TESTS_DIR.glob("test_*.py")
        if pattern in path.name
    )
    if not files:
        print(f"Nessun test trovato per {pattern!r}")
        return 1

    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    failures: list[tuple[str, str]] = []
    started = time.perf_counter()

    for path in files:
        t0 = time.perf_counter()
        try:
            result = subprocess.run(
                [sys.executable, str(path)],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=TIMEOUT_SECONDS,
            )
            ok = result.returncode == 0
            detail = (result.stdout + result.stderr).strip()
        except subprocess.TimeoutExpired:
            ok = False
            detail = f"timeout dopo {TIMEOUT_SECONDS}s"
        elapsed = time.perf_counter() - t0
        print(f"[{'PASS' if ok else 'FAIL'}] {path.name}  ({elapsed:.1f}s)")
        if not ok:
            failures.append((path.name, detail))

    total = time.perf_counter() - started
    print(f"\n{len(files) - len(failures)}/{len(files)} test passati in {total:.1f}s")
    for name, detail in failures:
        tail = "\n".join(detail.splitlines()[-15:])
        print(f"\n--- {name} ---\n{tail}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
