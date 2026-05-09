import asyncio
import logging
import random
import re
import threading
import time
import urllib.parse
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional, Callable, TypeVar

import yt_dlp
from config import Config
from core.log_colors import tag, b, ms, title, hi, dim, _GRN, _CYN, _BGRN, _BYEL, _BRED, _BBLU, _TEAL

# ── Sub-module imports ────────────────────────────────────────────────────────
# Scoring / math helpers (pure functions, no Config or I/O dependency)
from core.source_resolver.scoring import (
    _MV_KEYWORDS,
    _VARIANT_KEYWORDS,
    _NOISE_WORDS,
    _NON_MUSIC_QUERY_KEYWORDS,
    _ENRICH_CONFIDENCE_HIGH,
    _ENRICH_CONFIDENCE_MEDIUM,
    _ENRICH_CONFIDENCE_EXTREME_LOW,
    _ENRICH_DURATION_GOOD,
    _DURATION_DEFAULT_SCORE,
    _ARTIST_MISMATCH_THRESHOLD,
    _ENRICH_EXTREME_LOW_SIM_THRESHOLD,
    _ENRICH_WEIGHT_QUERY,
    _ENRICH_WEIGHT_YT,
    _ENRICH_WEIGHT_DURATION,
    _ENRICH_WEIGHT_ARTIST_HINT,
    _NON_MUSIC_QUERY_MAX_WORDS,
    _SPOTIFY_RETRY_BASE_DELAY_SECONDS,
    _ARTIST_TOKEN_MIN_LENGTH,
    _NON_MUSIC_QUERY_PENALTY,
    _JUNK_WORD_PENALTY,
    _MAX_JUNK_PENALTY,
    _is_music_video,
    _is_variant,
    _query_requests_variant,
    _str_sim,
    _normalize_for_sim,
    _jaccard_tokens,
    _enrich_sim,
    _duration_similarity,
    _contains_token,
    _dynamic_variant_penalty,
    _query_artist_signal,
    _is_probably_non_music_query,
    _compute_enrich_confidence,
)

# yt-dlp infrastructure helpers
from core.source_resolver.ytdlp import (
    _YTDLP_QUERY_CACHE_TTL,
    _YTDLP_QUERY_CACHE_MAX,
    _STREAM_URL_CACHE_TTL,
    _STREAM_URL_CACHE_MAX,
    _YdlLogger,
    _make_opts,
    _strip_yt_radio,
    _is_soundcloud_url,
)

# Spotify item helpers
from core.source_resolver.spotify import (
    _SPOTIFY_BATCH_CONCURRENCY,
    _SPOTIFY_BATCH_MAX_CONCURRENCY,
    _spotify_client,
    _spotify_item_name,
    _spotify_item_popularity,
    _spotify_item_artists,
    _spotify_item_query_similarity,
    _choose_spotify_track_item,
)

log = logging.getLogger("pitonazz.resolver")
enrich_log = logging.getLogger("pitonazz.spotify_enrich")

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

_YT_CANDIDATES = 3

_T = TypeVar("_T")


@dataclass
class TrackInfo:
    title:        str
    webpage_url:  str
    duration:     int
    thumbnail:    str
    requester:    str
    requester_id: int
    source:       str
    stream_url:   str = field(default="", repr=False)
    artist:       str = field(default="", repr=False)
    origin_query: str = field(default="", repr=False)
    spotify_url:  str = field(default="", repr=False)
    popularity:   int = field(default=0, repr=False)


def _clone_track(track: "TrackInfo") -> "TrackInfo":
    return TrackInfo(
        title=track.title,
        webpage_url=track.webpage_url,
        duration=track.duration,
        thumbnail=track.thumbnail,
        requester=track.requester,
        requester_id=track.requester_id,
        source=track.source,
        stream_url=track.stream_url,
        artist=track.artist,
        origin_query=track.origin_query,
        spotify_url=track.spotify_url,
        popularity=track.popularity,
    )


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


def spotify_style_shuffle(tracks: list["TrackInfo"]) -> list["TrackInfo"]:
    return _bucket_shuffle(tracks, lambda t: getattr(t, "artist", "") or "unknown")


def _shuffle_pairs(pairs: list[tuple]) -> list[tuple]:
    return _bucket_shuffle(pairs, lambda p: p[1])


def _is_yt_channel_url(url: str) -> bool:
    return bool(_YT_CHANNEL.match(url))


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
    # Spotify may include locale in the path
    # (e.g., /it/album/... , /en-us/album/... , /intl-it/album/...).
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


