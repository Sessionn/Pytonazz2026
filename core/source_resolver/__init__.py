import asyncio
import logging
import random
import re
import threading
import time
import urllib.parse
from collections import defaultdict
from typing import Optional, Callable, TypeVar

import yt_dlp
from config import Config
from core.log_colors import tag, b, ms, title, hi, dim, _GRN, _CYN, _BGRN, _BYEL, _BRED, _BBLU, _TEAL
from core.stream_expiry import stream_ttl_seconds
from core.source_resolver.models import TrackInfo, clone_track as _clone_track

# â”€â”€ Sub-module imports â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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

from core.source_resolver.ytdlp import (
    _YTDLP_QUERY_CACHE_TTL,
    _YTDLP_QUERY_CACHE_MAX,
    _STREAM_URL_CACHE_TTL,
    _STREAM_URL_CACHE_MAX,
    _YdlLogger,
    _make_opts,
    _strip_yt_radio,
    _is_soundcloud_url,
    _resolve_soundcloud_short_url,
    _strip_soundcloud_params,
)

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


def _drop_unrequested_variants(
    query: str,
    results: list["TrackInfo"],
    *,
    context: str = "",
) -> list["TrackInfo"]:
    """Reject explicit version variants unless the user asked for that variant.

    This is intentionally stricter than a scoring penalty: for a plain query like
    "donne ricche" an "acoustic version" result must not be cached as the answer.
    """
    if not results or _query_requests_variant(query):
        return results

    clean_results = [track for track in results if not _is_variant(getattr(track, "title", "") or "")]
    if clean_results or len(clean_results) == len(results):
        return clean_results

    variant_titles = ", ".join((getattr(track, "title", "") or "-") for track in results[:3])
    log.debug(tag(
        "RESOLVE",
        f"scarto variante non richiesta  {b(query)}"
        f"{f'  via={b(context)}' if context else ''}  reject={b(variant_titles)}",
    ))
    return []


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


# Parole chiave che identificano canali/upload ufficiali dell'artista
_OFFICIAL_UPLOADER_KEYWORDS = re.compile(
    r"\b(vevo|official|music|records?|label|entertainment|ufficiale)\b",
    re.IGNORECASE,
)


def _is_official_upload(track) -> bool:
    """Restituisce True se il track sembra provenire da un canale/upload ufficiale."""
    artist = getattr(track, "artist", "") or ""
    title  = getattr(track, "title", "") or ""
    # Canali VEVO sono sempre ufficiali
    if "vevo" in artist.lower():
        return True
    # "Official Audio", "Official Video", "Official Music Video" nel titolo
    if re.search(r"\bofficial\b", title, re.IGNORECASE):
        return True
    # Uploader coincide (parzialmente) con l'artista del brano
    if _OFFICIAL_UPLOADER_KEYWORDS.search(artist):
        return True
    return False


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

    # Preferire upload ufficiali (VEVO / Official Audio) sugli altri
    official = [c for c in pool if _is_official_upload(c)]
    if official:
        pool = official

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


def _is_short_or_ambiguous_query(query: str) -> bool:
    q_norm = _normalize_for_sim(query)
    if not q_norm:
        return False
    parts = q_norm.split()
    if len(parts) <= 2:
        return True
    return len(q_norm) <= 14


def _is_title_only_candidate(query: str) -> bool:
    q_norm = _normalize_for_sim(query)
    if not q_norm or _query_requests_variant(query):
        return False
    parts = q_norm.split()
    if len(parts) < 3 or len(parts) > 6:
        return False
    return not any(sep in q_norm for sep in (" - ", " feat ", " ft ", " by "))


_LYRIC_PHRASE_WORD_RE = re.compile(
    r"\b(i|im|i'm|me|my|you|youre|you're|your|we|our|they|them|she|he|her|him|"
    r"dont|don't|cant|can't|wont|won't|gonna|wanna)\b",
    re.IGNORECASE,
)
_LYRIC_PHRASE_PUNCT_RE = re.compile(r"[,!?\"']")


def _spotify_meta_popularity(sp_meta: dict) -> int:
    try:
        return int(sp_meta.get("popularity") or 0)
    except (TypeError, ValueError):
        return 0


def _looks_like_lyric_phrase_query(query: str) -> bool:
    raw = (query or "").strip()
    q_norm = _normalize_for_sim(raw)
    if not raw or not q_norm:
        return False
    parts = q_norm.split()
    if len(parts) < 2 or len(parts) > 8:
        return False
    if _query_requests_variant(raw):
        return False
    if any(sep in q_norm for sep in (" feat ", " ft ", " prod ", " by ")):
        return False
    has_phrase_punct = bool(_LYRIC_PHRASE_PUNCT_RE.search(raw))
    has_phrase_word = bool(_LYRIC_PHRASE_WORD_RE.search(raw))
    return has_phrase_punct and (has_phrase_word or len(parts) >= 3)


def _should_defer_spotify_canonical_for_phrase_query(query: str, sp_meta: dict) -> bool:
    if not sp_meta or not _looks_like_lyric_phrase_query(query):
        return False
    artist_sim, artist_hint_present = _query_artist_signal(query, sp_meta.get("artist", ""))
    if artist_hint_present and artist_sim > 0.45:
        return False
    return _spotify_meta_popularity(sp_meta) < 45


def _should_use_spotify_canonical_early(query: str, sp_meta: dict) -> bool:
    if not sp_meta:
        return False
    title_norm = _normalize_for_sim(sp_meta.get("title", ""))
    artist = sp_meta.get("artist", "")
    artist_sim, artist_hint_present = _query_artist_signal(query, artist)
    q_norm = _normalize_for_sim(query)
    if not q_norm or not title_norm:
        return False
    if artist_hint_present and artist_sim > 0:
        return False
    if q_norm == title_norm and _should_defer_spotify_canonical_for_phrase_query(query, sp_meta):
        return False
    return q_norm == title_norm


def _spotify_youtube_query(canonical: str, original_query: str) -> str:
    query = (canonical or "").strip()
    if not query:
        return ""
    if _is_short_or_ambiguous_query(original_query) and not _query_requests_variant(original_query):
        return f"{query} audio"
    return query


def _raw_result_supports_spotify_artist(query: str, track, sp_artist: str) -> bool:
    artist_sim, artist_hint_present = _query_artist_signal(query, sp_artist)
    if not artist_hint_present or artist_sim <= 0.0:
        return False
    yt_blob = _normalize_for_sim(
        f"{getattr(track, 'title', '') or ''} {getattr(track, 'artist', '') or ''}"
    )
    artist_tokens = [
        tok for tok in _normalize_for_sim(sp_artist).split()
        if len(tok) >= _ARTIST_TOKEN_MIN_LENGTH
    ]
    return any(_contains_token(yt_blob, tok) for tok in artist_tokens)


