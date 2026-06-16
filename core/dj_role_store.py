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
        log.debug(tag("DJ", f"dj_role_store load: path missing {_PATH}"))
        return {}
    try:
        data = json.loads(_PATH.read_text(encoding="utf-8"))
        log.debug(tag("DJ", f"dj_role_store load: loaded {len(data)} guild entries from {_PATH}"))
        return data
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
    role_id = int(raw) if isinstance(raw, int) else None
    log.debug(tag("DJ", f"dj_role_store get guild_id={guild_id} role_id={role_id} path={_PATH}"))
    return role_id


def set_dj_role(guild_id: int, role_id: int | None) -> None:
    data = _load()
    key = str(guild_id)
    if key not in data:
        data[key] = {}
    data[key]["role_id"] = role_id
    _save(data)
    log.info(tag("DJ", f"dj_role_store set guild_id={guild_id} role_id={role_id} path={_PATH}"))
