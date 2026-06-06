"""
tests/test_spotify_enrich_fuzzy_title_artist_equivalent.py

Esegui dalla root del progetto con:
    python tests/test_spotify_enrich_fuzzy_title_artist_equivalent.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.source_resolver.models import TrackInfo
from core.source_resolver.scoring import _compute_enrich_confidence


track = TrackInfo(
    title="Bee Gees - Staying Alive (Audio)",
    artist="",
    duration=242,
    webpage_url="https://youtube.com/watch?v=staying-alive",
    thumbnail="",
    requester="tester",
    requester_id=1,
    source="youtube",
)
meta = {
    "title": "Stayin Alive",
    "artist": "Bee Gees",
    "duration": 281,
}

score = _compute_enrich_confidence("staying alive", track, meta)

assert score["title_artist_equivalent"], score
assert score["decision"] == "full", score
assert score["confidence"] >= 0.72, score

print("OK: fuzzy title spelling can promote artist-title YouTube metadata")
