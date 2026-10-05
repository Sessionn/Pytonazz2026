"""
tests/test_music_playlist_links.py

Esegui dalla root del progetto con:
    python tests/test_music_playlist_links.py
"""

import os
import sys
import types
import importlib.util
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

sys.modules.setdefault("dotenv", types.SimpleNamespace(load_dotenv=lambda: None))

resolver_stub = types.ModuleType("core.source_resolver")


def _extract_spotify_entity_id(url: str, entity: str) -> str | None:
    if "spotify.com/" not in url:
        return None
    marker = f"/{entity}/"
    if marker not in url:
        return None
    value = url.split(marker, 1)[1].split("?", 1)[0].split("/", 1)[0]
    return value or None


resolver_stub.SourceResolver = object
resolver_stub.extract_spotify_album_id = lambda url: _extract_spotify_entity_id(url, "album")
resolver_stub.extract_spotify_playlist_id = lambda url: _extract_spotify_entity_id(url, "playlist")
resolver_stub.extract_spotify_track_id = lambda url: _extract_spotify_entity_id(url, "track")
resolver_stub.is_spotify_artist_url = lambda url: _extract_spotify_entity_id(url, "artist") is not None
sys.modules.setdefault("core.source_resolver", resolver_stub)

root = Path(__file__).resolve().parents[1]
platforms_spec = importlib.util.spec_from_file_location(
    "core.source_resolver.platforms", root / "core" / "source_resolver" / "platforms.py"
)
platforms = importlib.util.module_from_spec(platforms_spec)
sys.modules["core.source_resolver.platforms"] = platforms
platforms_spec.loader.exec_module(platforms)
resolver_stub.platforms = platforms
spec = importlib.util.spec_from_file_location("music_input_under_test", root / "core" / "music" / "input.py")
music_input = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(music_input)

is_multi_url = music_input.is_multi_url
normalize_url_like = music_input.normalize_url_like
spotify_kind = music_input.spotify_kind


spotify_playlist = normalize_url_like("open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M")
spotify_album = normalize_url_like("https://open.spotify.com/album/6s84u2TUpR3wdUv4NgKA2j")
youtube_playlist = normalize_url_like("youtube.com/playlist?list=PLFgquLnL59alCl_2TQvOiD5Vgm1hCaGSI")
soundcloud_set = normalize_url_like("soundcloud.com/user/sets/example-set")

assert spotify_kind(spotify_playlist) == "playlist"
assert spotify_kind(spotify_album) == "album"
assert is_multi_url(spotify_playlist)
assert is_multi_url(spotify_album)
assert is_multi_url(youtube_playlist)
assert is_multi_url(soundcloud_set)
# Profilo SoundCloud: raccolta flat, non estrazione completa di ogni brano.
assert is_multi_url("https://soundcloud.com/forss")
assert is_multi_url("soundcloud.com/forss/tracks")
assert not is_multi_url("https://soundcloud.com/forss/flickermood")

is_text_search = music_input.is_text_search

# Altre piattaforme: album/playlist = multi, singolo brano = no.
assert is_multi_url(normalize_url_like("deezer.com/it/playlist/908622995"))
assert is_multi_url("https://www.deezer.com/album/302127")
assert not is_multi_url("https://www.deezer.com/track/3135556")
assert is_multi_url("https://music.apple.com/us/album/after-hours/1499378108")
assert not is_multi_url("https://music.apple.com/us/album/after-hours/1499378108?i=1499378615")
assert is_multi_url("https://music.apple.com/it/playlist/todays-hits/pl.f4d106fed2bd41149aaacabb233eb5eb")
assert is_multi_url("https://music.youtube.com/playlist?list=OLAK5uy_kEXAMPLE")
# Mix automatici YouTube e Watch Later non sono raccolte riproducibili.
assert not is_multi_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=RDdQw4w9WgXcQ")

# Qualunque URL esplicito non e' una ricerca testuale.
for url in (
    "https://music.youtube.com/watch?v=dQw4w9WgXcQ",
    "https://m.youtube.com/watch?v=dQw4w9WgXcQ",
    "https://artist.bandcamp.com/track/song",
    "https://www.mixcloud.com/dj/set/",
    "music.apple.com/us/song/x/1499378615",
    "deezer.page.link/abc",
):
    assert not is_text_search(url), url
assert is_text_search("blinding lights the weeknd")

# Riconoscimento link piattaforma.
ref = platforms.parse_platform_url("https://music.apple.com/us/album/after-hours/1499378108?i=1499378615")
assert (ref.platform, ref.kind, ref.entity_id) == ("apple_music", "track", "1499378615"), ref
ref = platforms.parse_platform_url("https://www.deezer.com/fr/album/302127")
assert (ref.platform, ref.kind, ref.entity_id) == ("deezer", "album", "302127"), ref
ref = platforms.parse_platform_url("https://tidal.com/browse/track/77646169")
assert (ref.platform, ref.kind) == ("tidal", "track"), ref
assert platforms.is_short_link("https://spotify.link/AbCdEf")
assert platforms.is_short_link("https://deezer.page.link/xyz")
assert not platforms.is_short_link("https://youtu.be/dQw4w9WgXcQ")

print("OK: playlist links are routed as multi-track inputs")