def _candidate_query_similarity(query: str, candidate) -> float:
    q_norm = _normalize_for_sim(query)
    if not q_norm:
        return 0.0
    title_norm = _normalize_for_sim(getattr(candidate, "title", "") or "")
    artist_norm = _normalize_for_sim(getattr(candidate, "artist", "") or "")
    full_norm = (f"{title_norm} {artist_norm}").strip()
    return max(
        _jaccard_tokens(q_norm, title_norm),
        _jaccard_tokens(q_norm, full_norm),
    )


def _prefer_studio(candidates: list, sp_dur: float = 0, user_query: str = "") -> object:
    if not candidates:
        return None
    non_mv = [c for c in candidates if not _is_music_video(c.title, getattr(c, "artist", ""))]
    pool   = non_mv if non_mv else candidates
    if not _query_requests_variant(user_query):
        studio = [c for c in pool if not _is_variant(c.title)]
        pool   = studio if studio else pool
    if len(pool) == 1:
        return pool[0]

    if (user_query or "").strip():
        if sp_dur > 0:
            return max(
                pool,
                key=lambda c: (
                    _candidate_query_similarity(user_query, c),
                    -(abs(c.duration - sp_dur) if c.duration else 9999),
                ),
            )
        return max(pool, key=lambda c: _candidate_query_similarity(user_query, c))

    if sp_dur > 0:
        pool.sort(key=lambda c: abs(c.duration - sp_dur) if c.duration else 9999)
    return pool[0]


def _is_url_like_query(query: str) -> bool:
    q = (query or "").strip()
    if not q:
        return False
    if q.lower().startswith("spotify:"):
        return True
    return bool(re.match(r"^(?:https?://|www\.)", q, re.IGNORECASE))


def _should_enrich_with_spotify(query: str, tracks: list["TrackInfo"]) -> bool:
    if not Config.SPOTIFY_CLIENT_ID:
        return False
    if not tracks:
        return False
    q = (query or "").strip()
    if not q:
        return False
    if _is_url_like_query(q):
        return False
    return True


