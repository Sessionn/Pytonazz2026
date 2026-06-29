from __future__ import annotations

import asyncio
from dataclasses import dataclass
import re
import time
from urllib.parse import quote, urlparse

from config import Config
from core.audio_backends.base import AudioLoadResult
from core.music.input import is_text_search, normalize_url_like, spotify_kind
from core.source_resolver import SourceResolver, TrackInfo, extract_spotify_track_id
from core.source_resolver.selection import needs_quality_fallback, rank_tracks


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


def _is_youtube_url(query: str) -> bool:
    host = urlparse(query or "").netloc.lower()
    return host.endswith("youtube.com") or host.endswith("youtu.be")


def _clean_info_value(value: object, unknown: str) -> str:
    text = str(value or "").strip()
    return "" if text.lower() == unknown else text


def _is_http_url(query: str) -> bool:
    return (query or "").strip().lower().startswith(("http://", "https://"))


def _canonical_spotify_track_url(query: str) -> str:
    track_id = extract_spotify_track_id(query)
    return f"https://open.spotify.com/track/{track_id}" if track_id else query


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
            return await self._load_spotify_track(
                _canonical_spotify_track_url(normalized), requester, requester_id, t0
            )

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
            if _is_youtube_url(normalized):
                fallback = await self._load_youtube_stream_bridge(normalized, requester, requester_id, t0)
                if fallback.ok:
                    return fallback
            return AudioLoadResult(
                backend=self.name,
                query=query,
                ok=False,
                tracks_count=0,
                load_ms=elapsed,
                error=_payload_error(payload) or "no tracks",
            )

        track = _select_track(normalized, tracks, apply_ranking=is_text_search(normalized))
        if is_text_search(normalized):
            candidate = _candidate_from_track(track)
            if needs_quality_fallback(normalized, candidate):
                fallback = await self._load_current_stream_bridge(normalized, requester, requester_id, t0)
                if fallback.ok:
                    return fallback
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

    async def _load_current_stream_bridge(
        self,
        query: str,
        requester: str,
        requester_id: int,
        t0: float,
    ) -> AudioLoadResult:
        try:
            if is_text_search(query):
                resolved = await SourceResolver.resolve_choices(query, requester, requester_id, n=1)
            else:
                resolved = await SourceResolver.resolve(query, requester, requester_id)
            source_track = resolved[0] if resolved else None
            stream_url = (getattr(source_track, "stream_url", "") or "").strip()
            if not stream_url:
                return AudioLoadResult(
                    backend=self.name,
                    query=query,
                    ok=False,
                    load_ms=(time.perf_counter() - t0) * 1000,
                    error="quality bridge returned no stream URL",
                )

            payload = await self._request_loadtracks(stream_url)
            tracks = _tracks_from_payload(payload)
        except Exception as exc:
            return AudioLoadResult(
                backend=self.name,
                query=query,
                ok=False,
                load_ms=(time.perf_counter() - t0) * 1000,
                error=f"quality bridge: {type(exc).__name__}: {exc}",
            )

        elapsed = (time.perf_counter() - t0) * 1000
        if not tracks:
            return AudioLoadResult(
                backend=self.name,
                query=query,
                ok=False,
                tracks_count=0,
                load_ms=elapsed,
                error=f"quality bridge: {_payload_error(payload) or 'no tracks'}",
            )

        track = _select_track(query, tracks, apply_ranking=False)
        info = _track_info(track)
        return AudioLoadResult(
            backend=self.name,
            query=query,
            ok=True,
            title=_clean_info_value(info.get("title"), "unknown title") or getattr(source_track, "title", "") or "",
            artist=_clean_info_value(info.get("author"), "unknown artist") or getattr(source_track, "artist", "") or "",
            source="quality+lavalink-http",
            uri=info.get("uri") or getattr(source_track, "webpage_url", "") or query,
            stream_ready=True,
            tracks_count=len(tracks),
            load_ms=elapsed,
        )

    async def _load_youtube_stream_bridge(
        self,
        query: str,
        requester: str,
        requester_id: int,
        t0: float,
    ) -> AudioLoadResult:
        try:
            resolved = await SourceResolver.resolve(query, requester, requester_id)
            source_track = resolved[0] if resolved else None
            stream_url = (getattr(source_track, "stream_url", "") or "").strip()
            if not stream_url:
                return AudioLoadResult(
                    backend=self.name,
                    query=query,
                    ok=False,
                    load_ms=(time.perf_counter() - t0) * 1000,
                    error="youtube bridge returned no stream URL",
                )

            payload = await self._request_loadtracks(stream_url)
            tracks = _tracks_from_payload(payload)
        except Exception as exc:
            return AudioLoadResult(
                backend=self.name,
                query=query,
                ok=False,
                load_ms=(time.perf_counter() - t0) * 1000,
                error=f"youtube bridge: {type(exc).__name__}: {exc}",
            )

        elapsed = (time.perf_counter() - t0) * 1000
        if not tracks:
            return AudioLoadResult(
                backend=self.name,
                query=query,
                ok=False,
                tracks_count=0,
                load_ms=elapsed,
                error=f"youtube bridge: {_payload_error(payload) or 'no tracks'}",
            )

        track = _select_track(query, tracks, apply_ranking=False)
        info = _track_info(track)
        return AudioLoadResult(
            backend=self.name,
            query=query,
            ok=True,
            title=_clean_info_value(info.get("title"), "unknown title") or getattr(source_track, "title", "") or "",
            artist=_clean_info_value(info.get("author"), "unknown artist") or getattr(source_track, "artist", "") or "",
            source="youtube+lavalink-http",
            uri=info.get("uri") or query,
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

    async def resolve_track_info(
        self,
        query: str,
        *,
        requester: str = "bench",
        requester_id: int = 1,
    ) -> TrackInfo | None:
        normalized = normalize_url_like(query)
        if spotify_kind(normalized) == "track":
            return await self._resolve_spotify_track_info(
                _canonical_spotify_track_url(normalized), requester, requester_id
            )

        try:
            payload = await self._request_loadtracks(self._identifier(normalized))
            tracks = _tracks_from_payload(payload)
        except Exception:
            tracks = []

        if not tracks:
            return await self._current_track_info(normalized, requester, requester_id)

        track = _select_track(normalized, tracks, apply_ranking=is_text_search(normalized))
        if is_text_search(normalized) and needs_quality_fallback(normalized, _candidate_from_track(track)):
            return await self._current_track_info(normalized, requester, requester_id)

        info = _track_info(track)
        webpage_url = str(info.get("uri") or "").strip()
        if not _is_http_url(webpage_url):
            return await self._current_track_info(normalized, requester, requester_id)

        stream_url = await self._fetch_stream_url(webpage_url)
        if not stream_url:
            return await self._current_track_info(normalized, requester, requester_id)

        return self._track_info_from_lavalink(
            normalized,
            info,
            webpage_url,
            stream_url,
            requester,
            requester_id,
            source=str(info.get("sourceName") or "lavalink"),
        )

    async def _resolve_spotify_track_info(
        self,
        query: str,
        requester: str,
        requester_id: int,
    ) -> TrackInfo | None:
        try:
            native_payload = await self._request_loadtracks(query)
            native_tracks = _tracks_from_payload(native_payload)
        except Exception:
            native_tracks = []

        if not native_tracks:
            return await self._current_track_info(query, requester, requester_id)

        native_info = _track_info(native_tracks[0])
        search_query = " ".join(
            part
            for part in (
                str(native_info.get("title") or "").strip(),
                str(native_info.get("author") or "").strip(),
            )
            if part
        )
        if not search_query:
            return await self._current_track_info(query, requester, requester_id)

        try:
            search_payload = await self._request_loadtracks(f"{_search_prefix()}:{search_query}")
            search_tracks = _tracks_from_payload(search_payload)
        except Exception:
            search_tracks = []

        if not search_tracks:
            return await self._current_track_info(query, requester, requester_id)

        spotify_meta = {
            "title": native_info.get("title") or "",
            "artist": native_info.get("author") or "",
            "duration": int(int(native_info.get("length") or 0) / 1000),
        }
        track = _select_track(search_query, search_tracks, apply_ranking=True, spotify_meta=spotify_meta)
        info = _track_info(track)
        webpage_url = str(info.get("uri") or "").strip()
        if not _is_http_url(webpage_url):
            return await self._current_track_info(query, requester, requester_id)

        stream_url = await self._fetch_stream_url(webpage_url)
        if not stream_url:
            return await self._current_track_info(query, requester, requester_id)

        return self._track_info_from_lavalink(
            query,
            info,
            webpage_url,
            stream_url,
            requester,
            requester_id,
            source="spotify",
            spotify_url=query,
            title_fallback=str(native_info.get("title") or ""),
            artist_fallback=str(native_info.get("author") or ""),
            duration_fallback=int(int(native_info.get("length") or 0) / 1000),
            thumbnail_fallback=str(native_info.get("artworkUrl") or ""),
        )

    async def _fetch_stream_url(self, webpage_url: str) -> str:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, SourceResolver._fetch_stream_url, webpage_url)

    async def _current_track_info(self, query: str, requester: str, requester_id: int) -> TrackInfo | None:
        if is_text_search(query):
            tracks = await SourceResolver.resolve_choices(query, requester, requester_id, n=1)
        else:
            tracks = await SourceResolver.resolve(query, requester, requester_id)
        return tracks[0] if tracks else None

    def _track_info_from_lavalink(
        self,
        query: str,
        info: dict,
        webpage_url: str,
        stream_url: str,
        requester: str,
        requester_id: int,
        *,
        source: str,
        spotify_url: str = "",
        title_fallback: str = "",
        artist_fallback: str = "",
        duration_fallback: int = 0,
        thumbnail_fallback: str = "",
    ) -> TrackInfo:
        return TrackInfo(
            title=str(info.get("title") or title_fallback or webpage_url),
            webpage_url=webpage_url,
            duration=max(0, int(int(info.get("length") or 0) / 1000)) or int(duration_fallback or 0),
            thumbnail=str(info.get("artworkUrl") or thumbnail_fallback or ""),
            requester=requester,
            requester_id=requester_id,
            source=source,
            stream_url=stream_url,
            artist=str(info.get("author") or artist_fallback or ""),
            origin_query=query,
            spotify_url=spotify_url,
            thumbnail_source="spotify" if spotify_url and (info.get("artworkUrl") or thumbnail_fallback) else "",
        )
