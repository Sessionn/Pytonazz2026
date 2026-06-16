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
from core.log_colors import tag

log = logging.getLogger("pitonazz.dj_access")


class DJAccessController:
    def __init__(self, bot):
        self.bot = bot
        self._music_cog = None
        self._subscribers: dict[int, set[queue.Queue[str]]] = {}
        self._lock = threading.Lock()

    def bind_music_cog(self, music_cog) -> None:
        self._music_cog = music_cog
        log.info(tag("DJ", f"access bound music_cog={type(music_cog).__name__}"))

    def _resolve_music_cog(self):
        if self._music_cog is not None:
            return self._music_cog
        if not self.bot:
            log.debug(tag("DJ", "resolve music cog: bot missing"))
            return None
        cog = getattr(self.bot, "cogs", {}).get("Music")
        if cog is not None:
            self._music_cog = cog
            log.debug(tag("DJ", "resolve music cog: matched named cog Music"))
            return cog
        for candidate in getattr(self.bot, "cogs", {}).values():
            if hasattr(candidate, "_players"):
                self._music_cog = candidate
                log.debug(tag("DJ", f"resolve music cog: matched {type(candidate).__name__} via _players"))
                return candidate
        log.debug(tag("DJ", "resolve music cog: no candidate found"))
        return None

    def _find_player(self, guild_id: int):
        music_cog = self._resolve_music_cog()
        if music_cog and hasattr(music_cog, "_players"):
            player = music_cog._players.get(guild_id)
            if player:
                log.debug(tag("DJ", f"found player in bound cog guild_id={guild_id}"))
                return player
        for candidate in getattr(self.bot, "cogs", {}).values():
            players = getattr(candidate, "_players", None)
            if isinstance(players, dict):
                player = players.get(guild_id)
                if player:
                    self._music_cog = candidate
                    msg = f"found player by scan guild_id={guild_id} cog={type(candidate).__name__}"
                    log.debug(tag("DJ", msg))
                    return player
        log.debug(tag("DJ", f"player not found guild_id={guild_id}"))
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
            log.exception(tag("DJ", "publish_player_update snapshot failed"))
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
        if guild:
            msg = (
                f"snapshot request guild_id={guild_id} guild={guild.name} "
                f"connected={bool(voice_client)} has_player={bool(player)}"
            )
            log.debug(tag("DJ", msg))
        else:
            log.warning(tag("DJ", f"snapshot guild missing guild_id={guild_id}"))
        if not player:
            if voice_client:
                msg = (
                    f"snapshot without player guild_id={guild_id} "
                    f"voice={voice_name} has_music_cog={bool(self._resolve_music_cog())}"
                )
                log.warning(tag("DJ", msg))
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
                "base_filter_name": "off",
                "active_fx_names": [],
                "filter_catalog": {
                    "base_filters": [],
                    "fx_filters": [],
                },
                "eq": {"low": 0.0, "mid": 0.0, "high": 0.0},
                "tone_filters": {"highpass_hz": 0.0, "lowpass_hz": 20000.0},
                "current_track": None,
                "queue": [],
            }
        snapshot = player.to_public_state()
        current = snapshot.get("current_track") or {}
        msg = (
            f"snapshot ready guild_id={guild_id} connected={snapshot.get('connected')} "
            f"title={current.get('title')} paused={snapshot.get('is_paused')}"
        )
        log.debug(tag("DJ", msg))
        return snapshot

    async def _resolve_member(self, guild_id: int, user_id: int, force_refresh: bool = False):
        if not self.bot or not getattr(self.bot, "is_ready", lambda: False)():
            log.debug(tag("DJ", f"bot not ready guild_id={guild_id} user_id={user_id}"))
            return None, "bot_not_ready"
        guild = self.bot.get_guild(guild_id)
        if not guild:
            log.info(tag("DJ", f"guild not found guild_id={guild_id} user_id={user_id}"))
            return None, "guild_not_found"
        member = None if force_refresh else guild.get_member(user_id)
        if member:
            log.debug(tag("DJ", f"member cache hit guild_id={guild_id} user_id={user_id}"))
            return member, None
        try:
            member = await guild.fetch_member(user_id)
        except discord.NotFound:
            log.info(tag("DJ", f"member not found guild_id={guild_id} user_id={user_id}"))
            return None, "member_not_found"
        except discord.HTTPException:
            log.warning(tag("DJ", f"member lookup failed guild_id={guild_id} user_id={user_id}"), exc_info=True)
            return None, "member_lookup_failed"
        log.debug(tag("DJ", f"member fetched remotely guild_id={guild_id} user_id={user_id}"))
        return member, None

    @staticmethod
    def _member_has_role(member: discord.Member, role_id: int) -> bool:
        return any(role.id == role_id for role in getattr(member, "roles", ()))

    async def _check_access_async(self, guild_id: int, user_id: int) -> tuple[bool, str | None]:
        role_id = get_dj_role(guild_id)
        if not role_id:
            log.info(tag("DJ", f"denied role not configured guild_id={guild_id} user_id={user_id}"))
            return False, "dj_role_not_configured"
        member, err = await self._resolve_member(guild_id, user_id)
        if not member:
            level = logging.DEBUG if err == "bot_not_ready" else logging.INFO
            log.log(
                level,
                tag(
                    "DJ",
                    f"denied member unresolved guild_id={guild_id} "
                    f"user_id={user_id} role_id={role_id} error={err}",
                ),
            )
            return False, err
        if self._member_has_role(member, role_id):
            log.debug(tag("DJ", f"granted guild_id={guild_id} user_id={user_id} role_id={role_id}"))
            return True, None
        refreshed_member, refresh_err = await self._resolve_member(guild_id, user_id, force_refresh=True)
        if refreshed_member and self._member_has_role(refreshed_member, role_id):
            msg = f"granted after refresh guild_id={guild_id} user_id={user_id} role_id={role_id}"
            log.info(tag("DJ", msg))
            return True, None
        if refresh_err and refresh_err != "member_lookup_failed":
            msg = (
                f"refresh unresolved guild_id={guild_id} user_id={user_id} "
                f"role_id={role_id} error={refresh_err}"
            )
            log.info(tag("DJ", msg))
        roles = [getattr(role, "id", None) for role in getattr((refreshed_member or member), "roles", ())]
        msg = (
            f"denied missing role guild_id={guild_id} user_id={user_id} "
            f"role_id={role_id} roles={roles}"
        )
        log.info(tag("DJ", msg))
        return False, "missing_dj_role"

    def check_access(self, guild_id: int, user_id: int, timeout: float = 8.0) -> tuple[bool, str | None]:
        try:
            future = asyncio.run_coroutine_threadsafe(
                self._check_access_async(guild_id, user_id),
                self.bot.loop,
            )
            return future.result(timeout=timeout)
        except FuturesTimeoutError:
            log.warning(tag("DJ", f"access timeout guild_id={guild_id} user_id={user_id} timeout={timeout}"))
            return False, "bot_timeout"
        except Exception:
            log.exception(tag("DJ", f"check_access failed guild_id={guild_id} user_id={user_id}"))
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
        elif action == "set_base_filter":
            await player.set_base_filter(str(payload.get("filter_name", "off")))
        elif action == "reset_mixer":
            player.reset_live_mixer()
        elif action == "toggle_filter_fx":
            await player.toggle_filter_fx(
                str(payload.get("fx_name", "")),
                bool(payload.get("enabled", False)),
            )
        elif action == "set_eq":
            await player.set_eq(payload.get("eq") or {})
        elif action == "set_tone_filters":
            await player.set_tone_filters(payload.get("tone_filters") or {})
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
            log.exception(tag("DJ", "perform_action failed"))
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
