"""
tests/test_lavalink_backend_selection.py

Run from project root:
    python tests/test_lavalink_backend_selection.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.audio_backends.lavalink import _select_track


def _track(title: str, author: str = "h6itam", length: int = 97000) -> dict:
    return {
        "encoded": "encoded",
        "info": {
            "title": title,
            "author": author,
            "length": length,
            "uri": "https://youtube.test/watch",
            "sourceName": "youtube",
        },
    }


def test_lavalink_selection_uses_resolver_ranking() -> None:
    tracks = [
        _track("MONTAGEM ALQUIMIA (SLOWED)", length=114000),
        _track("MONTAGEM ALQUIMIA", length=97000),
    ]

    selected = _select_track("montagem alquimia", tracks, apply_ranking=True)

    assert selected["info"]["title"] == "MONTAGEM ALQUIMIA", selected


def test_lavalink_selection_keeps_first_for_direct_urls() -> None:
    tracks = [
        _track("First direct result"),
        _track("Better looking title"),
    ]

    selected = _select_track("https://www.youtube.com/watch?v=abc", tracks, apply_ranking=False)

    assert selected["info"]["title"] == "First direct result", selected


test_lavalink_selection_uses_resolver_ranking()
test_lavalink_selection_keeps_first_for_direct_urls()
print("OK: lavalink backend ranks search candidates and preserves direct URL order")
