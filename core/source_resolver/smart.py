"""
core/source_resolver/smart.py
-----------------------------
Query testuale -> brano giusto, come i bot musicali professionali (LavaSrc, spotDL).

1. Intento: dalla query si separano le parole di versione (cover, live, acoustic,
   remix, slowed, sped up, nightcore, 8D, strumentale, karaoke, TikTok, ...),
   l'intensita' ("super slowed" non e' "slowed") e la richiesta di videoclip o testo.
2. In parallelo: catalogo Deezer (titolo, artista, durata, popolarita'; API pubblica,
   ~0.15 s), YouTube Music e YouTube via Lavalink (~0.5 s).
3. Se il catalogo identifica il brano con la versione chiesta: ISRC -> YouTube Music
   (`ytmsearch:"ISRC"`, ~0.25 s) = la registrazione ufficiale. Senza ISRC utile si
   sceglie tra i risultati YouTube con le regole di spotDL (artista vincolante,
   durata, parole di versione non richieste penalizzate).
4. Senza catalogo (cover di utenti, meme, frasi del testo, upload amatoriali) si
   sceglie tra i risultati YouTube per copertura della query, versione e canale;
   se il vincitore e' una canzone pubblicata si passa comunque all'audio ufficiale.

Il modulo non fa I/O da solo: riceve `search_catalog`, `catalog_track` e
`loadtracks` (Lavalink), cosi' si prova con dati finti e si misura con quelli veri.
"""
from __future__ import annotations

import asyncio
import logging
import math
import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Awaitable, Callable, Iterable

log = logging.getLogger("pitonazz.smart")

# ── Intento ──────────────────────────────────────────────────────────────────

# Versioni: parola canonica -> espressione (titoli e query, piu' lingue).
TAG_PATTERNS: dict[str, re.Pattern[str]] = {
    "live": re.compile(r"\b(live|dal vivo|en vivo|ao vivo|in concert|concerto|concert|live session)\b"),
    "acoustic": re.compile(r"\b(acoustic|acustic[ao]|unplugged)\b"),
    "cover": re.compile(r"\bcover\b"),
    "remix": re.compile(r"\b(remix|rmx|bootleg|rework|vip mix|club mix|mashup)\b"),
    "slowed": re.compile(r"\b(slowed|slow(?:ed)? down)\b"),
    "sped_up": re.compile(r"\b(sped ?up|speed ?up|spedup|sped)\b"),
    "nightcore": re.compile(r"\bnightcore\b"),
    "reverb": re.compile(r"\breverb\b"),
    "8d": re.compile(r"\b8 ?d\b"),
    "instrumental": re.compile(r"\b(instrumental|strumentale|instrumentale|base musicale|beat only)\b"),
    "karaoke": re.compile(r"\bkaraoke\b"),
    "acapella": re.compile(r"\b(a ?cap?pella|vocals? only|solo voce)\b"),
    "tiktok": re.compile(r"\btik ?tok (?:version|versione|remix|edit|mix)\b|\b(?:version|versione|remix|edit) tik ?tok\b"),
    "extended": re.compile(r"\bextended\b"),
    "bass_boosted": re.compile(r"\bbass ?boost(?:ed)?\b"),
    "orchestral": re.compile(r"\b(orchestral|orchestra|symphonic)\b"),
    # Arrangiamenti: "Interstellar Main Theme (Piano)", "Gurenge (lofi box)", ...
    "piano": re.compile(r"\bpiano\b"),
    "lofi": re.compile(r"\blo ?fi\b"),
    "music_box": re.compile(r"\bmusic ?box\b"),
    "8bit": re.compile(r"\b(8 ?bit|chiptune)\b"),
    "jazz": re.compile(r"\b(jazz|bossa nova)\b"),
    "metal": re.compile(r"\bmetal\b"),
    "guitar": re.compile(r"\bguitar\b"),
    "strings": re.compile(r"\b(violin|cello|string quartet)\b"),
    "sax": re.compile(r"\bsax(?:ophone)?\b"),
}
# Parole che possono essere anche nel nome della canzone ("Live Forever", "Piano Man",
# "Cover Me", "Heavy Metal"): sono versioni solo fuori dal nome (parentesi, dopo " - ").
WEAK_TAGS = frozenset({"live", "cover", "acoustic", "remix", "extended", "orchestral", "piano", "jazz",
                       "metal", "guitar", "strings", "sax", "music_box", "lofi"})
