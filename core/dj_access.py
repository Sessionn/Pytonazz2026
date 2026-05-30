from __future__ import annotations

import asyncio
import json
import logging
import queue
import secrets
import threading
from concurrent.futures import TimeoutError as FuturesTimeoutError
from typing import Any

import discord

from core.dj_role_store import get_dj_role

log = logging.getLogger("pitonazz.dj_access")


class DJAccessController:
    def __init__(self, bot):
        self.bot = bot
        self._music_cog = None
        self._subscribers: dict[int, set[queue.Queue[str]]] = {}
        self._lock = threading.Lock()

    def bind_music_cog(self, music_cog) -> None:
        self._music_cog = music_cog

    def _resolve_music_cog(self):
        if self._music_cog is not None:
            return self._music_cog
        if not self.bot:
            return None
        cog = getattr(self.bot, "cogs", {}).get("Music")
        if cog is not None:
            self._music_cog = cog
            return cog
        for candidate in getattr(self.bot, "cogs", {}).values():
            if hasattr(candidate, "_players"):
                self._music_cog = candidate
                return candidate
        return None

    def _find_player(self, guild_id: int):
        music_cog = self._resolve_music_cog()
        if music_cog and hasattr(music_cog, "_players"):
            player = music_cog._players.get(guild_id)
            if player:
                return player
        for candidate in getattr(self.bot, "cogs", {}).values():
            players = getattr(candidate, "_players", None)
            if isinstance(players, dict):
                player = players.get(guild_id)
                if player:
                    self._music_cog = candidate
                    return player
        return None

    def subscribe(self, guild_id: int) -> queue.Queue[str]:
        q: queue.Queue[str] = queue.Queue()
        with self._lock:
            self._subscribers.setdefault(guild_id, set()).add(q)
        return q

    def unsubscribe(self, guild_id: int, q: queue.Queue[str]) -> None:
        with self._lock:
            subs = self._subscribers.get(guild_id)
            if not subs:
                return
            subs.discard(q)
            if not subs:
                self._subscribers.pop(guild_id, None)

    def publish_player_update(self, guild_id: int) -> None:
        try:
            payload = json.dumps(self.get_player_snapshot(guild_id), separators=(",", ":"))
        except Exception:
            log.exception("publish_player_update snapshot failed")
            return
        with self._lock:
            subscribers = list(self._subscribers.get(guild_id, ()))
        for q in subscribers:
            try:
                q.put_nowait(payload)
            except Exception:
                pass

    def get_player_snapshot(self, guild_id: int) -> dict[str, Any]:
        player = self._find_player(guild_id)
        guild = self.bot.get_guild(guild_id) if self.bot else None
        voice_client = guild.voice_client if guild else None
        voice_name = getattr(getattr(voice_client, "channel", None), "name", "")
        if not player:
            if voice_client:
                log.warning(
                    "DJ snapshot without player [guild_id=%s, voice_channel=%s, has_music_cog=%s]",
                    guild_id,
                    voice_name,
                    bool(self._resolve_music_cog()),
                )
            return {
                "guild_id": guild_id,
                "connected": bool(voice_client),
                "voice_channel_name": voice_name,
                "is_paused": False,
                "position": 0.0,
                "duration": 0,
                "volume": 0.0,
                "loop_mode": "off",
                "shuffle_mode": False,
                "autoplay_enabled": False,
                "filter_name": "off",
                "eq": {"low": 0.0, "mid": 0.0, "high": 0.0},
                "current_track": None,
                "queue": [],
            }
        return player.to_public_state()

    async def _resolve_member(self, guild_id: int, user_id: int):
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return None, "guild_not_found"
        member = guild.get_member(user_id)
        if member:
            return member, None
        try:
            member = await guild.fetch_member(user_id)
        except discord.NotFound:
            return None, "member_not_found"
        except discord.HTTPException:
            return None, "member_lookup_failed"
        return member, None

    async def _check_access_async(self, guild_id: int, user_id: int) -> tuple[bool, str | None]:
        role_id = get_dj_role(guild_id)
        if not role_id:
            return False, "dj_role_not_configured"
        member, err = await self._resolve_member(guild_id, user_id)
        if not member:
            return False, err
        if any(role.id == role_id for role in getattr(member, "roles", ())):
            return True, None
        return False, "missing_dj_role"

    def check_access(self, guild_id: int, user_id: int, timeout: float = 8.0) -> tuple[bool, str | None]:
        try:
            future = asyncio.run_coroutine_threadsafe(
                self._check_access_async(guild_id, user_id),
                self.bot.loop,
            )
            return future.result(timeout=timeout)
        except FuturesTimeoutError:
            return False, "bot_timeout"
        except Exception:
            log.exception("check_access failed")
            return False, "internal_error"

    def build_oauth_state(self, guild_id: int) -> str:
        return f"{guild_id}:{secrets.token_urlsafe(12)}"

    async def _perform_action_async(self, guild_id: int, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        player = self._find_player(guild_id)
        guild = self.bot.get_guild(guild_id) if self.bot else None
        if action == "stop" and guild and not player and guild.voice_client:
            await guild.voice_client.disconnect()
            return {"ok": True}
        if not player:
            return {"ok": False, "error": "player_not_found"}

        if action == "toggle_play":
            if player.is_paused:
                player.resume()
            else:
                player.pause()
        elif action == "stop":
            await player._delete_player_msg()
            player.stop()
            if self._music_cog:
                self._music_cog._players.pop(guild_id, None)
                self._music_cog._cancel_empty_task(guild_id)
            if guild and guild.voice_client:
                await guild.voice_client.disconnect()
        elif action == "skip":
            player.skip()
        elif action == "seek_relative":
            if not await player.seek_relative(float(payload.get("seconds", 0.0))):
                return {"ok": False, "error": "seek_unavailable"}
        elif action == "set_volume":
            if not player.set_volume(float(payload.get("volume", 0.0))):
                return {"ok": False, "error": "invalid_volume"}
        elif action == "set_loop_mode":
            if not player.set_loop_mode(str(payload.get("mode", "off"))):
                return {"ok": False, "error": "invalid_loop_mode"}
        elif action == "toggle_shuffle":
            player.toggle_shuffle()
        elif action == "set_autoplay":
            player.set_autoplay(bool(payload.get("enabled", False)))
        elif action == "set_filter":
            await player.set_filter(str(payload.get("filter_name", "off")))
        elif action == "set_eq":
            await player.set_eq(payload.get("eq") or {})
        else:
            return {"ok": False, "error": "invalid_action"}

        self.publish_player_update(guild_id)
        return {"ok": True}

    def perform_action(self, guild_id: int, action: str, payload: dict[str, Any], timeout: float = 10.0) -> dict[str, Any]:
        try:
            future = asyncio.run_coroutine_threadsafe(
                self._perform_action_async(guild_id, action, payload),
                self.bot.loop,
            )
            return future.result(timeout=timeout)
        except FuturesTimeoutError:
            return {"ok": False, "error": "bot_timeout"}
        except Exception:
            log.exception("perform_action failed")
            return {"ok": False, "error": "internal_error"}


_controller: DJAccessController | None = None


def init_dj_access_controller(bot) -> DJAccessController:
    global _controller
    if _controller is None:
        _controller = DJAccessController(bot)
    else:
        _controller.bot = bot
    return _controller


def get_dj_access_controller() -> DJAccessController | None:
    return _controller
