"""
core/source_resolver/tiktok.py
------------------------------
Link TikTok (video e suoni) senza account.

L'estrattore web di yt-dlp riceve "login richiesto" da TikTok e quello dei suoni
e' segnato come rotto (verificato 2026-10-07). Le pagine di embed, che TikTok
deve tenere pubbliche per mostrare i video su altri siti, contengono invece
tutto il necessario (~0.4 s):

- /embed/v2/<id_video>: link del video, durata, autore, testo, e il suono usato
  (nome, autore, se e' un "suono originale", playUrl = MP3 del suono);
- /embed/music/<id_suono>: autore del suono e i video che lo usano.

I link della CDN si riproducono direttamente con FFmpeg dalla VM.
"""
from __future__ import annotations

import json
import logging
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

log = logging.getLogger("pitonazz.resolver")

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)
_TIMEOUT = 10
_STATE_RE = re.compile(r'<script[^>]*id="__FRONTITY_CONNECT_STATE__"[^>]*>(.*?)</script>', re.S)
_HOSTS = ("tiktok.com", "www.tiktok.com", "m.tiktok.com", "vm.tiktok.com", "vt.tiktok.com")
_VIDEO_PATH = re.compile(r"/@([^/?#]+)/(?:video|photo)/(\d{8,})")
_MOBILE_VIDEO_PATH = re.compile(r"/v/(\d{8,})(?:\.html)?")
_EMBED_VIDEO_PATH = re.compile(r"/embed(?:/v2)?/(\d{8,})")
_MUSIC_PATH = re.compile(r"/music/(?:[^/?#]*-)?(\d{8,})")
_HASHTAG = re.compile(r"(?:^|\s)#\S+")


@dataclass(frozen=True)
class TikTokRef:
    kind: str  # "video", "music" o "short" (link breve da espandere)
    id: str
    user: str = ""


@dataclass
class TikTokSound:
    id: str
    title: str
    author: str
    original: bool
    play_url: str
    cover: str = ""


@dataclass
class TikTokVideo:
    id: str
    user: str
    author: str
    description: str
    duration: int
    video_url: str
    cover: str = ""
    sound: TikTokSound | None = field(default=None)


