"""
core/cache_report.py

Genera un file HTML standalone con il contenuto del song cache DB.
Usato da /cache-export in cogs/dev_cache.py.
"""

import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import sqlite3

from config import Config


def _fmt_ts(ts: Optional[int]) -> str:
    if not ts:
        return "-"
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


def _fmt_dur(secs: Optional[int]) -> str:
    if not secs:
        return "-"
    m, s = divmod(int(secs), 60)
    return f"{m}:{s:02d}"


def _read_db() -> tuple[list[dict], list[dict]]:
    """Legge song_cache e query_aliases direttamente via sqlite3."""
    try:
        conn = sqlite3.connect(Config.DB_PATH, check_same_thread=False, timeout=5)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        cur.execute("""
            SELECT id, query_raw, title, artist, source,
                   duration, hit_count, created_at, last_used, is_valid
              FROM song_cache
             ORDER BY hit_count DESC, last_used DESC
        """)
        songs = [dict(r) for r in cur.fetchall()]

        cur.execute("""
            SELECT qa.query_raw AS alias, sc.query_raw AS canonical, sc.title
              FROM query_aliases qa
              JOIN song_cache sc ON sc.id = qa.cache_id
             ORDER BY qa.id
        """)
        aliases = [dict(r) for r in cur.fetchall()]

        conn.close()
        return songs, aliases
    except Exception as e:
        return [], []


def _badge(is_valid: int) -> str:
    if is_valid:
        return '<span class="badge ok">valida</span>'
    return '<span class="badge err">invalida</span>'


def _src_badge(source: str) -> str:
    color = {
        "youtube":  "#FF0000",
        "spotify":  "#1DB954",
        "soundcloud": "#FF5500",
    }.get(source, "#888")
    return f'<span class="src" style="background:{color}">{source}</span>'


CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: 'Segoe UI', system-ui, sans-serif;
    background: #0f0f13;
    color: #d4d4d8;
    font-size: 14px;
    padding: 24px;
}
h1 { font-size: 22px; color: #fff; margin-bottom: 4px; }
.sub { color: #71717a; font-size: 12px; margin-bottom: 24px; }
.stats-row {
    display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 28px;
}
.stat {
    background: #1c1c24; border: 1px solid #2a2a36;
    border-radius: 8px; padding: 12px 20px;
    min-width: 110px; text-align: center;
}
.stat .val { font-size: 24px; font-weight: 700; color: #a78bfa; }
.stat .lbl { font-size: 11px; color: #71717a; margin-top: 2px; }
h2 { font-size: 15px; color: #a1a1aa; margin-bottom: 10px; margin-top: 28px;
     border-bottom: 1px solid #2a2a36; padding-bottom: 6px; }
table { width: 100%; border-collapse: collapse; }
th {
    text-align: left; padding: 8px 10px;
    background: #18181f; color: #71717a;
    font-size: 11px; text-transform: uppercase; letter-spacing: .05em;
    border-bottom: 1px solid #2a2a36;
    position: sticky; top: 0;
}
td {
    padding: 7px 10px; border-bottom: 1px solid #1e1e28;
    vertical-align: middle;
}
tr:hover td { background: #16161e; }
.badge {
    display: inline-block; border-radius: 4px;
    padding: 2px 7px; font-size: 11px; font-weight: 600;
}
.badge.ok  { background: #14532d; color: #4ade80; }
.badge.err { background: #450a0a; color: #f87171; }
.src {
    display: inline-block; border-radius: 4px;
    padding: 2px 7px; font-size: 10px; color: #fff; font-weight: 600;
}
.hits { color: #facc15; font-weight: 600; }
.dim  { color: #52525b; }
.title { color: #e4e4e7; font-weight: 500; }
.artist { color: #a1a1aa; font-size: 12px; }
.id-col { color: #3f3f46; font-size: 11px; }
.table-wrap { overflow-x: auto; }
"""


def build_html() -> str:
    """Genera e restituisce l'HTML completo del report."""
    songs, aliases = _read_db()
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total   = len(songs)
    valid   = sum(1 for s in songs if s["is_valid"])
    hits    = sum(s["hit_count"] for s in songs)
    ali_cnt = len(aliases)

    # ── Stats row
    stats_html = f"""
    <div class="stats-row">
        <div class="stat"><div class="val">{total}</div><div class="lbl">Entry totali</div></div>
        <div class="stat"><div class="val">{valid}</div><div class="lbl">Valide</div></div>
        <div class="stat"><div class="val">{total - valid}</div><div class="lbl">Invalide</div></div>
        <div class="stat"><div class="val">{hits}</div><div class="lbl">Hit totali</div></div>
        <div class="stat"><div class="val">{ali_cnt}</div><div class="lbl">Alias</div></div>
    </div>
    """

    # ── song_cache table
    rows_html = ""
    for s in songs:
        rows_html += f"""
        <tr>
            <td class="id-col">{s['id']}</td>
            <td><div class="title">{s['title'] or '-'}</div>
                <div class="artist">{s['artist'] or ''}</div></td>
            <td class="dim" style="font-size:11px;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{s['query_raw']}</td>
            <td>{_src_badge(s['source'])}</td>
            <td style="text-align:center">{_fmt_dur(s['duration'])}</td>
            <td class="hits" style="text-align:center">{s['hit_count']}</td>
            <td class="dim">{_fmt_ts(s['created_at'])}</td>
            <td class="dim">{_fmt_ts(s['last_used'])}</td>
            <td>{_badge(s['is_valid'])}</td>
        </tr>
        """

    cache_table = f"""
    <h2>&#128191; song_cache &nbsp;<span class="dim" style="font-size:11px">{total} righe</span></h2>
    <div class="table-wrap">
    <table>
        <thead><tr>
            <th>#</th><th>Titolo / Artista</th><th>Query</th>
            <th>Source</th><th>Dur.</th><th>Hits</th>
            <th>Creata</th><th>Usata</th><th>Stato</th>
        </tr></thead>
        <tbody>{rows_html}</tbody>
    </table>
    </div>
    """

    # ── aliases table
    if aliases:
        ali_rows = "".join(
            f"<tr><td class='dim' style='font-size:11px'>{a['alias']}</td>"
            f"<td>{a['canonical']}</td>"
            f"<td class='title'>{a['title'] or '-'}</td></tr>"
            for a in aliases
        )
        alias_table = f"""
        <h2>&#128279; query_aliases &nbsp;<span class="dim" style="font-size:11px">{ali_cnt} righe</span></h2>
        <div class="table-wrap">
        <table>
            <thead><tr><th>Alias</th><th>Query canonica</th><th>Titolo</th></tr></thead>
            <tbody>{ali_rows}</tbody>
        </table>
        </div>
        """
    else:
        alias_table = "<h2>&#128279; query_aliases</h2><p class='dim' style='padding:12px 0'>Nessun alias registrato.</p>"

    return f"""<!DOCTYPE html>
<html lang="it">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Pytonazz &#128191; Cache Report</title>
    <style>{CSS}</style>
</head>
<body>
    <h1>&#128191; Song Cache Report</h1>
    <div class="sub">Generato il {generated_at} &nbsp;&middot;&nbsp; DB: {Config.DB_PATH}</div>
    {stats_html}
    {cache_table}
    {alias_table}
</body>
</html>"""


def export_to_file(path: Path) -> Path:
    """Scrive il report HTML su disco e restituisce il path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_html(), encoding="utf-8")
    return path
