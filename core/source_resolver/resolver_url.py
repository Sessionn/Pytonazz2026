"""
core/source_resolver/resolver_url.py
--------------------------------------
URL / Spotify ID helpers and shuffle utilities extracted from
``core/source_resolver/__init__.py``.

Public symbols (re-exported from the package ``__init__.py``):
- ``extract_spotify_track_id``
- ``extract_spotify_playlist_id``
- ``extract_spotify_album_id``
- ``extract_spotify_artist_id``
- ``is_spotify_artist_url``
- ``_is_yt_channel_url``
- ``_is_url_like_query``
- ``spotify_style_shuffle``
"""
from __future__ import annotations

import random
import re
import urllib.parse
from collections import defaultdict
from typing import Callable, Optional, TypeVar

# ── Spotify host / pattern constants ──────────────────────────────────────────

_SPOTIFY_HOSTS = {"open.spotify.com", "spotify.com", "www.spotify.com"}
_SPOTIFY_LOCALE_SEGMENT = re.compile(
    r"(?:[a-z]{2}(?:-[a-z]{2})?|intl-[a-z]{2}(?:-[a-z]{2})?)",
    re.IGNORECASE,
)
_SPOTIFY_ID_PATTERN = re.compile(r"[A-Za-z0-9]+")

# ── YouTube channel URL pattern ───────────────────────────────────────────────

_YT_CHANNEL = re.compile(
    r"(?:https?://)?(?:www\.)?youtube\.com/"
    r"(?:channel/UC[A-Za-z0-9_-]+|c/[^/?#]+|user/[^/?#]+|@[^/?#]+)"
    r"(?:[/?#].*)?$"
)

_T = TypeVar("_T")


# ── Spotify ID extraction ─────────────────────────────────────────────────────

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


# ── YouTube / URL helpers ─────────────────────────────────────────────────────

def _is_yt_channel_url(url: str) -> bool:
    return bool(_YT_CHANNEL.match(url))


def _is_url_like_query(query: str) -> bool:
    q = (query or "").strip()
    if not q:
        return False
    if q.lower().startswith("spotify:"):
        return True
    return bool(re.match(r"^(?:https?://|www\.)", q, re.IGNORECASE))


# ── Shuffle utilities ─────────────────────────────────────────────────────────

def _popularity_tier_shuffle(pairs: list[tuple]) -> list[tuple]:
    if not pairs:
        return []
    sorted_pairs = sorted(
        pairs,
        key=lambda p: p[0].get("popularity", 0) if isinstance(p[0], dict) else getattr(p[0], "popularity", 0),
        reverse=True,
    )
    n     = len(sorted_pairs)
    third = max(1, n // 3)
    top   = sorted_pairs[:third]
    mid   = sorted_pairs[third:third * 2]
    deep  = sorted_pairs[third * 2:]
    random.shuffle(top)
    random.shuffle(mid)
    random.shuffle(deep)
    result = []
    for i in range(max(len(top), len(mid), len(deep))):
        if i < len(top):  result.append(top[i])
        if i < len(mid):  result.append(mid[i])
        if i < len(deep): result.append(deep[i])
    return result


def _bucket_shuffle(items: list[_T], key_fn: Callable[[_T], str]) -> list[_T]:
    if not items:
        return []
    buckets: dict[str, list] = defaultdict(list)
    for item in items:
        buckets[key_fn(item).strip().lower()].append(item)
    for lst in buckets.values():
        random.shuffle(lst)
    sorted_keys = sorted(buckets, key=lambda k: len(buckets[k]), reverse=True)
    total  = len(items)
    result: list = [None] * total
    for key in sorted_keys:
        group   = buckets[key]
        n       = len(group)
        spacing = total / n
        for i, item in enumerate(group):
            ideal = int((i + 0.5) * spacing)
            for delta in range(total):
                pos = (ideal + delta) % total
                if result[pos] is None:
                    result[pos] = item
                    break
    return [x for x in result if x is not None]


def spotify_style_shuffle(tracks: list) -> list:
    """Shuffle tracks so artists alternate (Spotify-style)."""
    return _bucket_shuffle(tracks, lambda t: getattr(t, "artist", "") or "unknown")


def _shuffle_pairs(pairs: list[tuple]) -> list[tuple]:
    return _bucket_shuffle(pairs, lambda p: p[1])
