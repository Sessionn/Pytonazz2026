"""
tests/test_live_fx_vectorized.py

LivePCMTransform elabora l'audio a blocchi (numpy + scipy). Verifica che:
- il biquad a blocchi coincida con la forma diretta II trasposta campione
  per campione, anche con lo stato portato tra un blocco e l'altro;
- senza effetti a volume 1.0 l'audio esca identico all'ingresso;
- volume, playback rate, pan e riverbero si comportino come prima;
- un read() con il preset piu' pesante resti ampiamente nei 20 ms di un
  pacchetto Discord (il vecchio ciclo Python ne impiegava ~14 da solo).

Esegui dalla root del progetto con:
    python tests/test_live_fx_vectorized.py
"""

import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402

from core.music.live_fx import LivePCMTransform, _Biquad  # noqa: E402

rng = np.random.default_rng(7)
CHUNK_FRAMES = 960


def make_chunks(count: int, amplitude: int = 9000) -> list[bytes]:
    t = np.arange(count * CHUNK_FRAMES)
    left = amplitude * np.sin(t / 9.0) + rng.normal(0, 600, t.size)
    right = amplitude * np.sin(t / 13.0) + rng.normal(0, 600, t.size)
    pcm = np.clip(np.column_stack((left, right)), -32768, 32767).astype(np.int16)
    return [pcm[i * CHUNK_FRAMES:(i + 1) * CHUNK_FRAMES].tobytes() for i in range(count)]


class ListSource:
    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.reads = 0

    def read(self):
        self.reads += 1
        return self.chunks.pop(0) if self.chunks else b""


def as_frames(data: bytes) -> np.ndarray:
    return np.frombuffer(data, dtype=np.int16).reshape(-1, 2)


# ── Biquad: blocchi == campione per campione ─────────────────────────────────
def reference_biquad(flt: _Biquad, block: np.ndarray, state: list[list[float]]) -> np.ndarray:
    out = np.empty_like(block)
    for ch in range(2):
        z1, z2 = state[ch]
        for i, x in enumerate(block[:, ch]):
            y = x * flt.b0 + z1
            z1 = x * flt.b1 + z2 - flt.a1 * y
            z2 = x * flt.b2 - flt.a2 * y
            out[i, ch] = y
        state[ch] = [z1, z2]
    return out


for kind, kwargs in (
    ("lowpass", {"cutoff_hz": 1500.0}),
    ("highpass", {"cutoff_hz": 120.0}),
    ("peaking", {"cutoff_hz": 1000.0, "gain_db": -4.0, "q": 0.95}),
    ("low_shelf", {"cutoff_hz": 120.0, "gain_db": 6.0}),
    ("high_shelf", {"cutoff_hz": 8000.0, "gain_db": 3.0}),
):
    flt = _Biquad()
    flt.configure(kind, **kwargs)
    assert flt.enabled, kind
    ref_state = [[0.0, 0.0], [0.0, 0.0]]
    for _ in range(3):
        block = rng.normal(0, 5000, (CHUNK_FRAMES, 2))
        expected = reference_biquad(flt, block, ref_state)
        got = flt.process(block)
        assert np.allclose(got, expected, atol=1e-6), kind
    assert np.allclose(flt.state, np.array(ref_state).T, atol=1e-6), kind

disabled = _Biquad()
disabled.configure("peaking", 1000.0, gain_db=0.0)
block = rng.normal(0, 100, (10, 2))
assert disabled.process(block) is block

# ── Bypass e volume ──────────────────────────────────────────────────────────
chunks = make_chunks(4)
bypass = LivePCMTransform(ListSource(chunks), volume=1.0)
for chunk in chunks[:3]:
    assert bypass.read() == chunk

chunks = make_chunks(3)
half = LivePCMTransform(ListSource(chunks), volume=0.5)
out = as_frames(half.read())
expected = np.rint(as_frames(chunks[0]) * 0.5)
assert np.abs(out - expected).max() <= 1, np.abs(out - expected).max()

# ── Fine sorgente: niente pacchetti parziali, poi b"" ────────────────────────
ending = LivePCMTransform(ListSource(make_chunks(2)), volume=1.0)
outputs = [ending.read() for _ in range(4)]
assert all(len(o) == CHUNK_FRAMES * 4 for o in outputs[:1])
assert outputs[-1] == b""

# ── Playback rate: piu' veloce = consuma piu' sorgente, stessa lunghezza ────
normal_src = ListSource(make_chunks(40))
fast_src = ListSource(make_chunks(40))
normal = LivePCMTransform(normal_src, volume=1.0)
fast = LivePCMTransform(fast_src, volume=1.0)
fast.set_filter_preset({"playback_rate": 1.25}, immediate=True)
for _ in range(20):
    assert len(normal.read()) == CHUNK_FRAMES * 4
    assert len(fast.read()) == CHUNK_FRAMES * 4
assert fast_src.reads > normal_src.reads + 3, (fast_src.reads, normal_src.reads)

# ── Pan 8D: sposta energia tra i canali e la fase avanza nel tempo ──────────
mono = np.full((CHUNK_FRAMES * 30, 2), 8000, dtype=np.int16)
pan = LivePCMTransform(ListSource([mono[i:i + CHUNK_FRAMES].tobytes() for i in range(0, len(mono), CHUNK_FRAMES)]), volume=1.0)
pan.set_filter_preset({"pan_rate_hz": 2.0, "pan_depth": 1.0}, immediate=True)
balances = []
for _ in range(25):
    frames = as_frames(pan.read()).astype(np.float64)
    balances.append(float(np.mean(frames[:, 0] - frames[:, 1])))
assert max(balances) > 1000 and min(balances) < -1000, (max(balances), min(balances))
assert 0.0 <= pan._pan_phase < 2.0 * math.pi

# ── Riverbero: coda udibile dopo un impulso ──────────────────────────────────
impulse = np.zeros((CHUNK_FRAMES * 12, 2), dtype=np.int16)
impulse[:CHUNK_FRAMES] = 12000
verb = LivePCMTransform(ListSource([impulse[i:i + CHUNK_FRAMES].tobytes() for i in range(0, len(impulse), CHUNK_FRAMES)]), volume=1.0)
verb.set_filter_preset({"reverb_mix": 0.4, "reverb_decay": 0.6}, immediate=True)
tail = [np.abs(as_frames(verb.read())).max() for _ in range(10)]
assert tail[0] > 0 and max(tail[6:9]) > 0, tail

# ── Budget di tempo: preset pesante ben sotto i 20 ms ────────────────────────
heavy = LivePCMTransform(ListSource(make_chunks(400)), volume=0.7)
heavy.set_eq(low=4, mid=-2, high=3)
heavy.set_tone_filters(80, 16000)
heavy.set_filter_preset({
    "low_gain": 5, "mid_gain": -1, "high_gain": 2, "presence_gain": 2,
    "highpass_hz": 60, "lowpass_hz": 12000,
    "pan_rate_hz": 0.3, "pan_depth": 0.6,
    "reverb_mix": 0.3, "reverb_decay": 0.5, "playback_rate": 1.12,
}, immediate=True)
for _ in range(10):
    heavy.read()
timings = []
for _ in range(200):
    t0 = time.perf_counter()
    assert heavy.read()
    timings.append((time.perf_counter() - t0) * 1000)
timings.sort()
p95 = timings[int(len(timings) * 0.95)]
assert p95 < 5.0, f"read() troppo lento: p95={p95:.2f}ms"

print(f"OK: live fx a blocchi (preset pesante p95={p95:.2f}ms)")
