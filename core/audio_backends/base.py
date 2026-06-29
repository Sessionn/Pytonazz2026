from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class AudioLoadResult:
    backend: str
    query: str
    ok: bool
    title: str = ""
    artist: str = ""
    source: str = ""
    uri: str = ""
    stream_ready: bool = False
    tracks_count: int = 0
    load_ms: float = 0.0
    error: str = ""


class AudioBackend(Protocol):
    name: str

    async def load(self, query: str, *, requester: str = "bench", requester_id: int = 1) -> AudioLoadResult:
        ...

    async def close(self) -> None:
        ...
