from __future__ import annotations

import time
from urllib.parse import quote

from config import Config
from core.audio_backends.base import AudioLoadResult
from core.music.input import is_text_search, normalize_url_like


def _search_prefix() -> str:
    raw = (Config.LAVALINK_SEARCH_SOURCE or "").replace("-", "_").lower()
    if raw in {"youtube", "yt"}:
        return "ytsearch"
    if raw in {"soundcloud", "sc"}:
        return "scsearch"
    return "ytmsearch"


def _tracks_from_payload(payload: dict) -> list[dict]:
    load_type = str(payload.get("loadType") or "").lower()
    data = payload.get("data")
    if load_type in {"track", "short"} and isinstance(data, dict):
        return [data]
    if load_type == "search" and isinstance(data, list):
        return data
    if load_type == "playlist" and isinstance(data, dict):
        tracks = data.get("tracks") or []
        return tracks if isinstance(tracks, list) else []
    return []


class LavalinkAudioBackend:
    name = "lavalink"

    def __init__(self, *, uri: str | None = None, password: str | None = None):
        self.uri = uri or Config.LAVALINK_URI
        self.password = password or Config.LAVALINK_PASSWORD
        self._session = None

    def _identifier(self, query: str) -> str:
        if is_text_search(query):
            return f"{_search_prefix()}:{query}"
        return query

    async def _request_loadtracks(self, identifier: str) -> dict:
        import aiohttp

        if self._session is None:
            self._session = aiohttp.ClientSession(
                headers={"Authorization": self.password},
                raise_for_status=True,
            )
        url = f"{self.uri.rstrip('/')}/v4/loadtracks?identifier={quote(identifier, safe='')}"
        async with self._session.get(url) as response:
            return await response.json()

    async def load(self, query: str, *, requester: str = "bench", requester_id: int = 1) -> AudioLoadResult:
        normalized = normalize_url_like(query)
        t0 = time.perf_counter()
        try:
            payload = await self._request_loadtracks(self._identifier(normalized))
            tracks = _tracks_from_payload(payload)
        except Exception as exc:
            return AudioLoadResult(
                backend=self.name,
                query=query,
                ok=False,
                load_ms=(time.perf_counter() - t0) * 1000,
                error=f"{type(exc).__name__}: {exc}",
            )

        elapsed = (time.perf_counter() - t0) * 1000
        if not tracks:
            return AudioLoadResult(
                backend=self.name,
                query=query,
                ok=False,
                tracks_count=0,
                load_ms=elapsed,
                error="no tracks",
            )

        track = tracks[0]
        info = track.get("info") or {}
        return AudioLoadResult(
            backend=self.name,
            query=query,
            ok=True,
            title=info.get("title") or "",
            artist=info.get("author") or "",
            source=info.get("sourceName") or "lavalink",
            uri=info.get("uri") or "",
            stream_ready=True,
            tracks_count=len(tracks),
            load_ms=elapsed,
        )

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None
