from __future__ import annotations

import io
import json
import logging
import zipfile
from datetime import datetime
from pathlib import Path

from core.log_colors import b, tag
from core.paths import (
    BIRTHDAYS_PATH,
    BOT_CONFIG_PATH,
    CUSTOM_STATUSES_PATH,
    WELCOME_CONFIG_PATH,
    WELCOME_IMAGES_DIR,
)

BACKUP_FILES = [
    BOT_CONFIG_PATH,
    CUSTOM_STATUSES_PATH,
    WELCOME_CONFIG_PATH,
    BIRTHDAYS_PATH,
]

MAX_RESTORE_BYTES = 10 * 1024 * 1024  # 10 MB


def build_backup_archive(*, bot_label: str, guild_count: int, log: logging.Logger) -> tuple[io.BytesIO, str, list[str]]:
    buffer = io.BytesIO()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    included: list[str] = []

    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for file_path in BACKUP_FILES:
            if file_path.exists():
                archive.write(file_path, file_path.name)
                included.append(file_path.name)
                log.info(tag("BACKUP", f"incluso: {b(file_path.name)}"))
            elif file_path.resolve() == BIRTHDAYS_PATH.resolve():
                archive.writestr(file_path.name, "{}\n")
                included.append(file_path.name)
                log.info(tag("BACKUP", f"incluso (vuoto): {b(file_path.name)}"))
            else:
                log.info(tag("BACKUP", f"non trovato (skip): {b(file_path.name)}"))

        if WELCOME_IMAGES_DIR.exists():
            for image_path in WELCOME_IMAGES_DIR.iterdir():
                if image_path.is_file():
                    archive_name = f"welcome_images/{image_path.name}"
                    archive.write(image_path, archive_name)
                    included.append(archive_name)
                    log.info(tag("BACKUP", f"incluso: {b(archive_name)}"))

        metadata = {
            "timestamp": timestamp,
            "bot": bot_label,
            "guilds": guild_count,
            "files": included,
        }
        archive.writestr("backup_info.json", json.dumps(metadata, indent=2))

    buffer.seek(0)
    filename = f"pytonazz_backup_{timestamp}.zip"
    log.info(tag("BACKUP", f"backup esportato: {b(filename)} ({len(included)} file)"))
    return buffer, filename, included


def restore_backup_archive(data: bytes, log: logging.Logger) -> list[str]:
    buffer = io.BytesIO(data)
    restored: list[str] = []

    with zipfile.ZipFile(buffer, "r") as archive:
        names = archive.namelist()
        for file_path in BACKUP_FILES:
            if file_path.name in names:
                content = archive.read(file_path.name)
                file_path.parent.mkdir(parents=True, exist_ok=True)
                file_path.write_bytes(content)
                restored.append(file_path.name)
                log.info(tag("RESTORE", f"ripristinato: {b(file_path.name)}"))

        for name in names:
            if name.startswith("welcome_images/") and not name.endswith("/"):
                image_name = Path(name).name
                destination = WELCOME_IMAGES_DIR / image_name
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(archive.read(name))
                restored.append(name)
                log.info(tag("RESTORE", f"ripristinato: {b(name)}"))

    log.info(tag("RESTORE", f"ripristinati {b(len(restored))} file"))
    return restored
