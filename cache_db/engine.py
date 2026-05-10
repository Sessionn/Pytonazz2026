"""
cache_db/engine.py

Motore SQLite per la cache persistente delle query musicali.
Zero dipendenze esterne: sqlite3 e' stdlib Python.

Schema:
  song_cache   — una riga per coppia (canonical_key, variant_tag)
  query_alias  — alias alternativi che puntano a un canonical_key

Lookup in 5 step (dal piu' economico al piu' costoso):
  1. Exact hit   su song_cache  (O log n, ~0.1 ms)
  2. Alias hit   su query_alias (O log n, ~0.1 ms)
  3. Spotify URL hit            (O log n, ~0.1 ms)
  4. webpage_url hit            (O log n, ~0.1 ms)
  5. Fuzzy scan  top-300 per hit_count, soglia jaccard >= 0.82
"""

from __future__ import annotations

import logging
import os
import re
import sqlite3
import threading
import unicodedata
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from core.source_resolver import TrackInfo

log = logging.getLogger("pitonazz.cache_db")

# ---------------------------------------------------------------------------
# Costanti
# ---------------------------------------------------------------------------
_FUZZY_TOP_N       = 300    # quante righe consideriamo nel fuzzy scan
_FUZZY_THRESHOLD   = 0.82   # soglia jaccard minima per accettare un match
_FUZZY_STR_WEIGHT  = 0.35   # peso _str_sim nella combinazione con jaccard
_TTL_DAYS_DEFAULT  = 30     # giorni prima che un URL venga considerato stale
_MAX_ENTRIES       = 10_000 # limite soft: oltre questa soglia si fa pruning LRU

# Parole/varianti che distinguono versioni diverse della stessa canzone.
# Importate da scoring.py a runtime per non creare dipendenza circolare al
# momento dell'import del package.
_VARIANT_KW_CACHE: Optional[set] = None


def _get_variant_keywords() -> set:
    global _VARIANT_KW_CACHE
    if _VARIANT_KW_CACHE is None:
        try:
            from core.source_resolver.scoring import _VARIANT_KEYWORDS
            _VARIANT_KW_CACHE = set(_VARIANT_KEYWORDS)
        except Exception:
            _VARIANT_KW_CACHE = {
                "speed up", "spedup", "sped up", "nightcore", "slowed",
                "reverb", "live", "acoustic", "cover", "remix", "instrumental",
                "karaoke", "extended", "radio edit", "official video",
                "music video", "lyric video", "lyrics",
            }
    return _VARIANT_KW_CACHE


# ---------------------------------------------------------------------------
# Normalizzazione
# ---------------------------------------------------------------------------
_RE_PUNCT  = re.compile(r"[^\w\s]", re.UNICODE)
_RE_SPACES = re.compile(r"\s+")
_NOISE_WORDS = frozenset([
    "il", "lo", "la", "i", "gli", "le", "un", "una", "uno",
    "di", "da", "in", "con", "su", "per", "tra", "fra",
    "the", "a", "an", "of", "in", "on", "at", "to", "by", "ft", "feat",
])


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def normalize(query: str) -> tuple[str, str]:
    """Restituisce (canonical_key, variant_tag) dalla query grezza.

    - canonical_key: query normalizzata senza variant keywords, senza
      punteggiatura, senza noise words, token ordinati alfabeticamente
      per rendere 'max gazze una musica puo fare' == 'una musica puo fare max gazze'
    - variant_tag:   stringa vuota per la versione studio, altrimenti
      la prima keyword variante trovata (es. 'speed up', 'live', 'cover')
    """
    raw = _nfc((query or "").strip().lower())
    variant_kw = _get_variant_keywords()

    # Individua e rimuovi variant keyword (piu' lunghe prima)
    found_variant = ""
    for kw in sorted(variant_kw, key=len, reverse=True):
        if kw in raw:
            if not found_variant:
                found_variant = kw
            raw = raw.replace(kw, " ")

    # Rimuovi punteggiatura e normalizza spazi
    raw = _RE_PUNCT.sub(" ", raw)
    raw = _RE_SPACES.sub(" ", raw).strip()

    # Tokenizza, rimuovi noise words, ordina (rende query bag-of-words)
    tokens = [t for t in raw.split() if t and t not in _NOISE_WORDS]
    canonical = " ".join(sorted(tokens))

    return canonical, found_variant


# ---------------------------------------------------------------------------
# Similarity helpers (riusa scoring.py se disponibile, fallback inline)
# ---------------------------------------------------------------------------

