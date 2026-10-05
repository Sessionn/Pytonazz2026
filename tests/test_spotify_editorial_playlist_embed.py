"""
tests/test_spotify_editorial_playlist_embed.py

Le playlist editoriali Spotify (37i9dQZF...) rispondono 404 alla Web API per
le app sviluppatore. Verifica offline che:
- la pagina embed pubblica venga letta come oggetti-traccia Web API;
- _sp_playlist e _sp_playlist_stream ripieghino sull'embed al 404;
- un errore a pagina successiva NON scateni l'embed (brani gia' accodati);
- link Amazon Music / Tidal album vengano segnalati come non supportati;
- on.soundcloud.com venga espanso prima del routing.

Esegui dalla root del progetto con:
    python tests/test_spotify_editorial_playlist_embed.py
"""

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.source_resolver import SourceResolver, platforms

PID = "37i9dQZF1DXcBWIGoYBM5M"
EMBED_URL = f"https://open.spotify.com/embed/playlist/{PID}"

entity = {
    "name": "Today's Top Hits",
    "coverArt": {"sources": [{"url": "https://image-cdn/cover.jpg", "width": 300}]},
    "trackList": [
        {"uri": "spotify:track:AAA", "title": "Song A", "subtitle": "Artist 1, Artist 2", "duration": 200500, "isPlayable": True},
        {"uri": "spotify:episode:EEE", "title": "Podcast", "subtitle": "Host", "duration": 1, "isPlayable": True},
        {"uri": "spotify:track:BBB", "title": "Blocked", "subtitle": "X", "duration": 1, "isPlayable": False},
        {"uri": "spotify:track:CCC", "title": "Song C", "subtitle": "Artist 3", "duration": 180000},
    ],
}
page = (
    "<html><script id=\"__NEXT_DATA__\" type=\"application/json\">"
    + json.dumps({"props": {"pageProps": {"state": {"data": {"entity": entity}}}}})
    + "</script></html>"
)
html_calls = []


def fake_get_html(url):
    html_calls.append(url)
    assert url == EMBED_URL, url
    return page


platforms._get_html = fake_get_html

# ── Parser embed ─────────────────────────────────────────────────────────────
name, tracks = platforms.spotify_embed_playlist(PID, 100)
assert name == "Today's Top Hits", name
assert [t["id"] for t in tracks] == ["AAA", "CCC"], tracks
first = tracks[0]
assert first["name"] == "Song A"
assert [a["name"] for a in first["artists"]] == ["Artist 1", "Artist 2"]
assert first["duration_ms"] == 200500
assert first["album"]["images"][0]["url"] == "https://image-cdn/cover.jpg"
assert first["external_urls"]["spotify"] == "https://open.spotify.com/track/AAA"
assert len(platforms.spotify_embed_playlist(PID, 1)[1]) == 1

platforms._get_html = lambda url: "<html>niente</html>"
try:
    platforms.spotify_embed_playlist(PID, 10)
    raise AssertionError("pagina senza __NEXT_DATA__ deve fallire")
except LookupError:
    pass
platforms._get_html = fake_get_html


# ── Fallback nel resolver ────────────────────────────────────────────────────
class NotFound(Exception):
    pass


class FakeSp:
    def __init__(self, fail_at_offset):
        self.fail_at_offset = fail_at_offset

    def playlist_tracks(self, pid, limit=100, offset=0):
        if offset == self.fail_at_offset:
            raise NotFound("http status: 404")
        item = {"track": {"id": f"api{offset}", "type": "track", "name": f"Api {offset}", "artists": [{"name": "Z"}]}}
        return {"items": [item], "next": "more"}


SourceResolver._sp_client = classmethod(lambda cls: FakeSp(fail_at_offset=0))
out = SourceResolver._sp_playlist(PID, "tester", 1)
assert [t.title for t in out] == ["Song A", "Song C"], out
assert out[0].artist == "Artist 1, Artist 2" and out[0].duration == 200
assert out[0].is_pending and out[0].source == "spotify"
assert out[0].spotify_url == "https://open.spotify.com/track/AAA"


async def collect():
    return [t async for t in SourceResolver._sp_playlist_stream(PID, "tester", 1)]


streamed = asyncio.run(collect())
assert [t.title for t in streamed] == ["Song A", "Song C"], streamed

# Errore dopo la prima pagina: si tengono i brani API, niente embed.
html_calls.clear()
SourceResolver._sp_client = classmethod(lambda cls: FakeSp(fail_at_offset=100))
out = SourceResolver._sp_playlist(PID, "tester", 1)
assert [t.title for t in out] == ["Api 0"], out
streamed = asyncio.run(collect())
assert [t.title for t in streamed] == ["Api 0"], streamed
assert not html_calls, html_calls

# ── Link non supportati e link brevi ─────────────────────────────────────────
assert platforms.unsupported_platform("https://music.amazon.com/albums/B09V9M8T6Q") == "Amazon Music"
assert platforms.unsupported_platform("https://music.amazon.it/tracks/B0ABC") == "Amazon Music"
assert platforms.unsupported_platform("https://www.amazon.com/music/player/albums/B08ZJTJCX8") == "Amazon Music"
assert platforms.unsupported_platform("https://tidal.com/browse/album/123") == "Tidal (album)"
assert platforms.unsupported_platform("https://tidal.com/browse/track/123") == ""
assert platforms.unsupported_platform("https://www.amazon.com/dp/B01DVD3QWG") == ""
assert platforms.unsupported_platform("https://open.spotify.com/track/x") == ""
assert platforms.is_short_link("https://on.soundcloud.com/UKiooEY3fmS9R53Z9")
assert not platforms.is_short_link("https://soundcloud.com/forss/flickermood")

# Profili SoundCloud = raccolte (flat), brani e pagine di servizio no.
for url in (
    "https://soundcloud.com/mrcrowleydj?utm_source=clipboard&utm_medium=text",
    "https://soundcloud.com/forss",
    "https://soundcloud.com/forss/",
    "https://m.soundcloud.com/forss/tracks",
    "https://soundcloud.com/forss/popular-tracks",
):
    assert platforms.is_soundcloud_profile(url), url
for url in (
    "https://soundcloud.com/forss/flickermood",
    "https://soundcloud.com/the-concept-band/sets/the-royal-concept-ep",
    "https://soundcloud.com/discover",
    "https://soundcloud.com/search?q=x",
    "https://soundcloud.com/",
    "https://on.soundcloud.com/UKiooEY3fmS9R53Z9",
):
    assert not platforms.is_soundcloud_profile(url), url

print("OK: playlist editoriali Spotify da embed, link non supportati e link brevi")
