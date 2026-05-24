"""Persistent quarantine/isolation registry."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

DEFAULT_PATH = Path("data") / "isolation_registry.json"


def _path() -> Path:
    raw = os.getenv("ISOLATION_REGISTRY_PATH", "").strip()
    return Path(raw) if raw else DEFAULT_PATH


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def load_quarantine_groups() -> dict[int, dict[int, dict]]:
    path = _path()
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    groups: dict[int, dict[int, dict]] = {}
    for gid_raw, guild_groups in (raw.get("guilds") or {}).items():
        gid = _to_int(gid_raw)
        if not gid or not isinstance(guild_groups, dict):
            continue
        groups[gid] = {}
        for gkey_raw, info in guild_groups.items():
            if not isinstance(info, dict):
                continue
            gkey = _to_int(gkey_raw)
            if not gkey:
                continue
            members = {_to_int(uid) for uid in info.get("members", [])}
            members.discard(0)
            pre_channels = {
                _to_int(uid): (_to_int(cid) or None)
                for uid, cid in (info.get("pre_channels") or {}).items()
            }
            groups[gid][gkey] = {
                "members": members,
                "channel_id": _to_int(info.get("channel_id")),
                "base_name": str(info.get("base_name") or "quarantena"),
                "label": str(info.get("label") or ""),
                "pre_channels": pre_channels,
            }
        if not groups[gid]:
            groups.pop(gid, None)
    return groups


def save_quarantine_groups(groups: dict[int, dict[int, dict]]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)

    payload: dict[str, dict[str, dict]] = {"guilds": {}}
    for gid, guild_groups in groups.items():
        serialized_groups: dict[str, dict] = {}
        for gkey, info in guild_groups.items():
            members = sorted(int(uid) for uid in info.get("members", set()))
            if not members:
                continue
            serialized_groups[str(int(gkey))] = {
                "members": members,
                "channel_id": int(info.get("channel_id") or 0),
                "base_name": str(info.get("base_name") or "quarantena"),
                "label": str(info.get("label") or ""),
                "pre_channels": {
                    str(int(uid)): (int(cid) if cid else None)
                    for uid, cid in (info.get("pre_channels") or {}).items()
                },
            }
        if serialized_groups:
            payload["guilds"][str(int(gid))] = serialized_groups

    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
