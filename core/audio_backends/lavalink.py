from __future__ import annotations

from dataclasses import dataclass
import re
import time
from urllib.parse import quote

from config import Config
from core.audio_backends.base import AudioLoadResult
from core.music.input import is_text_search, normalize_url_like, spotify_kind
from core.source_resolver import SourceResolver
from core.source_resolver.selection import rank_tracks


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


def _payload_error(payload: dict) -> str:
    load_type = str(payload.get("loadType") or "").lower()
    data = payload.get("data")
    if load_type != "error" or not isinstance(data, dict):
        return ""
    message = str(data.get("message") or "").strip()
    cause = str(data.get("cause") or "").strip()
    stack = str(data.get("causeStackTrace") or "")
    caused_by = re.findall(r"Caused by: [^:\n]+: ([^\n]+)", stack)
    if caused_by:
        return caused_by[-1].strip()
    if message and cause:
        return f"{message}: {cause}"
    return message or cause


@dataclass(frozen=True)
class _LavalinkCandidate:
    title: str
    artist: str
    duration: int
    raw: dict


def _track_info(track: dict) -> dict:
    info = track.get("info") if isinstance(track, dict) else None
    return info if isinstance(info, dict) else {}


def _candidate_from_track(track: dict) -> _LavalinkCandidate:
    info = _track_info(track)
    length_ms = int(info.get("length") or 0)
    return _LavalinkCandidate(
        title=str(info.get("title") or ""),
        artist=str(info.get("author") or ""),
        duration=max(0, length_ms // 1000),
        raw=track,
    )


def _select_track(
    query: str,
    tracks: list[dict],
    *,
    apply_ranking: bool,
    spotify_meta: dict | None = None,
) -> dict:
    if not tracks or not apply_ranking:
        return tracks[0] if tracks else {}

    candidates = [_candidate_from_track(track) for track in tracks]
    ranked = rank_tracks(query, candidates, spotify_meta)
    return ranked[0].track.raw if ranked else tracks[0]


def _spotify_search_query(track) -> str:
    title = (getattr(track, "title", "") or "").strip()
    artist = (getattr(track, "artist", "") or "").strip()
    return " ".join(part for part in (title, artist) if part).strip()


def _spotify_meta(track) -> dict:
    return {
        "title": getattr(track, "title", "") or "",
        "artist": getattr(track, "artist", "") or "",
        "duration": int(getattr(track, "duration", 0) or 0),
    }


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
        if spotify_kind(normalized) == "track":
            return await self._load_spotify_track(normalized, requester, requester_id, t0)

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
                error=_payload_error(payload) or "no tracks",
            )

        track = _select_track(normalized, tracks, apply_ranking=is_text_search(normalized))
        info = _track_info(track)
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

    async def _load_spotify_track(
        self,
        query: str,
        requester: str,
        requester_id: int,
        t0: float,
    ) -> AudioLoadResult:
        if Config.LAVALINK_SPOTIFY_NATIVE:
            native = await self._load_spotify_native(query, t0)
            if native.ok:
                return native

        try:
            resolved = await SourceResolver.resolve(query, requester, requester_id)
            source_track = resolved[0] if resolved else None
            search_query = _spotify_search_query(source_track)
            if not search_query:
                return AudioLoadResult(
                    backend=self.name,
                    query=query,
                    ok=False,
                    load_ms=(time.perf_counter() - t0) * 1000,
                    error="spotify bridge returned no searchable metadata",
                )

            payload = await self._request_loadtracks(f"{_search_prefix()}:{search_query}")
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
                error="spotify bridge produced no Lavalink tracks",
            )

        spotify_meta = _spotify_meta(source_track)
        search_query = _spotify_search_query(source_track) or query
        track = _select_track(search_query, tracks, apply_ranking=True, spotify_meta=spotify_meta)
        info = _track_info(track)
        return AudioLoadResult(
            backend=self.name,
            query=query,
            ok=True,
            title=info.get("title") or getattr(source_track, "title", "") or "",
            artist=info.get("author") or getattr(source_track, "artist", "") or "",
            source="spotify+lavalink",
            uri=info.get("uri") or getattr(source_track, "webpage_url", "") or "",
            stream_ready=True,
            tracks_count=len(tracks),
            load_ms=elapsed,
        )

    async def _load_spotify_native(self, query: str, t0: float) -> AudioLoadResult:
        try:
            payload = await self._request_loadtracks(query)
            tracks = _tracks_from_payload(payload)
        except Exception as exc:
            return AudioLoadResult(
                backend=self.name,
                query=query,
                ok=False,
                load_ms=(time.perf_counter() - t0) * 1000,
                error=f"native spotify: {type(exc).__name__}: {exc}",
            )

        elapsed = (time.perf_counter() - t0) * 1000
        if not tracks:
            return AudioLoadResult(
                backend=self.name,
                query=query,
                ok=False,
                tracks_count=0,
                load_ms=elapsed,
                error=f"native spotify: {_payload_error(payload) or 'no tracks'}",
            )

        track = _select_track(query, tracks, apply_ranking=False)
        info = _track_info(track)
        return AudioLoadResult(
            backend=self.name,
            query=query,
            ok=True,
            title=info.get("title") or "",
            artist=info.get("author") or "",
            source=info.get("sourceName") or "spotify+lavasrc",
            uri=info.get("uri") or query,
            stream_ready=True,
            tracks_count=len(tracks),
            load_ms=elapsed,
        )

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None
