"""Gestione persistenza compleanni su JSON.

Struttura assets/data/birthdays.json:
{
  "<guild_id>": {
    "channel_id":      <int|null>,
    "list_message_id": <int|null>,
    "wish_messages":   <list[str]>,
    "users": {
      "<user_id>": {"day": <int>, "month": <int>, "year": <int|null>}
    }
  }
}
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from core.log_colors import tag
from core.paths import BIRTHDAYS_PATH, ensure_runtime_dirs

log = logging.getLogger("pitonazz.birthday_store")

_DATA_PATH = BIRTHDAYS_PATH
ensure_runtime_dirs()


def _load() -> dict:
    if not _DATA_PATH.exists():
        return {}
    try:
        return json.loads(_DATA_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        log.error(tag("ERR", f"birthday_store: JSON corrotto ({_DATA_PATH}): {e}"))
        return {}
    except Exception as e:
        log.error(tag("ERR", f"birthday_store: errore lettura JSON: {e}"))
        return {}


def _save(data: dict) -> None:
    _DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        _DATA_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        log.error(tag("ERR", f"birthday_store: errore scrittura JSON: {e}"))


def _guild(data: dict, guild_id: int) -> dict:
    key = str(guild_id)
    if key not in data:
        data[key] = {"channel_id": None, "list_message_id": None, "wish_messages": [], "users": {}}
    if "list_message_id" not in data[key]:
        data[key]["list_message_id"] = None
    if "wish_messages" not in data[key]:
        data[key]["wish_messages"] = []
    return data[key]


# ── API pubblica ──────────────────────────────────────────────────────

def set_birthday(guild_id: int, user_id: int, day: int, month: int, year: Optional[int]) -> None:
    data = _load()
    g = _guild(data, guild_id)
    g["users"][str(user_id)] = {"day": day, "month": month, "year": year}
    _save(data)


def remove_birthday(guild_id: int, user_id: int) -> bool:
    data = _load()
    g = _guild(data, guild_id)
    existed = str(user_id) in g["users"]
    g["users"].pop(str(user_id), None)
    _save(data)
    return existed


def get_birthday(guild_id: int, user_id: int) -> Optional[dict]:
    data = _load()
    return data.get(str(guild_id), {}).get("users", {}).get(str(user_id))


def get_all_birthdays(guild_id: int) -> dict[str, dict]:
    data = _load()
    return data.get(str(guild_id), {}).get("users", {})


def set_channel(guild_id: int, channel_id: Optional[int]) -> None:
    data = _load()
    _guild(data, guild_id)["channel_id"] = channel_id
    _save(data)


def get_channel(guild_id: int) -> Optional[int]:
    data = _load()
    return data.get(str(guild_id), {}).get("channel_id")

def set_prompt_enabled(guild_id: int, enabled: bool) -> None:
    # Legacy no-op compat: mantenuta per non rompere import esterni.
    pass


def get_prompt_enabled(guild_id: int) -> bool:
    # Legacy compat: feature prompt IA rimossa.
    _ = guild_id
    return False


def set_wish_messages(guild_id: int, messages: list[str]) -> list[str]:
    data = _load()
    clean = [str(m).strip() for m in messages if str(m).strip()]
    _guild(data, guild_id)["wish_messages"] = clean
    _save(data)
    return clean


def get_wish_messages(guild_id: int) -> list[str]:
    data = _load()
    raw = data.get(str(guild_id), {}).get("wish_messages", [])
    return [str(m).strip() for m in raw if str(m).strip()]


def add_wish_message(guild_id: int, message: str) -> int:
    data = _load()
    g = _guild(data, guild_id)
    msgs = [str(m).strip() for m in g.get("wish_messages", []) if str(m).strip()]
    msg = str(message).strip()
    if msg:
        msgs.append(msg)
    g["wish_messages"] = msgs
    _save(data)
    return len(msgs)


def remove_wish_message(guild_id: int, index: int) -> str | None:
    data = _load()
    g = _guild(data, guild_id)
    msgs = [str(m).strip() for m in g.get("wish_messages", []) if str(m).strip()]
    if not (1 <= index <= len(msgs)):
        return None
    removed = msgs.pop(index - 1)
    g["wish_messages"] = msgs
    _save(data)
    return removed

def get_list_message_id(guild_id: int) -> Optional[int]:
    data = _load()
    return data.get(str(guild_id), {}).get("list_message_id")


def set_list_message_id(guild_id: int, message_id: Optional[int]) -> None:
    data = _load()
    _guild(data, guild_id)["list_message_id"] = message_id
    _save(data)


def get_todays_birthdays(guild_id: int, day: int, month: int) -> list[dict]:
    result = []
    for uid_str, entry in get_all_birthdays(guild_id).items():
        if entry["day"] == day and entry["month"] == month:
            result.append({"user_id": int(uid_str), **entry})
    return result
