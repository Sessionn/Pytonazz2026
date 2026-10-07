"""
tests/test_smart_resolver.py

Esegui dalla root del progetto con:
    python tests/test_smart_resolver.py

Logica del resolver testuale (core/source_resolver/smart.py) con dati finti:
niente rete, Deezer e Lavalink simulati.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.source_resolver.smart import CatalogTrack, SmartResolver, parse_intent, version_tags

# ── Intento ──────────────────────────────────────────────────────────────────
i = parse_intent("Blinding Lights (Slowed + Reverb)")
assert i.tags == {"slowed", "reverb"} and i.core == ["blinding", "lights"], i
assert parse_intent("misery super slowed pupsies").intensity == {"super"}
assert parse_intent("gangnam style official video").wants_video
assert parse_intent("smells like teen spirit lyrics").wants_lyrics
assert parse_intent("love nwantiti tiktok version").tags == {"tiktok"}
assert parse_intent("bohemian rhapsody").plain

# Parole ambigue: versione solo fuori dal nome del brano.
assert version_tags("Live Forever", "Oasis") == set()
assert version_tags("Hotel California (Live 1977)", "Eagles") == {"live"}
assert version_tags("Piano Man", "Billy Joel") == set()
assert version_tags("Interstellar Main Theme (Piano)", "Soundtrack Orchestra") == {"piano"}
assert version_tags("Blinding Lights slowed + reverb", "x") == {"slowed", "reverb"}


# ── Orchestrazione con fonti finte ───────────────────────────────────────────
def lavalink_track(title, author, seconds, vid):
    return {"info": {"title": title, "author": author, "length": seconds * 1000,
                     "uri": f"https://www.youtube.com/watch?v={vid}", "isStream": False}}


def resolver(catalog, ytm, yt, isrc_hits=None):
    """isrc_hits: {isrc: traccia Lavalink} restituita da ytmsearch:"ISRC"."""
    isrc_hits = isrc_hits or {}

    async def search_catalog(q):
        return [CatalogTrack(**c) for c in catalog]

    async def catalog_track(track_id):
        match = next((c for c in catalog if c["id"] == track_id), None)
        return CatalogTrack(**match) if match else None

    async def loadtracks(identifier):
        prefix, _, q = identifier.partition(":")
        if q.startswith('"'):
            hit = isrc_hits.get(q.strip('"'))
            return {"loadType": "search", "data": [hit] if hit else []}
        return {"loadType": "search", "data": ytm if prefix == "ytmsearch" else yt}

    return SmartResolver(search_catalog, catalog_track, loadtracks)


def run(res, q):
    return asyncio.run(res.choose(q))


# Titolo comune: il consenso con YouTube batte la popolarita' del solo catalogo.
catalog = [
    {"id": "1", "title": "Hallelujah", "artist": "JUL", "duration": 190, "rank": 900000},
    {"id": "2", "title": "Hallelujah", "artist": "Leonard Cohen", "duration": 279, "rank": 700000},
]
ytm = [lavalink_track("Hallelujah", "Leonard Cohen", 279, "cohen"), lavalink_track("Hallelujah", "Jeff Buckley", 414, "buckley")]
yt = [lavalink_track("Leonard Cohen - Hallelujah (Live In London)", "LeonardCohenVEVO", 446, "cohenlive")]
choice = run(resolver(catalog, ytm, yt), "hallelujah")
assert choice.artist == "Leonard Cohen" and choice.url.endswith("cohen"), choice

# Versione chiesta: "slowed" non accetta "super slowed".
ytm = [lavalink_track("Misery (Super Slowed)", "Release - Topic", 234, "super")]
yt = [lavalink_track("misery. (slowed)", "pupsies - Topic", 187, "slowed"),
      lavalink_track("Misery (Super Slowed)", "Release - Topic", 234, "super2")]
choice = run(resolver([], ytm, yt), "misery slowed pupsies")
assert choice.url.endswith("=slowed"), choice

# Frase del testo: YouTube Music e YouTube concordano sul brano.
ytm = [lavalink_track("Bohemian Rhapsody", "Queen", 355, "song")]
yt = [lavalink_track("Is this the real Life? Is this just...Fanta C", "NickyWhoMake", 30, "meme"),
      lavalink_track("Queen – Bohemian Rhapsody (Official Video Remastered)", "Queen Official", 360, "video")]
choice = run(resolver([], ytm, yt), "is this the real life is this just fantasy")
assert choice.url.endswith("=song"), choice

# Cover senza artista: vince la cover popolare di YouTube, non una del catalogo.
catalog = [{"id": "9", "title": "Hallelujah (Cover)", "artist": "Maddisyn Challe", "duration": 221, "rank": 47778}]
yt = [lavalink_track("Hallelujah - Lucy Thomas - (Official Music Video)", "Lucy Thomas Music", 225, "lucy"),
      lavalink_track("Hallelujah - Leonard Cohen (Cover by Pentatonix)", "PTXofficial", 260, "ptx")]
choice = run(resolver(catalog, [], yt), "hallelujah cover")
assert choice.url.endswith("=ptx"), choice

# Videoclip chiesto: si sceglie il video ufficiale.
ytm = [lavalink_track("Gangnam Style", "PSY", 219, "audio")]
yt = [lavalink_track("PSY - GANGNAM STYLE(강남스타일) M/V", "officialpsy", 252, "mv")]
choice = run(resolver([], ytm, yt), "gangnam style official video")
assert choice.url.endswith("=mv"), choice

# Refusi solo su parole lunghe: "notte blu" non e' "NOTTI BLU".
from core.source_resolver.smart import coverage  # noqa: E402
assert coverage(["notte", "blu"], ["notti", "blu"]) == 0.5
assert coverage(["despasito"], ["despacito"]) == 1.0
assert coverage(["take"], ["takes"]) == 1.0

# "tiktok sound" = canzone famosa su TikTok, non una versione; "tiktok version" si'.
assert parse_intent("i just get so nervy tiktok sound").plain
assert parse_intent("love nwantiti tiktok version").tags == {"tiktok"}

# Corrispondenza esatta (titolo e artista nella query) prima dell'accordo tra le fonti.
ytm = [lavalink_track("Love Tonight", "Shouse", 200, "shouse"),
       lavalink_track("All I Need Is Your Love Tonight", "Velvet Soul - Topic", 182, "velvet")]
yt = [lavalink_track("Shouse - Love Tonight (Edit)", "Shouse", 200, "shouse2")]
choice = run(resolver([], ytm, yt), "All i need is your love tonight")
assert choice.url.endswith("=velvet"), choice

# Niente di utilizzabile: None (il bot ripiega sul resolver precedente).
assert run(resolver([], [], []), "qualsiasi cosa") is None

print("OK: resolver testuale (intento, versioni, consenso, accordo, cover, videoclip)")
