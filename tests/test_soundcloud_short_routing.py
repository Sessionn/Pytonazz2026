"""
tests/test_soundcloud_short_routing.py

Esecuzione:
    python tests/test_soundcloud_short_routing.py
"""
from cogs.music import _is_text_search, _normalize_url_like


q = _normalize_url_like("on.soundcloud.com/abc123")
assert q == "https://on.soundcloud.com/abc123"
assert not _is_text_search(q)

q2 = _normalize_url_like("https://on.soundcloud.com/abc123")
assert q2 == "https://on.soundcloud.com/abc123"
assert not _is_text_search(q2)

print("OK: SoundCloud short link routing")
