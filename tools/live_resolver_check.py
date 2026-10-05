"""
tools/live_resolver_check.py

Prova LIVE (rete reale, niente Discord) del SourceResolver su link veri:
per ogni caso misura tempo, titolo trovato e se si ottiene un URL audio.

Esegui dalla root del progetto, nel venv del bot:
    python tools/live_resolver_check.py            # tutti i casi
    python tools/live_resolver_check.py deezer     # solo i casi che contengono "deezer"
"""

import asyncio
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.music.input import is_multi_url  # noqa: E402
from core.source_resolver import SourceResolver, platforms  # noqa: E402

CASES = [
    ("ricerca testuale",      "rick astley never gonna give you up"),
    ("youtube watch",         "https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
    ("youtu.be",              "https://youtu.be/dQw4w9WgXcQ"),
    ("youtube music",         "https://music.youtube.com/watch?v=dQw4w9WgXcQ"),
    ("youtube playlist",      "https://www.youtube.com/playlist?list=UUuAXFkgsw1L7xaCfnd5JJOw"),
    ("soundcloud brano",      "https://soundcloud.com/forss/flickermood"),
    ("soundcloud set",        "https://soundcloud.com/the-concept-band/sets/the-royal-concept-ep"),
    ("on.soundcloud (profilo)", "https://on.soundcloud.com/UKiooEY3fmS9R53Z9"),
    ("spotify brano",         "https://open.spotify.com/track/4PTG3Z6ehGkBFwjybzWkR8"),
    ("spotify album",         "https://open.spotify.com/album/0ETFjACtuP2ADo6LFhL6HN"),
    ("spotify playlist ed.",  "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"),
    ("deezer brano",          "https://www.deezer.com/track/14408104"),
    ("deezer album",          "https://www.deezer.com/album/1321413"),
    ("deezer playlist",       "https://www.deezer.com/playlist/908622995"),
    ("apple brano",           "https://music.apple.com/us/album/never-gonna-give-you-up/1773292758?i=1773293184"),
    ("apple album",           "https://music.apple.com/us/album/never-gonna-give-you-up/1773292758"),
    ("apple playlist",        "https://music.apple.com/us/playlist/todays-hits/pl.f4d106fed2bd41149aaacabb233eb5eb"),
    ("bandcamp brano",        "https://banditcamp.bandcamp.com/track/track-i"),
    ("tidal brano",           "https://tidal.com/browse/track/70973230"),
    ("amazon music album",    "https://music.amazon.com/albums/B09V9M8T6Q"),
]

TIMEOUT = 120.0


async def _stream_all(query: str) -> list:
    return [t async for t in SourceResolver.resolve_stream(query, "live-check", 0)]


async def run_case(label: str, query: str) -> dict:
    row = {"label": label, "n": 0, "title": "", "audio": False, "err": "", "t_resolve": 0.0, "t_audio": 0.0}
    t0 = time.perf_counter()
    # Come /play: link brevi espansi e piattaforme illeggibili rifiutate.
    if platforms.is_short_link(query):
        query = await asyncio.get_running_loop().run_in_executor(None, platforms.expand_short_link, query)
    if unsupported := platforms.unsupported_platform(query):
        row["err"] = f"non supportato da /play: {unsupported}"
        return row
    # Come /play: le raccolte passano da resolve_stream, il resto da resolve.
    try:
        if is_multi_url(query):
            tracks = await asyncio.wait_for(_stream_all(query), TIMEOUT)
        else:
            tracks = await asyncio.wait_for(SourceResolver.resolve(query, "live-check", 0), TIMEOUT)
    except Exception as exc:
        row["err"] = f"{type(exc).__name__}: {exc}"[:200]
        tracks = []
    row["t_resolve"] = time.perf_counter() - t0
    row["n"] = len(tracks)
    if not tracks:
        row["err"] = row["err"] or "nessun risultato"
        return row
    first = tracks[0]
    row["title"] = f"{first.title} [{first.source}{', pending' if first.is_pending else ''}]"
    t0 = time.perf_counter()
    try:
        url = await asyncio.wait_for(SourceResolver.resolve_fresh_url(first), TIMEOUT)
        row["audio"] = bool(url)
        if url:
            row["title"] += f" -> {first.webpage_url[:60]}"
        else:
            row["err"] = "resolve_fresh_url vuoto"
    except Exception as exc:
        row["err"] = f"fresh_url: {type(exc).__name__}: {exc}"[:200]
    row["t_audio"] = time.perf_counter() - t0
    return row


async def main() -> int:
    flt = sys.argv[1].lower() if len(sys.argv) > 1 else ""
    rows = []
    for label, query in CASES:
        if flt and flt not in label.lower() and flt not in query.lower():
            continue
        row = await run_case(label, query)
        rows.append(row)
        mark = "OK " if row["audio"] else "KO "
        print(
            f"{mark} {row['label']:<24} n={row['n']:<4} resolve={row['t_resolve']:5.1f}s "
            f"audio={row['t_audio']:5.1f}s  {row['title'][:110]}"
            + (f"\n     ERR {row['err']}" if row["err"] else ""),
            flush=True,
        )
    ok = sum(r["audio"] for r in rows)
    print(f"\n{ok}/{len(rows)} con URL audio")
    return 0 if ok == len(rows) else 1


if __name__ == "__main__":
    logging.basicConfig(level=os.getenv("LIVE_LOG_LEVEL", "WARNING"))
    sys.exit(asyncio.run(main()))