# Versioni che vivono su YouTube (upload di utenti): senza un artista nella query
# vince la rilevanza di YouTube, non una release sconosciuta del catalogo.
YT_NATIVE_TAGS = frozenset({"cover", "slowed", "sped_up", "nightcore", "8d", "karaoke", "tiktok", "reverb", "bass_boosted"})
# Modificatori che cambiano la versione: "super slowed" e "slowed" sono diverse.
INTENSITY_RE = re.compile(r"\b(super|ultra|extra|mega|hyper|hardtekk|hardstyle|phonk|daycore)\b")
VIDEO_RE = re.compile(r"\b(official (?:music )?video|music video|videoclip|video ufficiale|video oficial|m ?v)\b")
LYRICS_RE = re.compile(r"\b(lyrics?|lyric video|testo|letra|paroles)\b")
TRANSLATED_RE = re.compile(
    r"\b(sub(?:s|titulad[ao]|titles|titled)? (?:espanol|ita|italiano|eng|english|pt|portugues)"
    r"|subtitulad[ao]|traducid[ao]|traduccion|traduzione|tradotto|sottotitol[io]|legendad[ao]|traducao)\b"
)
# Parole che non identificano il brano.
FILLER = frozenset({
    "by", "di", "de", "feat", "ft", "featuring", "prod", "official", "audio", "ufficiale", "oficial",
    "song", "canzone", "cancion", "track", "full", "hq", "hd", "4k", "version", "versione", "version",
    "the", "original", "topic", "music", "musica", "video", "visualizer", "x", "e", "and", "con", "with",
    # "i just get so nervy tiktok sound": la canzone famosa su TikTok, non una versione.
    "tiktok", "tik", "tok", "sound", "trend", "viral", "reels",
})
# Artisti "di servizio" del catalogo: cover anonime, karaoke, tributi.
SERVICE_ARTIST_RE = re.compile(
    r"\b(karaoke|tribute|made famous|originally performed|cover band|covers?|piano|lullaby|the hit crew"
    r"|string quartet|8d|nightcore|sped up|slowed|tiktok|ringtone|workout|kids|bimbi|instrumental)\b"
)
BRACKETS_RE = re.compile(r"[\(\[\{][^\)\]\}]*[\)\]\}]")
FEAT_RE = re.compile(r"\s(?:feat\.?|ft\.?|featuring)\s.*$")


def strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def norm(text: str) -> str:
    text = strip_accents(text).lower().replace("&", " and ").replace("$", "s")
    text = re.sub(r"[^\w\s+]", " ", text)
    # "+" solo dentro un nome ("+2y"), non come in "Slowed + Reverb".
    text = re.sub(r"\+(?!\w)", " ", text)
    return " ".join(text.split())


def tokens(text: str) -> list[str]:
    return [t for t in norm(text).split() if t]


def content(words: Iterable[str]) -> list[str]:
    """Parole che identificano il brano (senza "the", "official", "feat", ...)."""
    kept = [w for w in words if w not in FILLER]
    return kept or list(words)


def find_tags(text: str) -> set[str]:
    n = norm(text)
    found = {tag for tag, rx in TAG_PATTERNS.items() if rx.search(n)}
    return found


def version_tags(title: str, artist: str = "") -> set[str]:
    """Versioni di un titolo, senza le parole ambigue che fanno parte del nome del brano."""
    name_tags = find_tags(core_title(title, artist)) & WEAK_TAGS
    return find_tags(title) - name_tags


def intensity_words(text: str) -> set[str]:
    return set(INTENSITY_RE.findall(norm(text)))


@dataclass
class Intent:
    raw: str
    core: list[str]      # parole del brano, senza versioni
    words: list[str]     # tutte le parole utili (anche "live" di "Live Forever")
    tags: set[str]
    intensity: set[str]
    wants_video: bool
    wants_lyrics: bool
    wants_translation: bool

    @property
    def plain(self) -> bool:
        return not self.tags and not self.wants_video and not self.wants_lyrics


