from __future__ import annotations

from collections import deque


class AIRuntimeState:
    def __init__(self):
        self.rate_limit_map: dict[int, float] = {}
        self.conversation_memory: dict[int, deque] = {}

    def reset(self) -> None:
        self.rate_limit_map.clear()
        self.conversation_memory.clear()


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
