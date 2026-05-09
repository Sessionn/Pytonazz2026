import random
from collections import deque
from typing import Optional

from config import Config


class MusicQueue:
    def __init__(self):
        self._queue:    deque = deque()
        self.history:   deque = deque(maxlen=50)
        self.loop_mode: str   = "off"   # off | track | queue
        self.shuffle_mode: bool = False

    def put(self, track) -> bool:
        """Aggiunge una traccia alla coda. Ritorna False se il limite MAX_QUEUE è stato raggiunto."""
        if len(self._queue) >= Config.MAX_QUEUE:
            return False
        self._queue.append(track)
        return True

    def put_many(self, tracks: list) -> int:
        """Aggiunge più tracce rispettando MAX_QUEUE. Ritorna il numero di tracce effettivamente aggiunte."""
        slots = Config.MAX_QUEUE - len(self._queue)
        if slots <= 0:
            return 0
        to_add = tracks[:slots]
        self._queue.extend(to_add)
        return len(to_add)

    def get(self) -> Optional[object]:
        return self._queue.popleft() if self._queue else None

    def peek(self) -> Optional[object]:
        """Ritorna la prossima traccia senza rimuoverla."""
        return self._queue[0] if self._queue else None

    def prepend(self, track) -> None:
        """Inserisce una traccia in testa alla coda (usato da /prev)."""
        self._queue.appendleft(track)

    def add_history(self, track) -> None:
        self.history.append(track)

    def clear(self) -> None:
        """Svuota solo le tracce in coda.
        Non tocca loop_mode né shuffle_mode: usare reset() per quello.
        Chiamato da /clearqueue, dove l'utente vuole pulire la coda
        ma mantenere le impostazioni di riproduzione attive.
        """
        self._queue.clear()

    def reset(self) -> None:
        """Svuota la coda E resetta loop_mode e shuffle_mode.
        Da usare solo in stop() o disconnect(), quando la sessione
        di riproduzione termina completamente.
        """
        self._queue.clear()
        self.loop_mode    = "off"
        self.shuffle_mode = False

    def remove(self, index: int) -> Optional[object]:
        if 0 <= index < len(self._queue):
            item = self._queue[index]
            del self._queue[index]
            return item
        return None

    def move(self, from_idx: int, to_idx: int) -> Optional[object]:
        n = len(self._queue)
        if not (0 <= from_idx < n and 0 <= to_idx < n) or from_idx == to_idx:
            return None
        lst = list(self._queue)
        track = lst.pop(from_idx)
        lst.insert(to_idx, track)
        self._queue = deque(lst)
        return track

    def skipto(self, index: int) -> int:
        """Salta alla traccia all'indice dato, aggiungendo le tracce saltate alla history."""
        n = len(self._queue)
        if not (0 <= index < n):
            return 0
        for _ in range(index):
            skipped = self._queue.popleft()
            self.history.append(skipped)
        return index

    def shuffle(self) -> None:
        lst = list(self._queue)
        random.shuffle(lst)
        self._queue = deque(lst)

    def spotify_shuffle(self) -> None:
        from core.source_resolver import spotify_style_shuffle
        shuffled    = spotify_style_shuffle(list(self._queue))
        self._queue = deque(shuffled)

    @property
    def items(self) -> list:
        return list(self._queue)

    def __len__(self) -> int:
        return len(self._queue)

    def __bool__(self) -> bool:
        return bool(self._queue)
