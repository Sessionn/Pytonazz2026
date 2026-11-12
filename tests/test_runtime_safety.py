"""Regression checks for startup updates and bounded DJ snapshots."""
from __future__ import annotations

import json
import logging
import os
import sys
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.dj_access import DJAccessController
from core.runtime import ensure_ytdlp_current

controller = DJAccessController(None)
subscriber = controller.subscribe(123)
for value in range(100):
    controller.get_player_snapshot = lambda guild_id, value=value: {"value": value}
    controller.publish_player_update(123)
assert subscriber.qsize() == 1
assert json.loads(subscriber.get_nowait()) == {"value": 99}
controller.unsubscribe(123, subscriber)

voice = SimpleNamespace(is_connected=lambda: False, channel=None)
guild = SimpleNamespace(voice_client=voice, name="Test")
bot = SimpleNamespace(get_guild=lambda guild_id: guild, cogs={})
snapshot = DJAccessController(bot).get_player_snapshot(123)
assert snapshot["connected"] is False
voice.is_connected = lambda: True
snapshot = DJAccessController(bot).get_player_snapshot(123)
assert snapshot["connected"] is True
assert snapshot["current_track"] is None

with patch.dict(os.environ, {}, clear=True), patch(
    "core.runtime.importlib.metadata.version", return_value="2026.10.26"
), patch("core.runtime.urllib.request.urlopen") as network, patch(
    "core.runtime.subprocess.run"
) as install:
    ensure_ytdlp_current(logging.getLogger("test"))
    network.assert_not_called()
    install.assert_not_called()

print("OK: bounded DJ snapshots, actual voice state, safe default startup")
