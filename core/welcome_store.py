"""Persistenza configurazione Welcome/Goodbye + AutoRole per guild.

Struttura JSON:
{
  "<guild_id>": {
    "auto_role_id": null,          -- ID ruolo assegnato automaticamente al join
    "welcome": {
      "channel_id": 123,
      "enabled": true,
      "title": "...",
      "description": "...",
      "footer": null,
      "color": 5765120,
      "thumbnail_url": null,
      "image_url": null,
      "author_name": null,
      "author_icon_url": null,
      "fields": [
        {"name": "Comportati bene", "value": "o finirai nel gulag!", "inline": false}
      ]
    },
    "goodbye": { ... stessa struttura ... }
  }
}

Placeholder supportati in tutti i campi testo:
  {mention}       - @utente
  {name}          - username
  {display_name}  - nickname sul server
  {guild}         - nome del server
  {count}         - numero di membri attuali
"""
from __future__ import annotations

import json
import logging
from typing import Any

from core.log_colors import tag
from core.paths import WELCOME_CONFIG_PATH, ensure_runtime_dirs

_PATH = WELCOME_CONFIG_PATH
ensure_runtime_dirs()
log = logging.getLogger("pitonazz.welcome_store")

_DEFAULT_WELCOME: dict = {
    "channel_id":      None,
    "enabled":         True,
    "title":           "Benvenuto/a!",
    "description":     "\U0001f44b {mention} \u00e8 entrato/a in **{guild}**!",
    "footer":          None,
    "color":           0x57F287,
    "thumbnail_url":   None,
    "image_url":       None,
    "author_name":     None,
    "author_icon_url": None,
    "fields":          [],
}

_DEFAULT_GOODBYE: dict = {
    "channel_id":      None,
    "enabled":         True,
    "title":           "Addio!",
    "description":     "\U0001f44b **{display_name}** ha lasciato il server.",
    "footer":          None,
    "color":           0xED4245,
    "thumbnail_url":   None,
    "image_url":       None,
    "author_name":     None,
    "author_icon_url": None,
    "fields":          [],
}


def _load() -> dict:
    if not _PATH.exists():
        return {}
    try:
        return json.loads(_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        log.error(tag("ERR", f"welcome_store: JSON corrotto ({_PATH}): {e}"))
        return {}
    except Exception as e:
        log.error(tag("ERR", f"welcome_store: errore lettura JSON: {e}"))
        return {}


def _save(data: dict) -> None:
    _PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _guild_cfg(data: dict, guild_id: int) -> dict:
    key = str(guild_id)
    if key not in data:
        data[key] = {
            "auto_role_id": None,
            "welcome": dict(_DEFAULT_WELCOME) | {"fields": []},
            "goodbye": dict(_DEFAULT_GOODBYE) | {"fields": []},
        }
    # migration: aggiungi chiavi mancanti a strutture esistenti
    if "auto_role_id" not in data[key]:
        data[key]["auto_role_id"] = None
    for ev in ("welcome", "goodbye"):
        if ev in data[key] and "fields" not in data[key][ev]:
            data[key][ev]["fields"] = []
    return data[key]


def get_config(guild_id: int, event: str) -> dict:
    data = _load()
    gc   = _guild_cfg(data, guild_id)
    cfg  = gc.get(event, {})
    base = dict(_DEFAULT_WELCOME if event == "welcome" else _DEFAULT_GOODBYE)
    base.update(cfg)
    if "fields" not in base:
        base["fields"] = []
    return base


def set_field(guild_id: int, event: str, field: str, value: Any) -> None:
    data = _load()
    gc   = _guild_cfg(data, guild_id)
    if event not in gc:
        gc[event] = dict(_DEFAULT_WELCOME if event == "welcome" else _DEFAULT_GOODBYE) | {"fields": []}
    gc[event][field] = value
    _save(data)


def add_embed_field(guild_id: int, event: str, name: str, value: str, inline: bool = False) -> int:
    """Aggiunge un field. Ritorna il numero di fields totali dopo l'aggiunta."""
    data = _load()
    gc   = _guild_cfg(data, guild_id)
    if event not in gc:
        gc[event] = dict(_DEFAULT_WELCOME if event == "welcome" else _DEFAULT_GOODBYE) | {"fields": []}
    if "fields" not in gc[event]:
        gc[event]["fields"] = []
    gc[event]["fields"].append({"name": name, "value": value, "inline": inline})
    _save(data)
    return len(gc[event]["fields"])


def remove_embed_field(guild_id: int, event: str, index: int) -> dict | None:
    """Rimuove il field all'indice (1-based). Ritorna il field rimosso o None se fuori range."""
    data = _load()
    gc   = _guild_cfg(data, guild_id)
    fields = gc.get(event, {}).get("fields", [])
    if not (1 <= index <= len(fields)):
        return None
    removed = fields.pop(index - 1)
    gc[event]["fields"] = fields
    _save(data)
    return removed


def reset_config(guild_id: int, event: str) -> None:
    data = _load()
    gc   = _guild_cfg(data, guild_id)
    gc[event] = dict(_DEFAULT_WELCOME if event == "welcome" else _DEFAULT_GOODBYE) | {"fields": []}
    _save(data)


# ── AutoRole ─────────────────────────────────────────────────────────────────

def get_auto_role(guild_id: int) -> int | None:
    data = _load()
    gc   = _guild_cfg(data, guild_id)
    return gc.get("auto_role_id")


def set_auto_role(guild_id: int, role_id: int | None) -> None:
    data = _load()
    gc   = _guild_cfg(data, guild_id)
    gc["auto_role_id"] = role_id
    _save(data)
