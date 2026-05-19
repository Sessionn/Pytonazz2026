from __future__ import annotations

import urllib.parse
import logging

import aiohttp

log = logging.getLogger("pitonazz.resolver")

_SHORT_SOUNDCLOUD_HOSTS = {"on.soundcloud.com", "sco.lt"}


def is_soundcloud_short_url(url: str) -> bool:
    raw = (url or "").strip()
    if not raw:
        return False
    parsed = urllib.parse.urlparse(raw if "://" in raw else f"https://{raw}")
    host = (parsed.hostname or "").lower()
    return host in _SHORT_SOUNDCLOUD_HOSTS


async def expand_soundcloud_short_url(url: str, timeout_seconds: float = 8.0) -> str:
    raw = (url or "").strip()
    if not is_soundcloud_short_url(raw):
        return raw
    timeout = aiohttp.ClientTimeout(total=timeout_seconds)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(raw, allow_redirects=True) as resp:
                return str(resp.url)
    except Exception as exc:
        log.debug("soundcloud short-link expansion failed for %s: %s", raw, exc)
        return raw
