"""
tests/test_spotify_enrich_logging_format.py

Esegui dalla root del progetto con:
    python tests/test_spotify_enrich_logging_format.py
"""

import io
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.source_resolver import SourceResolver


stream = io.StringIO()
handler = logging.StreamHandler(stream)
logger = logging.getLogger("pitonazz.spotify_enrich")
previous_handlers = logger.handlers[:]
previous_level = logger.level
previous_propagate = logger.propagate

logger.handlers = [handler]
logger.setLevel(logging.DEBUG)
logger.propagate = False

try:
    SourceResolver._log_spotify_enrich(
        1,
        "they call me sonic",
        "They Call Me Sonic",
        {
            "title": "They Call Me Sonic",
            "artist": "Console Allstars",
        },
        {
            "decision": "full",
            "confidence": 0.90,
            "query_sim": 0.94,
            "yt_sim": 0.98,
            "artist_sim": 0.71,
            "duration_sim": 0.99,
            "variant_penalty": 0.0,
            "non_music_penalty": 0.0,
            "reason": "spotify strong title/artist match",
        },
    )
finally:
    logger.handlers = previous_handlers
    logger.setLevel(previous_level)
    logger.propagate = previous_propagate

output = stream.getvalue()
assert "enrich[1]" in output, output
assert "\n  query=" in output, output
assert "\n  spotify=" in output, output
assert "\n  youtube=" in output, output
assert "\n  decision=" in output, output
assert "scores:" in output, output
assert "\n    query=" in output, output
assert "\n    reason=" in output, output

print("OK: spotify enrich logging is multiline and compact")
