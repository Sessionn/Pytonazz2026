"""
cache_db/engine.py

Motore SQLite per la cache persistente delle query musicali.
Zero dipendenze esterne: sqlite3 e' stdlib Python.

Schema:
  song_cache   - una riga per coppia (canonical_key, variant_tag)
  query_alias  - alias alternativi che puntano a un canonical_key

Lookup in 5 step (dal piu' economico al piu' costoso):
  1. Exact hit   su song_cache  (O log n, ~0.1 ms)
  2. Alias hit   su query_alias (O log n, ~0.1 ms)
  3. Spotify URL hit            (O log n, ~0.1 ms)
  4. webpage_url hit            (O log n, ~0.1 ms)
  5. Fuzzy scan  top-300 per hit_count, soglia jaccard >= 0.82
     NB: il fuzzy NON salva alias automaticamente.
         L'alias viene promosso solo dopo store() esplicita.
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

from core.log_colors import tag as _tag, b as _b, dim as _dim

log = logging.getLogger("pitonazz.cache_db")

# ---------------------------------------------------------------------------
# Colori locali (per le parti del messaggio DENTRO il tag, non per il tag stesso)
# ---------------------------------------------------------------------------
_R    = "\033[0m"
_BOLD = "\033[1m"
_DIM  = "\033[2m"
_GRN  = "\033[32m"
_BGRN = "\033[92m"
_YEL  = "\033[33m"
_BYEL = "\033[93m"
_BRED = "\033[91m"
_CYN  = "\033[36m"
_BCYN = "\033[96m"
_GRY  = "\033[90m"
_TEAL = "\033[38;5;80m"
_BLU  = "\033[34m"
_WHT  = "\033[97m"

def _grn(t):  return f"{_BGRN}{t}{_R}"
def _cyn(t):  return f"{_BCYN}{t}{_R}"
def _yel(t):  return f"{_BYEL}{t}{_R}"
def _red(t):  return f"{_BRED}{t}{_R}"
def _gry(t):  return f"{_GRY}{t}{_R}"
def _teal(t): return f"{_TEAL}{t}{_R}"

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
# Logging helpers — tutto sotto il tag CACHE_DB
# ---------------------------------------------------------------------------

def _trunc(s: str, n: int) -> str:
    s = str(s or "")
    return s if len(s) <= n else s[:n - 1] + "\u2026"


def _log_hit(query_raw: str, title: str, step: str) -> None:
    """\u2705 Traccia trovata nel DB (query identica)."""
    log.info(
        _tag("CACHE_DB",
             f"\u2705 HIT      {_cyn(f'{step:<5}')}  "
             f"{_gry(_trunc(query_raw, 36))}  \u2192  "
             f"{_b(_teal(_trunc(title, 45)))}"),
    )


def _log_alias(query_raw: str, title: str, score: float = 0.0) -> None:
    """\U0001f501 Traccia trovata tramite alias (query diversa, stesso brano)."""
    score_str = _gry(f"sim={score:.0%}") if score else ""
    log.info(
        _tag("CACHE_DB",
             f"\U0001f501 ALIAS     "
             f"{_gry(_trunc(query_raw, 32))}  \u007e\u003e  "
             f"{_b(_teal(_trunc(title, 40)))}  {score_str}"),
    )


def _log_add(query_raw: str, title: str, updated: bool) -> None:
    """\u2795 Traccia aggiunta nel DB (INSERT) oppure aggiornata (UPDATE)."""
    if updated:
        icon  = "\U0001f504"
        verb  = _yel("UPDATE")
        arrow = _gry("<=>")
    else:
        icon  = "\u2795"
        verb  = _grn("INSERT")
        arrow = _gry(" =>")
    log.info(
        _tag("CACHE_DB",
             f"{icon} {verb}    "
             f"{_gry(_trunc(query_raw, 36))}  {arrow}  "
             f"{_b(_trunc(title, 45))}"),
    )


def _log_fuzzy_candidate(query_raw: str, title: str, score: float) -> None:
    """\u26a0\ufe0f  Match fuzzy trovato ma alias NON salvato (in attesa di conferma)."""
    log.info(
        _tag("CACHE_DB",
             f"\u26a0\ufe0f  FUZZY     "
             f"{_gry(_trunc(query_raw, 32))}  \u007e\u003e  "
             f"{_b(_teal(_trunc(title, 40)))}  "
             f"{_gry(f'sim={score:.0%}')}"),
    )


def _log_alias_promoted(query_raw: str, title: str) -> None:
    """\U0001f4cc Alias confermato e salvato nel DB dopo store() esplicita."""
    log.info(
        _tag("CACHE_DB",
             f"\U0001f4cc ALIAS+    "
             f"{_gry(_trunc(query_raw, 32))}  \u2192  "
             f"{_b(_teal(_trunc(title, 40)))}"),
    )


# ---------------------------------------------------------------------------
# QueryCache
# ---------------------------------------------------------------------------

class QueryCache:
    """Cache persistente SQLite per le query musicali.

    Thread-safe: un lock globale + check_same_thread=False.
    Abilitabile/disabilitabile a runtime tramite self.enabled.

    Alias policy:
      - Gli alias NON vengono mai salvati automaticamente dal fuzzy lookup.
      - Vengono promossi SOLO da store() quando canonical_key della nuova
        query differisce da quello gia' in DB per la stessa traccia.
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
                _tag("CACHE_DB",
                     f"\U0001f5c4\ufe0f  avviata  "
                     f"{_gry(db_path)}  "
                     f"ttl={_b(f'{ttl_days}d')}  "
                     f"max={_b(str(max_entries))}  "
                     f"entries={_b(_grn(str(entries)))}  "
                     f"hits={_b(_cyn(str(hits)))}"),
            )
        else:
            log.info(_tag("CACHE_DB", f"\u23f8\ufe0f  {_yel('disabilitata')}"))

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

    def _new_conn(self) -> sqlite3.Connection:
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

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
        """
        Cerca la query nel DB in 5 step.
        Il fuzzy (step 5) restituisce il candidato ma NON salva alias:
        l'alias viene promosso solo da store() dopo conferma della traccia.
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
                    _log_hit(query, d.get("title", ""), "exact")
                    return d
                else:
                    conn.execute("UPDATE song_cache SET is_valid=0 WHERE canonical_key=? AND variant_tag=?",
                                 (canonical_key, variant_tag))
                    conn.commit()

            # Step 2 — Alias hit
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
                        _log_alias(query, d.get("title", ""))
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
                        _log_hit(query, d.get("title", ""), "sptfy")
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
                        _log_hit(query, d.get("title", ""), "url")
                        return d

            # Step 5 — Fuzzy scan top-N
            # NOTA: nessun alias viene salvato qui.
            # Il risultato viene restituito come candidato;
            # l'alias verra' promosso da store() se la traccia e' confermata corretta.
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
                    conn.commit()
                    # Segnala il candidato fuzzy nel log ma NON salva l'alias
                    _log_fuzzy_candidate(query, d.get("title", ""), best_score)
                    # Passa il canonical_key trovato nel dict cosi' store() sa
                    # a quale entry fare riferimento per promuovere l'alias.
                    d["_fuzzy_source_key"] = ck
                    d["_fuzzy_source_tag"] = vt
                    d["_query_canonical"]  = canonical_key
                    return d

        return None

    # ------------------------------------------------------------------
    # store
    # ------------------------------------------------------------------

    def store(self, query: str, track: "TrackInfo", force_alias: Optional[str] = None) -> None:
        """
        Salva la traccia nel DB.

        Promozione alias:
          - Se force_alias e' fornito, viene registrato come alias esplicito.
          - Se la traccia era stata trovata via fuzzy (lookup ha aggiunto
            _query_canonical nel dict), e il canonical della query corrente
            coincide con quello del lookup fuzzy, l'alias viene promosso ORA
            che la traccia e' confermata corretta.
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

        # Controlla se il lookup fuzzy aveva gia' trovato questa traccia
        fuzzy_source_ck = getattr(track, "_fuzzy_source_key", None)
        fuzzy_source_vt = getattr(track, "_fuzzy_source_tag", None)
        fuzzy_query_ck  = getattr(track, "_query_canonical",  None)

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
                _log_add(query, title, updated=True)
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
                _log_add(query, title, updated=False)

            # Promozione alias da fuzzy confermato
            if (
                fuzzy_source_ck
                and fuzzy_query_ck
                and fuzzy_query_ck != canonical_key
                and fuzzy_source_ck == canonical_key
            ):
                try:
                    conn.execute("""
                        INSERT OR IGNORE INTO query_alias(alias_key, canonical_key, variant_tag)
                        VALUES(?, ?, ?)
                    """, (fuzzy_query_ck, canonical_key, variant_tag))
                    _log_alias_promoted(query, title)
                except Exception:
                    pass

            # Alias esplicito (force_alias)
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
        log.debug(_tag("CACHE_DB", f"link_spotify  key={canonical_key!r}  url={spotify_url!r}"))

    # ------------------------------------------------------------------
    # Statistiche
    # ------------------------------------------------------------------

    def stats(self) -> dict:
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
    # inspect
    # ------------------------------------------------------------------

    def inspect(self, query: str) -> dict:
        """Info diagnostiche su una query: normalizzazione, hit, dati raw."""
        canonical_key, variant_tag = normalize(query)
        result = {
            "query_raw":     query,
            "canonical_key": canonical_key,
            "variant_tag":   variant_tag,
            "found":         False,
            "row":           None,
        }
        if not self.enabled or not canonical_key:
            return result
        with self._lock:
            conn = self._conn()
            row = conn.execute("""
                SELECT * FROM song_cache
                WHERE canonical_key = ? AND variant_tag = ? AND is_valid = 1
                LIMIT 1
            """, (canonical_key, variant_tag)).fetchone()
            if row:
                result["found"] = True
                result["row"] = dict(row)
        return result

    # ------------------------------------------------------------------
    # Clear
    # ------------------------------------------------------------------

    def clear(self) -> int:
        if not self.enabled:
            return 0
        with self._lock:
            conn = self._conn()
            deleted = conn.execute("DELETE FROM song_cache").rowcount
            conn.execute("DELETE FROM query_alias")
            conn.commit()
        log.info(_tag("CACHE_DB", f"\U0001f5d1\ufe0f  clear  {_b(str(deleted))} righe eliminate"))
        return deleted

    # ------------------------------------------------------------------
    # Pruning LRU
    # ------------------------------------------------------------------

    def _maybe_prune(self) -> None:
        import threading as _threading
        _threading.Thread(target=self._prune_lru, daemon=True).start()

    def _prune_lru(self) -> None:
        conn = self._new_conn()
        try:
            with self._lock:
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
                log.info(_tag("CACHE_DB", f"\U0001f9f9 prune LRU  {_b(str(to_delete))} record rimossi"))
        except Exception as exc:
            log.warning(_tag("CACHE_DB", f"\u274c prune LRU fallito: {exc}"))
        finally:
            conn.close()

    def prune_stale(self) -> int:
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
        log.info(_tag("CACHE_DB", f"\U0001f9f9 prune_stale  {_b(str(len(stale_ids)))} record invalidati"))
        return len(stale_ids)
