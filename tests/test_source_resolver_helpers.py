"""
Esegui dalla ROOT del progetto con:
    python tests/test_source_resolver_helpers.py
"""

import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.source_resolver.query import normalize_search_query
from core.source_resolver.scoring import _compute_enrich_confidence
from core.source_resolver.soundcloud import is_soundcloud_short_url


class _Track:
    def __init__(self, title: str, artist: str = "", duration: int = 200):
        self.title = title
        self.artist = artist
        self.duration = duration


print("TEST resolver helpers")

q = normalize_search_query("Dark horse  feat. Katy Perry!!!")
assert q.lower() == "dark horse feat katy perry", q
print("OK normalize_search_query")

assert is_soundcloud_short_url("https://on.soundcloud.com/abcd")
assert is_soundcloud_short_url("https://sco.lt/abcd")
assert not is_soundcloud_short_url("https://soundcloud.com/x/y")
print("OK is_soundcloud_short_url")

track = _Track("Dark Horse (cover)")
meta = {
    "title": "Dark Horse",
    "artist": "Katy Perry",
    "duration": 200,
    "thumbnail": "",
    "spotify_url": "https://open.spotify.com/track/example",
}
score = _compute_enrich_confidence("dark horse katy perry", track, meta)
assert score["confidence"] < 0.85 or score["decision"] != "cover_only"
print("OK enrich threshold/cover_only guard")
