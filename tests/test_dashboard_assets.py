"""
tests/test_dashboard_assets.py

Esegui dalla root del progetto con:
    python tests/test_dashboard_assets.py
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = ROOT / "data" / "database" / "dashboard" / "templates" / "index.html"
STYLE_CSS = ROOT / "data" / "database" / "dashboard" / "static" / "css" / "style.css"
DASHBOARD_JS = ROOT / "data" / "database" / "dashboard" / "static" / "js" / "dashboard.js"


index_html = INDEX_HTML.read_text(encoding="utf-8")
style_css = STYLE_CSS.read_text(encoding="utf-8")
dashboard_js = DASHBOARD_JS.read_text(encoding="utf-8")

for content, label in (
    (index_html, "index.html"),
    (style_css, "style.css"),
    (dashboard_js, "dashboard.js"),
):
    assert "â†" not in content, f"FAIL: caratteri corrotti trovati in {label}"

assert '<option value="soundcloud">SoundCloud</option>' in index_html, (
    "FAIL: filtro dashboard privo di SoundCloud"
)
assert "function sourceBadge(" in dashboard_js, "FAIL: manca sourceBadge() per sorgente SVG coerente"
assert "function actionIcon(" in dashboard_js, "FAIL: manca actionIcon() per azioni SVG coerenti"
assert "function actionLinks(" in dashboard_js, "FAIL: manca actionLinks() per azioni riproduzione uniformi"
assert "return [" in dashboard_js and "makeActionLink(youtubeUrl, \"youtube\"" in dashboard_js, (
    "FAIL: actionLinks non costruisce sempre i tre pulsanti piattaforma"
)
assert ".badge.ok" in style_css and ".badge.err" in style_css, (
    "FAIL: manca la stilizzazione dedicata per stati valida/invalida"
)
assert ".del-btn" in style_css, "FAIL: manca la stilizzazione della X di cancellazione"

delete_block_start = dashboard_js.index("function deleteSong(")
delete_block_end = dashboard_js.index("function openModal(", delete_block_start)
delete_block = dashboard_js[delete_block_start:delete_block_end]
assert "refreshLoadedSections()" not in delete_block, (
    "FAIL: le delete dashboard non devono ricaricare tutte le sezioni e perdere scroll/posizione"
)
assert "setTimeout(() => refreshStats" not in delete_block, (
    "FAIL: le delete dashboard non devono fare refresh automatici temporizzati dopo la cancellazione"
)
assert "removeDashboardRow" in delete_block, (
    "FAIL: le delete dashboard devono rimuovere la riga localmente senza refresh globale"
)
assert "applyCompactMaps(data.compact)" in delete_block, (
    "FAIL: le delete dashboard devono applicare localmente la mappa ID della compattazione"
)
assert "markSectionsStaleAfterDelete" in delete_block, (
    "FAIL: le delete dashboard devono marcare le altre sezioni stale senza ricaricarle subito"
)

print("OK: dashboard assets soundcloud/arrows/svg")
