"""
tests/test_selection_featuring.py

Esegui dalla root del progetto con:
    python tests/test_selection_featuring.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.source_resolver.models import TrackInfo
from core.source_resolver.scoring import _enrich_sim, _strip_featuring
from core.source_resolver.selection import select_best_track


def track(title: str, artist: str, duration: int) -> TrackInfo:
    return TrackInfo(title=title, webpage_url=f"https://www.youtube.com/watch?v={abs(hash(title)) % 10**11:011d}",
                     duration=duration, thumbnail="", requester="t", requester_id=1, source="youtube", artist=artist)


assert _strip_featuring("BRATZ (feat. Nerissima Serpe)").strip() == "BRATZ"
assert _strip_featuring("Song [ft. Someone]").strip() == "Song"
assert "Someone" not in _strip_featuring("Song feat. Someone - Remix")
assert _strip_featuring("With or Without You") == "With or Without You"

assert _enrich_sim("bratz", "BRATZ (feat. Nerissima Serpe)", "Sayf") == 1.0
# Nominare il featuring nella query continua a funzionare.
assert _enrich_sim("bratz nerissima serpe", "BRATZ (feat. Nerissima Serpe)", "Sayf") >= 0.99

# Caso reale del 2026-10-09: YouTube Music dava Sayf al primo posto, il bot
# sceglieva l'omonimo di Хестон perche' il featuring abbassava la somiglianza.
candidates = [
    track("BRATZ (feat. Nerissima Serpe)", "Sayf", 170),
    track("Bratz", "Хестон", 170),
]
best = select_best_track("BRATZ", candidates)
assert best.artist == "Sayf", best

print("OK: featuring non richiesto non penalizza il titolo")
