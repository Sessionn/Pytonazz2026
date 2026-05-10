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
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from core.source_resolver import TrackInfo

log = logging.getLogger("pitonazz.cache_db")

# ---------------------------------------------------------------------------
# Costanti
# ---------------------------------------------------------------------------
_FUZZY_TOP_N       = 300
_FUZZY_THRESHOLD   = 0.82
_FUZZY_STR_WEIGHT  = 0.35
_TTL_DAYS_DEFAULT  = 30
_MAX_ENTRIES       = 10_000

_DEFAULT_DB_PATH   = os.path.join("data", "database", "cache.db")

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
    """Restituisce (canonical_key, variant_tag) dalla query grezza."""
    raw = _nfc((query or "").strip().lower())
    variant_kw = _get_variant_keywords()

    found_variant = ""
    for kw in sorted(variant_kw, key=len, reverse=True):
        if kw in raw:
            if not found_variant:
                found_variant = kw
            raw = raw.replace(kw, " ")

    raw = _RE_PUNCT.sub(" ", raw)
    raw = _RE_SPACES.sub(" ", raw).strip()

    tokens = [t for t in raw.split() if t and t not in _NOISE_WORDS]
    canonical = " ".join(sorted(tokens))

    return canonical, found_variant


# ---------------------------------------------------------------------------
# Similarity helpers
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
# Logging DB helpers
# ---------------------------------------------------------------------------

def _log_db_hit(query_raw: str, title: str, step: str) -> None:
    """Brano trovato nel DB (query identica — exact/url hit)."""
    log.info(
        "\U0001f7e2 [DB] HIT      %-6s | %-40s => %s",
        step, _trunc(query_raw, 40), _trunc(title, 50),
    )


def _log_db_alias(query_raw: str, canonical: str, title: str, score: float = 0.0) -> None:
    """Brano trovato nel DB tramite corrispondenza fuzzy/alias (query diversa)."""
    score_str = f"  sim={score:.2f}" if score else ""
    log.info(
        "\U0001f7e1 [DB] ALIAS   %-40s ~> %-30s => %s%s",
        _trunc(query_raw, 40), _trunc(canonical, 30), _trunc(title, 40), score_str,
    )


def _log_db_store(query_raw: str, title: str, updated: bool) -> None:
    """Brano aggiunto o aggiornato nel DB."""
    verb = "UPDATE" if updated else "INSERT"
    log.info(
        "\U0001f535 [DB] %-6s  %-40s => %s",
        verb, _trunc(query_raw, 40), _trunc(title, 50),
    )


def _trunc(s: str, n: int) -> str:
    s = str(s or "")
    return s if len(s) <= n else s[:n - 1] + "\u2026"


# ---------------------------------------------------------------------------
# QueryCache
# ---------------------------------------------------------------------------

