"""
tests/test_scoring_guardrails.py

Esegui dalla root del progetto con:
    python tests/test_scoring_guardrails.py
"""

import os
import sys
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.source_resolver.scoring import _compute_enrich_confidence


@dataclass
class Track:
    title: str
    artist: str
    duration: int


sp_meta = {
    "title": "Dark Horse",
    "artist": "Katy Perry",
    "duration": 215,
}

clean = _compute_enrich_confidence(
    "dark horse katy perry",
    Track("Katy Perry - Dark Horse", "Katy Perry", 215),
    sp_meta,
)
dirty = _compute_enrich_confidence(
    "dark horse katy perry pizza music",
    Track("Katy Perry - Dark Horse Pizza Music", "Katy Perry", 215),
    sp_meta,
)

assert clean["decision"] in {"full", "cover_only"}, clean
assert dirty["decision"] == "skip", dirty
assert dirty["variant_penalty"] >= clean["variant_penalty"] + 0.20, (clean, dirty)

print("OK: scoring guardrails per query rischiose")