def parse_intent(query: str) -> Intent:
    n = norm(query)
    wants_video = bool(VIDEO_RE.search(n))
    wants_lyrics = bool(LYRICS_RE.search(n))
    stripped = n
    for rx in (*TAG_PATTERNS.values(), INTENSITY_RE, VIDEO_RE, LYRICS_RE):
        stripped = rx.sub(" ", stripped)
    core = [t for t in stripped.split() if t not in FILLER] or [t for t in n.split() if t]
    words = content(LYRICS_RE.sub(" ", VIDEO_RE.sub(" ", n)).split())
    return Intent(
        raw=query,
        core=core,
        words=words,
        tags=find_tags(query),
        intensity=intensity_words(query),
        wants_video=wants_video,
        wants_lyrics=wants_lyrics,
        wants_translation=bool(TRANSLATED_RE.search(n)),
    )


# ── Confronto testi ──────────────────────────────────────────────────────────

def _tok_match(a: str, b: str) -> bool:
    if a == b:
        return True
    short, long_ = sorted((a, b), key=len)
    # Plurale / lettera finale in piu' ("take" / "takes").
    if len(short) >= 3 and long_.startswith(short) and len(long_) - len(short) == 1:
        return True
    # Refusi solo su parole lunghe: "notte" e "notti" sono parole diverse.
    if len(short) < 6:
        return False
    return SequenceMatcher(None, a, b).ratio() >= 0.8


def coverage(needles: Iterable[str], haystack: Iterable[str]) -> float:
    needles = [t for t in needles if t]
    hay = [t for t in haystack if t]
    if not needles:
        return 0.0
    hit = sum(1 for t in needles if any(_tok_match(t, h) for h in hay))
    return hit / len(needles)


def core_title(title: str, artist: str = "") -> str:
    """Titolo senza parentesi, featuring e nome dell'artista ("Artista - Titolo")."""
    text = BRACKETS_RE.sub(" ", title or "")
    text = FEAT_RE.sub(" ", " " + text)
    parts = [p.strip() for p in re.split(r"\s[-–—|]\s", text) if p.strip()]
    if len(parts) >= 2 and artist:
        a = tokens(artist)
        # Tiene la parte che non e' l'artista.
        rest = [p for p in parts if coverage(tokens(p), a) < 0.6]
        if rest:
            text = " ".join(rest)
    return " ".join(tokens(text))


def title_similarity(a: str, b: str) -> float:
    ta, tb = a.split(), b.split()
    if not ta or not tb:
        return 0.0
    both = min(coverage(ta, tb), coverage(tb, ta))
    seq = SequenceMatcher(None, " ".join(sorted(ta)), " ".join(sorted(tb))).ratio()
    return max(both, seq * 0.95)


# ── Candidati ────────────────────────────────────────────────────────────────

@dataclass
class CatalogTrack:
    id: str
    title: str
    artist: str
    duration: int
    rank: int = 0
    cover: str = ""
    album: str = ""
    isrc: str = ""


@dataclass
class Candidate:
    title: str
    author: str
    duration: int
    url: str
    origin: str  # "isrc", "ytm", "yt"
    position: int = 0
    artwork: str = ""

    @property
    def is_topic(self) -> bool:
        return self.origin in ("isrc", "ytm") or self.author.lower().endswith(" - topic")


@dataclass
class Choice:
    url: str
    title: str
    artist: str
    duration: int
    thumbnail: str
    route: str
    score: float
    reason: str
    catalog: CatalogTrack | None = None
    source_title: str = ""
    source_author: str = ""
    candidates: list[Candidate] = field(default_factory=list, repr=False)


def candidate_from_lavalink(track: dict, origin: str, position: int) -> Candidate | None:
    info = track.get("info") if isinstance(track, dict) else None
    if not isinstance(info, dict) or info.get("isStream"):
        return None
    url = str(info.get("uri") or "")
    if not url.startswith(("https://", "http://")):
        return None
    return Candidate(
        title=str(info.get("title") or ""),
        author=str(info.get("author") or ""),
        duration=int(info.get("length") or 0) // 1000,
        url=url,
        origin=origin,
        position=position,
        artwork=str(info.get("artworkUrl") or ""),
    )


