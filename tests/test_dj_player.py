from __future__ import annotations

import asyncio
import os
import sys
from array import array
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.music.live_fx import LivePCMTransform
from core.music.player import MusicPlayer


player = MusicPlayer(SimpleNamespace(id=1, voice_client=None), None)
assert player.set_volume(0.8) is True
assert abs(player.volume - 0.8) < 1e-6

assert player.set_volume(5.0) is True
assert player.volume == 1.0

asyncio.run(player.set_eq({"low": 14, "mid": -3.5, "high": "2"}))
assert player.eq["low"] == 12.0
assert player.eq["mid"] == -3.5
assert player.eq["high"] == 2.0

asyncio.run(player.set_tone_filters({"highpass_hz": 85, "lowpass_hz": 14500}))
assert player.tone_filters["highpass_hz"] == 85.0
assert player.tone_filters["lowpass_hz"] == 14500.0

asyncio.run(player.set_filter("bassboost"))
assert player.filter_name == "bassboost"

state = player.to_public_state()
assert state["volume"] == 1.0
assert state["eq"]["low"] == 12.0
assert state["tone_filters"]["highpass_hz"] == 85.0
assert state["filter_name"] == "bassboost"


class DummySource:
    def __init__(self, payload: bytes):
        self.payload = payload
        self.done = False

    def read(self):
        if self.done:
            return b""
        self.done = True
        return self.payload

    def is_opus(self):
        return False


pcm = array("h", [2000, -2000] * 960).tobytes()
live = LivePCMTransform(DummySource(pcm), volume=0.5)
live.set_eq(low=6.0, mid=-2.5, high=4.0)
live.set_tone_filters(highpass_hz=120.0, lowpass_hz=12000.0)
for _ in range(4):
    processed = live.read()
    if processed:
        break
assert processed and processed != pcm
samples = array("h")
samples.frombytes(processed)
assert max(abs(value) for value in samples) < 2000

pcm2 = array("h", [3000, -3000] * 960).tobytes()
live_bypass = LivePCMTransform(DummySource(pcm2), volume=1.0)
live_bypass.set_tone_filters(highpass_hz=0.0, lowpass_hz=1500.0)
_ = live_bypass.read()
live_bypass.source = DummySource(pcm2)
live_bypass.set_tone_filters(highpass_hz=0.0, lowpass_hz=20000.0)
released = live_bypass.read()
assert released and released != b""

pcm3 = array("h", [1600, 1600, -1600, -1600] * 480).tobytes()
live_eq = LivePCMTransform(DummySource(pcm3), volume=1.0)
live_eq.set_eq(low=8.0, mid=0.0, high=-6.0)
eq_processed = live_eq.read()
assert eq_processed and eq_processed != pcm3

print("OK: dj player volume/eq/filter state")
