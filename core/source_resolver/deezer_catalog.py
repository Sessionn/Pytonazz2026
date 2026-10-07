"""
core/source_resolver/deezer_catalog.py
--------------------------------------
Catalogo Deezer per riconoscere il brano di una query testuale.

API pubblica, senza chiave: /search ~0.15 s dalla VM (titolo, artista, durata,
popolarita'), /track/<id> ~0.10 s (ISRC). Misurato 2026-10-07.
"""
from __future__ import annotations

import aiohttp

from core.source_resolver.smart import CatalogTrack

_API = "https://api.deezer.com"
_TIMEOUT = aiohttp.ClientTimeout(total=3.0)


def _track(item: dict) -> CatalogTrack | None:
    if not isinstance(item, dict) or not item.get("id") or not item.get("title"):
        return None
    album = item.get("album") or {}
    return CatalogTrack(
        id=str(item["id"]),
        title=str(item.get("title") or ""),
        artist=str((item.get("artist") or {}).get("name") or ""),
        duration=int(item.get("duration") or 0),
        rank=int(item.get("rank") or 0),
        cover=str(album.get("cover_xl") or album.get("cover_big") or ""),
        album=str(album.get("title") or ""),
        isrc=str(item.get("isrc") or ""),
    )


class DeezerCatalog:
    def __init__(self, session: aiohttp.ClientSession | None = None):
        self._session = session
        self._own = session is None

    async def _get(self, path: str, params: dict | None = None) -> dict:
        if self._session is None:
            self._session = aiohttp.ClientSession(timeout=_TIMEOUT)
        async with self._session.get(f"{_API}{path}", params=params) as resp:
            if resp.status != 200:
                return {}
            data = await resp.json(content_type=None)
            return data if isinstance(data, dict) and "error" not in data else {}

    async def search(self, query: str, limit: int = 10) -> list[CatalogTrack]:
        data = await self._get("/search", {"q": query, "limit": str(limit)})
        return [t for t in (_track(i) for i in data.get("data") or []) if t is not None]

    async def track(self, track_id: str) -> CatalogTrack | None:
        return _track(await self._get(f"/track/{track_id}"))

    async def close(self) -> None:
        if self._own and self._session is not None:
            await self._session.close()
            self._session = None
