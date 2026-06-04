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
unexpected_variant = _compute_enrich_confidence(
    "tony pitony donne ricche",
    Track("DONNE RICCHE - TonyPitony | ACOUSTIC VERSION", "", 215),
    {
        "title": "DONNE RICCHE",
        "artist": "TonyPitony",
        "duration": 215,
    },
)
requested_variant = _compute_enrich_confidence(
    "tony pitony donne ricche acoustic",
    Track("DONNE RICCHE - TonyPitony | ACOUSTIC VERSION", "", 215),
    {
        "title": "DONNE RICCHE acoustic",
        "artist": "TonyPitony",
        "duration": 215,
    },
)

notte_blu = _compute_enrich_confidence(
    "Notte blu dj shokka",
    Track("Notte Blu", "", 0),
    {
        "title": "Notte Blu",
        "artist": "DJ Shocca, Frank Siciliano",
        "duration": 0,
    },
)

assert clean["decision"] in {"full", "cover_only"}, clean
assert dirty["decision"] == "skip", dirty
assert dirty["variant_penalty"] >= clean["variant_penalty"] + 0.20, (clean, dirty)
assert unexpected_variant["variant_penalty"] >= 0.28, unexpected_variant
assert requested_variant["variant_penalty"] < unexpected_variant["variant_penalty"], (requested_variant, unexpected_variant)
assert notte_blu["decision"] == "cover_only", notte_blu
assert notte_blu["reason"] == "strong_yt_title_cover", notte_blu

print("OK: scoring guardrails per query rischiose")
