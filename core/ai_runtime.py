from __future__ import annotations

from collections import deque


class AIRuntimeState:
    def __init__(self):
        self.rate_limit_map: dict[int, float] = {}
        self.conversation_memory: dict[int, deque] = {}
        self.channel_recent_messages: dict[int, deque] = {}
        self.mention_background_cache: dict[tuple[int, int], tuple[float, str]] = {}
        self.web_retry_metrics: dict[str, int] = {
            "attempts": 0,
            "success": 0,
            "explicit_ctx": 0,
            "auto_ctx": 0,
            "no_ctx": 0,
        }

    def reset(self) -> None:
        self.rate_limit_map.clear()
        self.conversation_memory.clear()
        self.channel_recent_messages.clear()
        self.mention_background_cache.clear()
        for key in self.web_retry_metrics:
            self.web_retry_metrics[key] = 0


# Singleton condivisa tra cog AI e comandi dev.
# Evita import diretti cogs→cogs e mantiene lo stato runtime centralizzato.
_state = AIRuntimeState()


def clear_conversation_memory(channel_id: int | None = None) -> int:
    if channel_id is None:
        count = len(_state.conversation_memory)
        _state.conversation_memory.clear()
        return count
    _state.conversation_memory.pop(channel_id, None)
    return 1
