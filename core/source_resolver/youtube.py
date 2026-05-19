from __future__ import annotations

import re

from core.source_resolver.query import query_title_similarity


_YT_CHANNEL = re.compile(
    r"(?:https?://)?(?:www\.)?youtube\.com/"
    r"(?:channel/UC[A-Za-z0-9_-]+|c/[^/?#]+|user/[^/?#]+|@[^/?#]+)"
    r"(?:[/?#].*)?$"
)


def is_yt_channel_url(url: str) -> bool:
    return bool(_YT_CHANNEL.match((url or "").strip()))


def rank_search_results_by_query(results: list, query: str) -> list:
    if not results:
        return results
    key = lambda t: query_title_similarity(
        query,
        getattr(t, "title", "") or "",
        getattr(t, "artist", "") or "",
    )
    return sorted(results, key=key, reverse=True)
