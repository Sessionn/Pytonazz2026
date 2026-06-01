"""
tests/test_isolation_registry.py

Esecuzione:
    python tests/test_isolation_registry.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

with tempfile.TemporaryDirectory() as td:
    os.environ["ISOLATION_REGISTRY_PATH"] = str(Path(td) / "isolation_registry.json")

    from core.moderation.isolation_registry import load_quarantine_groups, save_quarantine_groups

    groups = {
        10: {
            123: {
                "members": {1, 2},
                "channel_id": 99,
                "base_name": "quarantena",
                "label": "A, B",
                "pre_channels": {1: 11, 2: None},
            }
        }
    }

    save_quarantine_groups(groups)
    loaded = load_quarantine_groups()

    assert loaded[10][123]["members"] == {1, 2}
    assert loaded[10][123]["channel_id"] == 99
    assert loaded[10][123]["base_name"] == "quarantena"
    assert loaded[10][123]["pre_channels"] == {1: 11, 2: None}

print("OK: isolation registry persist/load")
