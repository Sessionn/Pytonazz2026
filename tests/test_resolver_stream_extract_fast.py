"""
tests/test_resolver_stream_extract_fast.py

Esegui dalla root del progetto con:
    python tests/test_resolver_stream_extract_fast.py
"""

import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.source_resolver import SourceResolver
from core.source_resolver import ytdlp as ytdlp_helpers

URL = "https://www.youtube.com/watch?v=fastpath123"


def run_fetch(results: dict) -> tuple[str, list]:
    original = SourceResolver._extract_stream_url
    calls = []

    def fake_extract(cls, webpage_url, opts, *, quiet=False):
        kind = "rapida" if "extractor_args" in opts else "completa"
        calls.append((kind, quiet))
        return results.get(kind, "")

    SourceResolver._stream_url_cache.clear()
    try:
        SourceResolver._extract_stream_url = classmethod(fake_extract)
        return SourceResolver._fetch_stream_url(URL), calls
    finally:
        SourceResolver._extract_stream_url = original
        SourceResolver._stream_url_cache.clear()


# Estrazione rapida riuscita: nessuna estrazione completa.
url, calls = run_fetch({"rapida": "https://stream.test/fast"})
assert url == "https://stream.test/fast", url
assert calls == [("rapida", True)], calls

# Estrazione rapida fallita: si riprova con quella completa.
url, calls = run_fetch({"completa": "https://stream.test/full"})
assert url == "https://stream.test/full", url
assert calls == [("rapida", True), ("completa", False)], calls

# Fuori da YouTube (SoundCloud, ...) solo l'estrazione completa.
original = SourceResolver._extract_stream_url
seen = []
try:
    SourceResolver._extract_stream_url = classmethod(
        lambda cls, u, opts, quiet=False: seen.append("extractor_args" in opts) or "https://stream.test/sc"
    )
    assert SourceResolver._fetch_stream_url("https://soundcloud.com/a/b") == "https://stream.test/sc"
finally:
    SourceResolver._extract_stream_url = original
    SourceResolver._stream_url_cache.clear()
assert seen == [False], seen

# Rotazione della cache del player: via i file vecchi e quelli oltre il limite.
with tempfile.TemporaryDirectory() as tmp:
    cache_dir = Path(tmp)
    now = time.time()
    ages_days = [0, 1, 2, 3, 4, 5, 6, 6.5, 6.9, 8]
    for i, age in enumerate(ages_days):
        path = cache_dir / f"player,{i}.json"
        path.write_text("{}")
        os.utime(path, (now - age * 86400, now - age * 86400))
    (cache_dir / "lib.json").write_text("{}")
    removed = ytdlp_helpers.prune_player_cache(cache_dir, now=now)
    left = sorted(p.name for p in cache_dir.iterdir())
    # 10 player: il piu' vecchio supera 7 giorni, e dei 9 rimasti si tengono gli 8 piu' recenti.
    assert removed == 2, (removed, left)
    assert "lib.json" in left, left
    assert "player,9.json" not in left and "player,8.json" not in left, left

print("OK: estrazione stream rapida con ripiego e rotazione cache player")