def _host(url: str) -> str:
    try:
        return (urllib.parse.urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def is_tiktok_url(url: str) -> bool:
    host = _host((url or "").strip())
    return host in _HOSTS or host.endswith(".tiktok.com")


def parse_tiktok_url(url: str) -> TikTokRef | None:
    """Riconosce video, suoni e link brevi; ignora i parametri (?is_from_webapp=1...)."""
    raw = (url or "").strip()
    if not is_tiktok_url(raw):
        return None
    try:
        parts = urllib.parse.urlsplit(raw)
    except ValueError:
        return None
    path = urllib.parse.unquote(parts.path)
    host = (parts.hostname or "").lower()
    if m := _VIDEO_PATH.search(path):
        return TikTokRef("video", m.group(2), m.group(1).lstrip("@"))
    if m := _MUSIC_PATH.search(path):
        return TikTokRef("music", m.group(1))
    if m := _EMBED_VIDEO_PATH.search(path) or _MOBILE_VIDEO_PATH.search(path):
        return TikTokRef("video", m.group(1))
    if host in ("vm.tiktok.com", "vt.tiktok.com") or path.startswith("/t/"):
        code = path.strip("/").split("/")[-1]
        return TikTokRef("short", code) if code else None
    return None


def canonical_url(ref: TikTokRef) -> str:
    if ref.kind == "music":
        return f"https://www.tiktok.com/music/x-{ref.id}"
    user = ref.user or "_"
    return f"https://www.tiktok.com/@{user}/video/{ref.id}"


def _get(url: str) -> tuple[str, str]:
    """GET con redirect; restituisce (url finale, html)."""
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept-Language": "it,en;q=0.8"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return resp.geturl(), resp.read().decode("utf-8", "replace")


def expand_short_link(url: str) -> TikTokRef | None:
    """vm.tiktok.com/XYZ, vt.tiktok.com/XYZ, tiktok.com/t/XYZ -> link completo."""
    final_url, _ = _get(url)
    ref = parse_tiktok_url(final_url)
    return ref if ref and ref.kind != "short" else None


def _embed_state(path: str) -> dict:
    _, html = _get(f"https://www.tiktok.com{path}")
    m = _STATE_RE.search(html)
    if not m:
        raise ValueError("pagina embed senza dati")
    data = json.loads(m.group(1))["source"]["data"]
    return data.get(path) or data.get(path.rstrip("/") + "/") or {}


def _first(value) -> str:
    if isinstance(value, list):
        return str(value[0]) if value else ""
    return str(value or "")


def _truthy(value) -> bool:
    return value is True or str(value).strip().lower() == "true"


def fetch_video(video_id: str) -> TikTokVideo:
    state = _embed_state(f"/embed/v2/{video_id}")
    data = state.get("videoData") or {}
    infos = data.get("itemInfos") or {}
    video = infos.get("video") or {}
    author = data.get("authorInfos") or {}
    music = data.get("musicInfos") or {}
    video_url = _first(video.get("urls"))
    sound = None
    if music.get("musicId") and _first(music.get("playUrl")):
        sound = TikTokSound(
            id=str(music.get("musicId")),
            title=str(music.get("musicName") or ""),
            author=str(music.get("authorName") or ""),
            original=_truthy(music.get("original")),
            play_url=_first(music.get("playUrl")),
            cover=_first(music.get("coversMedium") or music.get("covers")),
        )
    if not video_url and sound is None:
        raise ValueError("video TikTok non disponibile")
    # Post di sole foto (slideshow): nessun video, si usa il suono.
    return TikTokVideo(
        id=str(video_id),
        user=str(author.get("uniqueId") or ""),
        author=str(author.get("nickName") or author.get("uniqueId") or ""),
        description=str(infos.get("text") or ""),
        duration=int(float((video.get("videoMeta") or {}).get("duration") or 0)),
        video_url=video_url,
        cover=_first(infos.get("covers") or video.get("cover")),
        sound=sound,
    )


def fetch_sound(music_id: str) -> TikTokSound:
    """Il suono si legge da uno dei video che lo usano (la sua pagina non ha l'audio)."""
    state = _embed_state(f"/embed/music/{music_id}")
    videos = state.get("videoList") or []
    info = state.get("embedInfo") or {}
    for item in videos[:3]:
        try:
            video = fetch_video(str(item.get("id")))
        except Exception as exc:
            log.debug(f"TikTok suono {music_id}: video {item.get('id')} saltato ({exc})")
            continue
        if video.sound and video.sound.id == str(music_id):
            if not video.sound.cover:
                video.sound.cover = str(info.get("coverUrl") or "")
            return video.sound
    raise ValueError("suono TikTok senza video utilizzabili")


def video_title(video: TikTokVideo) -> str:
    """Testo del video senza hashtag; se vuoto, il nome del suono o l'autore."""
    text = " ".join(_HASHTAG.sub(" ", video.description).split())
    if text:
        return text[:120]
    if video.sound and video.sound.title:
        return video.sound.title
    return f"TikTok di {video.author or video.user}"


def is_named_song(sound: TikTokSound) -> bool:
    """Suono che e' una canzone pubblicata (non un "suono originale" di un utente)."""
    if sound.original:
        return False
    title = sound.title.lower()
    return bool(sound.title) and not title.startswith(("original sound", "suono originale", "som original", "sonido original"))


def fresh_stream_url(webpage_url: str) -> str:
    """Nuovo link CDN per un brano TikTok gia' in coda (i link scadono in 1-2 giorni)."""
    ref = parse_tiktok_url(webpage_url)
    if ref is None:
        return ""
    if ref.kind == "short":
        ref = expand_short_link(webpage_url)
        if ref is None:
            return ""
    if ref.kind == "music":
        return fetch_sound(ref.id).play_url
    video = fetch_video(ref.id)
    return video.video_url or (video.sound.play_url if video.sound else "")
