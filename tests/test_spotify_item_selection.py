"""
Guardrail tests for Spotify item selection.

Esegui dalla root del progetto con:
    python tests/test_spotify_item_selection.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.source_resolver.spotify import (
    _choose_spotify_track_item,
    _spotify_item_query_similarity,
)


def item(name: str, artists: list[str], popularity: int) -> dict:
    return {
        "name": name,
        "artists": [{"name": a} for a in artists],
        "popularity": popularity,
    }


# Artist signal should beat popularity when query disambiguates the track.
hello_items = [
    item("Hello", ["Lionel Richie"], 95),
    item("Hello", ["Adele"], 70),
]
chosen_hello = _choose_spotify_track_item("hello adele", hello_items)
assert chosen_hello is not None
assert chosen_hello["artists"][0]["name"] == "Adele", chosen_hello


# When the user does not request a variant, noisy/variant candidates should be penalized.
dark_horse_items = [
    item("Dark Horse Acoustic", ["Katy Perry"], 90),
    item("Dark Horse", ["Katy Perry"], 70),
]
chosen_dark_horse = _choose_spotify_track_item("dark horse katy perry", dark_horse_items)
assert chosen_dark_horse is not None
assert chosen_dark_horse["name"] == "Dark Horse", chosen_dark_horse


# Token overlap should dominate over loose character similarity.
score_correct = _spotify_item_query_similarity(
    "blinding lights weeknd",
    item("Blinding Lights", ["The Weeknd"], 80),
)
score_wrong = _spotify_item_query_similarity(
    "blinding lights weeknd",
    item("Save Your Tears", ["The Weeknd"], 99),
)
assert score_correct > score_wrong, (score_correct, score_wrong)

print("OK: spotify item selection guardrails")
