"""
Buffer di pacchetti audio tra la catena FFmpeg -> LivePCMTransform e il
thread di invio di discord.py.

Il thread audio di discord.py deve consegnare un pacchetto ogni 20 ms. Se
read() fa lavoro vero (pipe FFmpeg, DSP con numpy/scipy) rilascia il GIL e,
quando un altro thread Python e' occupato (yt-dlp che prepara il prossimo
brano, la dashboard, ...), lo riprende solo dopo uno o piu' switch interval:
il pacchetto parte in ritardo e si sente un micro-scatto.

PrefetchedAudioSource prepara i pacchetti in anticipo in un thread dedicato:
read() si limita a prendere il prossimo dalla coda. Il ritardo introdotto
sui comandi live (volume, EQ, filtri) e' quello della coda: 8 pacchetti =
160 ms, impercettibile perche' quei parametri cambiano gia' con una rampa.
"""
from __future__ import annotations

import threading
from collections import deque

import discord

DEFAULT_PACKETS_AHEAD = 8
_JOIN_TIMEOUT_SECONDS = 1.0


class PrefetchedAudioSource(discord.AudioSource):
    def __init__(self, inner: discord.AudioSource, packets_ahead: int = DEFAULT_PACKETS_AHEAD):
        self.inner = inner
        self._packets_ahead = max(1, int(packets_ahead))
        self._queue: deque[bytes] = deque()
        self._cond = threading.Condition()
        self._done = False
        self._closed = False
        self._error: Exception | None = None
        self._thread: threading.Thread | None = None

    # ── Comandi live: passano alla sorgente interna ──────────────────────────
    def set_volume(self, volume: float) -> None:
        self.inner.set_volume(volume)

    def set_eq(self, *args, **kwargs) -> None:
        self.inner.set_eq(*args, **kwargs)

    def set_tone_filters(self, *args, **kwargs) -> None:
        self.inner.set_tone_filters(*args, **kwargs)

    def set_filter_preset(self, *args, **kwargs) -> None:
        self.inner.set_filter_preset(*args, **kwargs)

    # ── AudioSource ──────────────────────────────────────────────────────────
    def is_opus(self) -> bool:
        return self.inner.is_opus()

    def _start(self) -> None:
        self._thread = threading.Thread(target=self._fill, name="audio-prefetch", daemon=True)
        self._thread.start()

    def _fill(self) -> None:
        try:
            while True:
                with self._cond:
                    self._cond.wait_for(lambda: self._closed or len(self._queue) < self._packets_ahead)
                    if self._closed:
                        return
                data = self.inner.read()
                with self._cond:
                    if not data:
                        self._done = True
                        self._cond.notify_all()
                        return
                    self._queue.append(data)
                    self._cond.notify_all()
        except Exception as exc:
            # Errore della sorgente (FFmpeg, ...): read() lo rilancia dopo gli
            # ultimi pacchetti, cosi' discord.py lo passa ad after(err) come prima.
            with self._cond:
                self._error = exc
                self._done = True
                self._cond.notify_all()

    def read(self) -> bytes:
        if self._thread is None:
            self._start()
        with self._cond:
            # Come FFmpegPCMAudio: si aspetta il prossimo pacchetto, non si
            # inventa silenzio (all'avvio FFmpeg puo' metterci qualche centinaio di ms).
            self._cond.wait_for(lambda: self._queue or self._done or self._closed)
            if self._queue:
                data = self._queue.popleft()
                self._cond.notify_all()
                return data
            if self._error is not None and not self._closed:
                error, self._error = self._error, None
                raise error
            return b""

    def cleanup(self) -> None:
        with self._cond:
            self._closed = True
            self._cond.notify_all()
        cleanup = getattr(self.inner, "cleanup", None)
        if callable(cleanup):
            cleanup()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(_JOIN_TIMEOUT_SECONDS)
