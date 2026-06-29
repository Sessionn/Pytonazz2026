"""
Pure candidate selection policy for the music resolver.

The resolver decides which providers to call; this module decides which returned
track is the best answer for the user's intent. Keep this file free of network,
database and Config dependencies so the "brain" is cheap to test.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable

from core.source_resolver.scoring import (
    _compute_enrich_confidence,
    _duration_similarity,
    _enrich_sim,
    _is_music_video,
    _is_probably_non_music_query,
    _is_variant,
    _normalize_for_sim,
    _query_requests_variant,
    _variant_tags,
)


_OFFICIAL_UPLOADER_KEYWORDS = re.compile(
    r"\b(vevo|official|music|records?|label|entertainment|ufficiale)\b",
    re.IGNORECASE,
)
_OFFICIAL_AUDIO_RE = re.compile(r"\bofficial\s+audio\b|\baudio\s+ufficiale\b", re.IGNORECASE)
_VIDEO_INTENT_RE = re.compile(
    r"\b(official\s+video|music\s+video|video\s+ufficiale|videoclip|visualizer|\bmv\b)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CandidateScore:
    total: float
    query: float
    spotify: float
    duration: float
    official_bonus: float
    penalty: float
    severe_mismatch: bool
    reason: str


@dataclass(frozen=True)
class RankedCandidate:
    track: object
    score: CandidateScore
    index: int


def is_official_upload(track) -> bool:
    artist = getattr(track, "artist", "") or ""
    title = getattr(track, "title", "") or ""
    if "vevo" in artist.lower():
        return True
    if _OFFICIAL_AUDIO_RE.search(title):
        return True
    if re.search(r"\bofficial\b", title, re.IGNORECASE):
        return True
    return bool(_OFFICIAL_UPLOADER_KEYWORDS.search(artist))


def query_requests_video(query: str) -> bool:
    return bool(_VIDEO_INTENT_RE.search(query or ""))


def score_candidate(query: str, track, spotify_meta: dict | None = None) -> CandidateScore:
    q = (query or "").strip()
    title = getattr(track, "title", "") or ""
    artist = getattr(track, "artist", "") or ""
    duration = int(getattr(track, "duration", 0) or 0)

    query_score = _enrich_sim(q, title, artist) if q else 0.0
    duration_score = 0.45
    spotify_score = 0.0
    spotify_penalty = 0.0

    if spotify_meta:
        enrich_score = _compute_enrich_confidence(q, track, spotify_meta)
        spotify_score = float(enrich_score.get("confidence", 0.0) or 0.0)
        duration_score = float(enrich_score.get("duration_sim", 0.45) or 0.45)
        spotify_penalty = float(enrich_score.get("variant_penalty", 0.0) or 0.0)
    elif duration > 0:
        duration_score = _duration_shape_score(q, duration)

    official_bonus = 0.0
    if is_official_upload(track):
        official_bonus += 0.08
    if _OFFICIAL_AUDIO_RE.search(title):
        official_bonus += 0.04

    penalty = spotify_penalty
    requested_variant_tags = _variant_tags(q)
    candidate_variant_tags = _variant_tags(title)
    extra_variant_tags = candidate_variant_tags - requested_variant_tags
    unwanted_variant = _is_variant(title) and not _query_requests_variant(q)
    unwanted_video = _is_music_video(title, artist) and not query_requests_video(q)
    duration_penalty = _duration_penalty(q, duration, spotify_meta)

    if requested_variant_tags:
        if requested_variant_tags & candidate_variant_tags:
            official_bonus += 0.25
            if extra_variant_tags:
                penalty += min(0.28, 0.14 * len(extra_variant_tags))
        elif not candidate_variant_tags:
            penalty += 0.25
    if unwanted_variant:
        penalty += 0.30
    if unwanted_video:
        penalty += 0.18
    penalty += duration_penalty

    if spotify_meta:
        total = (
            query_score * 0.42
            + spotify_score * 0.34
            + duration_score * 0.14
            + official_bonus
            - penalty
        )
    else:
        total = (
            query_score * 0.78
            + duration_score * 0.10
            + official_bonus
            - penalty
        )

    total = max(0.0, min(1.0, total))
    severe = bool(
        unwanted_variant
        or unwanted_video
        or duration_penalty >= 0.22
        or (_looks_like_song_query(q) and query_score < 0.20)
    )
    reason_parts = []
    if unwanted_variant:
        reason_parts.append("unrequested_variant")
    if unwanted_video:
        reason_parts.append("unrequested_video")
    if duration_penalty:
        reason_parts.append("duration")
    if is_official_upload(track):
        reason_parts.append("official")
    if not reason_parts:
        reason_parts.append("match")

    return CandidateScore(
        total=total,
        query=query_score,
        spotify=spotify_score,
        duration=duration_score,
        official_bonus=official_bonus,
        penalty=penalty,
        severe_mismatch=severe,
        reason=",".join(reason_parts),
    )


def rank_tracks(
    query: str,
    candidates: Iterable,
    spotify_meta: dict | None = None,
) -> list[RankedCandidate]:
    ranked = [
        RankedCandidate(track=track, score=score_candidate(query, track, spotify_meta), index=index)
        for index, track in enumerate(candidates or [])
    ]
    ranked.sort(
        key=lambda item: (
            item.score.total,
            item.score.query,
            item.score.spotify,
            item.score.duration,
            -item.index,
        ),
        reverse=True,
    )
    return ranked


def select_best_track(
    query: str,
    candidates: Iterable,
    spotify_meta: dict | None = None,
):
    ranked = rank_tracks(query, candidates, spotify_meta)
    return ranked[0].track if ranked else None


def has_unrequested_extra_variant(query: str, candidate) -> bool:
    if not candidate:
        return False
    requested = _variant_tags(query or "")
    if not requested:
        return False
    title = getattr(candidate, "title", "") or ""
    candidate_tags = _variant_tags(title)
    return bool(candidate_tags - requested)


def needs_quality_fallback(query: str, candidate, spotify_meta: dict | None = None) -> bool:
    if not candidate:
        return False
    score = score_candidate(query, candidate, spotify_meta)
    if score.severe_mismatch:
        return True
    if has_unrequested_extra_variant(query, candidate):
        return True
    return bool((query or "").strip() and score.total < 0.34)


def needs_wider_search(query: str, candidate, spotify_meta: dict | None = None) -> bool:
    if not candidate:
        return False
    score = score_candidate(query, candidate, spotify_meta)
    if score.severe_mismatch:
        return True
    return _looks_like_song_query(query) and score.total < 0.38


def _looks_like_song_query(query: str) -> bool:
    q_norm = _normalize_for_sim(query)
    if not q_norm:
        return False
    words = q_norm.split()
    return 1 <= len(words) <= 8 and not _is_probably_non_music_query(query)


def _duration_shape_score(query: str, duration: int) -> float:
    if duration <= 0:
        return 0.45
    penalty = _duration_penalty(query, duration, None)
    return max(0.10, 0.62 - penalty)


def _duration_penalty(query: str, duration: int, spotify_meta: dict | None) -> float:
    if duration <= 0 or spotify_meta:
        return 0.0
    if not _looks_like_song_query(query):
        return 0.0
    if duration >= 900:
        return 0.35
    if duration >= 600:
        return 0.24
    if duration <= 35:
        return 0.12
    return 0.0
