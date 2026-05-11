from __future__ import annotations
import asyncio
import logging
import threading
import time
from typing import Optional, Callable, Awaitable

import discord
from config import Config
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
                 on_autoplay: Optional[Callable[["MusicPlayer", TrackInfo], Awaitable[int]]] = None):
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
        self._loading_count: int = 0
        self._version_switch: bool = False
        self._prefetch_task: Optional[asyncio.Task] = None

        self.filter:             Optional[str] = None
        self.filter_name:        str           = "off"
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
                log.info(tag("FILTER", f"{b(filter_name)}  URL pre-fetchato in {ms(elapsed)}"))
            was_paused = self._paused
            self._filter_replay = True
            self.vc.stop()
            if was_paused:
                asyncio.create_task(self._repause_after_filter())

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
            log.info(tag("SEEK", f"URL pre-fetchato in {ms(elapsed)}"))

        self._seek_position = target_pos
        was_paused = self._paused
        self._filter_replay = True
        self.vc.stop()
        if was_paused:
            asyncio.create_task(self._repause_after_filter())
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
            log.info(tag("PREFETCH", f"{title(nxt.title)}  {ms(elapsed)}"))

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

    def _build_ffmpeg_opts(self, seek_to: float = 0.0) -> dict:
        before = Config.FFMPEG_OPTIONS["before_options"]
        if seek_to > 1.0:
            before = f"-ss {seek_to:.2f} " + before
        af   = f"-af {self.filter}" if self.filter else ""
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
                volume=Config.DEFAULT_VOLUME,
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

    def resume(self):
        if self.vc and self.vc.is_paused():
            self.vc.resume()
            self._paused = False
            if self._pause_at > 0:
                self._paused_total += time.monotonic() - self._pause_at
                self._pause_at = 0.0

    def skip(self):
        if self.vc and (self.vc.is_playing() or self.vc.is_paused()):
            self.vc.stop()

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
