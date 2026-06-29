"""
Verifica che il budget resolver sia soft: superarlo non deve far fallire /play.

Esegui dalla root del progetto con:
    python tests/test_resolver_hard_timeout.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from core.source_resolver import SourceResolver
async def main() -> None:
    original_timeout = Config.RESOLVE_HARD_TIMEOUT_SECONDS
    original_max_wait = Config.RESOLVE_MAX_WAIT_SECONDS
    original_impl = SourceResolver._resolve_choices_impl

    async def slow_impl(cls, query, requester, requester_id, n=7):
        await asyncio.sleep(0.65)
        return ["late"]

    async def stuck_impl(cls, query, requester, requester_id, n=7):
        await asyncio.sleep(2.0)
        return ["too-late"]

    try:
        Config.RESOLVE_HARD_TIMEOUT_SECONDS = 0.15
        Config.RESOLVE_MAX_WAIT_SECONDS = 1.0
        SourceResolver._resolve_choices_impl = classmethod(slow_impl)
        t0 = time.perf_counter()
        result = await SourceResolver.resolve_choices("slow song", "tester", 1, n=1)
        elapsed = time.perf_counter() - t0

        Config.RESOLVE_MAX_WAIT_SECONDS = 0.30
        SourceResolver._resolve_choices_impl = classmethod(stuck_impl)
        t1 = time.perf_counter()
        stuck_result = await SourceResolver.resolve_choices("stuck song", "tester", 1, n=1)
        stuck_elapsed = time.perf_counter() - t1
    finally:
        Config.RESOLVE_HARD_TIMEOUT_SECONDS = original_timeout
        Config.RESOLVE_MAX_WAIT_SECONDS = original_max_wait
        SourceResolver._resolve_choices_impl = original_impl

    assert result == ["late"], result
    assert elapsed > 0.5, elapsed
    assert elapsed < 0.9, elapsed

    assert stuck_result == [], stuck_result
    assert stuck_elapsed < 0.8, stuck_elapsed


asyncio.run(main())
print("OK: resolver soft budget waits for late results but caps stuck searches")
