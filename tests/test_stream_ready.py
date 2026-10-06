"""
wait_until_ready: un link che risponde 403 per qualche istante (come i link
googlevideo appena generati) viene atteso con retry rapidi; un link che resta
403 non blocca oltre il timeout; altri errori lasciano decidere a FFmpeg.

Esegui dalla root del progetto con:
    python tests/test_stream_ready.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aiohttp import web

import core.music.stream_ready as stream_ready


async def main() -> None:
    counts: dict[str, int] = {}

    async def handler(request: web.Request) -> web.Response:
        name = request.match_info["name"]
        counts[name] = counts.get(name, 0) + 1
        assert request.headers.get("Range") == "bytes=0-0"
        if name == "warming" and counts[name] <= 3:
            return web.Response(status=403)
        if name == "forbidden":
            return web.Response(status=403)
        if name == "missing":
            return web.Response(status=404)
        return web.Response(status=206, body=b"x")

    app = web.Application()
    app.router.add_get("/{name}", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    base = f"http://127.0.0.1:{port}"

    original_needs_check = stream_ready._needs_check
    stream_ready._needs_check = lambda url: True
    stream_ready.RETRY_INTERVAL_SECONDS = 0.05
    try:
        started = time.perf_counter()
        assert await stream_ready.wait_until_ready(f"{base}/warming")
        assert counts["warming"] == 4
        assert time.perf_counter() - started < 1.0

        # Gia' verificato: nessuna nuova richiesta.
        assert await stream_ready.wait_until_ready(f"{base}/warming")
        assert counts["warming"] == 4

        started = time.perf_counter()
        assert not await stream_ready.wait_until_ready(f"{base}/forbidden", timeout=0.4)
        assert time.perf_counter() - started < 1.0

        assert await stream_ready.wait_until_ready(f"{base}/missing")  # decide FFmpeg
        assert counts["missing"] == 1
        assert await stream_ready.wait_until_ready("http://127.0.0.1:1/unreachable")
    finally:
        stream_ready._needs_check = original_needs_check
        await runner.cleanup()

    now = 1_800_000_000
    fresh = f"https://rr4---sn-h0jelne6.googlevideo.com/videoplayback?expire={now + 21598}&x=1"
    old_link = f"https://rr4---sn-h0jelne6.googlevideo.com/videoplayback?expire={now + 20000}&x=1"
    assert stream_ready._needs_check(fresh, now=now)
    assert not stream_ready._needs_check(old_link, now=now)  # dal DB o dal prefetch: nessuna richiesta
    assert stream_ready._needs_check("https://rr4---sn-h0jelne6.googlevideo.com/videoplayback?x=1", now=now)
    assert not stream_ready._needs_check("https://cdn.example.com/a.mp3", now=now)
    assert await stream_ready.wait_until_ready("https://cdn.example.com/a.mp3")  # nessuna richiesta


asyncio.run(main())
print("OK: link 403 temporanei attesi con retry rapidi, mai bloccanti")
