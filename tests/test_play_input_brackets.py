"""
tests/test_play_input_brackets.py

Esegui dalla root del progetto con:
    python tests/test_play_input_brackets.py

Le query con parentesi quadre ("love nwantiti [North African Remix] ...") facevano
fallire /play: urlparse("https://love nwantiti [...]") solleva "Invalid IPv6 URL".
Trovato rieseguendo tutte le query del cache DB (2026-10-07).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.music.input import is_multi_url, is_text_search, normalize_url_like, spotify_kind
from core.source_resolver import (
    _is_url_like_query,
    _is_yt_channel_url,
    extract_spotify_album_id,
    extract_spotify_artist_id,
    extract_spotify_playlist_id,
    extract_spotify_track_id,
    is_spotify_artist_url,
    platforms,
)
from core.source_resolver.ytdlp import _is_soundcloud_short_url, _is_soundcloud_url, _strip_soundcloud_params

QUERIES = [
    "love nwantiti [North African Remix] (feat. ElGrande Toto) CKay",
    "[",
    "]",
    "[bracket",
    "song ]",
    "http://[",
    "https://[::1",
    "open.spotify.com [x]",
    "//[foo]",
    "a [b] c [d]",
]

CHECKS = [
    normalize_url_like, spotify_kind, is_text_search, is_multi_url,
    _is_url_like_query, _is_yt_channel_url, is_spotify_artist_url,
    extract_spotify_track_id, extract_spotify_album_id, extract_spotify_playlist_id, extract_spotify_artist_id,
    platforms.is_short_link, platforms.unsupported_platform, platforms.parse_platform_url,
    _is_soundcloud_url, _is_soundcloud_short_url, _strip_soundcloud_params,
]

failures = []
for query in QUERIES:
    for check in CHECKS:
        try:
            check(query)
        except Exception as exc:  # qualsiasi eccezione qui fa fallire /play
            failures.append(f"{check.__name__}({query!r}): {type(exc).__name__}: {exc}")

assert not failures, "\n".join(failures)

query = "love nwantiti [North African Remix] (feat. ElGrande Toto) CKay"
assert is_text_search(normalize_url_like(query))
assert spotify_kind(query) is None

print("OK: query con parentesi quadre non rompono il riconoscimento dell'input di /play")
