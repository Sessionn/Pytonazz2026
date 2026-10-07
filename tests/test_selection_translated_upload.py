"""
tests/test_selection_translated_upload.py

Esegui dalla root del progetto con:
    python tests/test_selection_translated_upload.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.source_resolver.models import TrackInfo
from core.source_resolver.selection import is_translated_upload, select_best_track


def track(title: str, artist: str, duration: int) -> TrackInfo:
    return TrackInfo(title=title, webpage_url=f"https://www.youtube.com/watch?v={abs(hash(title)) % 10**11:011d}",
                     duration=duration, thumbnail="", requester="t", requester_id=1, source="youtube", artist=artist)


for title in (
    "Queen — Bohemian Rhapsody (Sub. Español / Lyrics)",
    "Bohemian Rhapsody - Queen (Subtitulada al Español)",
    "Queen - Bohemian Rhapsody [Traduzione in italiano]",
    "Bohemian Rhapsody (Letra)",
    "Bohemian Rhapsody legendado",
    "Bohemian Rhapsody (tradução)",
):
    assert is_translated_upload(title), title

for title in (
    "Queen – Bohemian Rhapsody (Official Video Remastered)",
    "Bohemian Rhapsody",
    "Subsonica - Tutti i miei sbagli",
    "Sub Urban - Cradles",
):
    assert not is_translated_upload(title), title

# Caso reale del 2026-10-07 (ricerca di riserva, metadati Spotify).
sp_meta = {"title": "Bohemian Rhapsody", "artist": "Queen", "duration": 355}
candidates = [
    track("Queen – Bohemian Rhapsody (Official Video Remastered)", "Queen Official", 360),
    track("Queen — Bohemian Rhapsody (Sub. Español / Lyrics)", "Richie Lyrics", 358),
    track("Queen - Bohemian Rhapsody (Live Aid 1985)", "Live Aid and Queen Official", 165),
]
best = select_best_track("bohemian rhapsody queen", candidates, sp_meta)
assert best.title.startswith("Queen – Bohemian Rhapsody (Official"), best.title

# Se l'utente chiede la versione tradotta, non va penalizzata.
best = select_best_track("bohemian rhapsody sub español", candidates, sp_meta)
assert "Sub. Español" in best.title, best.title

print("OK: caricamenti tradotti/sottotitolati penalizzati se non richiesti")
