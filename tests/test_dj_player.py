from __future__ import annotations

import asyncio
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.player import MusicPlayer


player = MusicPlayer(SimpleNamespace(id=1, voice_client=None), None)
assert player.set_volume(0.8) is True
assert abs(player.volume - 0.8) < 1e-6

assert player.set_volume(5.0) is True
assert player.volume == 1.0

asyncio.run(player.set_eq({"low": 14, "mid": -3.5, "high": "2"}))
assert player.eq["low"] == 12.0
assert player.eq["mid"] == -3.5
assert player.eq["high"] == 2.0

asyncio.run(player.set_filter("bassboost"))
assert player.filter_name == "bassboost"

state = player.to_public_state()
assert state["volume"] == 1.0
assert state["eq"]["low"] == 12.0
assert state["filter_name"] == "bassboost"

print("OK: dj player volume/eq/filter state")
