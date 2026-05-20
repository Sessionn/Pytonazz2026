"""
Esegui dalla ROOT del progetto con:
    python tests/test_source_resolver_helpers.py
"""

import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.source_resolver.query import normalize_search_query
from core.source_resolver.scoring import _compute_enrich_confidence
from core.source_resolver.__init__ import _should_store_query_cache
from core.source_resolver.soundcloud import is_soundcloud_short_url
from core.quote_card import _normalize_display_text


class _Track:
    def __init__(self, title: str, artist: str = "", duration: int = 200):
        self.title = title
        self.artist = artist
        self.duration = duration
        self.webpage_url = "https://youtube.com/watch?v=test"


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
if score["confidence"] >= 0.85:
    assert score["decision"] != "cover_only"
if score["decision"] == "cover_only":
    assert score["confidence"] < 0.85
print("OK enrich threshold/cover_only guard")

good = _Track("Waka Waka (This Time for Africa)", "Shakira")
bad = _Track("Video unavailable", "Unknown")
assert _should_store_query_cache("waka waka shakira", good)
assert not _should_store_query_cache("waka waka shakira", bad)
print("OK cache guardrail for low-quality entries")

assert _normalize_display_text("𝓟𝓲𝓮𝓻𝓸𝓛𝓸𝓷𝓮") == "PieroLone"
print("OK unicode quote normalization")
