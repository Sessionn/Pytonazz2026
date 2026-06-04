from __future__ import annotations

import time
import urllib.parse


_STREAM_EXPIRY_KEYS = {"expire", "expires", "expiration"}
_STREAM_EXPIRY_SAFETY_SECONDS = 180
_STREAM_EXPIRY_MAX_TTL_SECONDS = 6 * 60 * 60


def stream_expiry_epoch(
    stream_url: str,
    *,
    now: int | None = None,
    fallback_ttl: int,
) -> int:
    current = int(time.time()) if now is None else int(now)
    fallback = current + max(1, int(fallback_ttl))
    try:
        query = urllib.parse.parse_qs(urllib.parse.urlparse(stream_url).query)
    except (TypeError, ValueError):
        return fallback

    candidates: list[int] = []
    for key, values in query.items():
        if key.lower() not in _STREAM_EXPIRY_KEYS:
            continue
        for value in values:
            try:
                candidates.append(int(value))
            except (TypeError, ValueError):
                continue

    valid = [value for value in candidates if value > current + _STREAM_EXPIRY_SAFETY_SECONDS]
    if not valid:
        return fallback

    signed_expiry = min(valid) - _STREAM_EXPIRY_SAFETY_SECONDS
    return min(signed_expiry, current + _STREAM_EXPIRY_MAX_TTL_SECONDS)


def stream_ttl_seconds(stream_url: str, *, fallback_ttl: int) -> int:
    now = int(time.time())
    return max(1, stream_expiry_epoch(stream_url, now=now, fallback_ttl=fallback_ttl) - now)
