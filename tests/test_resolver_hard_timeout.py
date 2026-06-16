"""
Verifica lo SLA hard-timeout delle API pubbliche del resolver.

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
from core.source_resolver.models import TrackInfo


async def main() -> None:
    original_timeout = Config.RESOLVE_HARD_TIMEOUT_SECONDS
    original_impl = SourceResolver._resolve_choices_impl
    original_fallback = SourceResolver._resolve_fallback_track

    async def slow_impl(cls, query, requester, requester_id, n=7):
        await asyncio.sleep(2.0)
        return ["late"]

    async def fallback(cls, query, requester, requester_id):
        return TrackInfo(
            title="Fallback Song",
            webpage_url="https://www.youtube.com/watch?v=fallback",
            duration=0,
            thumbnail="",
            requester=requester,
            requester_id=requester_id,
            source="youtube",
            origin_query=query,
        )

    try:
        Config.RESOLVE_HARD_TIMEOUT_SECONDS = 0.15
        SourceResolver._resolve_choices_impl = classmethod(slow_impl)
        SourceResolver._resolve_fallback_track = classmethod(fallback)
        t0 = time.perf_counter()
        result = await SourceResolver.resolve_choices("slow song", "tester", 1, n=1)
        elapsed = time.perf_counter() - t0
    finally:
        Config.RESOLVE_HARD_TIMEOUT_SECONDS = original_timeout
        SourceResolver._resolve_choices_impl = original_impl
        SourceResolver._resolve_fallback_track = original_fallback

    assert len(result) == 1, result
    assert result[0].title == "Fallback Song", result
    assert result[0].webpage_url.endswith("fallback"), result
    assert elapsed < 0.8, elapsed


asyncio.run(main())
print("OK: resolver public API returns coherent fallback within hard timeout budget")