def _raw_result_beats_weak_spotify_hint(query: str, track, sp_meta: dict) -> bool:
    """Avoid replacing a query-coherent raw result with a weak Spotify guess."""
    raw_sim = _enrich_sim(query, getattr(track, "title", "") or "", getattr(track, "artist", "") or "")
    spotify_sim = _enrich_sim(query, sp_meta.get("title", ""), sp_meta.get("artist", ""))
    raw_recall = _query_token_recall(query, f"{getattr(track, 'title', '') or ''} {getattr(track, 'artist', '') or ''}")
    spotify_recall = _query_token_recall(query, f"{sp_meta.get('title', '')} {sp_meta.get('artist', '')}")
    if raw_recall >= 0.67 and raw_recall >= spotify_recall + 0.34:
        return True
    if raw_sim >= 0.55 and spotify_sim < 0.45:
        return True
    if raw_sim >= 0.42 and raw_sim >= spotify_sim + 0.18:
        return True
    return False


def _query_token_recall(query: str, candidate_text: str) -> float:
    query_tokens = [tok for tok in _normalize_for_sim(query).split() if tok]
    candidate_tokens = [tok for tok in _normalize_for_sim(candidate_text).split() if tok]
    if not query_tokens or not candidate_tokens:
        return 0.0
    matched = 0
    used: set[int] = set()
    for q_tok in query_tokens:
        best_idx = -1
        best_score = 0.0
        for idx, c_tok in enumerate(candidate_tokens):
            if idx in used:
                continue
            if q_tok == c_tok:
                best_idx = idx
                best_score = 1.0
                break
            if min(len(q_tok), len(c_tok)) >= 4 and abs(len(q_tok) - len(c_tok)) <= 3:
                sim = _str_sim(q_tok, c_tok)
                if sim >= 0.78 and sim > best_score:
                    best_idx = idx
                    best_score = sim
        if best_idx >= 0:
            used.add(best_idx)
            matched += 1
    return matched / len(query_tokens)


def _should_retry_canonical_after_weak_hint(query: str, track, sp_meta: dict, score: dict) -> bool:
    if _is_short_or_ambiguous_query(query):
        return True
    if _raw_result_beats_weak_spotify_hint(query, track, sp_meta):
        return False
    raw_artist_ok = _raw_result_supports_spotify_artist(query, track, sp_meta.get("artist", ""))
    if not _query_requests_variant(query) and float(score.get("variant_penalty", 0.0) or 0.0) >= 0.20:
        if (
            raw_artist_ok
            and float(score.get("duration_sim", 0.0) or 0.0) >= 0.82
            and max(float(score.get("query_sim", 0.0) or 0.0), float(score.get("yt_sim", 0.0) or 0.0)) >= 0.55
        ):
            return False
        return True
    if _is_variant(getattr(track, "title", "") or "") and not _query_requests_variant(query):
        return True
    if score.get("yt_sim", 0.0) < 0.50:
        return True
    if not raw_artist_ok:
        return True
    return False


def _should_retry_canonical_after_music_video_hint(query: str, track, sp_meta: dict, score: dict) -> bool:
    """For text queries, avoid caching official videos when a studio/audio result is nearby."""
    if _query_requests_variant(query):
        return False
    if not _is_music_video(getattr(track, "title", "") or "", getattr(track, "artist", "") or ""):
        return False
    if not (sp_meta.get("title") and sp_meta.get("artist")):
        return False
    if float(score.get("query_sim", 0.0) or 0.0) < 0.55:
        return False
    if float(score.get("duration_sim", 0.0) or 0.0) < _DURATION_DEFAULT_SCORE:
        return False
    return True


def _should_force_multi_candidate_retry(query: str, score: dict) -> bool:
    if not _is_short_or_ambiguous_query(query):
        return False
    if score.get("decision") != "skip":
        return False
    if float(score.get("confidence", 0.0) or 0.0) > 0.18:
        return False
    if float(score.get("yt_sim", 0.0) or 0.0) > 0.12:
        return False
    return True


def _should_accept_spotify_direct_fast_match(sp_title: str, track, score: dict) -> bool:
    if score.get("decision") in ("full", "cover_only"):
        return True
    if _is_music_video(getattr(track, "title", "") or "", getattr(track, "artist", "") or ""):
        return False
    if _is_variant(getattr(track, "title", "") or "") and not _query_requests_variant(sp_title):
        return False
    if float(score.get("confidence", 0.0) or 0.0) < 0.43:
        return False
    if float(score.get("query_sim", 0.0) or 0.0) < 0.95:
        return False
    if float(score.get("yt_sim", 0.0) or 0.0) < 0.50:
        return False
    if float(score.get("duration_sim", 0.0) or 0.0) < 0.82:
        return False
    if float(score.get("variant_penalty", 0.0) or 0.0) > 0.0:
        return False
    return True


def _select_best_spotify_hint_result(results: list, sp_meta: dict, query: str) -> list:
    if not results or len(results) <= 1:
        return results
    sp_dur = float(sp_meta.get("duration", 0) or 0)
    best = _prefer_studio(results, sp_dur=sp_dur, user_query=query)
    return [best] if best else results[:1]


def _should_try_track_derived_spotify_enrich(query: str, track, sp_meta: dict, score: dict) -> bool:
    if not sp_meta or not track:
        return False
    if _spotify_enrich_mode(score) != "skip":
        return False
    if _is_url_like_query(query):
        return False
    title_blob = f"{getattr(track, 'title', '') or ''} {getattr(track, 'artist', '') or ''}"
    if not title_blob.strip():
        return False
    if _is_music_video(getattr(track, "title", "") or "", getattr(track, "artist", "") or ""):
        return False
    if _should_defer_spotify_canonical_for_phrase_query(query, sp_meta):
        return True
    confidence = float(score.get("confidence", 0.0) or 0.0)
    return _spotify_meta_popularity(sp_meta) < 35 and confidence < 0.45 and (
        bool(getattr(track, "artist", "") or "") or " - " in getattr(track, "title", "")
    )


def _prefer_track_derived_spotify_meta(
    query: str,
    original_meta: dict,
    original_score: dict,
    derived_meta: dict | None,
    derived_score: dict | None,
) -> bool:
    if not derived_meta or not derived_score:
        return False
    if _spotify_enrich_mode(derived_score) == "skip":
        return False
    original_pop = _spotify_meta_popularity(original_meta)
    derived_pop = _spotify_meta_popularity(derived_meta)
    if _should_defer_spotify_canonical_for_phrase_query(query, original_meta):
        return derived_pop >= max(0, original_pop - 10)
    original_conf = float(original_score.get("confidence", 0.0) or 0.0)
    derived_conf = float(derived_score.get("confidence", 0.0) or 0.0)
    return derived_pop >= original_pop or derived_conf >= original_conf + 0.18


