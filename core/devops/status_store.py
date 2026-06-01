from __future__ import annotations

import json

from core.paths import CUSTOM_STATUSES_PATH


def load_custom_statuses() -> list[dict]:
    if not CUSTOM_STATUSES_PATH.exists():
        return []
    try:
        data = json.loads(CUSTOM_STATUSES_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []
    return data if isinstance(data, list) else []


def save_custom_statuses(data: list[dict]) -> None:
    CUSTOM_STATUSES_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
