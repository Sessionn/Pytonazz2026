"""
core/background.py
------------------
Avvio di task asyncio "fire and forget" in modo sicuro.

`asyncio.create_task()` restituisce un Task tenuto dall'event loop solo con un
riferimento debole: se nessuno lo conserva puo' essere raccolto dal garbage
collector a meta' esecuzione, e un'eccezione non letta finisce solo nel log
generico "Task exception was never retrieved". `spawn()` conserva il
riferimento finche' il task non termina e logga l'errore con il nome del task.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any

from core.log_colors import b, tag

log = logging.getLogger("pitonazz.background")

_TASKS: set[asyncio.Task] = set()


def _on_done(task: asyncio.Task) -> None:
    _TASKS.discard(task)
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        log.error(tag("TASK", f"background {b(task.get_name())} fallito: {exc}"), exc_info=exc)


def spawn(coro: Coroutine[Any, Any, Any], *, name: str | None = None) -> asyncio.Task:
    """Avvia `coro` in background mantenendone il riferimento fino al termine."""
    task = asyncio.create_task(coro, name=name)
    _TASKS.add(task)
    task.add_done_callback(_on_done)
    return task


def pending_count() -> int:
    """Numero di task in background ancora attivi (utile per diagnostica/test)."""
    return len(_TASKS)