def _spotify_track_derived_search_query(original_query: str, track) -> str:
    title_text = (getattr(track, "title", "") or "").strip()
    artist_text = (getattr(track, "artist", "") or "").strip()
    if _looks_like_lyric_phrase_query(original_query) and title_text:
        cleaned_title = re.sub(
            r"\((?:lyrics?|official\s+audio|official\s+video|audio|video)\)",
            " ",
            title_text,
            flags=re.IGNORECASE,
        )
        cleaned_title = re.sub(
            r"\[(?:lyrics?|official\s+audio|official\s+video|audio|video)\]",
            " ",
            cleaned_title,
            flags=re.IGNORECASE,
        )
        cleaned_title = re.sub(r"\s+", " ", cleaned_title).strip(" -|")
        if " - " in cleaned_title:
            left, right = cleaned_title.split(" - ", 1)
            return f"{left.strip()} {right.strip()}".strip()
        if artist_text and _contains_token(_normalize_for_sim(cleaned_title), _normalize_for_sim(artist_text)):
            return cleaned_title
        return " ".join(x for x in (cleaned_title, artist_text) if x).strip()

    search_parts = []
    search_parts.append(original_query)
    if title_text:
        search_parts.append(title_text)
    if artist_text:
        search_parts.append(artist_text)
    return " ".join(x.strip() for x in search_parts if x and x.strip())


def _spotify_enrich_mode(score: dict) -> str:
    decision = score.get("decision", "skip")
    if decision in ("full", "cover_only"):
        return decision

    confidence = float(score.get("confidence", 0.0) or 0.0)
    query_sim = float(score.get("query_sim", 0.0) or 0.0)
    yt_sim = float(score.get("yt_sim", 0.0) or 0.0)
    duration_sim = float(score.get("duration_sim", 0.0) or 0.0)
    variant_penalty = float(score.get("variant_penalty", 0.0) or 0.0)
    non_music_penalty = float(score.get("non_music_penalty", 0.0) or 0.0)
    artist_hint_present = bool(score.get("artist_hint_present"))
    artist_sim = float(score.get("artist_sim", 0.0) or 0.0)
    artist_mismatch = artist_hint_present and artist_sim < _ARTIST_MISMATCH_THRESHOLD

    if artist_mismatch:
        return "skip"

    if (
        confidence >= 0.42
        and query_sim >= 0.94
        and yt_sim >= 0.88
        and duration_sim >= 0.82
        and variant_penalty <= 0.07
        and non_music_penalty <= 0.0
    ):
        return "cover_link"

    if (
        confidence >= 0.38
        and max(query_sim, yt_sim) >= 0.84
        and duration_sim >= 0.68
        and variant_penalty <= 0.14
    ):
        return "link_only"

    return "skip"


# â”€â”€ Query Cache singleton (lazy init) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
_qc_instance: Optional[object] = None
_qc_lock = threading.Lock()
_FAST_STREAM_EXTRACT_OPTS = {
    "noplaylist": True,
    "format": "bestaudio[ext=m4a]/bestaudio[ext=mp3]/bestaudio",
    "youtube_include_dash_manifest": False,
    "youtube_include_hls_manifest": False,
}


def _get_query_cache():
    """Restituisce il singleton QueryCache oppure None se la cache non e' abilitata."""
    global _qc_instance
    if not Config.CACHE_ENABLED:
        return None
    if _qc_instance is None:
        with _qc_lock:
            if _qc_instance is None:
                try:
                    from core.cache_db import add_alias as _cache_add_alias
                    from core.cache_db import get as _cache_get, put as _cache_put
                    from core.cache_db import invalidate_webpage_url as _cache_invalidate_url
                    from core.cache_db import update_stream_url as _cache_update_stream_url

                    class _Adapter:
                        """Adatta l'API funzionale di cache_db all'interfaccia lookup/store."""
                        @staticmethod
                        def lookup(query: str) -> Optional[dict]:
                            return _cache_get(query)

                        @staticmethod
                        def store(query: str, track: "TrackInfo") -> None:
                            _cache_put(query, track)

                        @staticmethod
                        def link_spotify(sp_url: str, key: str, variant: str) -> None:
                            _cache_add_alias(sp_url, key, "spotify")

                        @staticmethod
                        def invalidate_url(webpage_url: str) -> None:
                            _cache_invalidate_url(webpage_url)

                        @staticmethod
                        def update_stream_url(webpage_url: str, stream_url: str) -> None:
                            _cache_update_stream_url(webpage_url, stream_url)

                    _qc_instance = _Adapter()
                except Exception as e:
                    log.warning(tag("CACHE", f"impossibile inizializzare QueryCache: {e}"))
                    _qc_instance = None
    return _qc_instance


def _cache_hit_to_track(
    hit: dict, requester: str, requester_id: int, stream_url: str = ""
) -> "TrackInfo":
    """Converte una riga del DB in TrackInfo pronta per la riproduzione."""
    return TrackInfo(
        title        = hit.get("title") or "Senza titolo",
        webpage_url  = hit.get("webpage_url") or "",
        duration     = int(hit.get("duration") or 0),
        thumbnail    = hit.get("thumbnail") or "",
        requester    = requester,
        requester_id = requester_id,
        source       = hit.get("source") or "youtube",
        stream_url   = stream_url,
        artist       = hit.get("artist") or "",
        spotify_url  = hit.get("spotify_url") or "",
        thumbnail_source = hit.get("thumbnail_source") or "",
        thumbnail_confidence = float(hit.get("thumbnail_confidence") or 0.0),
    )


