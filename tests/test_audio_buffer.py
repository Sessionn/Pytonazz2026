"""
tests/test_audio_buffer.py

PrefetchedAudioSource prepara i pacchetti in un thread dedicato. Verifica:
- stessi pacchetti, stesso ordine, poi b"" a fine brano;
- un errore della sorgente arriva a read() dopo gli ultimi pacchetti buoni
  (discord.py lo passa ad after(err) e il player ritenta lo stream);
- i comandi live arrivano alla sorgente interna;
- cleanup() chiude la sorgente e ferma il thread anche se e' in attesa.

Esegui dalla root del progetto con:
    python tests/test_audio_buffer.py
"""

import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.music.audio_buffer import PrefetchedAudioSource  # noqa: E402


class Packets:
    def __init__(self, count, fail=False):
        self.items = [bytes([i]) * 3840 for i in range(count)]
        self.fail = fail
        self.calls = []
        self.cleaned = False

    def read(self):
        if self.items:
            return self.items.pop(0)
        if self.fail:
            raise RuntimeError("ffmpeg morto")
        return b""

    def is_opus(self):
        return False

    def set_volume(self, v):
        self.calls.append(("volume", v))

    def set_eq(self, **kw):
        self.calls.append(("eq", kw))

    def set_tone_filters(self, hp, lp):
        self.calls.append(("tone", hp, lp))

    def set_filter_preset(self, preset, immediate=False):
        self.calls.append(("preset", preset, immediate))

    def cleanup(self):
        self.cleaned = True


# Ordine e fine brano
inner = Packets(20)
src = PrefetchedAudioSource(inner, packets_ahead=4)
got = []
while data := src.read():
    got.append(data[0])
assert got == list(range(20)), got
assert src.read() == b""
assert not src.is_opus()

# Errore della sorgente: prima i pacchetti buoni, poi l'eccezione, poi b""
src = PrefetchedAudioSource(Packets(3, fail=True), packets_ahead=8)
assert [src.read()[0] for _ in range(3)] == [0, 1, 2]
try:
    src.read()
    raise AssertionError("l'errore della sorgente deve arrivare a read()")
except RuntimeError as exc:
    assert "ffmpeg" in str(exc)
assert src.read() == b""

# Comandi live delegati
inner = Packets(5)
src = PrefetchedAudioSource(inner)
src.set_volume(0.8)
src.set_eq(low=3.0, mid=0.0, high=-2.0)
src.set_tone_filters(80.0, 12000.0)
src.set_filter_preset({"playback_rate": 1.1}, immediate=True)
assert [c[0] for c in inner.calls] == ["volume", "eq", "tone", "preset"], inner.calls

# Il thread non va oltre packets_ahead pacchetti di anticipo
inner = Packets(50)
src = PrefetchedAudioSource(inner, packets_ahead=4)
src.read()
time.sleep(0.05)
assert len(src._queue) <= 4 and len(inner.items) >= 50 - 6, (len(src._queue), len(inner.items))

# cleanup con il thread fermo sulla coda piena
src.cleanup()
assert inner.cleaned
assert src._thread is not None and not src._thread.is_alive()


# cleanup con il thread bloccato dentro read() della sorgente (pipe FFmpeg)
class Blocking(Packets):
    def __init__(self):
        super().__init__(1)
        self.release = threading.Event()

    def read(self):
        if self.items:
            return self.items.pop(0)
        self.release.wait(5)
        return b""

    def cleanup(self):
        super().cleanup()
        self.release.set()  # come FFmpeg killato: la read() in corso ritorna


inner = Blocking()
src = PrefetchedAudioSource(inner)
assert src.read()
t0 = time.perf_counter()
src.cleanup()
assert time.perf_counter() - t0 < 1.0
assert not src._thread.is_alive()

print("OK: buffer pacchetti audio")
