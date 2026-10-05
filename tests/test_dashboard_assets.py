"""
tests/test_dashboard_assets.py

Controlli statici sugli asset di dashboard e login: sicurezza (niente handler
inline, escaping), comportamento live e funzioni chiave della UI.

Esegui dalla root del progetto con:
    python tests/test_dashboard_assets.py
"""

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DASH = ROOT / "data" / "database" / "dashboard"
INDEX_HTML = (DASH / "templates" / "index.html").read_text(encoding="utf-8")
LOGIN_HTML = (DASH / "templates" / "login.html").read_text(encoding="utf-8")
STYLE_CSS = (DASH / "static" / "css" / "style.css").read_text(encoding="utf-8")
LOGIN_CSS = (DASH / "static" / "css" / "login.css").read_text(encoding="utf-8")
DASHBOARD_JS = (DASH / "static" / "js" / "dashboard.js").read_text(encoding="utf-8")
LOGIN_JS = (DASH / "static" / "js" / "login.js").read_text(encoding="utf-8")
DJ_JS = (DASH / "static" / "js" / "dj_console.js").read_text(encoding="utf-8")


def block(source: str, start: str, end: str) -> str:
    begin = source.index(start)
    return source[begin:source.index(end, begin)]


for content, label in (
    (INDEX_HTML, "index.html"),
    (LOGIN_HTML, "login.html"),
    (STYLE_CSS, "style.css"),
    (DASHBOARD_JS, "dashboard.js"),
):
    assert "â†" not in content, f"FAIL: caratteri corrotti trovati in {label}"

# ── Sicurezza: la CSP del backend vieta script e handler inline ─────────────
inline_handler = re.compile(r"\son[a-z]+\s*=", re.I)
for content, label in ((INDEX_HTML, "index.html"), (LOGIN_HTML, "login.html")):
    assert not inline_handler.search(content), f"FAIL: handler inline in {label}"
    assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", content), f"FAIL: script inline in {label}"
assert not inline_handler.search(DASHBOARD_JS.replace("addEventListener", "")), (
    "FAIL: dashboard.js genera markup con handler inline (onclick/onerror)"
)
assert "JSON.stringify(" not in DASHBOARD_JS, "FAIL: dati serializzati dentro attributi HTML"
assert '.replace(/\'/g, "&#39;")' in DASHBOARD_JS, "FAIL: esc() deve neutralizzare anche gli apici singoli"
assert "function safeUrl(" in DASHBOARD_JS, "FAIL: i link esterni devono passare da safeUrl()"
assert 'rel="noopener noreferrer"' in DASHBOARD_JS, "FAIL: link esterni senza rel=noopener"
assert "${track.title}" not in DJ_JS, "FAIL: la console DJ inserisce titoli come HTML"

# ── Funzioni UI ──────────────────────────────────────────────────────────────
for fn in ("sourceBadge", "actionLinks", "makeActionLink", "applyCompactMaps", "removeDashboardRow",
           "markSectionsStaleAfterDelete", "openDrawer", "showToast", "startRealtimeStats"):
    assert f"function {fn}(" in DASHBOARD_JS, f"FAIL: manca {fn}() in dashboard.js"
assert 'data-value="soundcloud"' in INDEX_HTML, "FAIL: filtro dashboard privo di SoundCloud"
assert ".badge.ok" in STYLE_CSS and ".badge.err" in STYLE_CSS, "FAIL: mancano gli stati valida/invalida"
assert ".del-btn" in STYLE_CSS, "FAIL: manca lo stile del pulsante elimina"
assert "prefers-reduced-motion" in STYLE_CSS and "prefers-reduced-motion" in LOGIN_CSS, (
    "FAIL: le animazioni devono rispettare prefers-reduced-motion"
)

# Le delete aggiornano i dati locali senza refresh globale della pagina.
delete_block = block(DASHBOARD_JS, "function deleteRow(", "function handleDeleteClick(")
assert "removeDashboardRow" in delete_block
assert "applyCompactMaps(data.compact)" in delete_block
assert "markSectionsStaleAfterDelete" in delete_block
assert "location.reload" not in DASHBOARD_JS, "FAIL: la dashboard non deve ricaricare la pagina"

# Eliminazione a due click (conferma esplicita).
assert "is-confirming" in block(DASHBOARD_JS, "function handleDeleteClick(", "/* ── Drawer")

# Gli eventi "stats" aggiornano solo i KPI; le tabelle si ricaricano su "cache_change".
events_block = block(DASHBOARD_JS, "function startRealtimeStats(", "function scheduleLiveRefresh(")
stats_listener = block(events_block, 'addEventListener("stats"', 'addEventListener("cache_change"')
assert "loadSection" not in stats_listener and "scheduleLiveRefresh" not in stats_listener, (
    "FAIL: gli eventi stats non devono ricaricare la tabella corrente"
)
assert 'addEventListener("cache_change", () => scheduleLiveRefresh())' in events_block

# Login: niente script inline, toggle password e stato di caricamento.
assert "aria-pressed" in LOGIN_HTML and "is-loading" in LOGIN_JS

print("OK: dashboard/login assets sicuri e coerenti")
