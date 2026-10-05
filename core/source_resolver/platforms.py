"""
core/source_resolver/platforms.py
---------------------------------
Metadati da piattaforme che non espongono audio riproducibile (Deezer,
Apple Music, Tidal, Amazon Music, ...). Come fanno i bot musicali
professionali (LavaSrc e simili), da questi link si ricavano titolo, artista,
durata e cover; l'audio viene poi cercato su YouTube con la stessa logica di
matching usata per Spotify.

Tutte le funzioni sono sincrone (httpx) e vanno chiamate in un executor.

Formato normalizzato di una traccia ("meta"):
    {"title", "artist", "duration" (secondi), "thumbnail", "url", "isrc"}
"""
from __future__ import annotations

import html
import json
import logging
import re
import threading
import time
import urllib.parse
from dataclasses import dataclass, field

import httpx

from config import Config
from core.log_colors import b, tag

log = logging.getLogger("pitonazz.platforms")

_TIMEOUT = 8.0
_HTML_MAX_BYTES = 1_500_000
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.8",
}

# ── Riconoscimento URL ───────────────────────────────────────────────────────

_RE_DEEZER = re.compile(
    r"^https?://(?:www\.)?deezer\.com/(?:[a-z]{2}(?:-[a-z]{2})?/)?(track|album|playlist)/(\d+)",
    re.IGNORECASE,
)
_RE_APPLE = re.compile(
    r"^https?://(?:(?:geo\.)?music|itunes)\.apple\.com/(?:([a-z]{2})/)?"
    r"(album|song|playlist)/(?:[^/?#]+/)?([A-Za-z0-9.\-]+)",
    re.IGNORECASE,
)
_RE_TIDAL = re.compile(
    r"^https?://(?:www\.|listen\.)?tidal\.com/(?:browse/)?(track|album|playlist)/([A-Za-z0-9\-]+)",
    re.IGNORECASE,
)
_SHORT_LINK_HOSTS = frozenset({
    "spotify.link",
    "spotify.app.link",
    "deezer.page.link",
    "link.deezer.com",
    "dzr.page.link",
    # Va espanso prima del routing: un set condiviso come link breve
    # altrimenti non viene riconosciuto come playlist.
    "on.soundcloud.com",
    "youtu.be",  # gestito da yt-dlp, ma lo normalizziamo comunque altrove
})
# Host di cui yt-dlp gestisce direttamente l'audio: nessun fallback da metadati.
_DIRECT_AUDIO_HOSTS = (
    "youtube.com", "youtu.be", "youtube-nocookie.com",
    "soundcloud.com", "bandcamp.com", "mixcloud.com", "vimeo.com",
    "twitch.tv", "audiomack.com",
)


@dataclass
class PlatformRef:
    platform: str          # deezer | apple_music | tidal
    kind: str              # track | album | playlist
    entity_id: str
    country: str = "us"
    song_id: str = ""      # Apple: ?i=<id> dentro un link album


@dataclass
class Collection:
    name: str
    tracks: list[dict] = field(default_factory=list)


