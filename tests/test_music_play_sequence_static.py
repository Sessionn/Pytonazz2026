"""
tests/test_music_play_sequence_static.py

Esegui dalla root del progetto con:
    python tests/test_music_play_sequence_static.py
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
music_py = (ROOT / "cogs" / "music.py").read_text(encoding="utf-8")

assert "self._play_next_ticket:" in music_py, (
    "FAIL: il cog musica deve prenotare ticket per guild per ordinare /play simultanei"
)
assert "def _reserve_play_turn(self, guild_id: int) -> int:" in music_py, (
    "FAIL: manca helper _reserve_play_turn(guild_id) per prenotare l'ordine di arrivo"
)
assert "await self._wait_play_turn(inter.guild_id, ticket)" in music_py, (
    "FAIL: /play deve risolvere in parallelo ma attendere il proprio turno prima dell'enqueue"
)
assert "async with self._play_lock" not in music_py, (
    "FAIL: /play non deve bloccare l'intera risoluzione dietro un lock completo"
)

print("OK: /play direct usa prenotazione slot per guild")
