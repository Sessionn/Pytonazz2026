"""Policy: shared resolver policies and helpers."""
from __future__ import annotations
import logging
import re
from config import Config
from core.log_colors import tag, b
from core.source_resolver.selection import select_best_track
from core.source_resolver.scoring import _DURATION_DEFAULT_SCORE, _ARTIST_MISMATCH_THRESHOLD, _ARTIST_TOKEN_MIN_LENGTH, _is_music_video, _is_variant, _query_requests_variant, _str_sim, _normalize_for_sim, _enrich_sim, _contains_token, _query_artist_signal

log = logging.getLogger("pitonazz.resolver")

_LYRIC_PHRASE_WORD_RE = re.compile(
    r"\b(i|im|i'm|me|my|you|youre|you're|your|we|our|they|them|she|he|her|him|"
    r"dont|don't|cant|can't|wont|won't|gonna|wanna)\b",
    re.IGNORECASE,
)

_LYRIC_PHRASE_PUNCT_RE = re.compile(r"[,!?\"']")


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


def _prefer_studio(
    candidates: list,
    sp_dur: float = 0,
    user_query: str = "",
    sp_meta: dict | None = None,
) -> object:
    if not candidates:
        return None
    meta = dict(sp_meta or {})
    if sp_dur > 0 and "duration" not in meta:
        meta["duration"] = sp_dur
    if (user_query or "").strip() or meta:
        best = select_best_track(user_query, candidates, meta or None)
        return best if best else candidates[0]
    return candidates[0]


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
    best = _prefer_studio(results, sp_dur=sp_dur, user_query=query, sp_meta=sp_meta)
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
