"""Process-local music state shared across cog reloads, owned by the bot."""
import asyncio
from dataclasses import dataclass, field


@dataclass
class MusicSession:
    players: dict = field(default_factory=dict)
    empty_ch_tasks: dict = field(default_factory=dict)
    batch_cancel: dict = field(default_factory=dict)
    play_debounce: dict = field(default_factory=dict)
    play_next_ticket: dict = field(default_factory=dict)
    play_commit_ticket: dict = field(default_factory=dict)
    play_turn_conditions: dict = field(default_factory=dict)
    warmup_sem: asyncio.Semaphore = field(default_factory=lambda: asyncio.Semaphore(3))


def music_session(bot) -> MusicSession:
    state = getattr(bot, '_pytonazz_music_session', None)
    if state is None:
        state = MusicSession()
        bot._pytonazz_music_session = state
    return state
