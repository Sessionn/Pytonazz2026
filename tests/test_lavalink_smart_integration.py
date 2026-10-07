"""
tests/test_lavalink_smart_integration.py

Esegui dalla root del progetto con:
    python tests/test_lavalink_smart_integration.py

/play testuale (LavalinkAudioBackend.resolve_track_info) usa il resolver
intelligente e ripiega sul percorso precedente se non c'e' una scelta affidabile.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from core.audio_backends import lavalink as lavalink_module
from core.audio_backends.lavalink import LavalinkAudioBackend
from core.source_resolver.smart import CatalogTrack, Choice

Config.CACHE_ENABLED = False


def run(choice, *, enabled=True):
    calls = {"stream": [], "loadtracks": []}
    original_choose = lavalink_module.SmartResolver.choose
    original_flag = Config.SMART_RESOLVER

    async def fake_choose(self, query):
        return choice

    async def fake_stream(self, url):
        calls["stream"].append(url)
        return "https://stream.test/" + url[-5:]

    async def fake_loadtracks(self, identifier):
        calls["loadtracks"].append(identifier)
        return {"loadType": "search", "data": [{"info": {
            "title": "Bohemian Rhapsody", "author": "Queen", "length": 355000,
            "uri": "https://www.youtube.com/watch?v=old01", "isStream": False}}]}

    async def no_network(self, query, requester, requester_id):
        raise AssertionError("il test non deve arrivare al resolver completo (rete)")

    async def go():
        backend = LavalinkAudioBackend()
        backend._fetch_stream_url = fake_stream.__get__(backend)
        backend._request_loadtracks = fake_loadtracks.__get__(backend)
        backend._current_track_info = no_network.__get__(backend)
        try:
            return await backend.resolve_track_info("bohemian rhapsody", requester="t", requester_id=1)
        finally:
            await backend.close()

    try:
        lavalink_module.SmartResolver.choose = fake_choose
        Config.SMART_RESOLVER = enabled
        return asyncio.run(go()), calls
    finally:
        lavalink_module.SmartResolver.choose = original_choose
        Config.SMART_RESOLVER = original_flag


meta = CatalogTrack("1", "Bohemian Rhapsody", "Queen", 354, cover="https://cdn.test/cover.jpg")
choice = Choice(url="https://www.youtube.com/watch?v=queen", title="Bohemian Rhapsody", artist="Queen",
                duration=355, thumbnail="https://cdn.test/cover.jpg", route="catalogo+isrc", score=90,
                reason="test", catalog=meta, source_title="Bohemian Rhapsody", source_author="Queen")

# Scelta affidabile: brano del catalogo, copertina del catalogo, stream del video scelto.
track, calls = run(choice)
assert track.webpage_url == "https://www.youtube.com/watch?v=queen", track
assert track.title == "Bohemian Rhapsody" and track.artist == "Queen", track
assert track.thumbnail_source == "deezer" and track.stream_url == "https://stream.test/queen", track
assert calls["loadtracks"] == [], calls

# Nessuna scelta: percorso precedente (ricerca Lavalink diretta).
track, calls = run(None)
assert track.webpage_url == "https://www.youtube.com/watch?v=old01", track
assert calls["loadtracks"], calls

# Interruttore SMART_RESOLVER=false: percorso precedente anche con una scelta disponibile.
track, calls = run(choice, enabled=False)
assert track.webpage_url == "https://www.youtube.com/watch?v=old01", track

print("OK: /play testuale usa il resolver intelligente con ripiego e interruttore")
