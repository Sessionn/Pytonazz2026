"""
tests/test_stream_expiry.py

Esegui dalla root del progetto con:
    python tests/test_stream_expiry.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.stream_expiry import stream_expiry_epoch, stream_ttl_seconds


now = 1_800_000_000

signed = stream_expiry_epoch(
    f"https://stream.example/audio?expire={now + 7200}&sig=test",
    now=now,
    fallback_ttl=1800,
)
assert signed == now + 7200 - 180, signed

capped = stream_expiry_epoch(
    f"https://stream.example/audio?Expires={now + 86400}&sig=test",
    now=now,
    fallback_ttl=1800,
)
assert capped == now + 21600, capped

fallback = stream_expiry_epoch(
    "https://stream.example/audio?sig=test",
    now=now,
    fallback_ttl=1800,
)
assert fallback == now + 1800, fallback

expired = stream_expiry_epoch(
    f"https://stream.example/audio?expire={now + 30}",
    now=now,
    fallback_ttl=1800,
)
assert expired == now + 1800, expired

ttl = stream_ttl_seconds("https://stream.example/audio", fallback_ttl=45)
assert 40 <= ttl <= 45, ttl

print("OK: signed stream expiry is reused safely")
