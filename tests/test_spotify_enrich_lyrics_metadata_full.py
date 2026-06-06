"""
tests/test_spotify_enrich_lyrics_metadata_full.py

Esegui dalla root del progetto con:
    python tests/test_spotify_enrich_lyrics_metadata_full.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.source_resolver.models import TrackInfo
from core.source_resolver.scoring import _compute_enrich_confidence


track = TrackInfo(
    title="CAPAREZZA - CONFUSIANESIMO TESTO (lyrics)",
    artist="",
    duration=310,
    webpage_url="https://youtube.com/watch?v=confusianesimo",
    thumbnail="",
    requester="tester",
    requester_id=1,
    source="youtube",
)
meta = {
    "title": "Confusianesimo",
    "artist": "Caparezza",
    "duration": 221,
}

score = _compute_enrich_confidence("confusianesimo caparezza", track, meta)

assert score["title_artist_equivalent"], score
assert score["decision"] == "full", score
assert score["reason"] in {"high_confidence", "title_artist_equivalent", "title_artist_equivalent_raw"}, score

print("OK: lyrics/testo wrappers can keep full Spotify metadata when title and artist match")
