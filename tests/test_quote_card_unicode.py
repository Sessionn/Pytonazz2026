"""
tests/test_quote_card_unicode.py

Esegui dalla root del progetto con:
    python tests/test_quote_card_unicode.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.quote_card import build_quote_card


async def main():
    data = await build_quote_card("Привет こんにちは 𝓣𝓮𝓼𝓽 — pizza", "作者")
    assert data.startswith(b"\x89PNG"), "FAIL: output non PNG"
    assert len(data) > 10_000, "FAIL: PNG troppo piccolo"
    print("OK: quote card unicode render")


asyncio.run(main())
