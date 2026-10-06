"""
tests/test_music_platforms_lazy.py

Verifica offline (HTTP e yt-dlp simulati):
- metadati Deezer / Apple Music normalizzati e paginati;
- fallback titolo pagina per siti senza audio diretto;
- collezioni Spotify/Deezer accodate in modo lazy e abbinate solo al play;
- playlist YouTube in modalita' flat senza video privati/eliminati.

Esegui dalla root del progetto con:
    python tests/test_music_platforms_lazy.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.source_resolver import SourceResolver, platforms
from core.source_resolver.models import TrackInfo

# ── HTTP simulato ────────────────────────────────────────────────────────────

JSON_ROUTES = {}
HTML_ROUTES = {}
calls = []


def fake_get_json(url, params=None):
    calls.append(url)
    key = url if params is None else (url, tuple(sorted((params or {}).items())))
    if key in JSON_ROUTES:
        return JSON_ROUTES[key]
    if url in JSON_ROUTES:
        return JSON_ROUTES[url]
    raise AssertionError(f"richiesta inattesa: {url} {params}")


def fake_get_html(url):
    calls.append(url)
    return HTML_ROUTES[url]


platforms._get_json = fake_get_json
platforms._get_html = fake_get_html

# Deezer: brano singolo
JSON_ROUTES["https://api.deezer.com/track/3135556"] = {
    "id": 3135556, "title": "Harder, Better, Faster, Stronger", "duration": 224, "isrc": "GBDUW0000059",
    "link": "https://www.deezer.com/track/3135556",
    "artist": {"name": "Daft Punk"}, "album": {"cover_xl": "https://cdn-images.dzcdn.net/xl.jpg"},
}
col = platforms.lookup(platforms.parse_platform_url("https://www.deezer.com/it/track/3135556"))
assert col.tracks[0]["title"] == "Harder, Better, Faster, Stronger"
assert col.tracks[0]["artist"] == "Daft Punk" and col.tracks[0]["duration"] == 224
assert col.tracks[0]["isrc"] == "GBDUW0000059"

# Deezer: playlist con paginazione "next" e brani non disponibili esclusi
JSON_ROUTES["https://api.deezer.com/playlist/42"] = {"title": "Road Trip"}
JSON_ROUTES[("https://api.deezer.com/playlist/42/tracks", (("limit", 100),))] = {
    "data": [
        {"id": 1, "title": "Uno", "duration": 100, "artist": {"name": "A"}, "album": {"cover_xl": "c1"}},
        {"id": 2, "title": "Bloccato", "duration": 100, "readable": False, "artist": {"name": "B"}},
    ],
    "next": "https://api.deezer.com/playlist/42/tracks?index=100",
}
JSON_ROUTES["https://api.deezer.com/playlist/42/tracks?index=100"] = {
    "data": [{"id": 3, "title": "Tre", "duration": 90, "artist": {"name": "C"}, "album": {}}],
}
col = platforms.lookup(platforms.parse_platform_url("https://www.deezer.com/playlist/42"))
assert col.name == "Road Trip"
assert [t["title"] for t in col.tracks] == ["Uno", "Tre"], col.tracks

# Apple Music: album ordinato per disco/traccia, artwork ad alta risoluzione
JSON_ROUTES[("https://itunes.apple.com/lookup", (("country", "us"), ("entity", "song"), ("id", "1499378108"), ("limit", 200)))] = {
    "results": [
        {"wrapperType": "collection", "collectionName": "After Hours"},
        {"wrapperType": "track", "kind": "song", "trackName": "Second", "artistName": "The Weeknd",
         "trackTimeMillis": 200000, "discNumber": 1, "trackNumber": 2,
         "artworkUrl100": "https://is1.mzstatic.com/x/100x100bb.jpg", "trackViewUrl": "https://music.apple.com/s2"},
        {"wrapperType": "track", "kind": "song", "trackName": "First", "artistName": "The Weeknd",
         "trackTimeMillis": 180000, "discNumber": 1, "trackNumber": 1,
         "artworkUrl100": "https://is1.mzstatic.com/x/100x100bb.jpg", "trackViewUrl": "https://music.apple.com/s1"},
    ]
}
col = platforms.lookup(platforms.parse_platform_url("https://music.apple.com/us/album/after-hours/1499378108"))
assert col.name == "After Hours"
assert [t["title"] for t in col.tracks] == ["First", "Second"]
assert col.tracks[0]["thumbnail"].endswith("/600x600bb.jpg"), col.tracks[0]["thumbnail"]
assert col.tracks[0]["duration"] == 180

# Apple Music: playlist letta dai meta music:song della pagina pubblica
HTML_ROUTES["https://music.apple.com/it/playlist/pl.abc"] = """
<html><head>
<meta property="og:title" content="Hit del momento su Apple Music">
<meta property="music:song" content="https://music.apple.com/it/song/uno/111">
<meta property="music:song" content="https://music.apple.com/it/song/due/222">
</head></html>"""
JSON_ROUTES[("https://itunes.apple.com/lookup", (("country", "it"), ("id", "111,222"), ("limit", 200)))] = {
    "results": [
        {"kind": "song", "trackId": 222, "trackName": "Due", "artistName": "B", "trackTimeMillis": 1000},
        {"kind": "song", "trackId": 111, "trackName": "Uno", "artistName": "A", "trackTimeMillis": 1000},
    ]
}
col = platforms.lookup(platforms.parse_platform_url("https://music.apple.com/it/playlist/hit/pl.abc"))
assert col.name == "Hit del momento", col.name
assert [t["title"] for t in col.tracks] == ["Uno", "Due"], "deve rispettare l'ordine della playlist"

# Fallback generico: titolo pagina ripulito dal nome del servizio
HTML_ROUTES["https://music.amazon.com/albums/X"] = '<meta property="og:title" content="Blinding Lights by The Weeknd on Amazon Music">'
assert platforms.page_search_query("https://music.amazon.com/albums/X") == "Blinding Lights The Weeknd"

print("OK: metadati Deezer / Apple Music / fallback pagina")

# ── Risoluzione lazy ─────────────────────────────────────────────────────────

ytdlp_queries = []


def fake_run_ytdlp(cls, query, requester, requester_id):
    ytdlp_queries.append(query)
    return [TrackInfo(
        title="Daft Punk - Harder Better Faster Stronger (Official Audio)",
        webpage_url="https://www.youtube.com/watch?v=GDpmVUEjagg",
        duration=225, thumbnail="https://i.ytimg.com/vi/x/hq.jpg",
        requester=requester, requester_id=requester_id, source="youtube",
        artist="Daft Punk",
    )]


stream_fetches = []


def fake_fetch_stream(cls, url):
    # L'abbinamento usa la ricerca flat: lo stream si estrae una volta sola, qui.
    stream_fetches.append(url)
    return "https://rr1---sn.googlevideo.com/audio"


def fail_full_search(cls, query, requester, requester_id):
    raise AssertionError("l'abbinamento non deve estrarre per intero i candidati")


SourceResolver._run_ytdlp_flat_candidates = classmethod(fake_run_ytdlp)
SourceResolver._run_ytdlp = classmethod(fail_full_search)
SourceResolver._fetch_stream_url = classmethod(fake_fetch_stream)


async def lazy_flow():
    tracks = await SourceResolver._resolve_impl("https://www.deezer.com/playlist/42", "tester", 7)
    assert [t.title for t in tracks] == ["Uno", "Tre"]
    assert all(t.is_pending and not t.webpage_url for t in tracks), "le collezioni devono restare lazy"
    assert not ytdlp_queries, "nessuna ricerca YouTube prima del play"
    assert tracks[0].source == "deezer" and tracks[0].spotify_url == ""

    url = await SourceResolver.resolve_fresh_url(tracks[0])
    assert url == "https://rr1---sn.googlevideo.com/audio", url
    assert tracks[0].webpage_url.startswith("https://www.youtube.com/"), tracks[0].webpage_url
    assert not tracks[0].is_pending
    assert tracks[0].title == "Uno", "il titolo resta quello della piattaforma"
    assert ytdlp_queries[0] == "ytsearch1:Uno A", ytdlp_queries
    assert stream_fetches == ["https://www.youtube.com/watch?v=GDpmVUEjagg"], stream_fetches

    # Brano singolo: abbinato subito.
    single = await SourceResolver._resolve_impl("https://www.deezer.com/track/3135556", "tester", 7)
    assert len(single) == 1 and single[0].webpage_url and not single[0].is_pending
    assert single[0].source == "deezer"


asyncio.run(lazy_flow())


class FakeSpotify:
    def __init__(self):
        self.track_calls = 0

    def track(self, _id):
        self.track_calls += 1
        raise AssertionError("le playlist non devono richiedere ogni brano a sp.track()")

    def playlist_tracks(self, pid, limit=100, offset=0):
        items = [
            {"track": {"id": "a", "type": "track", "name": "Song A", "duration_ms": 1000,
                       "artists": [{"name": "Art"}], "album": {"images": [{"url": "img"}]},
                       "external_urls": {"spotify": "https://open.spotify.com/track/a"}}},
            {"track": {"id": None, "type": "track", "name": "file locale"}},
            {"track": {"id": "ep", "type": "episode", "name": "Podcast"}},
            {"track": None},
        ]
        return {"items": items, "next": None}


fake_sp = FakeSpotify()
SourceResolver._sp_client = classmethod(lambda cls: fake_sp)


async def spotify_flow():
    out = [t async for t in SourceResolver._sp_playlist_stream("pl", "tester", 7)]
    assert [t.title for t in out] == ["Song A"], out
    assert out[0].spotify_url == "https://open.spotify.com/track/a" and out[0].is_pending


asyncio.run(spotify_flow())
assert fake_sp.track_calls == 0

print("OK: collezioni lazy, abbinamento solo al play")

# ── Playlist YouTube flat ────────────────────────────────────────────────────


class FakeYDL:
    def __init__(self, opts):
        assert opts.get("extract_flat") == "in_playlist"

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download=False):
        return {"entries": [
            {"id": "aaaaaaaaaaa", "url": "https://www.youtube.com/watch?v=aaaaaaaaaaa", "title": "Video A",
             "duration": 200, "channel": "Canale", "ie_key": "Youtube"},
            {"id": "bbbbbbbbbbb", "url": "bbbbbbbbbbb", "title": "[Private video]"},
            {"id": "ccccccccccc", "url": "ccccccccccc", "title": "Video C", "ie_key": "Youtube"},
            None,
        ]}


import core.source_resolver as resolver_module  # noqa: E402

resolver_module.yt_dlp.YoutubeDL = FakeYDL
flat = SourceResolver._ytdlp_flat_collection("https://www.youtube.com/playlist?list=PLx", "tester", 7)
assert [t.title for t in flat] == ["Video A", "Video C"], flat
assert flat[1].webpage_url == "https://www.youtube.com/watch?v=ccccccccccc"
assert all(t.source == "youtube" and not t.stream_url for t in flat)

print("OK: playlist YouTube flat")


# Set SoundCloud flat: yt-dlp non restituisce i titoli, si usa lo slug.
class FakeSoundCloudSetYDL(FakeYDL):
    def extract_info(self, url, download=False):
        return {"entries": [
            {"_type": "url_transparent", "ie_key": "Soundcloud", "id": "1", "title": None,
             "url": "https://soundcloud.com/the-concept-band/gimme-twice-mastered"},
            {"_type": "url_transparent", "ie_key": "Soundcloud", "id": "2", "title": None,
             "url": "https://api-v2.soundcloud.com/tracks/47127631"},
        ]}


resolver_module.yt_dlp.YoutubeDL = FakeSoundCloudSetYDL
flat = SourceResolver._ytdlp_flat_collection("https://soundcloud.com/the-concept-band/sets/ep", "tester", 7)
assert [t.title for t in flat] == ["Gimme Twice Mastered", "Senza titolo"], flat
assert flat[1].webpage_url == "https://api-v2.soundcloud.com/tracks/47127631"

print("OK: set SoundCloud flat con titoli dallo slug")
