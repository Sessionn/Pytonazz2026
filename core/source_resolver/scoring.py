"""
core/source_resolver/scoring.py
--------------------------------
Pure scoring, normalisation, penalty and confidence-calculation helpers
used by SourceResolver.  No I/O, no Config dependency — only math and
text processing.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Protocol

# ── Regex patterns ────────────────────────────────────────────────────────────

_MV_KEYWORDS = re.compile(
    r"\b(official\s+video|music\s+video|video\s+ufficiale|videoclip|\bvevo\b|\bclip\b|\bmv\b|\blyrics?\s+video\b)",
    re.IGNORECASE,
)

_VARIANT_KEYWORDS = re.compile(
    r"\b(acoustic|live|unplugged|remix|cover|instrumental|karaoke"
    r"|remaster(?:ed)?|version|demo|stripped|session"
    r"|piano\s+version|orchestral)\b",
    re.IGNORECASE,
)

_NOISE_WORDS = re.compile(
    r"\b(official|audio|video|ufficiale|lyrics?|ft\.?|feat\.?|vs\.?|&|remix|remaster(?:ed)?|explicit|clean)\b",
    re.IGNORECASE,
)

_NON_MUSIC_QUERY_KEYWORDS = re.compile(
    # Includes "bannato" because this bot is used mainly in Italian communities.
    r"\b(meme|clip|shitpost|tiktok|reel|funny|bannato)\b",
    re.IGNORECASE,
)

_RISKY_ENRICH_VARIANTS = re.compile(
    r"\b(nightcore|sped\s+up|speed\s+up|slowed|reverb|bass\s+boosted|pizza\s+music|tik\s*tok|tiktok)\b",
    re.IGNORECASE,
)


class _TrackLike(Protocol):
    title: str
    artist: str
    duration: int

# ── Numeric constants ─────────────────────────────────────────────────────────

_ENRICH_CONFIDENCE_HIGH          = 0.72
_ENRICH_CONFIDENCE_MEDIUM        = 0.68
_ENRICH_CONFIDENCE_EXTREME_LOW   = 0.22
_ENRICH_DURATION_GOOD            = 0.62
_DURATION_DEFAULT_SCORE          = 0.45
_ARTIST_MISMATCH_THRESHOLD       = 0.12
_ENRICH_EXTREME_LOW_SIM_THRESHOLD = 0.18
_ENRICH_WEIGHT_QUERY             = 0.38
_ENRICH_WEIGHT_YT                = 0.37
_ENRICH_WEIGHT_DURATION          = 0.15
_ENRICH_WEIGHT_ARTIST_HINT       = 0.10
_NON_MUSIC_QUERY_MAX_WORDS       = 6
_SPOTIFY_RETRY_BASE_DELAY_SECONDS = 0.4
_ARTIST_TOKEN_MIN_LENGTH         = 3
_NON_MUSIC_QUERY_PENALTY         = 0.35
_RISKY_VARIANT_PENALTY           = 0.25
_JUNK_WORD_PENALTY               = 0.07   # penalty per junk extra-word in YT title
_MAX_JUNK_PENALTY                = 0.30   # cap so a very noisy title never over-penalises


# ── Text helpers ──────────────────────────────────────────────────────────────

def _is_music_video(title_str: str, uploader: str = "") -> bool:
    return bool(_MV_KEYWORDS.search(f"{title_str} {uploader}"))


def _is_variant(title_str: str) -> bool:
    return bool(_VARIANT_KEYWORDS.search(title_str))


def _query_requests_variant(query: str) -> bool:
    return bool(_VARIANT_KEYWORDS.search(query))


def _str_sim(a: str, b: str) -> float:
    """Character-by-character similarity (SequenceMatcher).
    Used for Spotify item similarity scoring.

    Returns a float between 0.0 and 1.0, where 1.0 means identical strings.
    """
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _normalize_for_sim(text: str) -> str:
    text = _NOISE_WORDS.sub(" ", text)
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def _jaccard_tokens(a: str, b: str) -> float:
    """Jaccard similarity on tokens (words).

    Compares sets of words, not character sequences.
    Resistant to false positives caused by randomly shared characters.

    Examples:
      "sei stato bannato" vs "se telefonando"   → 0.00
      "blinding lights"   vs "blinding lights"  → 1.00
      "se telefonando mina" vs "se telefonando" → 0.67
    """
    set_a = set(a.split())
    set_b = set(b.split())
    if not set_a and not set_b:
        return 1.0
    if not set_a or not set_b:
        return 0.0
    intersection = len(set_a & set_b)
    union        = len(set_a | set_b)
    return intersection / union


def _enrich_sim(query: str, sp_title: str, sp_artist: str) -> float:
    """Compute max Jaccard similarity for query vs title and query vs title+artist."""
    q_norm  = _normalize_for_sim(query)
    t_norm  = _normalize_for_sim(sp_title)
    ta_norm = _normalize_for_sim(f"{sp_title} {sp_artist}")
    return max(_jaccard_tokens(q_norm, t_norm), _jaccard_tokens(q_norm, ta_norm))


def _duration_similarity(yt_duration: int, sp_duration: int) -> float:
    """Score 0..1 for YT↔Spotify duration consistency.

    Returns a similarity score based on duration difference thresholds, where
    near-exact matches (≤2s) score 1.0 and large differences drop to 0.1.
    """
    if yt_duration <= 0 or sp_duration <= 0:
        # Default score when duration is unavailable/unreliable on either side.
        return _DURATION_DEFAULT_SCORE
    delta = abs(yt_duration - sp_duration)
    if delta <= 2:
        return 1.0
    if delta <= 5:
        return 0.92
    if delta <= 10:
        return 0.82
    if delta <= 20:
        return 0.68
    if delta <= 35:
        return 0.55
    ratio = delta / sp_duration
    if ratio <= 0.12:
        return 0.45
    if ratio <= 0.20:
        return 0.30
    return 0.10


def _contains_token(haystack: str, needle: str) -> bool:
    if not haystack or not needle:
        return False
    return f" {needle} " in f" {haystack} "


def _dynamic_variant_penalty(query: str, yt_title: str, sp_title: str, sp_artist: str) -> float:
    """Dynamic penalty via set-difference triangulation: query ↔ yt_title ↔ Spotify metadata.

    Logic:
      intent_words   = words(query)    − words(sp_title + sp_artist)
                       → version-specific words the user explicitly requested
                         (e.g. "slowed", "live", "cover")
      extra_yt_words = words(yt_title) − words(sp_title + sp_artist)
                       → words in the YT title absent from the official release
      junk_words     = extra_yt_words  − words(query)
                       → extra YT words the user did NOT ask for
                         (e.g. "karaoke", "8d", "instrumental" when not requested)

    Penalty scales linearly with junk_words count (capped at _MAX_JUNK_PENALTY).
    When all extra words match the user's intent, no penalty is applied.
    This eliminates the need for a hardcoded keyword blocklist.
    """
    q_norm  = _normalize_for_sim(query)
    yt_norm = _normalize_for_sim(yt_title)
    sp_norm = _normalize_for_sim(f"{sp_title} {sp_artist}")

    if not q_norm or not yt_norm:
        return 0.0

    q_words  = set(q_norm.split())
    yt_words = set(yt_norm.split())
    sp_words = set(sp_norm.split()) if sp_norm else set()

    # Words in the YT title that deviate from the official Spotify release
    extra_yt_words = yt_words - sp_words
    if not extra_yt_words:
        return 0.0

    # Junk: deviating words the user never asked for
    junk_words = extra_yt_words - q_words
    if not junk_words:
        return 0.0

    return min(len(junk_words) * _JUNK_WORD_PENALTY, _MAX_JUNK_PENALTY)


def _query_artist_signal(query: str, sp_artist: str) -> tuple[float, bool]:
    q_norm = _normalize_for_sim(query)
    a_norm = _normalize_for_sim(sp_artist)
    if not q_norm or not a_norm:
        return 0.0, False
    artist_tokens = [tok for tok in a_norm.split() if len(tok) >= _ARTIST_TOKEN_MIN_LENGTH]
    if not artist_tokens:
        return 0.0, False
    hinted = any(_contains_token(q_norm, tok) for tok in artist_tokens)
    if not hinted:
        return 0.0, False
    return _jaccard_tokens(q_norm, a_norm), True


def _is_probably_non_music_query(query: str) -> bool:
    q_norm = _normalize_for_sim(query)
    if not q_norm:
        return False
    # Long free-form sentences are usually requests/conversation, not song queries.
    if len(q_norm.split()) >= _NON_MUSIC_QUERY_MAX_WORDS:
        return True
    if _NON_MUSIC_QUERY_KEYWORDS.search(q_norm):
        return True
    return False


def _compute_enrich_confidence(
    original_query: str, yt_track: _TrackLike, sp_meta: dict
) -> dict:
    """Compute confidence and enrichment decision for a YT track vs Spotify metadata.

    yt_track follows the _TrackLike protocol: .title, .artist, .duration are accessed.

    Returns a dict with similarity scores, penalties, boolean flags, and the
    enrichment decision ("full", "cover_only", or "skip") plus its reason.
    """
    sp_title    = sp_meta.get("title", "")
    sp_artist   = sp_meta.get("artist", "")
    sp_duration = int(sp_meta.get("duration") or 0)
    yt_title    = getattr(yt_track, "title", "") or ""
    yt_artist   = getattr(yt_track, "artist", "") or ""
    yt_duration = int(getattr(yt_track, "duration", 0) or 0)

    query_title_sim = _enrich_sim(original_query, sp_title, "")
    query_full_sim  = _enrich_sim(original_query, sp_title, sp_artist)
    query_sim       = max(query_title_sim, query_full_sim)

    yt_title_sim = _jaccard_tokens(_normalize_for_sim(yt_title), _normalize_for_sim(sp_title))
    yt_full_sim  = _jaccard_tokens(
        _normalize_for_sim(f"{yt_title} {yt_artist}".strip()),
        _normalize_for_sim(f"{sp_title} {sp_artist}".strip()),
    )
    yt_sim = max(yt_title_sim, yt_full_sim)

    artist_sim, artist_hint_present = _query_artist_signal(original_query, sp_artist)
    duration_sim    = _duration_similarity(yt_duration, sp_duration)
    variant_penalty = _dynamic_variant_penalty(original_query, yt_title, sp_title, sp_artist)
    if _RISKY_ENRICH_VARIANTS.search(f"{original_query} {yt_title}"):
        variant_penalty += _RISKY_VARIANT_PENALTY
    non_music_penalty = _NON_MUSIC_QUERY_PENALTY if _is_probably_non_music_query(original_query) else 0.0

    confidence = (
        (query_sim * _ENRICH_WEIGHT_QUERY)
        + (yt_sim * _ENRICH_WEIGHT_YT)
        + (duration_sim * _ENRICH_WEIGHT_DURATION)
        + ((artist_sim * _ENRICH_WEIGHT_ARTIST_HINT) if artist_hint_present else 0.0)
        - variant_penalty
        - non_music_penalty
    )
    confidence = max(0.0, min(1.0, confidence))

    # Explicit artist signal in query, but Spotify artist does not match enough.
    artist_mismatch = artist_hint_present and artist_sim < _ARTIST_MISMATCH_THRESHOLD
    extreme_low = confidence < _ENRICH_CONFIDENCE_EXTREME_LOW or (
        confidence < _ENRICH_CONFIDENCE_MEDIUM
        and query_sim < _ENRICH_EXTREME_LOW_SIM_THRESHOLD
        and yt_sim < _ENRICH_EXTREME_LOW_SIM_THRESHOLD
    )
    duration_good = duration_sim >= _ENRICH_DURATION_GOOD

    if confidence >= _ENRICH_CONFIDENCE_HIGH and not artist_mismatch:
        decision = "full"
        reason   = "high_confidence"
    elif confidence >= _ENRICH_CONFIDENCE_MEDIUM and not artist_mismatch and duration_good:
        decision = "cover_only"
        reason   = "medium_confidence"
    else:
        decision = "skip"
        if artist_mismatch:
            reason = "artist_mismatch"
        elif extreme_low:
            reason = "extreme_low"
        else:
            reason = "low_confidence"

    return {
        "confidence":        confidence,
        "query_sim":         query_sim,
        "yt_sim":            yt_sim,
        "artist_sim":        artist_sim if artist_hint_present else 0.0,
        "artist_hint_present": artist_hint_present,
        "duration_sim":      duration_sim,
        "variant_penalty":   variant_penalty,
        "non_music_penalty": non_music_penalty,
        "artist_mismatch":   artist_mismatch,
        "duration_good":     duration_good,
        "extreme_low":       extreme_low,
        "decision":          decision,
        "reason":            reason,
    }