class SourceResolver:
    _sp = None
    _cache_lock = threading.Lock()
    _ytdlp_query_cache: dict[str, tuple[float, list["TrackInfo"]]] = {}
    _stream_url_cache: dict[str, tuple[float, str]] = {}
    _ytdlp_query_inflight: dict[str, threading.Event] = {}
    _stream_url_inflight: dict[str, threading.Event] = {}

    @staticmethod
    def _apply_spotify_meta(track: "TrackInfo", meta: dict, score: dict) -> None:
        decision = score["decision"]
        enrich_mode = _spotify_enrich_mode(score)
        apply_spotify_link = enrich_mode in ("full", "cover_only", "cover_link", "link_only")
        apply_cover_and_spotify = enrich_mode in ("full", "cover_only", "cover_link")

        if apply_spotify_link and meta.get("spotify_url"):
            track.spotify_url = meta["spotify_url"]

        if apply_cover_and_spotify and meta.get("thumbnail"):
            track.thumbnail = meta["thumbnail"]
            track.thumbnail_source = meta.get("thumbnail_source") or "spotify"
            track.thumbnail_confidence = max(
                float(meta.get("thumbnail_confidence") or 0.0),
                float(score.get("confidence") or 0.0),
            )

        if enrich_mode == "full":
            if meta.get("title"):
                track.title = meta["title"]
            if meta.get("artist"):
                track.artist = meta["artist"]
    @staticmethod
    def _log_spotify_enrich(idx: int, original_query: str, yt_title_before: str, meta: dict, score: dict) -> None:
        decision = _spotify_enrich_mode(score)
        _dc = _BGRN if decision == "full" else (_BYEL if decision in ("cover_only", "cover_link") else (_TEAL if decision == "link_only" else _BRED))
        sp_title = meta.get("title", "")
        sp_artist = meta.get("artist", "")
        conf_pct = int(score["confidence"] * 100)
        clip = lambda value, limit=68: (str(value)[: limit - 3] + "...") if len(str(value)) > limit else str(value)
        sp_label = clip(sp_title + (f"  {sp_artist}" if sp_artist else ""))
        yt_label = clip(yt_title_before)
        enrich_log.info(tag("SPOTIFY", f"enrich[{idx}]"))
        enrich_log.info(tag("SPOTIFY", f"  query={b(clip(original_query))}"))
        enrich_log.info(tag("SPOTIFY", f"  spotify={b(sp_label)}"))
        enrich_log.info(tag("SPOTIFY", f"  youtube={(dim(yt_label) if decision == 'full' else b(yt_label))}"))
        enrich_log.info(tag("SPOTIFY", f"  decision={hi(decision, _dc)}  conf={hi(f'{conf_pct}%', _dc)}"))
        enrich_log.debug(tag("SPOTIFY", f"enrich[{idx}] scores"))
        enrich_log.debug(tag("SPOTIFY", f"  query={int(score['query_sim'] * 100)}%"))
        enrich_log.debug(tag("SPOTIFY", f"  youtube={int(score['yt_sim'] * 100)}%"))
        enrich_log.debug(tag("SPOTIFY", f"  artist={int(score['artist_sim'] * 100)}%"))
        enrich_log.debug(tag("SPOTIFY", f"  duration={int(score['duration_sim'] * 100)}%"))
        enrich_log.debug(tag("SPOTIFY", f"  junk={int(score['variant_penalty'] * 100)}%"))
        enrich_log.debug(tag("SPOTIFY", f"  non_music={int(score['non_music_penalty'] * 100)}%"))
        enrich_log.debug(tag("SPOTIFY", f"  reason={dim(clip(score['reason']))}"))

    @classmethod
    def _cache_prune_locked(cls, cache: dict, max_size: int) -> None:
        now = time.monotonic()
        expired_keys = [k for k, (exp, _) in cache.items() if exp <= now]
        for key in expired_keys:
            cache.pop(key, None)
        while len(cache) > max_size:
            cache.pop(next(iter(cache)), None)

    @classmethod
    def _get_cached_ytdlp_results(
        cls, key: str, requester: str, requester_id: int
    ) -> Optional[list["TrackInfo"]]:
        now = time.monotonic()
        with cls._cache_lock:
            cached = cls._ytdlp_query_cache.get(key)
            if not cached:
                return None
            exp, tracks = cached
            if exp <= now:
                cls._ytdlp_query_cache.pop(key, None)
                return None
            cls._ytdlp_query_cache.pop(key, None)
            cls._ytdlp_query_cache[key] = (exp, tracks)
            hydrated = []
            for track in tracks:
                clone = _clone_track(track)
                clone.requester = requester
                clone.requester_id = requester_id
                hydrated.append(clone)
            return hydrated

    @classmethod
    def _set_cached_ytdlp_results(cls, key: str, tracks: list["TrackInfo"]) -> None:
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
            cls._stream_url_cache.pop(webpage_url, None)
            cls._stream_url_cache[webpage_url] = (exp, url)
            return url

    @classmethod
    def _set_cached_stream_url(cls, webpage_url: str, stream_url: str) -> None:
        if not stream_url:
            return
        ttl = stream_ttl_seconds(stream_url, fallback_ttl=int(_STREAM_URL_CACHE_TTL))
        with cls._cache_lock:
            cls._stream_url_cache.pop(webpage_url, None)
            cls._stream_url_cache[webpage_url] = (
                time.monotonic() + ttl,
                stream_url,
            )
            cls._cache_prune_locked(cls._stream_url_cache, _STREAM_URL_CACHE_MAX)

    @classmethod
    def invalidate_stream_cache(cls, webpage_url: str) -> None:
        normalized_webpage_url = (webpage_url or "").strip()
        if not normalized_webpage_url:
            return
        with cls._cache_lock:
            cls._stream_url_cache.pop(normalized_webpage_url, None)

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
                    "thumbnail_source": "spotify" if images else "",
                    "thumbnail_confidence": 0.92 if images else 0.0,
                    "duration":    int((t.get("duration_ms") or 0) / 1000),
                    "artist":      ", ".join(a["name"] for a in t.get("artists", [])),
                    "spotify_url": t.get("external_urls", {}).get("spotify", ""),
                    "popularity":  _spotify_item_popularity(t),
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
        search_query = _spotify_track_derived_search_query(original_query, track)
        if not search_query:
            return None, None

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
                        "thumbnail_source": "spotify" if images else "",
                        "thumbnail_confidence": 0.92 if images else 0.0,
                        "duration": int((item.get("duration_ms") or 0) / 1000),
                        "artist": ", ".join(a["name"] for a in item.get("artists", [])),
                        "spotify_url": item.get("external_urls", {}).get("spotify", ""),
                        "popularity": _spotify_item_popularity(item),
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
        if not Config.SPOTIFY_CLIENT_ID:
            return tracks
        for idx, track in enumerate(tracks, start=1):
            try:
                meta, score = cls._sp_search_track_meta_for_track(original_query, track)
            except Exception as e:
                enrich_log.debug(tag("SPOTIFY", f"enrich skip: {e}"))
                continue

            if not meta or not score:
                enrich_log.info(tag("SPOTIFY", f"enrich[{idx}]  {b(track.title)}  skip  reason=no_meta"))
                continue
            if not any(meta.get(k) for k in ("thumbnail", "title", "artist", "spotify_url")):
                enrich_log.info(tag("SPOTIFY", f"enrich[{idx}]  {b(track.title)}  skip  reason=empty_meta"))
                continue

            yt_title_before = track.title
            decision = _spotify_enrich_mode(score)
            sp_title = meta.get("title", "")
            sp_artist = meta.get("artist", "")
            apply_spotify_link = decision in ("full", "cover_only", "cover_link", "link_only")
            apply_cover_and_spotify = decision in ("full", "cover_only", "cover_link")

            if apply_spotify_link and meta.get("spotify_url"):
                track.spotify_url = meta["spotify_url"]

            if apply_cover_and_spotify and meta.get("thumbnail"):
                track.thumbnail = meta["thumbnail"]
                track.thumbnail_source = meta.get("thumbnail_source") or "spotify"
                track.thumbnail_confidence = max(
                    float(meta.get("thumbnail_confidence") or 0.0),
                    float(score.get("confidence") or 0.0),
                )
            if decision == "full":
                if sp_title:
                    track.title = sp_title
                if sp_artist:
                    track.artist = sp_artist
            cls._log_spotify_enrich(idx, original_query, yt_title_before, meta, score)
        return tracks

    @classmethod
    async def _resolve_cached_track(
        cls, query: str, requester: str, requester_id: int
    ) -> Optional["TrackInfo"]:
        qc = _get_query_cache()
        if qc is None:
            return None
        hit = qc.lookup(query)
        if not hit or not hit.get("webpage_url"):
            return None

        now_ts = int(time.time())
        cached_stream = (hit.get("stream_url") or "").strip()
        stream_expires_at = int(hit.get("stream_expires_at") or 0)
        if cached_stream and stream_expires_at > now_ts + 60:
            log.info(tag("STREAM", f"DB hit  {b(hit['webpage_url'])}"))
            return _cache_hit_to_track(hit, requester, requester_id, cached_stream)

        refresh_t0 = time.perf_counter()
        stream_url = await asyncio.get_running_loop().run_in_executor(
            None, cls._fetch_stream_url, hit["webpage_url"]
        )
        refresh_elapsed = (time.perf_counter() - refresh_t0) * 1000
        if stream_url:
            if hasattr(qc, "update_stream_url"):
                qc.update_stream_url(hit["webpage_url"], stream_url)
            log.info(tag("STREAM", f"DB refresh  {b(hit['webpage_url'])}  {ms(refresh_elapsed)}"))
            return _cache_hit_to_track(hit, requester, requester_id, stream_url)

        if hasattr(qc, "invalidate_url"):
            qc.invalidate_url(hit["webpage_url"])
        return None

    @classmethod
    async def resolve(cls, query: str, requester: str, requester_id: int = 0) -> list:
        loop = asyncio.get_running_loop()

        if _is_url_like_query(query):
            try:
                cached_track = await cls._resolve_cached_track(query, requester, requester_id)
                if cached_track is not None:
                    log.info(tag("CACHE", f"{b(query)}  ->  cache hit direct-url"))
                    return [cached_track]
            except Exception as _ce:
                log.debug(tag("CACHE", f"direct-url read path error (ignorato): {_ce}"))

        # â”€â”€ Spotify track singola â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        if track_id := extract_spotify_track_id(query):
            results = await loop.run_in_executor(
                None, cls._sp_track, track_id, requester, requester_id
            )
            # 6.2 â€” cache per link Spotify diretto
            if results and results[0].title:
                try:
                    qc = _get_query_cache()
                    if qc is not None:
                        qc.store(query, results[0])
                except Exception as _we:
                    log.debug(tag("CACHE", f"write path spotify-direct (ignorato): {_we}"))
            return results

        # â”€â”€ Spotify playlist / album / artista â†’ no cache (multi-traccia) â”€â”€â”€â”€
        if playlist_id := extract_spotify_playlist_id(query):
            return await loop.run_in_executor(
                None, cls._sp_playlist, playlist_id, requester, requester_id
            )
        if album_id := extract_spotify_album_id(query):
            return await loop.run_in_executor(
                None, cls._sp_album, album_id, requester, requester_id
            )
        if artist_id := extract_spotify_artist_id(query):
            tracks = []
            async for t in cls.resolve_artist_stream_by_id(
                artist_id, requester, requester_id, limit=20
            ):
                tracks.append(t)
            return tracks

        # â”€â”€ URL YouTube / SoundCloud diretto â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        results = await loop.run_in_executor(
            None, cls._search_or_url, query, requester, requester_id
        )
        # 6.2 â€” cache per URL diretto (YT/SC): salva solo se Ã¨ effettivamente un URL
        if results and results[0].title and _is_url_like_query(query):
            try:
                qc = _get_query_cache()
                if qc is not None:
                    qc.store(query, results[0])
            except Exception as _we:
                log.debug(tag("CACHE", f"write path url-direct (ignorato): {_we}"))
        return results

    @classmethod
    async def resolve_choices(
        cls, query: str, requester: str, requester_id: int, n: int = 7
    ) -> list:
        loop = asyncio.get_running_loop()
        t0   = time.perf_counter()

        # â”€â”€ READ PATH: cache-first lookup (solo per n==1, query testuale) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        if n == 1 and not _is_url_like_query(query):
            try:
                cached_track = await cls._resolve_cached_track(query, requester, requester_id)
                if cached_track is not None:
                    elapsed = (time.perf_counter() - t0) * 1000
                    log.info(tag("CACHE", f"{b(query)}  \u2192  cache hit  {ms(elapsed)}"))
                    return [cached_track]
                if _get_query_cache() is not None:
                    log.info(tag("CACHE", f"{b(query)}  \u2192  stale url, ricerca fresca"))
            except Exception as _ce:
                log.debug(tag("CACHE", f"read path error (ignorato): {_ce}"))
        # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

        search_n = max(n, _YT_CANDIDATES)
        canonical_search_n = 1 if n == 1 else search_n
        results = []
        sp_meta_hint: Optional[dict] = None
        used_spotify_hint = False
        fast_path = n == 1 and not _is_url_like_query(query)
        sp_future = None

        if fast_path:
            if Config.SPOTIFY_CLIENT_ID:
                sp_future = loop.run_in_executor(None, cls._sp_search_track_meta, query)
            yt_query = query
            if sp_future is not None and _is_short_or_ambiguous_query(query):
                sp_t0 = time.perf_counter()
                try:
                    await asyncio.wait_for(
                        asyncio.shield(sp_future),
                        timeout=max(0.0, float(Config.SPOTIFY_AMBIGUOUS_WAIT_SECONDS)),
                    )
                except asyncio.TimeoutError:
                    log.debug(tag("PERF", f"spotify ambiguous hint timeout  {b(query)}"))
                except Exception:
                    pass
                if sp_future.done():
                    try:
                        sp_meta_hint = sp_future.result()
                    except Exception:
                        sp_meta_hint = None
                    log.debug(tag("PERF", f"spotify ambiguous hint  {b(query)}  {ms((time.perf_counter() - sp_t0) * 1000)}"))
                if sp_meta_hint and not _should_defer_spotify_canonical_for_phrase_query(query, sp_meta_hint):
                    canonical = f"{sp_meta_hint['title']} {sp_meta_hint['artist']}".strip()
                    if canonical:
                        yt_query = _spotify_youtube_query(canonical, query)
            elif sp_future is not None and _is_title_only_candidate(query):
                sp_t0 = time.perf_counter()
                try:
                    await asyncio.wait_for(
                        asyncio.shield(sp_future),
                        timeout=max(0.55, float(Config.SPOTIFY_HINT_WAIT_SECONDS)),
                    )
                except asyncio.TimeoutError:
                    log.debug(tag("PERF", f"spotify title-only hint timeout  {b(query)}"))
                except Exception:
                    pass
                if sp_future.done():
                    try:
                        sp_meta_hint = sp_future.result()
                    except Exception:
                        sp_meta_hint = None
                    log.debug(tag("PERF", f"spotify title-only hint  {b(query)}  {ms((time.perf_counter() - sp_t0) * 1000)}"))
                if sp_meta_hint and _should_use_spotify_canonical_early(query, sp_meta_hint):
                    canonical = f"{sp_meta_hint['title']} {sp_meta_hint['artist']}".strip()
                    if canonical:
                        yt_query = _spotify_youtube_query(canonical, query)

            yt_t0 = time.perf_counter()
            results = await loop.run_in_executor(
                None, cls._run_ytdlp, f"ytsearch1:{yt_query}", requester, requester_id
            )
            log.debug(tag("PERF", f"ytsearch1 raw  {b(yt_query)}  {ms((time.perf_counter() - yt_t0) * 1000)}"))

            if sp_future is not None and sp_meta_hint is None:
                sp_t0 = time.perf_counter()
                if not sp_future.done():
                    try:
                        await asyncio.wait_for(
                            asyncio.shield(sp_future),
                            timeout=max(0.0, float(Config.SPOTIFY_HINT_WAIT_SECONDS)),
                        )
                    except asyncio.TimeoutError:
                        log.debug(tag("PERF", f"spotify hint timeout  {b(query)}"))
                    except Exception:
                        pass
                if sp_future.done():
                    try:
                        sp_meta_hint = sp_future.result()
                    except Exception:
                        sp_meta_hint = None
                    log.debug(tag("PERF", f"spotify hint  {b(query)}  {ms((time.perf_counter() - sp_t0) * 1000)}"))

            results = _drop_unrequested_variants(query, results, context="ytsearch1")

            if sp_meta_hint and results:
                score = _compute_enrich_confidence(query, results[0], sp_meta_hint)
                retry_music_video = _should_retry_canonical_after_music_video_hint(
                    query, results[0], sp_meta_hint, score
                )
                if retry_music_video:
                    canonical = f"{sp_meta_hint['title']} {sp_meta_hint['artist']}".strip()
                    canonical_yt_query = _spotify_youtube_query(canonical, query)
                    if canonical_yt_query:
                        log.debug(tag(
                            "SPOTIFY",
                            f"video ufficiale evitabile  {b(query)}"
                            f"  retry={b(canonical_yt_query)}  keep_if_empty={b(results[0].title)}",
                        ))
                        yt_t0 = time.perf_counter()
                        canonical_results = await loop.run_in_executor(
                            None, cls._run_ytdlp, f"ytsearch{search_n}:{canonical_yt_query}", requester, requester_id
                        )
                        log.debug(tag("PERF", f"ytsearch{search_n} video-retry  {b(canonical_yt_query)}  {ms((time.perf_counter() - yt_t0) * 1000)}"))
                        if canonical_results:
                            ranked = _select_best_spotify_hint_result(
                                _drop_unrequested_variants(query, canonical_results, context="video-retry"),
                                sp_meta_hint,
                                query,
                            )
                            if ranked:
                                results = ranked
                                score = _compute_enrich_confidence(query, results[0], sp_meta_hint)

                if _spotify_enrich_mode(score) != "skip":
                    used_spotify_hint = True
                    yt_title_before = results[0].title
                    cls._apply_spotify_meta(results[0], sp_meta_hint, score)
                    cls._log_spotify_enrich(1, query, yt_title_before, sp_meta_hint, score)
                else:
                    defer_spotify_canonical = _should_defer_spotify_canonical_for_phrase_query(query, sp_meta_hint)
                    canonical = f"{sp_meta_hint['title']} {sp_meta_hint['artist']}".strip()
                    canonical_yt_query = _spotify_youtube_query(canonical, query)
                    same_query_retry = (
                        canonical_yt_query
                        and canonical_yt_query == yt_query
                        and _should_force_multi_candidate_retry(query, score)
                    )
                    if (
                        canonical_yt_query
                        and not defer_spotify_canonical
                        and (
                            same_query_retry
                            or (
                                canonical_yt_query != yt_query
                                and _should_retry_canonical_after_weak_hint(query, results[0], sp_meta_hint, score)
                            )
                        )
                    ):
                        retry_n = search_n if same_query_retry else canonical_search_n
                        log.debug(tag(
                            "SPOTIFY",
                            f"raw hint debole  {b(query)}  score={int(score['confidence'] * 100)}%"
                            f"  reason={dim(score['reason'])}  fallback={b(canonical_yt_query)}"
                            f"  n={b(str(retry_n))}",
                        ))
                        yt_t0 = time.perf_counter()
                        canonical_results = await loop.run_in_executor(
                            None, cls._run_ytdlp, f"ytsearch{retry_n}:{canonical_yt_query}", requester, requester_id
                        )
                        log.debug(tag("PERF", f"ytsearch{retry_n} canonical  {b(canonical_yt_query)}  {ms((time.perf_counter() - yt_t0) * 1000)}"))
                        if canonical_results:
                            results = _drop_unrequested_variants(query, canonical_results, context="canonical")
                            results = _select_best_spotify_hint_result(results, sp_meta_hint, query)
                            if results:
                                canonical_score = _compute_enrich_confidence(query, results[0], sp_meta_hint)
                                if _spotify_enrich_mode(canonical_score) != "skip":
                                    used_spotify_hint = True
                                    yt_title_before = results[0].title
                                    cls._apply_spotify_meta(results[0], sp_meta_hint, canonical_score)
                                    cls._log_spotify_enrich(1, query, yt_title_before, sp_meta_hint, canonical_score)
                    elif defer_spotify_canonical and canonical_yt_query and canonical_yt_query != yt_query:
                        log.debug(tag(
                            "SPOTIFY",
                            f"canonical differito per query frase  {b(query)}"
                            f"  spotify={b(canonical)}  keep={b(results[0].title)}"
                            f"  pop={b(str(_spotify_meta_popularity(sp_meta_hint)))}",
                        ))
                    elif canonical_yt_query and canonical_yt_query != yt_query:
                        log.debug(tag(
                            "SPOTIFY",
                            f"raw hint debole ma risultato gia coerente  {b(query)}"
                            f"  score={int(score['confidence'] * 100)}%  keep={b(results[0].title)}",
                        ))

            if not results and sp_meta_hint:
                canonical = f"{sp_meta_hint['title']} {sp_meta_hint['artist']}".strip()
                canonical_yt_query = _spotify_youtube_query(canonical, query)
                if canonical_yt_query:
                    retry_n = search_n if fast_path else canonical_search_n
                    yt_t0 = time.perf_counter()
                    results = await loop.run_in_executor(
                        None, cls._run_ytdlp, f"ytsearch{retry_n}:{canonical_yt_query}", requester, requester_id
                    )
                    results = _drop_unrequested_variants(query, results, context="canonical-empty")
                    log.debug(tag("PERF", f"ytsearch{retry_n} canonical  {b(canonical_yt_query)}  {ms((time.perf_counter() - yt_t0) * 1000)}"))

        if not results:
            yt_t0 = time.perf_counter()
            results  = await loop.run_in_executor(
                None, cls._run_ytdlp, f"ytsearch{search_n}:{query}", requester, requester_id
            )
            results = _drop_unrequested_variants(query, results, context="fallback")
            log.debug(tag("PERF", f"ytsearch{search_n} fallback  {b(query)}  {ms((time.perf_counter() - yt_t0) * 1000)}"))

        if results:
            if fast_path and sp_meta_hint is None and sp_future is not None:
                late_wait = 0.0
                elapsed_so_far = time.perf_counter() - t0
                if sp_future.done():
                    late_wait = 0.0
                elif _is_short_or_ambiguous_query(query):
                    late_wait = 0.55 if elapsed_so_far >= 2.0 else 0.25
                elif elapsed_so_far >= 4.0:
                    late_wait = 0.35

                if late_wait > 0.0:
                    try:
                        sp_t0 = time.perf_counter()
                        await asyncio.wait_for(asyncio.shield(sp_future), timeout=late_wait)
                        log.debug(tag("PERF", f"spotify late hint  {b(query)}  {ms((time.perf_counter() - sp_t0) * 1000)}"))
                    except asyncio.TimeoutError:
                        log.debug(tag("PERF", f"spotify late hint timeout  {b(query)}"))
                    except Exception:
                        pass

                if sp_future.done():
                    try:
                        sp_meta_hint = sp_future.result()
                    except Exception:
                        sp_meta_hint = None

            sp_dur = float(sp_meta_hint.get("duration", 0) or 0) if sp_meta_hint else 0.0
            if n == 1 and len(results) > 1:
                best = _prefer_studio(results, sp_dur=sp_dur, user_query=query)
                results = [best] if best else results[:1]

            if sp_meta_hint and results and not used_spotify_hint:
                score = _compute_enrich_confidence(query, results[0], sp_meta_hint)
                raw_beats_hint = _raw_result_beats_weak_spotify_hint(query, results[0], sp_meta_hint)
                if raw_beats_hint:
                    log.debug(tag(
                        "SPOTIFY",
                        f"raw risultato preferito a hint debole  {b(query)}"
                        f"  keep={b(results[0].title)}"
                        f"  spotify={b((sp_meta_hint.get('title') or '').strip())}",
                    ))
                elif _should_try_track_derived_spotify_enrich(query, results[0], sp_meta_hint, score):
                    try:
                        alt_meta, alt_score = await loop.run_in_executor(
                            None, cls._sp_search_track_meta_for_track, query, results[0]
                        )
                    except Exception as e:
                        alt_meta, alt_score = None, None
                        log.debug(tag("SPOTIFY", f"track-derived enrich skip  {b(query)}  {e}"))
                    if _prefer_track_derived_spotify_meta(query, sp_meta_hint, score, alt_meta, alt_score):
                        log.debug(tag(
                            "SPOTIFY",
                            f"track-derived enrich preferito  {b(query)}"
                            f"  old_pop={b(str(_spotify_meta_popularity(sp_meta_hint)))}"
                            f"  new_pop={b(str(_spotify_meta_popularity(alt_meta or {})))}",
                        ))
                        sp_meta_hint = alt_meta
                        score = alt_score
                if not raw_beats_hint and _spotify_enrich_mode(score) != "skip":
                    yt_title_before = results[0].title
                    cls._apply_spotify_meta(results[0], sp_meta_hint, score)
                    cls._log_spotify_enrich(1, query, yt_title_before, sp_meta_hint, score)
            elif fast_path and not sp_meta_hint and results and _looks_like_lyric_phrase_query(query):
                try:
                    alt_meta, alt_score = await loop.run_in_executor(
                        None, cls._sp_search_track_meta_for_track, query, results[0]
                    )
                except Exception as e:
                    alt_meta, alt_score = None, None
                    log.debug(tag("SPOTIFY", f"lyrics track-derived enrich skip  {b(query)}  {e}"))
                if alt_meta and alt_score and _spotify_enrich_mode(alt_score) != "skip":
                    yt_title_before = results[0].title
                    cls._apply_spotify_meta(results[0], alt_meta, alt_score)
                    cls._log_spotify_enrich(1, query, yt_title_before, alt_meta, alt_score)
            elif not sp_meta_hint and _should_enrich_with_spotify(query, results):
                should_retry_enrich = (
                    not fast_path
                    or _is_short_or_ambiguous_query(query)
                    or (time.perf_counter() - t0) >= 4.0
                )
                if fast_path and sp_future is not None and not sp_future.done():
                    should_retry_enrich = False
                if should_retry_enrich:
                    results = await loop.run_in_executor(
                        None, cls._enrich_with_spotify, results, query
                    )

        # â”€â”€ WRITE PATH: salva il risultato in cache â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        if n == 1 and results and not _is_url_like_query(query):
            try:
                qc = _get_query_cache()
                if qc is not None:
                    qc.store(query, results[0])
            except Exception as _we:
                log.debug(tag("CACHE", f"write path error (ignorato): {_we}"))
        # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

        elapsed = (time.perf_counter() - t0) * 1000
        log.info(tag("RESOLVE", f"{b(query)}  \u2192  {b(str(len(results)))} risultati  {ms(elapsed)}"))
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
        sp_meta = {
            "title": sp_title,
            "artist": artists_str,
            "duration": sp_dur,
            "thumbnail": sp_thumb,
            "spotify_url": sp_url,
        }

        fast_query = f"ytsearch1:{query_with_artist}" if query_with_artist else ""
        if fast_query:
            fast_candidates = cls._run_ytdlp(fast_query, requester, requester_id)
            if fast_candidates:
                fast_score = _compute_enrich_confidence(query_with_artist, fast_candidates[0], sp_meta)
                if _should_accept_spotify_direct_fast_match(sp_title, fast_candidates[0], fast_score):
                    candidates = fast_candidates
                    for c in candidates:
                        c.source = "spotify"
                    chosen = _prefer_studio(candidates, sp_dur, user_query=sp_title)
                    chosen.title = sp_title
                    chosen.popularity = sp_pop
                    chosen.duration = int(round(sp_dur)) if sp_dur else int(chosen.duration or 0)
                    if sp_thumb:
                        chosen.thumbnail = sp_thumb
                        chosen.thumbnail_source = "spotify"
                        chosen.thumbnail_confidence = 0.95
                    chosen.artist = artists_str
                    chosen.origin_query = query_with_artist
                    chosen.spotify_url = sp_url

                    log.info(tag("SPOTIFY", f"{hi(sp_title, _TEAL)}  →  {hi(chosen.webpage_url, _BBLU)}"))
                    if sp_url:
                        try:
                            qc = _get_query_cache()
                            if qc is not None:
                                qc.link_spotify(sp_url, query_with_artist, "")
                        except Exception:
                            pass
                    return chosen

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
        chosen.duration    = int(round(sp_dur)) if sp_dur else int(chosen.duration or 0)
        if sp_thumb:
            chosen.thumbnail = sp_thumb
            chosen.thumbnail_source = "spotify"
            chosen.thumbnail_confidence = 0.95
        chosen.artist      = artists_str
        chosen.origin_query = query_with_artist
        chosen.spotify_url = sp_url

        log.info(tag("SPOTIFY", f"{hi(sp_title, _TEAL)}  \u2192  {hi(chosen.webpage_url, _BBLU)}"))

        # â”€â”€ WRITE PATH Spotify: salva in cache DB â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        if sp_url:
            try:
                qc = _get_query_cache()
                if qc is not None:
                    qc.link_spotify(sp_url, query_with_artist, "")
            except Exception:
                pass
        # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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
            query = _resolve_soundcloud_short_url(query)
            query = _strip_soundcloud_params(query)
            query = _strip_yt_radio(query)
        else:
            query = "ytsearch:" + query
        return cls._run_ytdlp(query, requester, requester_id)

    @classmethod
    def _run_ytdlp(cls, query: str, requester: str, requester_id: int) -> list:
        cache_key = query.strip()
        cached = cls._get_cached_ytdlp_results(cache_key, requester, requester_id)
        if cached is not None:
            log.debug(tag("RESOLVE", f"cache hit ytdlp  {b(query)}"))
            return cached
        with cls._cache_lock:
            inflight = cls._ytdlp_query_inflight.get(cache_key)
            if inflight is None:
                inflight = threading.Event()
                cls._ytdlp_query_inflight[cache_key] = inflight
                owns_inflight = True
            else:
                owns_inflight = False
        if not owns_inflight:
            inflight.wait()
            cached = cls._get_cached_ytdlp_results(cache_key, requester, requester_id)
            return cached if cached is not None else []
        normalized_query = query.strip()
        origin_query = re.sub(r"^ytsearch\d*:", "", normalized_query, count=1).strip() or normalized_query
        try:
            fast_search_results = cls._run_ytdlp_flat_first(normalized_query, requester, requester_id, origin_query)
            if fast_search_results is not None:
                cls._set_cached_ytdlp_results(cache_key, fast_search_results)
                return fast_search_results
            try:
                with yt_dlp.YoutubeDL(_make_opts()) as ydl:
                    info = ydl.extract_info(query, download=False)
            except yt_dlp.utils.ExtractorError as e:
                err_str = str(e).lower()
                # Video non disponibile (rimosso, geo-bloccato, privato, ecc.)
                if any(kw in err_str for kw in ("video unavailable", "private video",
                                                 "this video is not available",
                                                 "has been removed", "geo")):
                    log.warning(tag("WARN", f"video non disponibile, fallback search: {b(query)}"))
                    # Se era un URL diretto, proviamo una ricerca testuale con il titolo
                    if query.startswith("http"):
                        return []  # per URL diretti non c'Ã¨ fallback sicuro
                    # Per query ytsearch, logghiamo e restituiamo vuoto
                    return []
                log.error(tag("ERR", f"yt-dlp ExtractorError: {e}"))
                return []
            except Exception as e:
                log.error(tag("ERR", f"yt-dlp: {e}"))
                return []
            if not info:
                return []
            results = cls._tracks_from_ytdlp_info(info, requester, requester_id, origin_query)
            cls._set_cached_ytdlp_results(cache_key, results)
            return results
        finally:
            with cls._cache_lock:
                done = cls._ytdlp_query_inflight.pop(cache_key, None)
                if done is not None:
                    done.set()

    @classmethod
    def _run_ytdlp_flat_first(
        cls,
        query: str,
        requester: str,
        requester_id: int,
        origin_query: str,
    ) -> Optional[list]:
        if not re.match(r"^ytsearch1:", query, re.IGNORECASE):
            return None
        try:
            with yt_dlp.YoutubeDL(_make_opts({"extract_flat": True, "format": "bestaudio/best"})) as ydl:
                info = ydl.extract_info(query, download=False)
            direct_url = cls._first_ytdlp_webpage_url(info or {})
            if not direct_url:
                return None
            with yt_dlp.YoutubeDL(_make_opts(_FAST_STREAM_EXTRACT_OPTS)) as ydl:
                direct_info = ydl.extract_info(direct_url, download=False)
            results = cls._tracks_from_ytdlp_info(direct_info or {}, requester, requester_id, origin_query)
            return results if results else None
        except Exception as exc:
            log.debug(tag("RESOLVE", f"flat-first ytsearch fallback  {b(query)}  {exc}"))
            return None

    @staticmethod
    def _first_ytdlp_webpage_url(info: dict) -> str:
        entries = info.get("entries") or []
        first = entries[0] if entries else info
        if not first:
            return ""
        url = first.get("webpage_url") or first.get("url") or ""
        if url and not url.startswith(("http://", "https://")):
            url = f"https://www.youtube.com/watch?v={url}"
        return url

    @classmethod
    def _tracks_from_ytdlp_info(cls, info: dict, requester: str, requester_id: int, origin_query: str) -> list:
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
                thumbnail_source = src,
                thumbnail_confidence = 0.45,
            ))
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
        with cls._cache_lock:
            inflight = cls._stream_url_inflight.get(normalized_webpage_url)
            if inflight is None:
                inflight = threading.Event()
                cls._stream_url_inflight[normalized_webpage_url] = inflight
                owns_inflight = True
            else:
                owns_inflight = False
        if not owns_inflight:
            inflight.wait()
            return cls._get_cached_stream_url(normalized_webpage_url) or ""
        try:
            try:
                with yt_dlp.YoutubeDL(_make_opts(_FAST_STREAM_EXTRACT_OPTS)) as ydl:
                    info = ydl.extract_info(normalized_webpage_url, download=False)
            except yt_dlp.utils.ExtractorError as e:
                cls.invalidate_stream_cache(normalized_webpage_url)
                err_str = str(e).lower()
                if any(kw in err_str for kw in ("video unavailable", "private video",
                                                 "this video is not available",
                                                 "has been removed")):
                    log.warning(tag("WARN", f"video non disponibile (rimosso/privato): {b(normalized_webpage_url)}"))
                else:
                    log.error(tag("ERR", f"fetch_stream_url ExtractorError: {e}"))
                return ""
            except Exception as e:
                cls.invalidate_stream_cache(normalized_webpage_url)
                log.error(tag("ERR", f"fetch_stream_url: {e}"))
                return ""
            if not info or cls._is_drm(info):
                cls.invalidate_stream_cache(normalized_webpage_url)
                return ""
            stream_url = cls._best_audio_url(info) or ""
            if stream_url:
                cls._set_cached_stream_url(normalized_webpage_url, stream_url)
            else:
                cls.invalidate_stream_cache(normalized_webpage_url)
            return stream_url
        finally:
            with cls._cache_lock:
                done = cls._stream_url_inflight.pop(normalized_webpage_url, None)
                if done is not None:
                    done.set()

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


