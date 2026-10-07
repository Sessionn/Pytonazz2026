from __future__ import annotations

import asyncio
import logging
import re

from config import Config
from core.log_colors import b, tag
from core.source_resolver import platforms
from core.source_resolver import (
    SourceResolver,
    extract_spotify_album_id,
    extract_spotify_playlist_id,
    extract_spotify_track_id,
    is_spotify_artist_url,
)

log = logging.getLogger("pitonazz.music_input")

# list= prefix comuni nelle raccolte YouTube (anche music.youtube.com):
# PL playlist, OLAK album, RDCLAK radio curate, UU upload canale, LL/FL liked.
# Mix automatici (RD...) e Watch Later (WL, privata) non sono raccolte riproducibili.
RE_YT_PLAYLIST = re.compile(
    r"(?:youtube\.com/playlist|[?&]list=(?:PL|OLAK|RDCLAK|UU|LL|FL))",
    re.IGNORECASE,
)
RE_SC_COLLECTION = re.compile(r"soundcloud\.com/[^/?#]+/(?:sets|albums)/[^/?#]+", re.IGNORECASE)
# Domini musicali riconosciuti anche senza "https://" davanti.
RE_URL_LIKE = re.compile(
    r"^(?:https?://)?(?:"
    r"(?:www\.)?(?:open\.)?spotify\.com|spotify\.link|spotify\.app\.link"
    r"|(?:www\.|m\.|music\.)?youtube\.com|youtu\.be"
    r"|(?:www\.|m\.)?soundcloud\.com|on\.soundcloud\.com"
    r"|(?:www\.)?deezer\.com|deezer\.page\.link|link\.deezer\.com"
    r"|(?:geo\.)?music\.apple\.com"
    r"|(?:www\.|listen\.)?tidal\.com"
    r"|[a-z0-9-]+\.bandcamp\.com"
    r"|(?:www\.|m\.|vm\.|vt\.)?tiktok\.com"
    r")(?:/|$)",
    re.IGNORECASE,
)


def normalize_url_like(query: str) -> str:
    normalized = (query or "").strip()
    if not normalized:
        return ""
    if normalized.startswith(("http://", "https://")):
        return normalized
    if RE_URL_LIKE.match(normalized):
        return f"https://{normalized}"
    return normalized


def is_spotify_uri(query: str) -> bool:
    return (query or "").strip().lower().startswith("spotify:")


def spotify_kind(query: str) -> str | None:
    normalized = (query or "").strip()
    if not normalized:
        return None
    if extract_spotify_track_id(normalized):
        return "track"
    if extract_spotify_playlist_id(normalized):
        return "playlist"
    if extract_spotify_album_id(normalized):
        return "album"
    if is_spotify_artist_url(normalized):
        return "artist"
    return None


def is_text_search(query: str) -> bool:
    normalized = (query or "").strip().lower()
    if normalized.startswith(("http://", "https://")):
        return False
    return not (RE_URL_LIKE.match(normalized) or is_spotify_uri(normalized))


def is_multi_url(query: str) -> bool:
    normalized = normalize_url_like(query)
    if spotify_kind(normalized) in {"playlist", "album"}:
        return True
    if not normalized.startswith(("http://", "https://")):
        return False
    if platforms.is_platform_collection(normalized):
        return True
    return bool(
        RE_YT_PLAYLIST.search(normalized)
        or RE_SC_COLLECTION.search(normalized)
        or platforms.is_soundcloud_profile(normalized)
    )


async def fetch_playlist_meta(query: str) -> tuple[str, int]:
    nome = "Playlist"
    total = 0
    loop = asyncio.get_running_loop()

    try:
        if (ref := platforms.parse_platform_url(query)) and ref.kind in {"album", "playlist"}:
            collection = await loop.run_in_executor(None, platforms.lookup, ref)
            nome = collection.name or platforms.PLATFORM_LABELS.get(ref.platform, "Playlist")
            total = len(collection.tracks)
        elif pid := extract_spotify_playlist_id(query):
            sp = SourceResolver._sp_client()
            if sp:
                try:
                    playlist = await loop.run_in_executor(
                        None,
                        lambda _id=pid: sp.playlist(_id, fields="name,tracks.total"),
                    )
                    nome = playlist.get("name") or "Playlist"
                    total = playlist.get("tracks", {}).get("total", 0)
                except Exception:
                    # Playlist editoriali: la Web API risponde 404, la pagina embed no.
                    nome, tracks = await loop.run_in_executor(
                        None, platforms.spotify_embed_playlist, pid, Config.MAX_QUEUE,
                    )
                    total = len(tracks)
        elif aid := extract_spotify_album_id(query):
            sp = SourceResolver._sp_client()
            if sp:
                album = await loop.run_in_executor(
                    None,
                    lambda _id=aid: sp.album(_id),
                )
                nome = album.get("name") or "Album"
                total = album.get("total_tracks", 0)
        elif (
            RE_YT_PLAYLIST.search(query)
            or RE_SC_COLLECTION.search(query)
            or platforms.is_soundcloud_profile(query)
        ):
            import yt_dlp

            ydl_opts = {
                **Config.YDL_OPTIONS,
                "extract_flat": True,
                "playlistend": Config.MAX_QUEUE,
                "skip_download": True,
                "quiet": True,
            }
            info = await loop.run_in_executor(
                None,
                lambda current=query: yt_dlp.YoutubeDL(ydl_opts).extract_info(current, download=False),
            )
            if info:
                entries = info.get("entries") or []
                valid_entries = sum(1 for entry in entries if entry)
                if valid_entries > 0:
                    nome = info.get("title") or info.get("uploader") or "Playlist"
                    total = valid_entries
                else:
                    fallback_keys = ("playlist_count", "n_entries", "entry_count")
                    raw_total = next((value for key in fallback_keys if (value := info.get(key)) is not None), None)
                    try:
                        fallback_total = int(raw_total) if raw_total is not None else 0
                    except (TypeError, ValueError):
                        fallback_total = 0
                    if fallback_total > 0:
                        nome = info.get("title") or info.get("uploader") or "Playlist"
                        total = fallback_total
    except Exception as exc:
        log.warning(tag("WARN", f"fetch_playlist_meta: {exc} [{b(query)}]"))

    return nome, total
