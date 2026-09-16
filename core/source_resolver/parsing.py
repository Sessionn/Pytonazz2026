"""Parsing: shared resolver policies and helpers."""
from __future__ import annotations
import re
import urllib.parse
from typing import Optional

_SPOTIFY_HOSTS = {"open.spotify.com", "spotify.com", "www.spotify.com"}

_SPOTIFY_LOCALE_SEGMENT = re.compile(
    r"(?:[a-z]{2}(?:-[a-z]{2})?|intl-[a-z]{2}(?:-[a-z]{2})?)",
    re.IGNORECASE,
)

_SPOTIFY_ID_PATTERN = re.compile(r"[A-Za-z0-9]+")

_YT_CHANNEL  = re.compile(
    r"(?:https?://)?(?:www\.)?youtube\.com/"
    r"(?:channel/UC[A-Za-z0-9_-]+|c/[^/?#]+|user/[^/?#]+|@[^/?#]+)"
    r"(?:[/?#].*)?$"
)

_YOUTUBE_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{6,}$")


def _is_yt_channel_url(url: str) -> bool:
    return bool(_YT_CHANNEL.match(url))


def _youtube_video_id(entry: dict, webpage_url: str) -> str:
    candidate = str(entry.get("id") or "").strip()
    if _YOUTUBE_VIDEO_ID.fullmatch(candidate):
        return candidate

    parsed = urllib.parse.urlparse(webpage_url or "")
    host = (parsed.hostname or "").lower()
    if host.endswith("youtu.be"):
        candidate = parsed.path.strip("/").split("/")[0]
    elif host.endswith("youtube.com"):
        if parsed.path == "/watch":
            candidate = urllib.parse.parse_qs(parsed.query).get("v", [""])[0]
        else:
            parts = [part for part in parsed.path.split("/") if part]
            candidate = parts[1] if len(parts) >= 2 and parts[0] in {"shorts", "embed", "live"} else ""
    return candidate if _YOUTUBE_VIDEO_ID.fullmatch(candidate) else ""


def _entry_thumbnail(entry: dict, webpage_url: str, source: str) -> str:
    direct = str(entry.get("thumbnail") or "").strip()
    if direct:
        return direct

    thumbnails = [item for item in (entry.get("thumbnails") or []) if isinstance(item, dict)]
    urls = [str(item.get("url") or "").strip() for item in thumbnails]
    urls = [url for url in urls if url]
    if urls:
        return urls[-1]

    artwork = str(entry.get("artwork_url") or "").strip()
    if artwork:
        return artwork

    if source == "youtube":
        video_id = _youtube_video_id(entry, webpage_url)
        if video_id:
            return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
    return ""


def _extract_spotify_entity_id(url: str, entity: str) -> Optional[str]:
    entity = (entity or "").lower()
    raw = (url or "").strip()
    if not raw:
        return None

    if raw.lower().startswith("spotify:"):
        parts = raw.split(":")
        if len(parts) >= 3 and parts[1].lower() == entity:
            spotify_id = parts[2].split("?")[0].strip()
            if not spotify_id:
                return None
            return spotify_id if _SPOTIFY_ID_PATTERN.fullmatch(spotify_id) else None

    parsed = urllib.parse.urlparse(raw if "://" in raw else f"https://{raw}")
    host = (parsed.hostname or "").lower()
    if host not in _SPOTIFY_HOSTS:
        return None

    parts = [p for p in parsed.path.split("/") if p]
    if (
        len(parts) >= 3
        and _SPOTIFY_LOCALE_SEGMENT.fullmatch(parts[0])
        and parts[1].lower() == entity
    ):
        parts = parts[1:]
    if len(parts) < 2:
        return None
    if parts[0].lower() != entity:
        return None

    spotify_id = parts[1]
    return spotify_id if _SPOTIFY_ID_PATTERN.fullmatch(spotify_id) else None


def extract_spotify_track_id(url: str) -> Optional[str]:
    return _extract_spotify_entity_id(url, "track")


def extract_spotify_playlist_id(url: str) -> Optional[str]:
    return _extract_spotify_entity_id(url, "playlist")


def extract_spotify_album_id(url: str) -> Optional[str]:
    return _extract_spotify_entity_id(url, "album")


def extract_spotify_artist_id(url: str) -> Optional[str]:
    return _extract_spotify_entity_id(url, "artist")


def is_spotify_artist_url(url: str) -> bool:
    return extract_spotify_artist_id(url) is not None