class QueryCache:
    """Cache persistente SQLite per le query musicali.

    Thread-safe: un lock globale + check_same_thread=False.
    Abilitabile/disabilitabile a runtime tramite self.enabled.
    """

    def __init__(self, db_path: str, enabled: bool = True,
                 ttl_days: int = _TTL_DAYS_DEFAULT,
                 max_entries: int = _MAX_ENTRIES) -> None:
        self.db_path     = db_path
        self.enabled     = enabled
        self.ttl_days    = ttl_days
        self.max_entries = max_entries
        self._lock       = threading.Lock()
        self._local      = threading.local()
        if enabled:
            self._init_db()
            entries = self._count_entries()
            hits    = self._count_hits()
            log.info(
                "\u2705  %-8s db=%-28s  ttl=%dd  max=%-6d  entries=%-5d  hit_totali=%d",
                "[CACHE]", db_path, ttl_days, max_entries, entries, hits,
            )
        else:
            log.info("\u26d4  [CACHE]  disabilitata")

    # ------------------------------------------------------------------
    # Connessione per-thread
    # ------------------------------------------------------------------

    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA foreign_keys=ON")
            self._local.conn = conn
        return self._local.conn

    # ------------------------------------------------------------------
    # Inizializzazione schema
    # ------------------------------------------------------------------

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
                    source        TEXT    NOT NULL DEFAULT 'youtube',
                    spotify_url   TEXT    NOT NULL DEFAULT '',
                    created_at    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
                    last_used     TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
                    hit_count     INTEGER NOT NULL DEFAULT 1,
                    is_valid      INTEGER NOT NULL DEFAULT 1,
                    UNIQUE(canonical_key, variant_tag)
                );

                CREATE TABLE IF NOT EXISTS query_alias (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    alias_key     TEXT    NOT NULL UNIQUE,
                    canonical_key TEXT    NOT NULL,
                    variant_tag   TEXT    NOT NULL DEFAULT '',
                    created_at    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
                );

                CREATE INDEX IF NOT EXISTS idx_sc_canonical
                    ON song_cache(canonical_key, variant_tag);
                CREATE INDEX IF NOT EXISTS idx_sc_spotify
                    ON song_cache(spotify_url) WHERE spotify_url != '';
                CREATE INDEX IF NOT EXISTS idx_sc_webpage
                    ON song_cache(webpage_url);
                CREATE INDEX IF NOT EXISTS idx_sc_last_used
                    ON song_cache(last_used);
                CREATE INDEX IF NOT EXISTS idx_sc_hit_count
                    ON song_cache(hit_count DESC);
                CREATE INDEX IF NOT EXISTS idx_qa_alias
                    ON query_alias(alias_key);
                CREATE INDEX IF NOT EXISTS idx_qa_canonical
                    ON query_alias(canonical_key, variant_tag);
            """)
            conn.commit()

    # ------------------------------------------------------------------
    # Helpers interni
    # ------------------------------------------------------------------

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def _is_stale(self, last_used_iso: str) -> bool:
        try:
            lu = datetime.strptime(last_used_iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            delta = datetime.now(timezone.utc) - lu
            return delta.days >= self.ttl_days
        except Exception:
            return False

    def _touch(self, conn: sqlite3.Connection, canonical_key: str, variant_tag: str) -> None:
        conn.execute("""
            UPDATE song_cache
            SET last_used = ?, hit_count = hit_count + 1
            WHERE canonical_key = ? AND variant_tag = ?
        """, (self._now_iso(), canonical_key, variant_tag))

    def _row_to_dict(self, row) -> dict:
        return dict(row) if row else {}

    def _count_entries(self) -> int:
        try:
            with self._lock:
                conn = self._conn()
                return conn.execute("SELECT COUNT(*) FROM song_cache WHERE is_valid=1").fetchone()[0]
        except Exception:
            return 0

    def _count_hits(self) -> int:
        try:
            with self._lock:
                conn = self._conn()
                return conn.execute("SELECT COALESCE(SUM(hit_count),0) FROM song_cache WHERE is_valid=1").fetchone()[0]
        except Exception:
            return 0

    # ------------------------------------------------------------------
    # lookup
    # ------------------------------------------------------------------

    def lookup(self, query: str) -> Optional[dict]:
        """Cerca una corrispondenza per `query`.

        Ritorna un dict con i metadati del brano (stessa struttura di song_cache)
        oppure None se non trovato / stale / disabilitata.
        """
        if not self.enabled:
            return None

        canonical_key, variant_tag = normalize(query)
        if not canonical_key:
            return None

        with self._lock:
            conn = self._conn()

            # Step 1 — Exact hit
            row = conn.execute("""
                SELECT * FROM song_cache
                WHERE canonical_key = ? AND variant_tag = ? AND is_valid = 1
                LIMIT 1
            """, (canonical_key, variant_tag)).fetchone()

            if row:
                d = self._row_to_dict(row)
                if not self._is_stale(d.get("last_used", "")):
                    self._touch(conn, canonical_key, variant_tag)
                    conn.commit()
                    _log_db_hit(query, d.get("title", ""), "exact")
                    return d
                else:
                    conn.execute("UPDATE song_cache SET is_valid=0 WHERE canonical_key=? AND variant_tag=?",
                                 (canonical_key, variant_tag))
                    conn.commit()

            # Step 2 — Alias hit (query diversa mappata allo stesso canonical)
            alias_row = conn.execute("""
                SELECT canonical_key, variant_tag FROM query_alias
                WHERE alias_key = ?
                LIMIT 1
            """, (canonical_key,)).fetchone()

            if alias_row:
                ck, vt = alias_row["canonical_key"], alias_row["variant_tag"]
                row = conn.execute("""
                    SELECT * FROM song_cache
                    WHERE canonical_key = ? AND variant_tag = ? AND is_valid = 1
                    LIMIT 1
                """, (ck, vt)).fetchone()
                if row:
                    d = self._row_to_dict(row)
                    if not self._is_stale(d.get("last_used", "")):
                        self._touch(conn, ck, vt)
                        conn.commit()
                        _log_db_alias(query, ck, d.get("title", ""))
                        return d

            # Step 3 — Spotify URL hit
            q_stripped = (query or "").strip()
            if "spotify" in q_stripped.lower():
                row = conn.execute("""
                    SELECT * FROM song_cache
                    WHERE spotify_url = ? AND is_valid = 1
                    LIMIT 1
                """, (q_stripped,)).fetchone()
                if row:
                    d = self._row_to_dict(row)
                    if not self._is_stale(d.get("last_used", "")):
                        self._touch(conn, d["canonical_key"], d["variant_tag"])
                        conn.commit()
                        _log_db_hit(query, d.get("title", ""), "sptfy")
                        return d

            # Step 4 — webpage_url hit
            if q_stripped.startswith("http"):
                row = conn.execute("""
                    SELECT * FROM song_cache
                    WHERE webpage_url = ? AND is_valid = 1
                    LIMIT 1
                """, (q_stripped,)).fetchone()
                if row:
                    d = self._row_to_dict(row)
                    if not self._is_stale(d.get("last_used", "")):
                        self._touch(conn, d["canonical_key"], d["variant_tag"])
                        conn.commit()
                        _log_db_hit(query, d.get("title", ""), "url")
                        return d

            # Step 5 — Fuzzy scan sui top-N per hit_count
            rows = conn.execute("""
                SELECT * FROM song_cache
                WHERE is_valid = 1
                ORDER BY hit_count DESC
                LIMIT ?
            """, (_FUZZY_TOP_N,)).fetchall()

            best_score = 0.0
            best_row   = None
            for r in rows:
                score = _combined_sim(canonical_key, r["canonical_key"])
                if score > best_score:
                    best_score = score
                    best_row   = r

            if best_row and best_score >= _FUZZY_THRESHOLD:
                d = self._row_to_dict(best_row)
                if not self._is_stale(d.get("last_used", "")):
                    ck, vt = d["canonical_key"], d["variant_tag"]
                    self._touch(conn, ck, vt)
                    # Alias persistente: velocizza il prossimo lookup identico
                    try:
                        conn.execute("""
                            INSERT OR IGNORE INTO query_alias(alias_key, canonical_key, variant_tag)
                            VALUES(?, ?, ?)
                        """, (canonical_key, ck, vt))
                    except Exception:
                        pass
                    conn.commit()
                    _log_db_alias(query, ck, d.get("title", ""), best_score)
                    return d

        return None

    # ------------------------------------------------------------------
    # store
    # ------------------------------------------------------------------

    def store(self, query: str, track: "TrackInfo", force_alias: Optional[str] = None) -> None:
        """Salva o aggiorna l'associazione query -> brano.

        Se la chiave esiste gia', aggiorna i metadati e incrementa hit_count.
        Se non esiste, inserisce una nuova riga.

        force_alias: se fornito, viene salvato come alias aggiuntivo esplicito
        che punta alla stessa entry (usato quando si sa gia' che una query
        diversa deve puntare allo stesso brano).

        NOTA sugli alias automatici:
        Gli alias vengono creati SOLO dal motore di lookup (step 2 e step 5)
        quando una query diversa produce un match fuzzy/alias sul DB esistente.
        store() di per se' NON crea alias: salva solo la query normalizzata
        come chiave primaria. Cosi' una query errata non inquina il DB.
        """
        if not self.enabled:
            return

        webpage_url = (getattr(track, "webpage_url", "") or "").strip()
        if not webpage_url:
            return

        canonical_key, variant_tag = normalize(query)
        if not canonical_key:
            return

        now = self._now_iso()
        title       = (getattr(track, "title",       "") or "").strip()
        artist      = (getattr(track, "artist",      "") or "").strip()
        duration    = int(getattr(track, "duration",  0)  or 0)
        thumbnail   = (getattr(track, "thumbnail",   "") or "").strip()
        source      = (getattr(track, "source",      "youtube") or "youtube").strip()
        spotify_url = (getattr(track, "spotify_url", "") or "").strip()

        with self._lock:
            conn = self._conn()
            existing = conn.execute("""
                SELECT id, hit_count FROM song_cache
                WHERE canonical_key = ? AND variant_tag = ?
                LIMIT 1
            """, (canonical_key, variant_tag)).fetchone()

            if existing:
                conn.execute("""
                    UPDATE song_cache
                    SET webpage_url   = ?,
                        title         = ?,
                        artist        = ?,
                        duration      = ?,
                        thumbnail     = ?,
                        source        = ?,
                        spotify_url   = CASE WHEN ? != '' THEN ? ELSE spotify_url END,
                        last_used     = ?,
                        hit_count     = hit_count + 1,
                        is_valid      = 1
                    WHERE canonical_key = ? AND variant_tag = ?
                """, (
                    webpage_url, title, artist, duration, thumbnail, source,
                    spotify_url, spotify_url,
                    now,
                    canonical_key, variant_tag,
                ))
                _log_db_store(query, title, updated=True)
            else:
                conn.execute("""
                    INSERT INTO song_cache
                        (canonical_key, variant_tag, webpage_url, title, artist,
                         duration, thumbnail, source, spotify_url, created_at, last_used, hit_count, is_valid)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 1)
                """, (
                    canonical_key, variant_tag, webpage_url, title, artist,
                    duration, thumbnail, source, spotify_url, now, now,
                ))
                _log_db_store(query, title, updated=False)

            if force_alias:
                alias_key, _ = normalize(force_alias)
                if alias_key and alias_key != canonical_key:
                    try:
                        conn.execute("""
                            INSERT OR IGNORE INTO query_alias(alias_key, canonical_key, variant_tag)
                            VALUES(?, ?, ?)
                        """, (alias_key, canonical_key, variant_tag))
                    except Exception:
                        pass

            conn.commit()

        self._maybe_prune()

    # ------------------------------------------------------------------
    # link_spotify
    # ------------------------------------------------------------------

    def link_spotify(self, spotify_url: str, canonical_key: str, variant_tag: str) -> None:
        """Associa uno Spotify URL a una entry gia' presente in cache."""
        if not self.enabled or not spotify_url or not canonical_key:
            return
        with self._lock:
            conn = self._conn()
            conn.execute("""
                UPDATE song_cache
                SET spotify_url = ?
                WHERE canonical_key = ? AND variant_tag = ? AND is_valid = 1
            """, (spotify_url, canonical_key, variant_tag))
            conn.commit()
        log.debug("[DB] link_spotify  key=%r  url=%r", canonical_key, spotify_url)

    # ------------------------------------------------------------------
    # Statistiche
    # ------------------------------------------------------------------

    def stats(self) -> dict:
        """Ritorna statistiche sul database."""
        if not self.enabled:
            return {"enabled": False}
        with self._lock:
            conn = self._conn()
            total = conn.execute("SELECT COUNT(*) FROM song_cache").fetchone()[0]
            valid = conn.execute("SELECT COUNT(*) FROM song_cache WHERE is_valid=1").fetchone()[0]
            aliases = conn.execute("SELECT COUNT(*) FROM query_alias").fetchone()[0]
            top_row = conn.execute("""
                SELECT title, hit_count FROM song_cache
                WHERE is_valid=1
                ORDER BY hit_count DESC LIMIT 1
            """).fetchone()
            total_hits = conn.execute("SELECT SUM(hit_count) FROM song_cache WHERE is_valid=1").fetchone()[0] or 0
            db_size_bytes = os.path.getsize(self.db_path) if os.path.exists(self.db_path) else 0
        return {
            "enabled":       True,
            "total_entries": total,
            "valid_entries": valid,
            "aliases":       aliases,
            "total_hits":    total_hits,
            "top_song":      dict(top_row) if top_row else None,
            "db_size_kb":    round(db_size_bytes / 1024, 1),
            "db_path":       self.db_path,
            "ttl_days":      self.ttl_days,
            "max_entries":   self.max_entries,
        }

    # ------------------------------------------------------------------
    # Clear
    # ------------------------------------------------------------------

    def clear(self) -> int:
        """Svuota l'intera cache. Ritorna il numero di righe cancellate."""
        if not self.enabled:
            return 0
        with self._lock:
            conn = self._conn()
            deleted = conn.execute("DELETE FROM song_cache").rowcount
            conn.execute("DELETE FROM query_alias")
            conn.commit()
        log.info("[DB] clear  %d righe eliminate", deleted)
        return deleted

    # ------------------------------------------------------------------
    # Pruning LRU
    # ------------------------------------------------------------------

    def _maybe_prune(self) -> None:
        import threading as _threading
        _threading.Thread(target=self._prune_lru, daemon=True).start()

    def _prune_lru(self) -> None:
        with self._lock:
            conn = self._conn()
            total = conn.execute("SELECT COUNT(*) FROM song_cache").fetchone()[0]
            if total <= self.max_entries:
                return
            to_delete = total - self.max_entries
            conn.execute("""
                DELETE FROM song_cache
                WHERE id IN (
                    SELECT id FROM song_cache
                    ORDER BY last_used ASC
                    LIMIT ?
                )
            """, (to_delete,))
            conn.execute("""
                DELETE FROM query_alias
                WHERE canonical_key NOT IN (
                    SELECT canonical_key FROM song_cache
                )
            """)
            conn.commit()
            log.info("[DB] prune LRU  eliminati %d record", to_delete)

    def prune_stale(self) -> int:
        """Invalida tutte le righe il cui last_used supera il TTL."""
        if not self.enabled:
            return 0
        with self._lock:
            conn = self._conn()
            rows = conn.execute(
                "SELECT id, last_used FROM song_cache WHERE is_valid=1"
            ).fetchall()
            stale_ids = [
                r["id"] for r in rows
                if self._is_stale(r["last_used"])
            ]
            if stale_ids:
                conn.execute(
                    f"UPDATE song_cache SET is_valid=0 WHERE id IN ({','.join('?' * len(stale_ids))})",
                    stale_ids,
                )
                conn.commit()
        log.info("[DB] prune_stale  invalidati %d record", len(stale_ids))
        return len(stale_ids)
