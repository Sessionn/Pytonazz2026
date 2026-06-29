"""
tests/test_ffmpeg_reconnect_options.py

Esegui dalla root del progetto con:
    python tests/test_ffmpeg_reconnect_options.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config


before_options = Config.FFMPEG_OPTIONS["before_options"]

for required in (
    "-reconnect 1",
    "-reconnect_streamed 1",
    "-reconnect_on_network_error 1",
    "-reconnect_on_http_error 4xx,5xx",
    "-reconnect_delay_max 5",
    "-rw_timeout 15000000",
):
    assert required in before_options, f"Missing FFmpeg option: {required}"

for unsupported in (
    "-reconnect_max_retries",
    "-reconnect_delay_total_max",
    "-reconnect_at_eof",
):
    assert unsupported not in before_options, f"Unsupported FFmpeg option still present: {unsupported}"

print("OK: FFmpeg reconnect options cover transient TLS/HTTPS drops without EOF reconnect loops")
