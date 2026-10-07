"""
Valuta la scelta del brano per le query testuali contro tools/resolver_gold.json.

Uso (sulla VM, serve Lavalink):
    python tools/resolver_eval.py smart   [--set db|curati] [--out risultati.jsonl] [--only "query"]
    python tools/resolver_eval.py current [...]

- smart:   core.source_resolver.smart (catalogo Deezer + ISRC + YouTube Music/YouTube)
- current: percorso attuale di /play (LavalinkAudioBackend.resolve_track_info)

Non estrae stream (la scelta avviene prima) e non usa la cache DB: si possono
rieseguire centinaia di query senza far scattare i controlli anti-bot di YouTube.
Si mette in pausa se il bot sta suonando (ffmpeg attivo).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import subprocess
import sys
import time
from urllib.parse import quote

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config  # noqa: E402

Config.CACHE_ENABLED = False

from core.source_resolver.smart import (  # noqa: E402
    LYRICS_RE, VIDEO_RE, content, core_title, coverage, find_tags, norm, title_similarity, tokens,
)

GOLD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resolver_gold.json")


def title_ok(expected: str, expected_artists: list[str], *candidates: tuple[str, str]) -> bool:
    forms = [content(core_title(expected, a).split()) for a in expected_artists] or [content(core_title(expected).split())]
    return any(_title_form_ok(want, *candidates) for want in forms)


def artist_ok(expected: str, haystack: str) -> bool:
    """Anche senza spazi: "TonyPitony" e "Tony Pitony" sono lo stesso artista."""
    if coverage(content(tokens(expected)), tokens(haystack)) >= 0.6:
        return True
    joined = "".join(tokens(expected))
    return len(joined) >= 4 and joined in "".join(tokens(haystack))


def _title_form_ok(want: list[str], *candidates: tuple[str, str]) -> bool:
    for title, author in candidates:
        if not title:
            continue
        got = core_title(title, author)
        if coverage(want, got.split()) >= 0.85 or title_similarity(" ".join(want), got) >= 0.75:
            return True
        # Anche con le parentesi: "DONNE RICCHE (Acoustic Version)".
        if coverage(want, tokens(title)) >= 0.85:
            return True
    return False


def check(exp: dict, query: str, res: dict | None) -> tuple[bool, str]:
    if not res or not res.get("url"):
        return False, "nessun risultato"
    if exp.get("any"):
        return True, ""
    src_title, src_author = res.get("source_title", ""), res.get("source_author", "")
    shown = (res.get("title", ""), res.get("artist", ""))
    problems = []
    if exp.get("title") and not any(title_ok(t, exp.get("artist", []), shown, (src_title, src_author)) for t in exp["title"]):
        problems.append("titolo")
    if exp.get("artist"):
        hay = f"{res.get('artist', '')} {src_author} {src_title}"
        if not any(artist_ok(a, hay) for a in exp["artist"]):
            problems.append("artista")
    have = find_tags(src_title)
    for tag in exp.get("tags", []):
        ok = have & {"tiktok", "sped_up", "remix", "nightcore"} if tag == "tiktok" else tag in have
        if not ok:
            problems.append(f"manca {tag}")
    extra = have - find_tags(query) - {"reverb"}
    if "tiktok" in find_tags(query):
        extra -= {"sped_up", "remix", "tiktok"}
    if extra and not exp.get("any"):
        problems.append("versione non chiesta: " + ",".join(sorted(extra)))
    for word in exp.get("forbid_words", []):
        if word in norm(src_title).split():
            problems.append(f"contiene {word}")
    if exp.get("video") and not VIDEO_RE.search(norm(src_title)):
        problems.append("non e' il videoclip")
    if exp.get("lyrics") and not LYRICS_RE.search(norm(src_title)):
        problems.append("non e' il video col testo")
    return not problems, ", ".join(problems)


def busy() -> bool:
    try:
        return subprocess.run(["pgrep", "-x", "ffmpeg"], capture_output=True).returncode == 0
    except FileNotFoundError:
        return False


async def make_smart():
    import aiohttp
    from core.source_resolver.deezer_catalog import DeezerCatalog
    from core.source_resolver.smart import SmartResolver

    session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5))
    deezer = DeezerCatalog(session)
    base = Config.LAVALINK_URI.rstrip("/")

    async def loadtracks(identifier: str) -> dict:
        url = f"{base}/v4/loadtracks?identifier={quote(identifier, safe='')}"
        async with session.get(url, headers={"Authorization": Config.LAVALINK_PASSWORD}) as resp:
            return await resp.json()

    resolver = SmartResolver(deezer.search, deezer.track, loadtracks)

    async def run(query: str) -> dict | None:
        choice = await resolver.choose(query)
        if choice is None:
            return None
        return {"url": choice.url, "title": choice.title, "artist": choice.artist,
                "source_title": choice.source_title, "source_author": choice.source_author,
                "route": choice.route, "score": choice.score, "reason": choice.reason}

    return run, session.close


async def make_current():
    from core.audio_backends.lavalink import LavalinkAudioBackend
    from core.source_resolver import SourceResolver

    SourceResolver._fetch_stream_url = classmethod(lambda cls, url: "https://stream.invalid/eval")

    async def run(query: str) -> dict | None:
        backend = LavalinkAudioBackend()
        try:
            track = await backend.resolve_track_info(query, requester="eval", requester_id=1)
        finally:
            await backend.close()
        if track is None:
            return None
        return {"url": track.webpage_url, "title": track.title, "artist": track.artist,
                "source_title": track.title, "source_author": track.artist, "route": "current"}

    async def noop():
        return None

    return run, noop


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["smart", "current"])
    parser.add_argument("--set", choices=["db", "curati"])
    parser.add_argument("--only")
    parser.add_argument("--out")
    parser.add_argument("--pause", type=float, default=0.8)
    args = parser.parse_args()
    logging.disable(logging.WARNING)

    gold = json.load(open(GOLD, encoding="utf-8"))
    if args.set:
        gold = [g for g in gold if g["set"] == args.set]
    if args.only:
        gold = [g for g in gold if g["q"] == args.only]
    run, close = await (make_smart() if args.mode == "smart" else make_current())
    out = open(args.out, "w", encoding="utf-8") if args.out else None
    passed, times, failures = 0, [], []
    try:
        for i, g in enumerate(gold, 1):
            while busy():
                await asyncio.sleep(15)
            t0 = time.perf_counter()
            try:
                res = await run(g["q"])
                err = ""
            except Exception as exc:
                res, err = None, f"{type(exc).__name__}: {exc}"
            secs = time.perf_counter() - t0
            ok, why = check(g, g["q"], res)
            why = why or err
            passed += ok
            times.append(secs)
            if not ok:
                failures.append((g, res, why))
            if out:
                out.write(json.dumps({"q": g["q"], "set": g["set"], "ok": ok, "why": why, "secs": round(secs, 2),
                                      **(res or {})}, ensure_ascii=False) + "\n")
                out.flush()
            print(f"{i}/{len(gold)} {'OK ' if ok else 'NO '} {secs:4.2f}s {g['q'][:50]}", flush=True)
            await asyncio.sleep(args.pause)
    finally:
        await close()
        if out:
            out.close()

    times.sort()
    print(f"\n{args.mode}: {passed}/{len(gold)} corrette  "
          f"tempo mediano {times[len(times) // 2]:.2f}s  p90 {times[int(len(times) * 0.9)]:.2f}s  max {times[-1]:.2f}s")
    for g, res, why in failures:
        got = f"{res.get('source_title', '')} | {res.get('source_author', '')} [{res.get('route', '')}]" if res else "-"
        print(f"  NO [{g['set']}] {g['q']!r}: {why}\n       atteso {g.get('title')} {g.get('artist') or ''} {g.get('tags') or ''}\n       avuto  {got}")


if __name__ == "__main__":
    asyncio.run(main())
