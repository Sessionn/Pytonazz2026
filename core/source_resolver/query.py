from __future__ import annotations

import re
from difflib import SequenceMatcher


_FEAT_PATTERN = re.compile(r"\b(featuring|feat\.?|ft\.?)\b", re.IGNORECASE)
_SPACES_PATTERN = re.compile(r"\s+")
_PUNCT_PATTERN = re.compile(r"[^\w\s]")


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
