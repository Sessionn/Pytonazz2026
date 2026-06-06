"""
tests/test_spotify_enrich_producer_tag_full.py

Esegui dalla root del progetto con:
    python tests/test_spotify_enrich_producer_tag_full.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.source_resolver.models import TrackInfo
from core.source_resolver.scoring import _compute_enrich_confidence


track = TrackInfo(
    title="BUCKSHOT - CALM DES FCKDOWN (PROD. ASA NISI MASA)",
    artist="",
    duration=129,
    webpage_url="https://youtube.com/watch?v=calm-des-fckdown",
    thumbnail="",
    requester="tester",
    requester_id=1,
    source="youtube",
)
meta = {
    "title": "CALM DES FCKDOWN",
    "artist": "Buckshot",
    "duration": 129,
}

score = _compute_enrich_confidence("calm des fckdown", track, meta)

assert score["decision"] == "full", score
assert score["variant_penalty"] == 0.0, score
assert score["reason"] in {"high_confidence", "title_artist_equivalent_raw"}, score

print("OK: producer tags do not block full Spotify metadata")