def _jaccard(a: str, b: str) -> float:
    try:
        from core.source_resolver.scoring import _jaccard_tokens, _normalize_for_sim
        return _jaccard_tokens(_normalize_for_sim(a), _normalize_for_sim(b))
    except Exception:
        sa = set((a or "").lower().split())
        sb = set((b or "").lower().split())
        if not sa and not sb:
            return 1.0
        inter = len(sa & sb)
        union = len(sa | sb)
        return inter / union if union else 0.0


def _str_sim(a: str, b: str) -> float:
    try:
        from core.source_resolver.scoring import _str_sim as _ss, _normalize_for_sim
        return _ss(_normalize_for_sim(a), _normalize_for_sim(b))
    except Exception:
        if not a and not b:
            return 1.0
        if not a or not b:
            return 0.0
        longer = max(len(a), len(b))
        matches = sum(x == y for x, y in zip(a.lower(), b.lower()))
        return matches / longer


def _combined_sim(a: str, b: str) -> float:
    j = _jaccard(a, b)
    s = _str_sim(a, b)
    return j * (1 - _FUZZY_STR_WEIGHT) + s * _FUZZY_STR_WEIGHT


# ---------------------------------------------------------------------------
# QueryCache
# ---------------------------------------------------------------------------

class QueryCache:
    """Cache persistente SQLite per le query musicali.

    Thread-safe: usa un lock + una connessione per thread (check_same_thread=False).
    La cache puo' essere abilitata/disabilitata a runtime tramite il toggle
    `enabled` senza riavviare il bot.
    """

    def __init__(self, db_path: str, enabled: bool = True) -> None:
        self.db_path = db_path
        self.enabled = enabled
        self._lock = threading.Lock()
        self._local = threading.local()
        if enabled:
            self._init_db()
            log.info(f"[CACHE] avviata  db={db_path}")
        else:
            log.info("[CACHE] disabilitata (QUERY_CACHE_ENABLED non impostato)")

    # ------------------------------------------------------------------
    # DB init
    # ------------------------------------------------------------------

    def _conn(self) -> sqlite3.Connection:
        """Connessione per-thread, lazy init."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA foreign_keys=ON")
            self._local.conn = conn
        return self._local.conn

    def _init_db(self) -> None:
        with self._lock:
            conn = self._conn()
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS song_cache (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    canonical_key TEXT    NOT NULL,
                    variant_tag   TEXT    NOT NULL DEFAULT '',
                    webpage_url   TEXT    NOT NULL,
                    title         TEXT    NOT NULL DEFAULT '',
                    artist        TEXT    NOT NULL DEFAULT '',
                    duration      INTEGER NOT NULL DEFAULT 0,
                    thumbnail     TEXT    NOT NULL DEFAULT '',
                    spotify_url   TEXT    NOT NULL DEFAULT '',
                    source        TEXT    NOT NULL DEFAULT 'youtube',
                    hit_count     INTEGER NOT NULL DEFAULT 1,
                    last_hit      TEXT    NOT NULL DEFAULT (datetime('now')),
                    created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
                    confidence    REAL    NOT NULL DEFAULT 1.0,
                    UNIQUE(canonical_key, variant_tag)
                );

                CREATE TABLE IF NOT EXISTS query_alias (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    alias_key     TEXT    NOT NULL UNIQUE,
                    canonical_key TEXT    NOT NULL,
                    variant_tag   TEXT    NOT NULL DEFAULT ''
                );

                CREATE INDEX IF NOT EXISTS idx_sc_canonical
                    ON song_cache(canonical_key, variant_tag);
                CREATE INDEX IF NOT EXISTS idx_sc_spotify
                    ON song_cache(spotify_url)
                    WHERE spotify_url != '';
                CREATE INDEX IF NOT EXISTS idx_sc_webpage
                    ON song_cache(webpage_url);
                CREATE INDEX IF NOT EXISTS idx_sc_hits
                    ON song_cache(hit_count DESC);
                CREATE INDEX IF NOT EXISTS idx_alias_key
                    ON query_alias(alias_key);
            """)
            conn.commit()

    # ------------------------------------------------------------------
    # Lookup — 5 step
    # ------------------------------------------------------------------

    def lookup(self, query: str) -> Optional[dict]:
        """Cerca una corrispondenza per `query`.

        Restituisce un dict con i campi di song_cache se trovato,
        None altrimenti. Aggiorna hit_count e last_hit automaticamente.
        """
        if not self.enabled:
            return None
        try:
            return self._lookup_inner(query)
        except Exception as e:
            log.debug(f"[CACHE] lookup error: {e}")
            return None

    def _lookup_inner(self, query: str) -> Optional[dict]:
        canonical, variant = normalize(query)
        conn = self._conn()

        # Step 1 — exact hit
        row = conn.execute(
            "SELECT * FROM song_cache WHERE canonical_key=? AND variant_tag=?",
            (canonical, variant),
        ).fetchone()
        if row:
            self._bump(conn, row["id"])
            return dict(row)

        # Step 2 — alias hit
        alias_row = conn.execute(
            "SELECT canonical_key, variant_tag FROM query_alias WHERE alias_key=?",
            (canonical,),
        ).fetchone()
        if alias_row:
            row = conn.execute(
                "SELECT * FROM song_cache WHERE canonical_key=? AND variant_tag=?",
                (alias_row["canonical_key"], alias_row["variant_tag"]),
            ).fetchone()
            if row:
                self._bump(conn, row["id"])
                return dict(row)

        # Step 3 — Spotify URL hit (se la query sembra un link Spotify)
        q_strip = query.strip()
        if "spotify" in q_strip.lower():
            row = conn.execute(
                "SELECT * FROM song_cache WHERE spotify_url=?",
                (q_strip,),
            ).fetchone()
            if row:
                self._bump(conn, row["id"])
                return dict(row)

        # Step 4 — webpage_url hit (se la query e' un link YouTube diretto)
        if "youtube.com/watch" in q_strip or "youtu.be/" in q_strip:
            row = conn.execute(
                "SELECT * FROM song_cache WHERE webpage_url=?",
                (q_strip,),
            ).fetchone()
            if row:
                self._bump(conn, row["id"])
                return dict(row)

        # Step 5 — fuzzy scan top-300
        rows = conn.execute(
            "SELECT * FROM song_cache ORDER BY hit_count DESC LIMIT ?",
            (_FUZZY_TOP_N,),
        ).fetchall()

        best_score = 0.0
        best_row   = None
        for r in rows:
            # Il variant_tag deve corrispondere esattamente:
            # 'breathe u in speed up' non deve mai matchare 'breathe u in' studio
            if r["variant_tag"] != variant:
                continue
            score = _combined_sim(canonical, r["canonical_key"])
            if score > best_score:
                best_score = score
                best_row = r

        if best_row and best_score >= _FUZZY_THRESHOLD:
            # Salva il canonical corrente come alias per velocizzare lookup futuri
            self._add_alias(conn, canonical, best_row["canonical_key"], variant)
            self._bump(conn, best_row["id"])
            log.debug(f"[CACHE] fuzzy hit  score={best_score:.3f}  '{canonical}' -> '{best_row['canonical_key']}'")
            return dict(best_row)

        return None

    def _bump(self, conn: sqlite3.Connection, row_id: int) -> None:
        with self._lock:
            conn.execute(
                "UPDATE song_cache SET hit_count=hit_count+1, last_hit=datetime('now') WHERE id=?",
                (row_id,),
            )
            conn.commit()

    def _add_alias(self, conn: sqlite3.Connection, alias_key: str, canonical_key: str, variant_tag: str) -> None:
        try:
            with self._lock:
                conn.execute(
                    "INSERT OR IGNORE INTO query_alias(alias_key, canonical_key, variant_tag) VALUES(?,?,?)",
                    (alias_key, canonical_key, variant_tag),
                )
                conn.commit()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Store
    # ------------------------------------------------------------------

    def store(self, query: str, track: "TrackInfo", confidence: float = 1.0) -> None:
        """Salva (o aggiorna) una entry per `query` con i dati di `track`."""
        if not self.enabled:
            return
        try:
            self._store_inner(query, track, confidence)
        except Exception as e:
            log.debug(f"[CACHE] store error: {e}")

    def _store_inner(self, query: str, track: "TrackInfo", confidence: float) -> None:
        canonical, variant = normalize(query)
        if not canonical or not getattr(track, "webpage_url", ""):
            return

        conn = self._conn()
        with self._lock:
            conn.execute("""
                INSERT INTO song_cache
                    (canonical_key, variant_tag, webpage_url, title, artist,
                     duration, thumbnail, spotify_url, source, confidence)
                VALUES (?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(canonical_key, variant_tag) DO UPDATE SET
                    webpage_url = excluded.webpage_url,
                    title       = excluded.title,
                    artist      = excluded.artist,
                    duration    = excluded.duration,
                    thumbnail   = excluded.thumbnail,
                    spotify_url = CASE WHEN excluded.spotify_url != '' THEN excluded.spotify_url ELSE song_cache.spotify_url END,
                    hit_count   = song_cache.hit_count + 1,
                    last_hit    = datetime('now'),
                    confidence  = excluded.confidence
            """, (
                canonical,
                variant,
                track.webpage_url,
                getattr(track, "title", "") or "",
                getattr(track, "artist", "") or "",
                getattr(track, "duration", 0) or 0,
                getattr(track, "thumbnail", "") or "",
                getattr(track, "spotify_url", "") or "",
                getattr(track, "source", "youtube") or "youtube",
                confidence,
            ))
            conn.commit()

        # Se la query grezza non coincide col canonical, salva come alias
        raw_stripped = _RE_SPACES.sub(" ", _RE_PUNCT.sub(" ", _nfc(query.lower()))).strip()
        raw_canonical, _ = normalize(raw_stripped)
        if raw_canonical and raw_canonical != canonical:
            self._add_alias(conn, raw_canonical, canonical, variant)

        self._maybe_prune(conn)
        log.debug(f"[CACHE] stored  '{canonical}'  variant='{variant}'  url={track.webpage_url}")

    def link_spotify(self, spotify_url: str, canonical_key: str, variant_tag: str = "") -> None:
        """Collega un URL Spotify a una entry esistente nel DB."""
        if not self.enabled or not spotify_url or not canonical_key:
            return
        try:
            conn = self._conn()
            with self._lock:
                conn.execute(
                    "UPDATE song_cache SET spotify_url=? WHERE canonical_key=? AND variant_tag=? AND spotify_url=''",
                    (spotify_url, canonical_key, variant_tag),
                )
                conn.commit()
        except Exception as e:
            log.debug(f"[CACHE] link_spotify error: {e}")

    # ------------------------------------------------------------------
    # Pruning LRU
    # ------------------------------------------------------------------

    def _maybe_prune(self, conn: sqlite3.Connection) -> None:
        count = conn.execute("SELECT COUNT(*) FROM song_cache").fetchone()[0]
        if count <= _MAX_ENTRIES:
            return
        to_delete = count - int(_MAX_ENTRIES * 0.9)
        with self._lock:
            conn.execute("""
                DELETE FROM song_cache WHERE id IN (
                    SELECT id FROM song_cache ORDER BY last_hit ASC LIMIT ?
                )
            """, (to_delete,))
            conn.commit()
        log.info(f"[CACHE] prune: rimossi {to_delete} record LRU")

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def stats(self) -> dict:
        """Restituisce statistiche aggregate della cache."""
        if not self.enabled:
            return {"enabled": False}
        try:
            conn = self._conn()
            total      = conn.execute("SELECT COUNT(*) FROM song_cache").fetchone()[0]
            aliases    = conn.execute("SELECT COUNT(*) FROM query_alias").fetchone()[0]
            total_hits = conn.execute("SELECT SUM(hit_count) FROM song_cache").fetchone()[0] or 0
            top10      = conn.execute(
                "SELECT title, artist, hit_count FROM song_cache ORDER BY hit_count DESC LIMIT 10"
            ).fetchall()
            return {
                "enabled":    True,
                "total":      total,
                "aliases":    aliases,
                "total_hits": total_hits,
                "top10":      [dict(r) for r in top10],
                "db_path":    self.db_path,
            }
        except Exception as e:
            return {"enabled": True, "error": str(e)}

    def inspect(self, query: str) -> dict:
        """Simula un lookup senza aggiornare hit_count. Solo per debug."""
        canonical, variant = normalize(query)
        result = self.lookup(query)
        return {
            "query":         query,
            "canonical_key": canonical,
            "variant_tag":   variant,
            "hit":           result is not None,
            "match":         result,
        }

    # ------------------------------------------------------------------
    # Clear
    # ------------------------------------------------------------------

    def clear(self) -> int:
        """Svuota completamente la cache. Restituisce il numero di righe rimosse."""
        if not self.enabled:
            return 0
        try:
            conn = self._conn()
            with self._lock:
                n = conn.execute("SELECT COUNT(*) FROM song_cache").fetchone()[0]
                conn.execute("DELETE FROM song_cache")
                conn.execute("DELETE FROM query_alias")
                conn.commit()
            log.warning(f"[CACHE] svuotata manualmente: {n} record rimossi")
            return n
        except Exception as e:
            log.error(f"[CACHE] clear error: {e}")
            return 0
