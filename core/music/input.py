from __future__ import annotations

import asyncio
import logging
import re

from config import Config
from core.log_colors import b, tag
from core.source_resolver import (
    SourceResolver,
    extract_spotify_album_id,
    extract_spotify_playlist_id,
    extract_spotify_track_id,
    is_spotify_artist_url,
)

log = logging.getLogger("pitonazz.music_input")

RE_YT_PLAYLIST = re.compile(
    r"(?:youtube\.com/playlist|[?&]list=(?:PL|OLAK|RDCLAK|UU|LL|FL|WL))",
    re.IGNORECASE,
)
RE_SC_COLLECTION = re.compile(r"soundcloud\.com/[^/?#]+/(?:sets|albums)/[^/?#]+", re.IGNORECASE)
RE_URL_LIKE = re.compile(
    r"^(?:https?://)?(?:(?:www\.)?(?:open\.)?spotify\.com|(?:www\.)?youtube\.com|youtu\.be|(?:www\.)?soundcloud\.com|on\.soundcloud\.com)(?:/|$)",
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
    return not (RE_URL_LIKE.match(normalized) or is_spotify_uri(normalized))


def is_multi_url(query: str) -> bool:
    normalized = normalize_url_like(query)
    if spotify_kind(normalized) in {"playlist", "album"}:
        return True
    if not normalized.startswith(("http://", "https://")):
        return False
    return bool(RE_YT_PLAYLIST.search(normalized) or RE_SC_COLLECTION.search(normalized))


async def fetch_playlist_meta(query: str) -> tuple[str, int]:
    nome = "Playlist"
    total = 0
    loop = asyncio.get_running_loop()

    try:
        if pid := extract_spotify_playlist_id(query):
            sp = SourceResolver._sp_client()
            if sp:
                playlist = await loop.run_in_executor(
                    None,
                    lambda _id=pid: sp.playlist(_id, fields="name,tracks.total"),
                )
                nome = playlist.get("name") or "Playlist"
                total = playlist.get("tracks", {}).get("total", 0)
        elif aid := extract_spotify_album_id(query):
            sp = SourceResolver._sp_client()
            if sp:
                album = await loop.run_in_executor(
                    None,
                    lambda _id=aid: sp.album(_id),
                )
                nome = album.get("name") or "Album"
                total = album.get("total_tracks", 0)
        elif RE_YT_PLAYLIST.search(query) or RE_SC_COLLECTION.search(query):
            import yt_dlp

            ydl_opts = {
                **Config.YDL_OPTIONS,
                "extract_flat": True,
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
