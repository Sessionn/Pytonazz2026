"""
/backupconfig e /restoreconfig: ogni file di configurazione salvato da
comando deve uscire nello ZIP e tornare al suo posto, ruolo DJ incluso.

Esegui dalla root del progetto con:
    python tests/test_backup_roundtrip.py
"""

from __future__ import annotations

import logging
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.devops.backup as backup

log = logging.getLogger("test.backup")

with tempfile.TemporaryDirectory() as folder:
    root = Path(folder)
    originals = list(backup.BACKUP_FILES)
    original_images = backup.WELCOME_IMAGES_DIR
    files = [root / "live" / path.name for path in originals]
    backup.BACKUP_FILES[:] = files
    backup.WELCOME_IMAGES_DIR = root / "live" / "welcome_images"
    try:
        assert "dj_role_config.json" in [path.name for path in files]
        files[0].parent.mkdir(parents=True)
        for path in files:
            path.write_text(f'{{"file": "{path.name}"}}', encoding="utf-8")

        archive, _, included = backup.build_backup_archive(bot_label="bot", guild_count=1, log=log)
        assert sorted(included) == sorted(path.name for path in files), included

        for path in files:
            path.unlink()
        restored = backup.restore_backup_archive(archive.getvalue(), log)
        assert sorted(restored) == sorted(path.name for path in files), restored
        for path in files:
            assert path.read_text(encoding="utf-8") == f'{{"file": "{path.name}"}}'
    finally:
        backup.BACKUP_FILES[:] = originals
        backup.WELCOME_IMAGES_DIR = original_images

print("OK: backup/restore copre tutta la configurazione, ruolo DJ incluso")