class SourceResolver:
    _sp = None
    _cache_lock = threading.Lock()
    _ytdlp_query_cache: dict[tuple[int, str], tuple[float, list["TrackInfo"]]] = {}
    _stream_url_cache: dict[str, tuple[float, str]] = {}

    @classmethod
    def _cache_prune_locked(cls, cache: dict, max_size: int) -> None:
        now = time.monotonic()
        expired_keys = [k for k, (exp, _) in cache.items() if exp <= now]
        for key in expired_keys:
            cache.pop(key, None)
        while len(cache) > max_size:
            cache.pop(next(iter(cache)), None)

    @classmethod
    def _get_cached_ytdlp_results(cls, key: tuple[int, str]) -> Optional[list["TrackInfo"]]:
        now = time.monotonic()
        with cls._cache_lock:
            cached = cls._ytdlp_query_cache.get(key)
            if not cached:
                return None
            exp, tracks = cached
            if exp <= now:
                cls._ytdlp_query_cache.pop(key, None)
                return None
            # Move-to-end: keep LRU eviction using an ordered dict.
            cls._ytdlp_query_cache.pop(key, None)
            cls._ytdlp_query_cache[key] = (exp, tracks)
            return [_clone_track(t) for t in tracks]

    @classmethod
    def _set_cached_ytdlp_results(cls, key: tuple[int, str], tracks: list["TrackInfo"]) -> None:
        with cls._cache_lock:
            cls._ytdlp_query_cache.pop(key, None)
            cls._ytdlp_query_cache[key] = (
                time.monotonic() + _YTDLP_QUERY_CACHE_TTL,
                [_clone_track(t) for t in tracks],
            )
            cls._cache_prune_locked(cls._ytdlp_query_cache, _YTDLP_QUERY_CACHE_MAX)

    @classmethod
    def _get_cached_stream_url(cls, webpage_url: str) -> Optional[str]:
        now = time.monotonic()
        with cls._cache_lock:
            cached = cls._stream_url_cache.get(webpage_url)
            if not cached:
                return None
            exp, url = cached
            if exp <= now:
                cls._stream_url_cache.pop(webpage_url, None)
                return None
            # Move-to-end: keep LRU eviction using an ordered dict.
            cls._stream_url_cache.pop(webpage_url, None)
            cls._stream_url_cache[webpage_url] = (exp, url)
            return url

    @classmethod
    def _set_cached_stream_url(cls, webpage_url: str, stream_url: str) -> None:
        with cls._cache_lock:
            cls._stream_url_cache.pop(webpage_url, None)
            cls._stream_url_cache[webpage_url] = (
                time.monotonic() + _STREAM_URL_CACHE_TTL,
                stream_url,
            )
            cls._cache_prune_locked(cls._stream_url_cache, _STREAM_URL_CACHE_MAX)

    @classmethod
    def _sp_client(cls):
        if cls._sp is None:
            cls._sp = _spotify_client()
        return cls._sp

    @classmethod
    def _sp_search_track_meta(cls, query: str) -> Optional[dict]:
        for attempt in range(3):
            sp = cls._sp_client()
            if not sp:
                return None
            try:
                res = sp.search(q=query, type="track", limit=5)
                items = res.get("tracks", {}).get("items", [])
                if not items:
                    return None
                t = _choose_spotify_track_item(query, items)
                if not t:
                    return None
                images = t.get("album", {}).get("images", [])
                return {
                    "title":       t.get("name", ""),
                    "thumbnail":   images[0]["url"] if images else "",
                    "duration":    int((t.get("duration_ms") or 0) / 1000),
                    "artist":      ", ".join(a["name"] for a in t.get("artists", [])),
                    "spotify_url": t.get("external_urls", {}).get("spotify", ""),
                }
            except Exception as e:
                cls._sp = None
                if attempt < 2:
                    time.sleep(0.4 * (attempt + 1))
                    continue
                log.debug(tag("SPOTIFY", f"{b(query)}  fallito dopo 3 tentativi: {e}"))
        return None

    @classmethod
    def _sp_search_track_meta_for_track(
        cls, original_query: str, track: "TrackInfo"
    ) -> tuple[Optional[dict], Optional[dict]]:
        """Search Spotify metadata for a single YT track and return (meta, score_info)."""
        search_parts = [original_query]
        if track.title:
            search_parts.append(track.title)
        if track.artist:
            search_parts.append(track.artist)
        search_query = " ".join(x.strip() for x in search_parts if x and x.strip())

        for attempt in range(3):
            sp = cls._sp_client()
            if not sp:
                return None, None
            try:
                res = sp.search(q=search_query, type="track", limit=5)
                items = res.get("tracks", {}).get("items", [])
                if not items:
                    return None, None

                best_meta = None
                best_score = None
                for item in items:
                    images = item.get("album", {}).get("images", [])
                    meta = {
                        "title": item.get("name", ""),
                        "thumbnail": images[0]["url"] if images else "",
                        "duration": int((item.get("duration_ms") or 0) / 1000),
                        "artist": ", ".join(a["name"] for a in item.get("artists", [])),
                        "spotify_url": item.get("external_urls", {}).get("spotify", ""),
                    }
                    score = _compute_enrich_confidence(original_query, track, meta)
                    if best_score is None or score["confidence"] > best_score["confidence"]:
                        best_meta = meta
                        best_score = score

                return best_meta, best_score
            except Exception as e:
                cls._sp = None
                if attempt < 2:
                    time.sleep(_SPOTIFY_RETRY_BASE_DELAY_SECONDS * (attempt + 1))
                    continue
                enrich_log.debug(tag("SPOTIFY", f"{b(search_query)}  fallito dopo 3 tentativi: {e}"))
        return None, None

    @classmethod
    def _enrich_with_spotify(
        cls, tracks: list["TrackInfo"], original_query: str
    ) -> list["TrackInfo"]:
        """
        Enrich YT tracks with Spotify metadata.

        Per-track logic:
        - full: update title/artist/thumbnail/spotify_url
        - cover_only: update thumbnail/spotify_url
        - skip: keep YT metadata
        """
        if not Config.SPOTIFY_CLIENT_ID:
            return tracks
        for idx, track in enumerate(tracks, start=1):
            try:
                meta, score = cls._sp_search_track_meta_for_track(original_query, track)
            except Exception as e:
                enrich_log.debug(tag("SPOTIFY", f"enrich skip: {e}"))
                continue

            if not meta or not score:
                enrich_log.debug(tag("SPOTIFY", f"enrich[{idx}]  {b(track.title)}  ❌ skip  reason=no_meta"))
                continue
            if not any(meta.get(k) for k in ("thumbnail", "title", "artist", "spotify_url")):
                enrich_log.debug(tag("SPOTIFY", f"enrich[{idx}]  {b(track.title)}  ❌ skip  reason=empty_meta"))
                continue

            decision = score["decision"]
            sp_title = meta.get("title", "")
            sp_artist = meta.get("artist", "")
            yt_title_before = track.title
            apply_cover_and_spotify = decision in ("full", "cover_only")

            if apply_cover_and_spotify and meta.get("spotify_url"):
                track.spotify_url = meta["spotify_url"]

            if apply_cover_and_spotify and meta.get("thumbnail"):
                track.thumbnail = meta["thumbnail"]
            if decision == "full":
                if sp_title:
                    track.title = sp_title
                if sp_artist:
                    track.artist = sp_artist

            _dc = _BGRN if decision == "full" else (_BYEL if decision == "cover_only" else _BRED)
            enrich_log.debug(tag(
                "SPOTIFY",
                f"enrich[{idx}]  {b(original_query)}  →  {b(sp_title)}\n"
                f"          {'yt':<10} {b(yt_title_before)}\n"
                f"          {'conf':<10} {score['confidence']:.2f}  "
                f"q={score['query_sim']:.2f}  yt={score['yt_sim']:.2f}  "
                f"art={score['artist_sim']:.2f}  dur={score['duration_sim']:.2f}  "
                f"junk_pen={score['variant_penalty']:.2f}  nm={score['non_music_penalty']:.2f}  "
                f"→ {hi(decision, _dc)}  {dim(score['reason'])}"
            ))
        return tracks

    @classmethod
    async def resolve(cls, query: str, requester: str, requester_id: int = 0) -> list:
        loop = asyncio.get_running_loop()
        if track_id := extract_spotify_track_id(query):
            return await loop.run_in_executor(None, cls._sp_track, track_id, requester, requester_id)
        if playlist_id := extract_spotify_playlist_id(query):
            return await loop.run_in_executor(None, cls._sp_playlist, playlist_id, requester, requester_id)
        if album_id := extract_spotify_album_id(query):
            return await loop.run_in_executor(None, cls._sp_album, album_id, requester, requester_id)
        if artist_id := extract_spotify_artist_id(query):
            tracks = []
            async for t in cls.resolve_artist_stream_by_id(
                artist_id, requester, requester_id, limit=20
            ):
                tracks.append(t)
            return tracks
        return await loop.run_in_executor(None, cls._search_or_url, query, requester, requester_id)

    @classmethod
    async def resolve_choices(
        cls, query: str, requester: str, requester_id: int, n: int = 7
    ) -> list:
        """Resolve a query into up to n candidate tracks.

        For plain-text queries with n == 1 and Spotify available, Spotify-first
        metadata is used to craft a canonical YouTube search query while the
        original query remains available for enrichment.
        """
        loop = asyncio.get_running_loop()
        t0   = time.perf_counter()

        # ── Spotify-first for direct /play text queries (n == 1) ────────────────
        # For plain-text queries we ask Spotify first to obtain the canonical
        # title + artist.  This corrects typos (Spotify's search engine is
        # very tolerant) and replaces vague queries like "Fever" with a precise
        # one like "Fever Elvis Presley", so YouTube returns the studio version
        # instead of a live recording or an unrelated video.
        # The original query is always preserved for the enrichment step so that
        # metadata quality doesn't degrade.
        sp_meta_hint: Optional[dict] = None
        yt_query = query
        if n == 1 and not _is_url_like_query(query) and Config.SPOTIFY_CLIENT_ID:
            try:
                sp_meta_hint = await loop.run_in_executor(
                    None, cls._sp_search_track_meta, query
                )
            except Exception:
                sp_meta_hint = None
            if sp_meta_hint:
                canonical = f"{sp_meta_hint['title']} {sp_meta_hint['artist']}".strip()
                if canonical:
                    yt_query = canonical
                    log.debug(tag("SPOTIFY", f"first  {b(query)}  →  {b(yt_query)}"))

        search_n = max(n, _YT_CANDIDATES)
        results  = await loop.run_in_executor(
            None, cls._run_ytdlp, f"ytsearch{search_n}:{yt_query}", requester, requester_id
        )

        if results:
            sp_dur = float(sp_meta_hint.get("duration", 0) or 0) if sp_meta_hint else 0.0
            if n == 1 and len(results) > 1:
                best = _prefer_studio(results, sp_dur=sp_dur, user_query=query)
                results = [best] if best else results[:1]

            # Use the canonical query for enrichment when Spotify-first succeeded,
            # so the confidence scores are computed against the correct metadata.
            enrich_query = yt_query if sp_meta_hint else query
            if _should_enrich_with_spotify(enrich_query, results):
                results = await loop.run_in_executor(
                    None, cls._enrich_with_spotify, results, enrich_query
                )

        elapsed = (time.perf_counter() - t0) * 1000
        log.info(tag("RESOLVE", f"{b(query)}  →  {b(str(len(results)))} risultati  {ms(elapsed)}"))
        return results

    @classmethod
    async def resolve_stream(cls, query: str, requester: str, requester_id: int = 0):
        if playlist_id := extract_spotify_playlist_id(query):
            async for t in cls._sp_playlist_stream(playlist_id, requester, requester_id):
                yield t
            return
        if album_id := extract_spotify_album_id(query):
            async for t in cls._sp_album_stream(album_id, requester, requester_id):
                yield t
            return
        try:
            tracks = await cls.resolve(query, requester, requester_id)
        except Exception as e:
            log.error(tag("ERR", f"resolve_stream fallback: {e}"))
            return
        for t in tracks:
            yield t

    @classmethod
    async def resolve_artist_stream(
        cls, artist_name: str, requester: str, requester_id: int, limit: int = 20
    ):
        loop = asyncio.get_running_loop()
        sp = cls._sp_client()

        if not sp:
            tracks = await loop.run_in_executor(
                None, cls._run_ytdlp, f"ytsearch{limit}:{artist_name}", requester, requester_id
            )
            for t in spotify_style_shuffle(tracks):
                yield t
            return

        try:
            raw = await loop.run_in_executor(
                None, lambda: sp.search(q=artist_name, type="artist", limit=5)
            )
            items = raw["artists"]["items"]
            if not items:
                log.warning(tag("WARN", f"Artista non trovato: {b(artist_name)}"))
                return
            artist_id, found_name = cls._best_artist_match(artist_name, items)
        except Exception as e:
            log.error(tag("ERR", f"resolve_artist_stream setup: {e}"))
            return

        async for t in cls._artist_stream_from_id(artist_id, found_name, requester, requester_id, limit, loop, sp):
            yield t

    @classmethod
    async def resolve_artist_stream_by_id(
        cls, artist_id: str, requester: str, requester_id: int, limit: int = 20
    ):
        loop = asyncio.get_running_loop()
        sp = cls._sp_client()
        if not sp:
            log.warning(tag("WARN", "Spotify non configurato, impossibile usare link artista"))
            return
        try:
            artist_data = await loop.run_in_executor(None, lambda: sp.artist(artist_id))
            found_name  = artist_data.get("name", "Artista")
            log.info(tag("SPOTIFY", f"Artista da ID  {b(found_name)}  (id: {hi(artist_id, _CYN)})"))
        except Exception as e:
            log.error(tag("ERR", f"resolve_artist_stream_by_id: {e}"))
            return
        async for t in cls._artist_stream_from_id(artist_id, found_name, requester, requester_id, limit, loop, sp):
            yield t

    @classmethod
    async def _artist_stream_from_id(
        cls, artist_id: str, found_name: str,
        requester: str, requester_id: int,
        limit: int, loop, sp
    ):
        try:
            top_tracks = await loop.run_in_executor(
                None, lambda: sp.artist_top_tracks(artist_id)["tracks"][:10]
            )
        except Exception as e:
            log.error(tag("ERR", f"_artist_stream_from_id top_tracks: {e}"))
            return

        pairs = [(t, found_name) for t in top_tracks if t.get("id")]

        remaining = limit - len(pairs)
        if remaining > 0:
            try:
                albums_raw = await loop.run_in_executor(
                    None,
                    lambda: sp.artist_albums(artist_id, album_type="album", limit=10)["items"]
                )
                random.shuffle(albums_raw)

                existing_ids = {t["id"] for t, _ in pairs}
                extra: list[tuple] = []
                for album in albums_raw:
                    if len(extra) >= remaining:
                        break
                    try:
                        album_tracks = await loop.run_in_executor(
                            None,
                            lambda a=album["id"]: sp.album_tracks(a, limit=50)["items"]
                        )
                        random.shuffle(album_tracks)
                        for t in album_tracks:
                            if t.get("id") and t["id"] not in existing_ids:
                                art = t["artists"][0]["name"] if t.get("artists") else found_name
                                extra.append((t, art))
                                existing_ids.add(t["id"])
                                if len(extra) >= remaining:
                                    break
                    except Exception:
                        continue

                enriched: list[tuple] = []
                ids_to_fetch = [t["id"] for t, _ in extra]
                for i in range(0, len(ids_to_fetch), 50):
                    batch = ids_to_fetch[i:i + 50]
                    try:
                        full = await loop.run_in_executor(
                            None, lambda b=batch: sp.tracks(b)["tracks"]
                        )
                        art_map = {t["id"]: a for t, a in extra}
                        for ft in full:
                            if ft and ft.get("id"):
                                enriched.append((ft, art_map.get(ft["id"], found_name)))
                    except Exception:
                        enriched.extend(extra[i:i + 50])

                pairs.extend(enriched)
                log.info(tag("SPOTIFY", f"album_tracks fill  {b(found_name)}  +{len(enriched)} tracce"))
            except Exception as e:
                log.warning(tag("WARN", f"album_tracks fill fallita per {b(found_name)}: {e}"))

        pairs = _popularity_tier_shuffle(pairs)
        log.info(tag("SPOTIFY", f"popularity-tier shuffle  {b(found_name)}  {len(pairs)} tracce"))

        for sp_track, art_name in pairs:
            resolved = await loop.run_in_executor(
                None, cls._sp_track_from_obj, sp_track, art_name, requester, requester_id
            )
            if resolved:
                yield resolved

    @staticmethod
    def _best_artist_match(query: str, artists: list) -> tuple:
        def norm(s: str) -> str:
            return s.lower().replace(" ", "").replace("-", "").replace("'", "")
        q_norm = norm(query)
        for a in artists:
            if norm(a["name"]) == q_norm:
                return a["id"], a["name"]
        return artists[0]["id"], artists[0]["name"]

    @classmethod
    def _sp_track_from_obj(
        cls, sp_track: dict, artist_name: str, requester: str, requester_id: int
    ) -> Optional["TrackInfo"]:
        artists_str = ", ".join(a["name"] for a in sp_track.get("artists", [])) or artist_name
        sp_dur      = (sp_track.get("duration_ms") or 0) / 1000
        sp_title    = sp_track.get("name", "Senza titolo")
        images      = sp_track.get("album", {}).get("images", [])
        sp_thumb    = images[0]["url"] if images else ""
        sp_url      = sp_track.get("external_urls", {}).get("spotify", "")
        sp_pop      = sp_track.get("popularity", 0)

        query_title = sp_title.strip()
        query_artist = artists_str.strip()
        query_with_artist = f"{query_title} {query_artist}" if query_artist else query_title
        normalized_with_artist = _normalize_for_sim(query_with_artist)
        normalized_title = _normalize_for_sim(query_title)
        yt_queries = [
            f"ytsearch{_YT_CANDIDATES}:{query_with_artist} audio",
            f"ytsearch{_YT_CANDIDATES}:{query_with_artist}",
        ]
        if normalized_with_artist != normalized_title:
            yt_queries.append(f"ytsearch{_YT_CANDIDATES}:{query_title}")
        candidates = []
        used_step  = 0
        for step, q in enumerate(yt_queries, start=1):
            candidates = cls._run_ytdlp(q, requester, requester_id)
            if candidates:
                used_step = step
                break

        if not candidates:
            log.warning(tag("WARN", f"Nessun risultato YT per {b(sp_title)}"))
            return None

        if used_step > 1:
            log.info(tag("FALLBACK", f"{b(sp_title)}  trovata al passo {used_step}"))

        for c in candidates:
            c.source = "spotify"

        chosen = _prefer_studio(candidates, sp_dur, user_query=sp_title)

        chosen.title       = sp_title
        chosen.popularity  = sp_pop
        if sp_thumb:
            chosen.thumbnail = sp_thumb
        chosen.artist      = artists_str
        chosen.origin_query = query_with_artist
        chosen.spotify_url = sp_url

        log.info(tag("SPOTIFY", f"{hi(sp_title, _TEAL)}  →  {hi(chosen.webpage_url, _BBLU)}"))
        return chosen

    @classmethod
    async def _sp_playlist_stream(cls, pid: str, requester: str, requester_id: int):
        loop = asyncio.get_running_loop()
        sp = cls._sp_client()
        if not sp:
            return
        try:
            all_items = []
            offset = 0
            while True:
                page = await loop.run_in_executor(
                    None, lambda o=offset: sp.playlist_tracks(pid, limit=50, offset=o)
                )
                items = page.get("items", [])
                all_items.extend(items)
                if not page.get("next"):
                    break
                offset += 50
        except Exception as e:
            log.error(tag("ERR", f"playlist_tracks: {e}"))
            return
        ids = [
            item["track"]["id"]
            for item in all_items
            if item.get("track") and item["track"] and item["track"].get("id")
        ]
        async for t in cls._resolve_ids_batched(ids, requester, requester_id):
            yield t

    @classmethod
    async def _sp_album_stream(cls, aid: str, requester: str, requester_id: int):
        loop = asyncio.get_running_loop()
        sp = cls._sp_client()
        if not sp:
            return
        try:
            all_tracks = []
            offset = 0
            while True:
                page = await loop.run_in_executor(
                    None, lambda o=offset: sp.album_tracks(aid, limit=50, offset=o)
                )
                tracks = page.get("items", [])
                all_tracks.extend(tracks)
                if not page.get("next"):
                    break
                offset += 50
        except Exception as e:
            log.error(tag("ERR", f"album_tracks: {e}"))
            return
        ids = [t["id"] for t in all_tracks if t.get("id")]
        async for t in cls._resolve_ids_batched(ids, requester, requester_id):
            yield t

    @classmethod
    async def _resolve_ids_batched(
        cls, ids: list, requester: str, requester_id: int, batch: int = _SPOTIFY_BATCH_CONCURRENCY
    ):
        loop = asyncio.get_running_loop()
        if not ids:
            return

        max_concurrent = max(1, min(_SPOTIFY_BATCH_MAX_CONCURRENCY, int(batch)))

        async def _resolve_one(track_id: str):
            return await loop.run_in_executor(
                None, cls._sp_track, track_id, requester, requester_id
            )

        ids_iter = iter(ids)
        in_flight: set[asyncio.Task] = set()

        def _schedule_next() -> bool:
            try:
                tid = next(ids_iter)
            except StopIteration:
                return False
            in_flight.add(asyncio.create_task(_resolve_one(tid)))
            return True

        for _ in range(max_concurrent):
            if not _schedule_next():
                break

        try:
            while in_flight:
                done_set, _ = await asyncio.wait(
                    in_flight, return_when=asyncio.FIRST_COMPLETED
                )
                in_flight.difference_update(done_set)
                for done in done_set:
                    try:
                        res = done.result()
                    except Exception as exc:
                        log.warning(tag("WARN", f"_resolve_ids_batched: traccia saltata: {exc}"))
                        _schedule_next()
                        continue
                    if isinstance(res, list):
                        for t in res:
                            yield t
                    _schedule_next()
        finally:
            for t in in_flight:
                t.cancel()
            await asyncio.gather(*in_flight, return_exceptions=True)

    @classmethod
    async def resolve_fresh_url(cls, track) -> str:
        loop = asyncio.get_running_loop()
        t0   = time.perf_counter()
        url  = await loop.run_in_executor(None, cls._fetch_stream_url, track.webpage_url)
        elapsed = (time.perf_counter() - t0) * 1000
        status  = hi("OK", _BGRN) if url else hi("FAIL", _BRED)
        log.info(tag("STREAM", f"{title(track.title)}  {ms(elapsed)}  {status}"))
        return url

    @classmethod
    def _search_or_url(cls, query: str, requester: str, requester_id: int) -> list:
        if query.startswith("http"):
            if _is_yt_channel_url(query):
                log.debug(tag("RESOLVER", f"URL canale YouTube ignorato: {b(query)}"))
                return []
            query = _strip_yt_radio(query)
        else:
            query = "ytsearch:" + query
        return cls._run_ytdlp(query, requester, requester_id)

    @classmethod
    def _run_ytdlp(cls, query: str, requester: str, requester_id: int) -> list:
        cache_key = (int(requester_id or 0), query.strip())
        cached = cls._get_cached_ytdlp_results(cache_key)
        if cached is not None:
            log.debug(tag("RESOLVE", f"cache hit ytdlp  {b(query)}"))
            return cached
        normalized_query = query.strip()
        origin_query = re.sub(r"^ytsearch\d*:", "", normalized_query, count=1).strip() or normalized_query
        try:
            with yt_dlp.YoutubeDL(_make_opts()) as ydl:
                info = ydl.extract_info(query, download=False)
        except Exception as e:
            log.error(tag("ERR", f"yt-dlp: {e}"))
            return []
        if not info:
            return []
        raw_entries = info.get("entries")
        entries = raw_entries if raw_entries is not None else [info]
        results = []
        for e in entries:
            if not e or cls._is_drm(e):
                continue
            url = cls._best_audio_url(e)
            if not url:
                continue
            webpage_url = e.get("webpage_url", "")
            src    = "soundcloud" if _is_soundcloud_url(webpage_url) else "youtube"
            artist = e.get("artist") or e.get("creator") or e.get("uploader", "")
            results.append(TrackInfo(
                title        = e.get("title", "Senza titolo"),
                webpage_url  = webpage_url,
                duration     = int(e.get("duration") or 0),
                thumbnail    = e.get("thumbnail", ""),
                requester    = requester,
                requester_id = requester_id,
                source       = src,
                stream_url   = url,
                artist       = artist,
                origin_query = origin_query,
            ))
        cls._set_cached_ytdlp_results(cache_key, results)
        return results

    @classmethod
    def _fetch_stream_url(cls, webpage_url: str) -> str:
        normalized_webpage_url = (webpage_url or "").strip()
        if not normalized_webpage_url:
            return ""
        cached = cls._get_cached_stream_url(normalized_webpage_url)
        if cached is not None:
            log.debug(tag("STREAM", f"cache hit stream_url  {b(normalized_webpage_url)}"))
            return cached
        try:
            with yt_dlp.YoutubeDL(_make_opts({"noplaylist": True})) as ydl:
                info = ydl.extract_info(normalized_webpage_url, download=False)
        except Exception as e:
            log.error(tag("ERR", f"fetch_stream_url: {e}"))
            return ""
        if not info or cls._is_drm(info):
            return ""
        stream_url = cls._best_audio_url(info) or ""
        cls._set_cached_stream_url(normalized_webpage_url, stream_url)
        return stream_url

    @staticmethod
    def _is_drm(info: dict) -> bool:
        if info.get("is_drm_protected"):
            return True
        formats = info.get("formats", [])
        return bool(formats) and all(f.get("has_drm") for f in formats)

    @staticmethod
    def _best_audio_url(info: dict) -> Optional[str]:
        formats = info.get("formats", [])
        audio = [
            f for f in formats
            if f.get("vcodec") == "none"
            and f.get("acodec") not in (None, "none")
            and f.get("url")
            and not f.get("has_drm")
        ]
        if not audio:
            return info.get("url")
        _DIRECT = {"https", "http", ""}
        direct  = [f for f in audio if (f.get("protocol") or "").split("+")[0] in _DIRECT]
        pool    = direct if direct else audio
        return max(pool, key=lambda f: f.get("abr") or f.get("tbr") or 0)["url"]

    @classmethod
    def _sp_track(cls, track_id: str, requester: str, requester_id: int) -> list:
        sp = cls._sp_client()
        if not sp:
            return []
        try:
            t = sp.track(track_id)
        except Exception as e:
            log.error(tag("ERR", f"spotipy.track: {e}"))
            return []
        artists_str = ", ".join(a["name"] for a in t.get("artists", []))
        resolved = cls._sp_track_from_obj(t, artists_str, requester, requester_id)
        return [resolved] if resolved else []

    @classmethod
    def _sp_playlist(cls, pid: str, requester: str, requester_id: int) -> list:
        sp = cls._sp_client()
        if not sp:
            return []
        try:
            all_items = []
            offset = 0
            while True:
                page = sp.playlist_tracks(pid, limit=50, offset=offset)
                all_items.extend(page.get("items", []))
                if not page.get("next"):
                    break
                offset += 50
        except Exception as e:
            log.error(tag("ERR", f"playlist_tracks: {e}"))
            return []
        out = []
        for item in all_items:
            t = item.get("track")
            if t and t.get("id"):
                out.extend(cls._sp_track(t["id"], requester, requester_id))
        return out

    @classmethod
    def _sp_album(cls, aid: str, requester: str, requester_id: int) -> list:
        sp = cls._sp_client()
        if not sp:
            return []
        try:
            all_tracks = []
            offset = 0
            while True:
                page = sp.album_tracks(aid, limit=50, offset=offset)
                all_tracks.extend(page.get("items", []))
                if not page.get("next"):
                    break
                offset += 50
        except Exception as e:
            log.error(tag("ERR", f"album_tracks: {e}"))
            return []
        out = []
        for t in all_tracks:
            if t.get("id"):
                out.extend(cls._sp_track(t["id"], requester, requester_id))
        return out