def _host(url: str) -> str:
    try:
        return (urllib.parse.urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


def is_short_link(url: str) -> bool:
    host = _host(url)
    return host in _SHORT_LINK_HOSTS and host != "youtu.be"


def parse_platform_url(url: str) -> PlatformRef | None:
    raw = (url or "").strip()
    if m := _RE_DEEZER.match(raw):
        return PlatformRef("deezer", m.group(1).lower(), m.group(2))
    if m := _RE_APPLE.match(raw):
        country = (m.group(1) or "us").lower()
        kind = m.group(2).lower()
        entity_id = m.group(3)
        query = urllib.parse.parse_qs(urllib.parse.urlparse(raw).query)
        song_id = (query.get("i") or [""])[0]
        if kind == "album" and song_id:
            return PlatformRef("apple_music", "track", song_id, country)
        if kind == "song":
            return PlatformRef("apple_music", "track", entity_id, country)
        return PlatformRef("apple_music", kind, entity_id, country)
    if m := _RE_TIDAL.match(raw):
        return PlatformRef("tidal", m.group(1).lower(), m.group(2))
    return None


_RE_SC_PROFILE = re.compile(
    r"^https?://(?:www\.|m\.)?soundcloud\.com/([^/?#]+)"
    r"(?:/(?:tracks|popular-tracks|albums|sets|reposts))?/?(?:[?#]|$)",
    re.IGNORECASE,
)
_SC_RESERVED_PATHS = frozenset({
    "discover", "search", "stream", "feed", "you", "charts", "upload", "pages",
    "settings", "messages", "notifications", "people", "tags", "terms-of-use",
    "mobile", "jobs", "imprint", "pro", "premium", "go", "artists", "for-artists",
    "connect", "signin", "logout", "home",
})


def is_soundcloud_profile(url: str) -> bool:
    """Profilo SoundCloud (o sua scheda brani): va letto in modalita' flat come
    una playlist. Estrarre ogni brano per intero fa scattare il 403 di SoundCloud."""
    m = _RE_SC_PROFILE.match((url or "").strip())
    return bool(m and m.group(1).lower() not in _SC_RESERVED_PATHS)


def unsupported_platform(url: str) -> str:
    """Nome della piattaforma se il link non e' leggibile in alcun modo, altrimenti ""."""
    host = _host(url)
    path = urllib.parse.urlparse(url).path if host else ""
    # Amazon Music serve solo una pagina JavaScript: nessun metadato lato server.
    if host.startswith("music.amazon.") or (host.startswith(("amazon.", "www.amazon.")) and path.startswith("/music/")):
        return "Amazon Music"
    if (ref := parse_platform_url(url)) and ref.platform == "tidal" and ref.kind != "track":
        return f"Tidal ({ref.kind})"
    return ""


def is_platform_collection(url: str) -> bool:
    ref = parse_platform_url(url)
    return bool(ref and ref.kind in {"album", "playlist"})


def has_direct_audio(url: str) -> bool:
    host = _host(url)
    return any(host == h or host.endswith("." + h) for h in _DIRECT_AUDIO_HOSTS)


PLATFORM_LABELS = {
    "deezer": "Deezer",
    "apple_music": "Apple Music",
    "tidal": "Tidal",
}

# ── HTTP ─────────────────────────────────────────────────────────────────────


def _client() -> httpx.Client:
    return httpx.Client(timeout=_TIMEOUT, follow_redirects=True, headers=_HEADERS)


def expand_short_link(url: str) -> str:
    """Segue i redirect dei link brevi (spotify.link, deezer.page.link, ...)."""
    if not is_short_link(url):
        return url
    try:
        with _client() as client:
            resp = client.get(url)
            final = str(resp.url)
        # I link brevi Spotify a volte atterrano su una pagina con ?si=...: va bene.
        log.info(tag("RESOLVE", f"link breve  {b(url)}  ->  {b(final)}"))
        return final
    except httpx.HTTPError as exc:
        log.warning(tag("RESOLVE", f"link breve non risolto  {b(url)}  {exc}"))
        return url


def _get_json(url: str, params: dict | None = None) -> dict:
    with _client() as client:
        resp = client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()


def _get_html(url: str) -> str:
    with _client() as client:
        with client.stream("GET", url) as resp:
            resp.raise_for_status()
            chunks: list[bytes] = []
            size = 0
            for chunk in resp.iter_bytes():
                chunks.append(chunk)
                size += len(chunk)
                if size >= _HTML_MAX_BYTES:
                    break
    return b"".join(chunks).decode("utf-8", errors="replace")


def _meta_tags(page: str, prop: str) -> list[str]:
    pattern = re.compile(
        r"<meta[^>]+(?:property|name)=[\"']" + re.escape(prop) + r"[\"'][^>]*content=[\"']([^\"']*)[\"']",
        re.IGNORECASE,
    )
    alt = re.compile(
        r"<meta[^>]+content=[\"']([^\"']*)[\"'][^>]*(?:property|name)=[\"']" + re.escape(prop) + r"[\"']",
        re.IGNORECASE,
    )
    return [html.unescape(v) for v in pattern.findall(page) + alt.findall(page)]


def _meta(title: str, artist: str, duration: float, thumbnail: str, url: str, isrc: str = "") -> dict:
    return {
        "title": (title or "").strip(),
        "artist": (artist or "").strip(),
        "duration": float(duration or 0),
        "thumbnail": thumbnail or "",
        "url": url or "",
        "isrc": isrc or "",
    }


# ── Deezer (API pubblica, nessuna chiave) ────────────────────────────────────

_DEEZER_API = "https://api.deezer.com"


def _deezer_check(data: dict) -> dict:
    if isinstance(data, dict) and data.get("error"):
        raise LookupError(str(data["error"].get("message") or data["error"]))
    return data


def _deezer_track_meta(item: dict, cover: str = "") -> dict:
    album = item.get("album") or {}
    return _meta(
        item.get("title") or item.get("title_short") or "",
        (item.get("artist") or {}).get("name", ""),
        item.get("duration") or 0,
        album.get("cover_xl") or album.get("cover_big") or cover,
        item.get("link") or f"https://www.deezer.com/track/{item.get('id', '')}",
        item.get("isrc") or "",
    )


def _deezer_paged_tracks(path: str, limit: int, cover: str = "") -> list[dict]:
    tracks: list[dict] = []
    next_url: str | None = f"{_DEEZER_API}/{path}"
    params: dict | None = {"limit": 100}
    while next_url and len(tracks) < limit:
        page = _deezer_check(_get_json(next_url, params))
        params = None  # "next" contiene gia' i parametri di paginazione
        for item in page.get("data") or []:
            if item.get("readable") is False:
                continue
            tracks.append(_deezer_track_meta(item, cover))
            if len(tracks) >= limit:
                break
        next_url = page.get("next")
    return tracks


def deezer_lookup(ref: PlatformRef, limit: int) -> Collection:
    if ref.kind == "track":
        item = _deezer_check(_get_json(f"{_DEEZER_API}/track/{ref.entity_id}"))
        meta = _deezer_track_meta(item)
        return Collection(meta["title"], [meta])
    if ref.kind == "album":
        album = _deezer_check(_get_json(f"{_DEEZER_API}/album/{ref.entity_id}"))
        cover = album.get("cover_xl") or album.get("cover_big") or ""
        tracks = _deezer_paged_tracks(f"album/{ref.entity_id}/tracks", limit, cover)
        return Collection(album.get("title") or "Album Deezer", tracks)
    playlist = _deezer_check(_get_json(f"{_DEEZER_API}/playlist/{ref.entity_id}"))
    tracks = _deezer_paged_tracks(f"playlist/{ref.entity_id}/tracks", limit)
    return Collection(playlist.get("title") or "Playlist Deezer", tracks)


# ── Apple Music (iTunes Lookup API + pagina pubblica per le playlist) ───────

_ITUNES_LOOKUP = "https://itunes.apple.com/lookup"


def _apple_artwork(url: str) -> str:
    # artworkUrl100 -> versione 600x600, stessa CDN.
    return re.sub(r"/\d+x\d+(bb)?\.(jpg|png)$", r"/600x600bb.\2", url or "")


def _itunes_track_meta(item: dict) -> dict:
    return _meta(
        item.get("trackName") or "",
        item.get("artistName") or "",
        (item.get("trackTimeMillis") or 0) / 1000,
        _apple_artwork(item.get("artworkUrl100") or ""),
        item.get("trackViewUrl") or "",
    )


def _itunes_lookup(ids: list[str], country: str, entity: str | None = None, limit: int = 200) -> list[dict]:
    params = {"id": ",".join(ids), "country": country, "limit": limit}
    if entity:
        params["entity"] = entity
    data = _get_json(_ITUNES_LOOKUP, params)
    return data.get("results") or []


def apple_lookup(ref: PlatformRef, limit: int) -> Collection:
    if ref.kind == "track":
        results = [r for r in _itunes_lookup([ref.entity_id], ref.country) if r.get("kind") == "song"]
        if not results:
            raise LookupError("brano Apple Music non trovato")
        meta = _itunes_track_meta(results[0])
        return Collection(meta["title"], [meta])

    if ref.kind == "album":
        results = _itunes_lookup([ref.entity_id], ref.country, entity="song", limit=min(limit, 200))
        collection = next((r for r in results if r.get("wrapperType") == "collection"), {})
        ordered = sorted(
            (r for r in results if r.get("wrapperType") == "track" and r.get("kind") == "song"),
            key=lambda r: (r.get("discNumber") or 1, r.get("trackNumber") or 0),
        )
        tracks = [_itunes_track_meta(r) for r in ordered][:limit]
        return Collection(collection.get("collectionName") or "Album Apple Music", tracks)

    # Playlist: nessuna API pubblica. La pagina web espone i brani come
    # <meta property="music:song" content=".../song/<slug>/<id>">.
    page_url = f"https://music.apple.com/{ref.country}/playlist/{ref.entity_id}"
    page = _get_html(page_url)
    name = next(iter(_meta_tags(page, "og:title")), "") or "Playlist Apple Music"
    name = re.sub(r"\s*(?:on|su)\s+Apple\s+Music\s*$", "", name, flags=re.IGNORECASE).strip()
    song_ids: list[str] = []
    for song_url in _meta_tags(page, "music:song"):
        if m := re.search(r"/(\d+)(?:\?|$)", song_url):
            if m.group(1) not in song_ids:
                song_ids.append(m.group(1))
    song_ids = song_ids[:limit]
    by_id: dict[str, dict] = {}
    for start in range(0, len(song_ids), 150):
        for item in _itunes_lookup(song_ids[start:start + 150], ref.country):
            if item.get("kind") == "song":
                by_id[str(item.get("trackId"))] = _itunes_track_meta(item)
    tracks = [by_id[sid] for sid in song_ids if sid in by_id]
    if not tracks:
        raise LookupError("playlist Apple Music vuota o non leggibile")
    return Collection(name, tracks)


# ── Spotify: pagina embed pubblica ───────────────────────────────────────────
# Le playlist editoriali/algoritmiche di Spotify (id 37i9dQZF...) rispondono 404
# alla Web API per le app sviluppatore. La pagina embed pubblica le espone
# comunque (max ~100 brani) dentro __NEXT_DATA__.

_RE_NEXT_DATA = re.compile(r"<script[^>]+id=[\"']__NEXT_DATA__[\"'][^>]*>(.*?)</script>", re.DOTALL)


def spotify_embed_playlist(playlist_id: str, limit: int) -> tuple[str, list[dict]]:
    """Nome e brani di una playlist Spotify, nel formato oggetto-traccia della
    Web API (name, artists, duration_ms, album.images, external_urls, id)."""
    page = _get_html(f"https://open.spotify.com/embed/playlist/{playlist_id}")
    m = _RE_NEXT_DATA.search(page)
    if not m:
        raise LookupError("pagina embed Spotify senza dati")
    try:
        entity = json.loads(m.group(1))["props"]["pageProps"]["state"]["data"]["entity"]
    except (ValueError, KeyError, TypeError) as exc:
        raise LookupError(f"pagina embed Spotify non leggibile: {exc}") from exc
    images = [
        {"url": src["url"]}
        for src in ((entity.get("coverArt") or {}).get("sources") or [])
        if isinstance(src, dict) and src.get("url")
    ]
    tracks: list[dict] = []
    for item in entity.get("trackList") or []:
        uri = item.get("uri") or ""
        if not uri.startswith("spotify:track:") or item.get("isPlayable") is False:
            continue
        track_id = uri.rsplit(":", 1)[1]
        tracks.append({
            "id": track_id,
            "type": "track",
            "name": item.get("title") or "",
            "artists": [{"name": a.strip()} for a in (item.get("subtitle") or "").split(",") if a.strip()],
            "duration_ms": int(item.get("duration") or 0),
            "album": {"images": images},
            "external_urls": {"spotify": f"https://open.spotify.com/track/{track_id}"},
        })
        if len(tracks) >= limit:
            break
    return (entity.get("name") or entity.get("title") or "Playlist Spotify"), tracks


# ── Fallback generico: titolo della pagina ───────────────────────────────────

_TITLE_NOISE = re.compile(
    r"\s*(?:[|\-–—]\s*)?(?:(?:on|su|by)\s+)?"
    r"(?:TIDAL|Apple Music|Amazon Music|Deezer|Spotify|YouTube Music|Napster|Qobuz|Audiomack)\s*$",
    re.IGNORECASE,
)


def page_search_query(url: str) -> str:
    """Testo di ricerca ricavato da og:title/description di una pagina musicale."""
    try:
        page = _get_html(url)
    except httpx.HTTPError as exc:
        log.warning(tag("RESOLVE", f"pagina non leggibile  {b(url)}  {exc}"))
        return ""
    title = next(iter(_meta_tags(page, "og:title")), "")
    if not title:
        if m := re.search(r"<title[^>]*>(.*?)</title>", page, re.IGNORECASE | re.DOTALL):
            title = html.unescape(m.group(1))
    title = _TITLE_NOISE.sub("", " ".join(title.split())).strip()
    # "Brano by Artista" / "Brano di Artista" -> "Brano Artista"
    title = re.sub(r"\s+(?:by|di|von|de)\s+", " ", title, count=1, flags=re.IGNORECASE)
    return title[:200]


_LOOKUP_CACHE_TTL = 120.0
_lookup_cache: dict[tuple, tuple[float, Collection]] = {}
_lookup_lock = threading.Lock()


def lookup(ref: PlatformRef, limit: int | None = None) -> Collection:
    """Metadati di brano/album/playlist. Cache breve: /play chiede prima nome e
    totale della raccolta e subito dopo l'elenco dei brani."""
    limit = max(1, int(limit or Config.MAX_QUEUE))
    key = (ref.platform, ref.kind, ref.entity_id, ref.country, limit)
    now = time.monotonic()
    with _lookup_lock:
        cached = _lookup_cache.get(key)
        if cached and now - cached[0] < _LOOKUP_CACHE_TTL:
            return cached[1]
    collection = _lookup_uncached(ref, limit)
    with _lookup_lock:
        if len(_lookup_cache) > 64:
            _lookup_cache.clear()
        _lookup_cache[key] = (now, collection)
    return collection


def _lookup_uncached(ref: PlatformRef, limit: int) -> Collection:
    if ref.platform == "deezer":
        return deezer_lookup(ref, limit)
    if ref.platform == "apple_music":
        return apple_lookup(ref, limit)
    if ref.platform == "tidal" and ref.kind == "track":
        query = page_search_query(f"https://tidal.com/browse/track/{ref.entity_id}")
        if not query:
            raise LookupError("brano Tidal non leggibile")
        return Collection(query, [_meta(query, "", 0, "", f"https://tidal.com/browse/track/{ref.entity_id}")])
    raise LookupError(f"{PLATFORM_LABELS.get(ref.platform, ref.platform)}: {ref.kind} non supportato")
