from __future__ import annotations

import time

from config import Config
from core.audio_backends.base import AudioLoadResult
from core.music.input import is_text_search, normalize_url_like


def _track_source(wavelink):
    raw = (Config.LAVALINK_SEARCH_SOURCE or "").replace("-", "_").lower()
    if raw in {"youtube", "yt"}:
        return wavelink.TrackSource.YouTube
    if raw in {"soundcloud", "sc"}:
        return wavelink.TrackSource.SoundCloud
    return wavelink.TrackSource.YouTubeMusic


class LavalinkAudioBackend:
    name = "lavalink"

    def __init__(self, *, uri: str | None = None, password: str | None = None):
        self.uri = uri or Config.LAVALINK_URI
        self.password = password or Config.LAVALINK_PASSWORD
        self._connected = False
        self._wavelink = None

    async def _ensure_connected(self):
        if self._connected:
            return self._wavelink
        import wavelink

        node = wavelink.Node(uri=self.uri, password=self.password)
        await wavelink.Pool.connect(nodes=[node], client=None)
        self._connected = True
        self._wavelink = wavelink
        return wavelink

    async def load(self, query: str, *, requester: str = "bench", requester_id: int = 1) -> AudioLoadResult:
        normalized = normalize_url_like(query)
        t0 = time.perf_counter()
        try:
            wavelink = await self._ensure_connected()
            if is_text_search(normalized):
                loaded = await wavelink.Playable.search(normalized, source=_track_source(wavelink))
            else:
                loaded = await wavelink.Pool.fetch_tracks(normalized)
            tracks = list(loaded.tracks if hasattr(loaded, "tracks") else loaded)
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
        return AudioLoadResult(
            backend=self.name,
            query=query,
            ok=True,
            title=getattr(track, "title", "") or "",
            artist=getattr(track, "author", "") or "",
            source="lavalink",
            uri=getattr(track, "uri", "") or "",
            stream_ready=True,
            tracks_count=len(tracks),
            load_ms=elapsed,
        )

    async def close(self) -> None:
        if not self._connected or self._wavelink is None:
            return
        try:
            await self._wavelink.Pool.close()
        finally:
            self._connected = False
