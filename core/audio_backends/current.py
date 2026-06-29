from __future__ import annotations

import time

from core.audio_backends.base import AudioLoadResult
from core.music.input import is_text_search, normalize_url_like
from core.source_resolver import SourceResolver


class CurrentAudioBackend:
    name = "current"

    async def load(self, query: str, *, requester: str = "bench", requester_id: int = 1) -> AudioLoadResult:
        normalized = normalize_url_like(query)
        t0 = time.perf_counter()
        try:
            if is_text_search(normalized):
                tracks = await SourceResolver.resolve_choices(normalized, requester, requester_id, n=1)
            else:
                tracks = await SourceResolver.resolve(normalized, requester, requester_id)
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
            artist=getattr(track, "artist", "") or "",
            source=getattr(track, "source", "") or "",
            uri=getattr(track, "webpage_url", "") or "",
            stream_ready=bool(getattr(track, "stream_url", "")),
            tracks_count=len(tracks),
            load_ms=elapsed,
        )

    async def close(self) -> None:
        return None
