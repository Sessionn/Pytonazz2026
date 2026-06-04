"""
tests/test_spotify_enrich_title_artist_equivalent.py

Esegui dalla root del progetto con:
    python tests/test_spotify_enrich_title_artist_equivalent.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.source_resolver.models import TrackInfo
from core.source_resolver.scoring import _compute_enrich_confidence


track = TrackInfo(
    title="TonyPitony - SESSONLINE",
    artist="",
    duration=171,
    webpage_url="https://youtube.com/watch?v=sessonline",
    thumbnail="",
    requester="tester",
    requester_id=1,
    source="youtube",
)
meta = {
    "title": "SESSONLINE",
    "artist": "TonyPitony",
    "duration": 171,
}

score = _compute_enrich_confidence("sessonline tony pitony", track, meta)

assert score["title_artist_equivalent"], score
assert score["artist_hint_present"], score
assert score["decision"] == "full", score
assert score["reason"] in {"high_confidence", "title_artist_equivalent"}, score

print("OK: artist-title YouTube uploads can promote to full Spotify metadata")
