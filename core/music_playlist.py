from __future__ import annotations

import asyncio
import re

import yt_dlp

from config import Config
from core.source_resolver import (
    SourceResolver,
    extract_spotify_album_id,
    extract_spotify_playlist_id,
)


_RE_YT_PLAYLIST = re.compile(
    r"(?:youtube\.com/playlist|[?&]list=(?:PL|OLAK|RDCLAK|UU|LL|FL|WL))",
    re.IGNORECASE,
)
_RE_SC_COLLECTION = re.compile(
    r"soundcloud\.com/[^/?#]+/(?:sets|albums)/[^/?#]+",
    re.IGNORECASE,
)


async def fetch_playlist_meta(query: str) -> tuple[str, int]:
    nome = "Playlist"
    total = 0
    loop = asyncio.get_running_loop()
    try:
        if pid_str := extract_spotify_playlist_id(query):
            sp = SourceResolver._sp_client()
            if sp:
                pl = await loop.run_in_executor(
                    None,
                    lambda _id=pid_str: sp.playlist(_id, fields="name,tracks.total"),
                )
                nome = pl.get("name") or "Playlist"
                total = pl.get("tracks", {}).get("total", 0)
        elif aid_str := extract_spotify_album_id(query):
            sp = SourceResolver._sp_client()
            if sp:
                al = await loop.run_in_executor(None, lambda _id=aid_str: sp.album(_id))
                nome = al.get("name") or "Album"
                total = al.get("total_tracks", 0)
        elif _RE_YT_PLAYLIST.search(query) or _RE_SC_COLLECTION.search(query):
            info = await loop.run_in_executor(
                None,
                lambda _q=query: yt_dlp.YoutubeDL(
                    {
                        **Config.YDL_OPTIONS,
                        "extract_flat": True,
                        "skip_download": True,
                        "quiet": True,
                    }
                ).extract_info(_q, download=False),
            )
            if info:
                entries = info.get("entries") or []
                valid_entries_count = sum(1 for e in entries if e)
                if valid_entries_count > 0:
                    nome = info.get("title") or info.get("uploader") or "Playlist"
                    total = valid_entries_count
                else:
                    fallback_keys = ("playlist_count", "n_entries", "entry_count")
                    raw_total = next(
                        (value for key in fallback_keys if (value := info.get(key)) is not None),
                        None,
                    )
                    try:
                        fallback_total = int(raw_total) if raw_total is not None else 0
                    except (TypeError, ValueError):
                        fallback_total = 0
                    if fallback_total > 0:
                        nome = info.get("title") or info.get("uploader") or "Playlist"
                        total = fallback_total
    except Exception:
        return "Playlist", 0
    return nome, total
