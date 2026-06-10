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

print("OK: playlist links are routed as multi-track inputs")
