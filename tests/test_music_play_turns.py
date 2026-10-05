"""
tests/test_music_play_turns.py

Verifica runtime dell'ordinamento /play per guild: piu' richieste concorrenti
devono essere servite tutte, nell'ordine di prenotazione, senza deadlock.

Esegui dalla root del progetto con:
    python tests/test_music_play_turns.py
"""

import asyncio
import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cogs.music import Music


def _bare_cog() -> Music:
    cog = Music.__new__(Music)
    cog._play_next_ticket = {}
    cog._play_commit_ticket = {}
    cog._play_turn_conditions = {}
    return cog


async def _run_concurrent(count: int) -> list[int]:
    cog = _bare_cog()
    order: list[int] = []

    async def worker(ticket: int) -> None:
        await cog._wait_play_turn(1, ticket)
        order.append(ticket)
        await asyncio.sleep(0.005)
        await cog._finish_play_turn(1)

    tickets = [cog._reserve_play_turn(1) for _ in range(count)]
    # Avvio in ordine inverso: i ticket alti entrano in wait() per primi.
    await asyncio.wait_for(asyncio.gather(*(worker(t) for t in reversed(tickets))), 3)
    assert not cog._play_turn_conditions, "FAIL: stato turni non liberato a fine coda"
    assert not cog._play_next_ticket and not cog._play_commit_ticket
    return order


order = asyncio.run(_run_concurrent(6))
assert order == [1, 2, 3, 4, 5, 6], f"FAIL: ordine turni errato {order}"


async def _run_waves() -> None:
    # Una seconda ondata dopo lo svuotamento deve ripartire da ticket 1.
    for _ in range(2):
        cog_order = await _run_concurrent(3)
        assert cog_order == [1, 2, 3]


asyncio.run(_run_waves())

artist_src = inspect.getsource(Music.artistshuffle.callback)
assert "ticket=ticket" in artist_src, "FAIL: /artistshuffle deve passare il ticket a _start_batch_stream"

print("OK: /play turni concorrenti senza deadlock")
