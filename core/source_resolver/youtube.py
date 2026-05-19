from __future__ import annotations

import re

from core.source_resolver.query import score_candidate


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
    return sorted(results, key=lambda t: score_candidate(query, t), reverse=True)
