from __future__ import annotations

import json
import logging

from core.log_colors import tag
from core.paths import DJ_ROLE_CONFIG_PATH, ensure_runtime_dirs

log = logging.getLogger("pitonazz.dj_role_store")
_PATH = DJ_ROLE_CONFIG_PATH
ensure_runtime_dirs()


def _load() -> dict:
    if not _PATH.exists():
        return {}
    try:
        return json.loads(_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        log.error(tag("ERR", f"dj_role_store: JSON corrotto ({_PATH}): {exc}"))
        return {}
    except Exception as exc:
        log.error(tag("ERR", f"dj_role_store: errore lettura JSON: {exc}"))
        return {}


def _save(data: dict) -> None:
    _PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def get_dj_role(guild_id: int) -> int | None:
    data = _load()
    raw = data.get(str(guild_id), {}).get("role_id")
    return int(raw) if isinstance(raw, int) else None


def set_dj_role(guild_id: int, role_id: int | None) -> None:
    data = _load()
    key = str(guild_id)
    if key not in data:
        data[key] = {}
    data[key]["role_id"] = role_id
    _save(data)