def _version_penalty(intent: Intent, title: str, author: str = "") -> tuple[float, list[str]]:
    """Penalita' per versioni non chieste o mancanti (spotDL: -15 per parola)."""
    have = version_tags(title, author)
    # "Live Forever" chiesto come "live forever oasis": "live" e' il nome, non la versione.
    want = set(intent.tags) - (find_tags(core_title(title, author)) & WEAK_TAGS)
    notes = []
    penalty = 0.0
    # "tiktok version" e' quasi sempre una versione sped up o un edit.
    if "tiktok" in want:
        want.discard("tiktok")
        if not have & {"tiktok", "sped_up", "remix", "slowed", "nightcore"}:
            penalty += 25
            notes.append("manca:tiktok")
        have -= {"tiktok", "sped_up"}
    # "slowed + reverb": reverb da solo non e' una versione diversa da slowed.
    if "slowed" in want or "slowed" in have:
        want.discard("reverb")
        have.discard("reverb")
    missing = want - have
    extra = have - want
    if missing:
        penalty += 30 * len(missing)
        notes.append("manca:" + ",".join(sorted(missing)))
    if extra:
        penalty += 15 * len(extra)
        notes.append("extra:" + ",".join(sorted(extra)))
    extra_intensity = intensity_words(title) - intent.intensity
    if extra_intensity and (have or want):
        penalty += 15
        notes.append("intensita':" + ",".join(sorted(extra_intensity)))
    if TRANSLATED_RE.search(norm(title)) and not intent.wants_translation:
        penalty += 25
        notes.append("tradotto")
    elif LYRICS_RE.search(norm(title)) and not intent.wants_lyrics:
        penalty += 10
        notes.append("testo")
    return penalty, notes


def _presentation_bonus(intent: Intent, cand: Candidate) -> float:
    """Videoclip o video col testo chiesti: premia quelli, penalizza gli audio di YouTube Music."""
    bonus = 0.0
    title = norm(cand.title)
    if intent.wants_video:
        bonus += 15 if VIDEO_RE.search(title) else (-15 if cand.origin in ("isrc", "ytm") else 0)
    if intent.wants_lyrics:
        bonus += 15 if LYRICS_RE.search(title) else (-10 if cand.origin in ("isrc", "ytm") else 0)
    return bonus


# ── Punteggi ─────────────────────────────────────────────────────────────────

def score_catalog(intent: Intent, track: CatalogTrack) -> tuple[float, bool, str]:
    """Quanto il brano del catalogo corrisponde alla query. (punteggio, affidabile, motivo)"""
    t = content(core_title(track.title).split())
    a = content(tokens(track.artist))
    title_in_query = coverage(t, intent.words)
    # Tutto il titolo (anche le parentesi: "Bohemian Rhapsody (Live Aid)") e l'artista.
    query_explained = coverage(intent.core, content(tokens(track.title)) + a)
    artist_named = coverage(a, intent.words)
    penalty, notes = _version_penalty(intent, track.title, track.artist)
    if SERVICE_ARTIST_RE.search(norm(track.artist)) and not intent.tags:
        penalty += 25
        notes.append("artista-di-servizio")
    popularity = 12 * math.log10(max(track.rank, 1) + 1) / 6
    score = 50 * title_in_query + 30 * query_explained + 15 * artist_named + popularity - penalty
    reliable = title_in_query >= 0.75 and query_explained >= 0.65 and penalty < 15
    if intent.tags & YT_NATIVE_TAGS and artist_named < 0.5:
        reliable = False
        notes.append("versione-da-youtube")
    reason = f"titolo={title_in_query:.2f} query={query_explained:.2f} artista={artist_named:.2f} pop={popularity:.1f} {' '.join(notes)}"
    return score, reliable, reason


