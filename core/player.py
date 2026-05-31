from __future__ import annotations
import asyncio
import logging
import threading
import time
from typing import Optional, Callable, Awaitable

import discord
from config import Config
import core.cache_db as cache_db
from core.audio_filters import EQ_DEFAULT, compose_audio_filter, get_filter_preset, normalize_eq
from core.queue import MusicQueue
from core.source_resolver import TrackInfo, SourceResolver
from core.log_colors import tag, b, ms, title, hi, _CYN

log = logging.getLogger("pitonazz.player")

_FILTER_SEEK_OVERLAP = 0.5
_SEEK_END_GUARD_SECONDS = 0.05
_MIN_SEEK_DELTA_SECONDS = 0.01


class MusicPlayer:
    def __init__(self, guild: discord.Guild, text_channel: discord.TextChannel,
                 on_cleanup: Optional[Callable[[int], None]] = None,
                 on_autoplay: Optional[Callable[["MusicPlayer", TrackInfo], Awaitable[int]]] = None,
                 on_state_change: Optional[Callable[[int], None]] = None):
        self.guild        = guild
        self.text_channel = text_channel
        self.queue        = MusicQueue()
        self.current:     Optional[TrackInfo] = None
        self._paused:     bool  = False
        # threading.Event è thread-safe per definizione: il set/is_set/clear
        # possono essere chiamati sia dal thread asyncio sia dal thread FFmpeg
        # senza affidarsi al GIL di CPython.
        self._stopping:   threading.Event = threading.Event()
        self._idle_task:  Optional[asyncio.Task] = None
        self._player_msg: Optional[discord.Message] = None
        self._on_cleanup: Optional[Callable[[int], None]] = on_cleanup
        self._on_autoplay = on_autoplay
        self._on_state_change = on_state_change
        self._loading_count: int = 0
        self._version_switch: bool = False
        self._prefetch_task: Optional[asyncio.Task] = None

        self.filter:             Optional[str] = None
        self.filter_name:        str           = "off"
        self.eq:                 dict[str, float] = dict(EQ_DEFAULT)
        self.volume:             float         = Config.DEFAULT_VOLUME
        self._filter_replay:     bool          = False
        self._seek_position:     float         = 0.0
        self._cached_stream_url: str           = ""

        self._play_start:   float = 0.0
        self._seek_offset:  float = 0.0
        self._pause_at:     float = 0.0
        self._paused_total: float = 0.0
        self.autoplay_enabled: bool = False

    @property
    def position(self) -> float:
        if self._play_start == 0.0:
            return 0.0
        paused = self._paused_total
        if self._paused and self._pause_at > 0:
            paused += time.monotonic() - self._pause_at
        return max(0.0, self._seek_offset + (time.monotonic() - self._play_start) - paused)

    @property
    def is_paused(self) -> bool:
        return self._paused

    @property
    def vc(self) -> Optional[discord.VoiceClient]:
        return self.guild.voice_client

    def _notify_state_change(self):
        if not self._on_state_change or not self.guild:
            return
        try:
            self._on_state_change(self.guild.id)
        except Exception:
            log.debug(tag("PLAYER", "_notify_state_change failed"), exc_info=True)

    def _serialize_track(self, track: Optional[TrackInfo]) -> Optional[dict]:
        if not track:
            return None
        return {
            "title": track.title,
            "artist": track.artist,
            "duration": int(track.duration or 0),
            "thumbnail": track.thumbnail or "",
            "requester": track.requester,
            "requester_id": int(track.requester_id or 0),
            "webpage_url": track.webpage_url or "",
            "spotify_url": track.spotify_url or "",
            "source": track.source,
        }

    def to_public_state(self) -> dict:
        vc = self.vc
        return {
            "guild_id": self.guild.id if self.guild else 0,
            "connected": bool(vc),
            "voice_channel_name": getattr(getattr(vc, "channel", None), "name", ""),
            "is_paused": self.is_paused,
            "position": round(float(self.position), 2),
            "duration": int(getattr(self.current, "duration", 0) or 0),
            "volume": round(float(self.volume), 3),
            "loop_mode": self.queue.loop_mode,
            "shuffle_mode": bool(self.queue.shuffle_mode),
            "autoplay_enabled": bool(self.autoplay_enabled),
            "filter_name": self.filter_name,
            "eq": dict(self.eq),
            "current_track": self._serialize_track(self.current),
            "queue": [self._serialize_track(track) for track in self.queue.items],
        }

    async def apply_filter(self, filter_name: str, filter_str: Optional[str]):
        self.filter_name = filter_name
        self.filter      = filter_str
        if self.current and self.vc and (self.vc.is_playing() or self.vc.is_paused()):
            self._seek_position = max(0.0, self.position - _FILTER_SEEK_OVERLAP)
            t0    = time.perf_counter()
            fresh = await SourceResolver.resolve_fresh_url(self.current)
            if fresh:
                self._cached_stream_url = fresh
                elapsed = (time.perf_counter() - t0) * 1000
                log.debug(tag("FILTER", f"{b(filter_name)}  URL pre-fetchato in {ms(elapsed)}"))
            was_paused = self._paused
            self._filter_replay = True
            self.vc.stop()
            if was_paused:
                asyncio.create_task(self._repause_after_filter())
        self._notify_state_change()

    async def set_filter(self, filter_name: str):
        filter_str, _ = get_filter_preset(filter_name)
        await self.apply_filter(filter_name, filter_str)

    async def set_eq(self, eq_values: dict):
        self.eq = normalize_eq(eq_values)
        await self.apply_filter(self.filter_name, self.filter)

    def set_volume(self, volume: float) -> bool:
        try:
            normalized = float(volume)
        except (TypeError, ValueError):
            return False
        normalized = max(0.0, min(Config.MAX_VOLUME, normalized))
        self.volume = normalized
        if self.vc and self.vc.source and hasattr(self.vc.source, "volume"):
            self.vc.source.volume = normalized
        self._notify_state_change()
        return True

    def set_loop_mode(self, mode: str) -> bool:
        if mode not in {"off", "track", "queue"}:
            return False
        self.queue.loop_mode = mode
        self._notify_state_change()
        return True

    def toggle_shuffle(self) -> bool:
        self.queue.shuffle_mode = not self.queue.shuffle_mode
        if self.queue.shuffle_mode and len(self.queue) > 1:
            self.queue.shuffle()
        self._notify_state_change()
        return self.queue.shuffle_mode

    def set_autoplay(self, enabled: bool) -> None:
        self.autoplay_enabled = bool(enabled)
        self._notify_state_change()

    async def seek_relative(self, seconds: float) -> bool:
        if not self.current or not self.vc or not (self.vc.is_playing() or self.vc.is_paused()):
            return False

        current_pos = self.position
        target_pos = max(0.0, current_pos + float(seconds))
        duration = float(self.current.duration or 0)
        if duration > 0:
            # Evita seek esattamente a fine traccia: alcuni stream chiudono subito
            # e causano skip/restart immediato.
            target_pos = min(target_pos, max(0.0, duration - _SEEK_END_GUARD_SECONDS))
        # Evita restart FFmpeg inutili per seek praticamente identici.
        if abs(target_pos - current_pos) < _MIN_SEEK_DELTA_SECONDS:
            return False

        t0    = time.perf_counter()
        fresh = await SourceResolver.resolve_fresh_url(self.current)
        if fresh:
            self._cached_stream_url = fresh
            elapsed = (time.perf_counter() - t0) * 1000
            log.debug(tag("SEEK", f"URL pre-fetchato in {ms(elapsed)}"))

        self._seek_position = target_pos
        was_paused = self._paused
        self._filter_replay = True
        self.vc.stop()
        if was_paused:
            asyncio.create_task(self._repause_after_filter())
        self._notify_state_change()
        return True

    async def _prefetch_next_stream(self):
        nxt = self.queue.peek()
        if not nxt or nxt.stream_url:
            return
        t0 = time.perf_counter()
        url = await SourceResolver.resolve_fresh_url(nxt)
        elapsed = (time.perf_counter() - t0) * 1000
        if url and not nxt.stream_url:
            nxt.stream_url = url
            log.debug(tag("PREFETCH", f"{title(nxt.title)}  {ms(elapsed)}"))

    def _schedule_prefetch_next(self):
        if self._prefetch_task and not self._prefetch_task.done():
            self._prefetch_task.cancel()
        self._prefetch_task = asyncio.create_task(self._prefetch_next_stream())

    async def _repause_after_filter(self):
        """Rimette in pausa il player dopo un replay da filtro, se era in pausa.

        Attende che FFmpeg inizi la riproduzione (max 1.5s).
        Se il timeout scade senza che la riproduzione parta, logga un warning
        invece di fallire silenziosamente.
        """
        for _ in range(60):  # max 3.0s (60 × 50ms)
            await asyncio.sleep(0.05)
            if self.vc and self.vc.is_playing():
                self.pause()
                return
        log.warning(tag(
            "PLAYER",
            "_repause_after_filter: timeout — il player non ha ripreso entro 3.0s dopo il cambio filtro. "
            "La pausa non è stata ripristinata."
        ))

    def switch_version(self, track: TrackInfo):
        if not self.current:
            return
        self.current.webpage_url = track.webpage_url
        self.current.title       = track.title
        self.current.duration    = track.duration
        self.current.thumbnail   = track.thumbnail
        self.current.artist      = track.artist
        self.current.spotify_url = track.spotify_url
        self.current.source      = track.source
        self._filter_replay      = True
        self._version_switch     = True
        self._seek_position      = 0.0
        self._seek_offset        = 0.0
        self._cached_stream_url  = ""
        if self.vc and (self.vc.is_playing() or self.vc.is_paused()):
            self.vc.stop()
        self._notify_state_change()

    def _build_ffmpeg_opts(self, seek_to: float = 0.0) -> dict:
        before = Config.FFMPEG_OPTIONS["before_options"]
        if seek_to > 1.0:
            before = f"-ss {seek_to:.2f} " + before
        chain = compose_audio_filter(self.filter, self.eq)
        af   = f"-af {chain}" if chain else ""
        opts = f"-vn {af} -bufsize 64k".strip()
        return {"before_options": before, "options": opts}

    @staticmethod
    def _is_expected_ffmpeg_sigkill(err: Exception) -> bool:
        text = str(err).lower()
        return "return code of -9" in text or "sigkill" in text

    async def _try_autoplay_refill(self) -> bool:
        if not (self.autoplay_enabled and self.current and self._on_autoplay):
            return False
        try:
            added = await self._on_autoplay(self, self.current)
        except Exception as exc:
            log.warning(tag("WARN", f"autoplay refill fallita: {exc}"))
            return False
        return added > 0

    async def _retry_current_after_ffmpeg_error(self, track, depth: int) -> None:
        if self.current is not track or depth > 0:
            await self.play_next(_depth=depth + 1)
            return
        if getattr(track, "_ffmpeg_retrying", False):
            track.stream_url = ""
            await self.play_next(_depth=depth + 1)
            return

        setattr(track, "_ffmpeg_retrying", True)
        track.stream_url = ""
        self._cached_stream_url = ""
        SourceResolver.invalidate_stream_cache(track.webpage_url)
        try:
            cache_db.invalidate_webpage_url(track.webpage_url)
        except Exception:
            pass
        self._filter_replay = True
        log.warning(tag("PLAYER", f"FFmpeg fallito, refetch stream  \u2192  {title(track.title)}"))
        await self.play_next(_depth=depth + 1)

    async def play_next(self, _depth: int = 0):
        if not self.vc:
            return
        if _depth > Config.MAX_RETRY_DEPTH:
            log.error(tag("ERR", "play_next: troppi errori consecutivi, interrompo"))
            self.current = None
            self._arm_idle()
            return

        loop         = asyncio.get_running_loop()
        seek_to      = 0.0
        is_filter_ch = False
        is_version_sw = False

        if self._filter_replay and self.current:
            self._filter_replay  = False
            is_filter_ch         = True
            is_version_sw        = self._version_switch
            self._version_switch = False
            nxt                  = self.current
            seek_to              = self._seek_position
            self._seek_offset    = seek_to
        elif self.queue.loop_mode == "track" and self.current:
            nxt = self.current
            self._seek_offset = 0.0
        elif self.queue.loop_mode == "queue" and self.current:
            self.queue.put(self.current)
            nxt = self.queue.get()
            self._seek_offset = 0.0
        else:
            if self.current:
                self.queue.add_history(self.current)
            nxt = self.queue.get()
            self._seek_offset = 0.0

        if not nxt:
            if await self._try_autoplay_refill():
                await self.play_next(_depth=0)
                return
            self.current = None
            await self._delete_player_msg()
            self._arm_idle()
            return

        self.current = nxt
        # Resetta il flag di stop prima di avviare FFmpeg: garantisce che
        # l'_after callback del prossimo play non venga soppressa per errore.
        self._stopping.clear()
        try:
            t_resolve_start = time.perf_counter()
            if _depth == 0 and is_filter_ch and self._cached_stream_url:
                stream_url              = self._cached_stream_url
                self._cached_stream_url = ""
                log.info(tag("FILTER", f"Riuso URL cachato  \u2192  {title(nxt.title)}"))
            elif _depth == 0 and nxt.stream_url:
                stream_url     = nxt.stream_url
                nxt.stream_url = ""
                log.info(tag("PLAYER", f"Stream cachato  \u2192  {title(nxt.title)}"))
            else:
                stream_url = await SourceResolver.resolve_fresh_url(nxt)
            t_resolve_end = time.perf_counter()

            if not stream_url:
                log.warning(tag("WARN", f"URL scaduto  \u2192  {title(nxt.title)}  (skip)"))
                nxt.stream_url = ""
                await self.play_next(_depth=_depth + 1)
                return

            ffmpeg_opts = self._build_ffmpeg_opts(seek_to)

            t_start_play = time.perf_counter()
            source = discord.PCMVolumeTransformer(
                discord.FFmpegPCMAudio(stream_url, **ffmpeg_opts),
                volume=self.volume,
            )

            def _after(err):
                # threading.Event.is_set() è thread-safe: nessun rischio di
                # race condition tra il thread FFmpeg e il loop asyncio.
                if self._stopping.is_set():
                    self._stopping.clear()
                    return
                if err:
                    if self._is_expected_ffmpeg_sigkill(err):
                        log.debug(tag("PLAYER", f"FFmpeg stop intenzionale: {err}"))
                    else:
                        log.error(tag("ERR", f"FFmpeg error: {err}"))
                        try:
                            asyncio.run_coroutine_threadsafe(
                                self._retry_current_after_ffmpeg_error(nxt, _depth),
                                loop,
                            )
                        except RuntimeError:
                            log.debug(tag("PLAYER", "Loop chiuso, skip stream retry"))
                        return
                elif getattr(nxt, "_ffmpeg_retrying", False):
                    try:
                        delattr(nxt, "_ffmpeg_retrying")
                    except Exception:
                        pass
                try:
                    asyncio.run_coroutine_threadsafe(self.play_next(), loop)
                except RuntimeError:
                    log.debug(tag("PLAYER", "Loop chiuso, skip play_next"))

            self.vc.play(source, after=_after)
            self._play_start   = time.monotonic()
            self._pause_at     = 0.0
            self._paused_total = 0.0
            self._paused       = False
            t_end_play = time.perf_counter()
            log.info(tag(
                "PERF",
                f"play_next {title(nxt.title)}  resolve={ms((t_resolve_end-t_resolve_start)*1000)}  "
                f"start={ms((t_end_play-t_start_play)*1000)}"
            ))
            self._schedule_prefetch_next()
            self._notify_state_change()

            if not is_filter_ch:
                log.info(tag("PLAYER", f"\u25b6  {title(nxt.title)}  \u2014  {hi(nxt.source, _CYN)}"))

            if is_filter_ch and not is_version_sw:
                await self._update_msg_inplace()
            else:
                await self._repost_msg()

        except Exception as exc:
            log.error(tag("ERR", f"play_next depth={_depth}  {title(nxt.title)}: {exc}"))
            nxt.stream_url = ""
            await self.play_next(_depth=_depth + 1)

    def pause(self):
        if self.vc and self.vc.is_playing():
            self.vc.pause()
            self._paused   = True
            self._pause_at = time.monotonic()
            self._notify_state_change()

    def resume(self):
        if self.vc and self.vc.is_paused():
            self.vc.resume()
            self._paused = False
            if self._pause_at > 0:
                self._paused_total += time.monotonic() - self._pause_at
                self._pause_at = 0.0
            self._notify_state_change()

    def skip(self):
        if self.vc and (self.vc.is_playing() or self.vc.is_paused()):
            self.vc.stop()
            self._notify_state_change()

    def stop(self):
        """Ferma la riproduzione e resetta completamente lo stato.
        Usa queue.reset() per azzerare anche loop_mode e shuffle_mode,
        poiché la sessione termina. /clearqueue usa queue.clear() invece,
        che non tocca i flag.
        """
        self._stopping.set()
        if self._prefetch_task and not self._prefetch_task.done():
            self._prefetch_task.cancel()
            self._prefetch_task = None
        self.queue.reset()  # azzera coda + loop_mode + shuffle_mode
        self.current = None
        if self._idle_task and not self._idle_task.done():
            self._idle_task.cancel()
            self._idle_task = None
        if self.vc and (self.vc.is_playing() or self.vc.is_paused()):
            self.vc.stop()
        self._notify_state_change()

    def _arm_idle(self):
        if self._loading_count > 0:
            log.debug(tag("PLAYER", f"_arm_idle soppressa: {self._loading_count} fill attivi"))
            return
        if self._idle_task and not self._idle_task.done():
            self._idle_task.cancel()
        self._idle_task = asyncio.create_task(self._idle_disconnect())

    async def _idle_disconnect(self):
        """Disconnette silenziosamente dopo IDLE_TIMEOUT secondi di inattività.
        Non disconnette se il player è in pausa: lascia all'utente
        la scelta di riprendere la riproduzione.

        force=True bypassa _voice_disconnect() di discord.py che chiama
        _log.info() in modo sync, evitando un potenziale deadlock sul lock
        del logging handler che blocca il loop asyncio e impedisce i heartbeat.
        """
        await asyncio.sleep(Config.IDLE_TIMEOUT)
        if self.vc and not self.vc.is_playing() and not self._paused:
            await self._delete_player_msg()
            await self.vc.disconnect(force=True)
            if self._on_cleanup:
                self._on_cleanup(self.guild.id)
            self._notify_state_change()
        self._idle_task = None

    async def _delete_player_msg(self):
        if self._player_msg:
            try:
                await self._player_msg.delete()
            except (discord.NotFound, discord.HTTPException):
                pass
            self._player_msg = None

    async def _repost_msg(self):
        from embeds.music_embeds import now_playing_embed
        from views.player_view import PlayerView
        if self._player_msg:
            try:
                await self._player_msg.delete()
            except (discord.NotFound, discord.HTTPException):
                pass
            self._player_msg = None
        try:
            self._player_msg = await self.text_channel.send(
                embed=now_playing_embed(self), view=PlayerView(self)
            )
        except Exception as e:
            log.error(tag("ERR", f"Invio player message: {e}"))

    async def _update_msg_inplace(self):
        from embeds.music_embeds import now_playing_embed
        from views.player_view import PlayerView
        if not self._player_msg:
            return
        try:
            if self.current:
                await self._player_msg.edit(
                    embed=now_playing_embed(self), view=PlayerView(self)
                )
            else:
                await self._delete_player_msg()
        except discord.NotFound:
            self._player_msg = None

    async def send_player_message(self, channel: discord.TextChannel):
        self.text_channel = channel
        await self._repost_msg()
        self._notify_state_change()
