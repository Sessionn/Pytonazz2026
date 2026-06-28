"""
tests/test_resolver_flat_first_url_guard.py

Esegui dalla root del progetto con:
    python tests/test_resolver_flat_first_url_guard.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.source_resolver import SourceResolver


assert (
    SourceResolver._first_ytdlp_webpage_url(
        {"entries": [{"url": "ytsearch1:Boris Albeathor audio"}]}
    )
    == ""
)

assert (
    SourceResolver._first_ytdlp_webpage_url(
        {"entries": [{"webpage_url": "https://www.youtube.com/watch?v=abc123def45"}]}
    )
    == "https://www.youtube.com/watch?v=abc123def45"
)

assert (
    SourceResolver._first_ytdlp_webpage_url(
        {"entries": [{"url": "abc123def45"}]}
    )
    == "https://www.youtube.com/watch?v=abc123def45"
)

print("OK: resolver flat-first rejects ytsearch pseudo urls")