def score_against_catalog(intent: Intent, cand: Candidate, meta: CatalogTrack) -> tuple[float, bool, str]:
    """Candidato YouTube contro il brano del catalogo (regole spotDL)."""
    t_sim = title_similarity(core_title(cand.title, meta.artist), core_title(meta.title))
    meta_artist = tokens(meta.artist)
    a_sim = max(coverage(meta_artist, tokens(cand.author)), coverage(meta_artist, tokens(cand.title)))
    diff = abs(cand.duration - meta.duration) if cand.duration and meta.duration else None
    duration = math.exp(-0.1 * diff) if diff is not None else 0.5
    penalty, notes = _version_penalty(intent, cand.title, cand.author)
    bonus = {"isrc": 15, "ytm": 5}.get(cand.origin, 0) + (4 if cand.is_topic else 0)
    bonus += _presentation_bonus(intent, cand)
    score = 40 * t_sim + 30 * a_sim + 20 * duration + bonus - penalty
    # Durata: tolleranza piu' larga per versioni (live, remix...) e video.
    duration_ok = diff is None or diff <= 12 or bool(intent.tags) or intent.wants_video
    reliable = t_sim >= 0.7 and a_sim >= 0.5 and duration_ok and penalty < 15
    reason = f"titolo={t_sim:.2f} artista={a_sim:.2f} durata={'-' if diff is None else diff}s {cand.origin} {' '.join(notes)}"
    return score, reliable, reason


def score_free(intent: Intent, cand: Candidate) -> tuple[float, bool, str]:
    """Candidato YouTube senza catalogo: copertura della query, versione, canale, rilevanza."""
    words = tokens(f"{cand.title} {cand.author}")
    title_words = content(core_title(cand.title, cand.author).split())
    q_cov = coverage(intent.core, words)
    t_cov = coverage(title_words, intent.core + tokens(cand.author)) if title_words else 0.0
    penalty, notes = _version_penalty(intent, cand.title, cand.author)
    rank_bonus = 10 * max(0.0, 1 - cand.position / 10)
    bonus = (4 if cand.is_topic else 0) + (3 if cand.origin == "ytm" and intent.plain else 0)
    bonus += _presentation_bonus(intent, cand)
    score = 50 * q_cov + 20 * t_cov + rank_bonus + bonus - penalty
    reliable = q_cov >= 0.6 and penalty < 30
    reason = f"query={q_cov:.2f} titolo={t_cov:.2f} pos={cand.position} {cand.origin} {' '.join(notes)}"
    return score, reliable, reason


# ── Orchestrazione ───────────────────────────────────────────────────────────

SearchCatalog = Callable[[str], Awaitable[list[CatalogTrack]]]
CatalogDetail = Callable[[str], Awaitable[CatalogTrack | None]]
LoadTracks = Callable[[str], Awaitable[dict]]


def _tracks(payload: dict) -> list[dict]:
    data = (payload or {}).get("data")
    if (payload or {}).get("loadType") == "search" and isinstance(data, list):
        return data
    if (payload or {}).get("loadType") in ("track", "short") and isinstance(data, dict):
        return [data]
    return []


async def _safe(coro, default, timeout: float):
    try:
        return await asyncio.wait_for(coro, timeout)
    except Exception as exc:
        log.debug(f"smart: richiesta saltata ({type(exc).__name__}: {exc})")
        return default


