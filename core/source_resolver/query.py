from __future__ import annotations

import re
from difflib import SequenceMatcher


_FEAT_PATTERN = re.compile(r"\b(featuring|feat\.?|ft\.?)\b", re.IGNORECASE)
_SPACES_PATTERN = re.compile(r"\s+")
_PUNCT_PATTERN = re.compile(r"[^\w\s]")

_SCORE_PENALTY_KEYWORDS = re.compile(
    r"\b(cover|karaoke|tutorial|reaction|remix)\b",
    re.IGNORECASE,
)
_SCORE_LYRICS_KEYWORDS = re.compile(
    r"\b(lyrics?\s+video|lyric\s+video|lyrics?)\b",
    re.IGNORECASE,
)


def normalize_search_query(query: str) -> str:
    q = (query or "").strip()
    if not q:
        return ""
    q = _FEAT_PATTERN.sub(" feat ", q)
    q = _PUNCT_PATTERN.sub(" ", q)
    return _SPACES_PATTERN.sub(" ", q).strip()


def query_title_similarity(query: str, title: str, artist: str = "") -> float:
    q = normalize_search_query(query).lower()
    if not q:
        return 0.0
    t = normalize_search_query(title).lower()
    a = normalize_search_query(artist).lower()
    if not t and not a:
        return 0.0
    ta = f"{t} {a}".strip()
    token_q = set(q.split())
    token_t = set(ta.split())
    token_sim = (len(token_q & token_t) / len(token_q | token_t)) if token_q and token_t else 0.0
    seq_sim = SequenceMatcher(None, q, ta).ratio() if ta else 0.0
    return max(token_sim, seq_sim)


def score_candidate(query: str, track: object) -> float:
    """Score a search candidate in 0.0–1.0 range against the given query.

    Combines:
    - token overlap (50%): fraction of query words found in title+artist
    - substring boost (20%): +0.2 if normalised query is a substring of normalised title
    - SequenceMatcher (30%): ratio between query and "title artist"

    Applies:
    - penalty -0.15 if title contains cover/karaoke/tutorial/reaction/remix
      (unless the query also contains those words)
    - penalty -0.10 if title contains lyrics/lyric video
      (unless the query also contains those words)
    """
    q = normalize_search_query(query).lower()
    if not q:
        return 0.0

    title = normalize_search_query(getattr(track, "title", "") or "").lower()
    artist = normalize_search_query(getattr(track, "artist", "") or "").lower()

    if not title and not artist:
        return 0.0

    ta = f"{title} {artist}".strip()

    # Token overlap (50%): fraction of query tokens present in title+artist
    q_tokens = set(q.split())
    ta_tokens = set(ta.split())
    token_overlap = len(q_tokens & ta_tokens) / len(q_tokens) if q_tokens else 0.0

    # Substring boost (20%): normalised query contained in normalised title
    substring_boost = 0.2 if title and q in title else 0.0

    # SequenceMatcher similarity (30%)
    seq_sim = SequenceMatcher(None, q, ta).ratio() if ta else 0.0

    score = token_overlap * 0.5 + substring_boost + seq_sim * 0.3

    # Penalties applied on the raw (non-normalised) title
    raw_title = (getattr(track, "title", "") or "").lower()
    raw_query = (query or "").lower()
    if _SCORE_PENALTY_KEYWORDS.search(raw_title) and not _SCORE_PENALTY_KEYWORDS.search(raw_query):
        score -= 0.15
    if _SCORE_LYRICS_KEYWORDS.search(raw_title) and not _SCORE_LYRICS_KEYWORDS.search(raw_query):
        score -= 0.10

    return max(0.0, min(1.0, score))
