"""
tests/test_spotify_enrich_long_title.py

Esegui dalla root del progetto con:
    python tests/test_spotify_enrich_long_title.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.source_resolver.models import TrackInfo
from core.source_resolver.scoring import _compute_enrich_confidence


track = TrackInfo(
    title="Gucci Flip Flops x Careless Whisper",
    artist="",
    duration=201,
    webpage_url="https://youtube.com/watch?v=GUCCI",
    thumbnail="",
    requester="tester",
    requester_id=1,
    source="youtube",
)
meta = {
    "title": "Gucci Flip Flops x Careless Whisper",
    "artist": "Moonshine",
    "duration": 201,
}

score = _compute_enrich_confidence("Gucci Flip Flops x Careless Whisper", track, meta)

assert score["query_sim"] == 1.0, score
assert score["yt_sim"] == 1.0, score
assert score["duration_sim"] == 1.0, score
assert score["non_music_penalty"] == 0.0, score
assert score["decision"] == "full", score

print("OK: long exact music titles are not penalized as non-music queries")