class SmartResolver:
    CATALOG_TIMEOUT = 2.5
    SEARCH_TIMEOUT = 4.0

    def __init__(self, search_catalog: SearchCatalog, catalog_track: CatalogDetail, loadtracks: LoadTracks):
        self.search_catalog = search_catalog
        self.catalog_track = catalog_track
        self.loadtracks = loadtracks

    async def _search(self, prefix: str, query: str, origin: str) -> list[Candidate]:
        payload = await _safe(self.loadtracks(f"{prefix}:{query}"), {}, self.SEARCH_TIMEOUT)
        out = []
        for i, t in enumerate(_tracks(payload)[:12]):
            if (c := candidate_from_lavalink(t, origin, i)) is not None:
                out.append(c)
        return out

    async def _by_isrc(self, meta: CatalogTrack) -> list[Candidate]:
        detail = meta if meta.isrc else await _safe(self.catalog_track(meta.id), None, self.CATALOG_TIMEOUT)
        if detail is None or not detail.isrc:
            return []
        meta.isrc = detail.isrc
        return await self._search("ytmsearch", f'"{detail.isrc}"', "isrc")

    @staticmethod
    def _reliable_catalog(intent: Intent, catalog: list[CatalogTrack]) -> list[tuple[float, CatalogTrack, str]]:
        scored = []
        for track in catalog:
            score, reliable, reason = score_catalog(intent, track)
            if reliable:
                scored.append((score, track, reason))
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored

    @staticmethod
    def _consensus(meta: CatalogTrack, pool: list[Candidate]) -> bool:
        """Il brano del catalogo compare tra i primi risultati di YouTube Music/YouTube.

        La popolarita' di Deezer da sola sbaglia sui titoli comuni ("hallelujah" ->
        JUL, molto ascoltato su Deezer in Francia): i bot professionali incrociano le fonti.
        """
        title = core_title(meta.title)
        artist = content(tokens(meta.artist))
        for cand in pool:
            if cand.position >= 5:
                continue
            if title_similarity(core_title(cand.title, meta.artist), title) < 0.8:
                continue
            if max(coverage(artist, tokens(cand.author)), coverage(artist, tokens(cand.title))) >= 0.6:
                return True
        return False

    @staticmethod
    def _exact(intent: Intent, cands: list[Candidate]):
        """Audio il cui titolo e artista stanno interamente nella query
        ("All i need is your love tonight", "Aquecendo no Passinho V.V.V."): vince
        sull'accordo tra le fonti, che altrimenti preferirebbe il brano piu' famoso."""
        best = None
        for cand in cands:
            title = content(core_title(cand.title, cand.author).split())
            artist = content(tokens(cand.author.removesuffix(" - Topic")))
            if not title or _version_penalty(intent, cand.title, cand.author)[0]:
                continue
            if coverage(title, intent.words) < 0.95 or coverage(intent.core, title + artist) < 0.9:
                continue
            score = 80.0 - cand.position + (5 if cand.is_topic else 0)
            if best is None or score > best[0]:
                best = (score, cand, f"esatto pos={cand.position} {cand.origin}")
        return best

    @staticmethod
    def _agreement(intent: Intent, ytm: list[Candidate], yt: list[Candidate]):
        """YouTube Music e YouTube concordano sul brano in cima (frasi del testo,
        soprannomi come "rick roll", titoli scritti male): ci si fida dell'accordo."""
        for song in ytm[:3]:
            if _version_penalty(intent, song.title, song.author)[0]:
                continue
            name = core_title(song.title, song.author)
            artist = content(tokens(song.author.removesuffix(" - Topic")))
            for video in yt[:3]:
                same_title = title_similarity(core_title(video.title, song.author), name) >= 0.85
                same_artist = max(coverage(artist, tokens(video.author)), coverage(artist, tokens(video.title))) >= 0.6
                if same_title and same_artist:
                    return (60.0 - song.position, song, f"accordo ytm#{song.position}+yt#{video.position}")
        return None

    def _pick(self, intent: Intent, cands: list[Candidate], meta: CatalogTrack | None):
        best = None
        for cand in cands:
            if meta is not None:
                score, reliable, reason = score_against_catalog(intent, cand, meta)
            else:
                score, reliable, reason = score_free(intent, cand)
            if reliable and (best is None or score > best[0]):
                best = (score, cand, reason)
        return best

    async def choose(self, query: str) -> Choice | None:
        intent = parse_intent(query)
        catalog_task = asyncio.create_task(_safe(self.search_catalog(query), [], self.CATALOG_TIMEOUT))
        ytm_task = asyncio.create_task(self._search("ytmsearch", query, "ytm"))
        yt_task = asyncio.create_task(self._search("ytsearch", query, "yt"))

        catalog = await catalog_task
        reliable = self._reliable_catalog(intent, catalog)[:3]
        # ISRC dei migliori 3 gia' in corsa mentre arrivano i risultati di YouTube.
        isrc_tasks = {}
        if not intent.wants_video and not intent.wants_lyrics:
            isrc_tasks = {id(meta): asyncio.create_task(self._by_isrc(meta)) for _, meta, _ in reliable}

        ytm, yt = await asyncio.gather(ytm_task, yt_task)
        pool = [*ytm, *yt]

        best_cat = None
        agreed = self._agreement(intent, ytm, yt) if intent.plain else None
        if reliable:
            ranked = sorted(
                (
                    (score + (15 if self._consensus(meta, pool) else 0), meta, reason, self._consensus(meta, pool))
                    for score, meta, reason in reliable
                ),
                key=lambda x: x[0],
                reverse=True,
            )
            score, meta, reason, confirmed = ranked[0]
            # Brano del catalogo assente da YouTube mentre YouTube Music e YouTube concordano
            # su un altro: tipico delle cover "(From ...)" di colonne sonore e sigle anime.
            if confirmed or agreed is None:
                best_cat = (score, meta, reason)
        for task in isrc_tasks.values():
            if best_cat is None or task is not isrc_tasks.get(id(best_cat[1])):
                task.cancel()

        if best_cat is not None:
            meta = best_cat[1]
            task = isrc_tasks.get(id(meta))
            isrc = await _safe(task, [], self.SEARCH_TIMEOUT) if task else []
            picked = self._pick(intent, isrc + pool, meta)
            if picked is not None:
                score, cand, reason = picked
                return self._choice(cand, meta, "catalogo+" + cand.origin, score, f"{best_cat[2]} | {reason}", pool)

        picked = (
            (self._exact(intent, pool) if not (intent.wants_video or intent.wants_lyrics) else None)
            or agreed
            or self._pick(intent, pool, None)
            or self._by_relevance(intent, ytm + yt if intent.plain else yt + ytm)
        )
        if picked is None:
            return None
        score, cand, reason = picked
        # Canzone pubblicata trovata su YouTube (es. frase del testo): audio ufficiale.
        if intent.plain and not best_cat:
            upgraded = await self._upgrade_to_official(intent, cand)
            if upgraded is not None:
                return upgraded
        return self._choice(cand, None, "youtube-" + cand.origin, score, reason, pool)

    @staticmethod
    def _by_relevance(intent: Intent, cands: list[Candidate]):
        """Nessun candidato copre la query (es. frase del testo): ci si fida
        dell'ordine di YouTube, purche' la versione non sia sbagliata."""
        for cand in cands[:3]:
            penalty, notes = _version_penalty(intent, cand.title, cand.author)
            if penalty < 15:
                return (10.0 - cand.position, cand, f"rilevanza pos={cand.position} {cand.origin}")
        return None

    async def _upgrade_to_official(self, intent: Intent, cand: Candidate) -> Choice | None:
        guess = f"{core_title(cand.title, cand.author)} {cand.author.removesuffix(' - Topic')}".strip()
        catalog = await _safe(self.search_catalog(guess), [], self.CATALOG_TIMEOUT)
        guess_intent = parse_intent(guess)
        for meta in catalog[:5]:
            t_sim = title_similarity(core_title(meta.title), core_title(cand.title, meta.artist))
            a_sim = max(coverage(tokens(meta.artist), tokens(cand.author)), coverage(tokens(meta.artist), tokens(cand.title)))
            if t_sim < 0.85 or a_sim < 0.8 or _version_penalty(guess_intent, meta.title, meta.artist)[0]:
                continue
            isrc = await self._by_isrc(meta)
            picked = self._pick(intent, isrc, meta)
            if picked is not None:
                score, official, reason = picked
                return self._choice(official, meta, "youtube->ufficiale", score, reason, [cand])
        return None

    @staticmethod
    def _choice(cand: Candidate, meta: CatalogTrack | None, route: str, score: float, reason: str, pool) -> Choice:
        if meta is not None:
            title, artist = meta.title, meta.artist
        else:
            title, artist = cand.title, cand.author.removesuffix(" - Topic")
        return Choice(
            url=cand.url,
            title=title,
            artist=artist,
            duration=cand.duration or (meta.duration if meta else 0),
            thumbnail=(meta.cover if meta and meta.cover else cand.artwork),
            route=route,
            score=round(score, 1),
            reason=reason,
            catalog=meta,
            source_title=cand.title,
            source_author=cand.author,
            candidates=list(pool),
        )
