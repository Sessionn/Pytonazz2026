"""Music extension: lifecycle and orchestration; commands live in sibling modules."""
from .queue import QueueCommands

from .batch import BatchCommands

import asyncio
import logging
import time
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from config import Config
from core.audio_backends import create_audio_backend
from core.audio_backends.lavalink import LavalinkAudioBackend
from core.dj_access import get_dj_access_controller
from core.music.input import (
    fetch_playlist_meta,
    is_multi_url,
    is_text_search,
    normalize_url_like,
    spotify_kind,
)
from core.music.player import MusicPlayer
from core.music.session import music_session
from core.music.voice_lifecycle import voice_session_ended
from core.source_resolver import (
    SourceResolver,
    _is_yt_channel_url,
    is_spotify_artist_url,
)
from ui.music.controls import PlaySelectView, VersionView, start_if_idle
from ui.music.embeds import batch_added_embed, error_embed, queue_notification_embed, search_results_embed, success_embed, versions_embed
from core.log_colors import tag, b, ms, guild, user, ch

log = logging.getLogger("pitonazz.music")
_QUEUE_PROGRESS_STEP = 10
_PLAY_DEBOUNCE_WINDOW_SECONDS = 1.8
_PLAY_DEBOUNCE_CLEANUP_MULTIPLIER = 4
_PLAY_DEBOUNCE_GC_EVERY = 8
_BATCH_WARMUP_LIMIT = 8
_AUTOPLAY_REFILL_LIMIT = 8

# Alias legacy mantenuti per compatibilita con test/script che importano ancora
# gli helper direttamente dal cog anziche dal modulo dedicato.
_is_text_search = is_text_search
_normalize_url_like = normalize_url_like

# list= prefix comuni nelle raccolte YouTube:
# PL playlist, OLAK album/topic, RDCLAK radio/mix, UU upload canale, LL liked, FL favorites, WL watch later.


class Music(QueueCommands, BatchCommands, commands.Cog):
    COG_ICON  = "🎵"
    COG_LABEL = "Musica"
    COG_TYPE  = "public"

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        state = music_session(bot)
        self._players:        dict[int, MusicPlayer] = state.players
        self._empty_ch_tasks: dict[int, asyncio.Task] = state.empty_ch_tasks
        self._batch_cancel:   dict[int, asyncio.Event] = state.batch_cancel
        self._play_debounce:  dict[tuple[int, str], float] = state.play_debounce
        self._play_next_ticket: dict[int, int] = state.play_next_ticket
        self._play_commit_ticket: dict[int, int] = state.play_commit_ticket
        self._play_turn_conditions: dict[int, asyncio.Condition] = state.play_turn_conditions
        self._play_debounce_gc_counter: int = 0
        self._warmup_sem = state.warmup_sem
        for player in self._players.values():
            player._on_cleanup = lambda guild_id: self._players.pop(guild_id, None)
            player._on_autoplay = self._autoplay_refill
            player._on_state_change = self._notify_dj_state_change
        controller = get_dj_access_controller()
        if controller:
            controller.bind_music_cog(self)

    def _player(self, gid: int, ch_) -> MusicPlayer:
        if gid not in self._players:
            self._players[gid] = MusicPlayer(
                self.bot.get_guild(gid), ch_,
                on_cleanup=lambda guild_id: self._players.pop(guild_id, None),
                on_autoplay=self._autoplay_refill,
                on_state_change=self._notify_dj_state_change,
            )
        return self._players[gid]

    def _play_turn_condition(self, guild_id: int) -> asyncio.Condition:
        condition = self._play_turn_conditions.get(guild_id)
        if condition is None:
            condition = asyncio.Condition()
            self._play_turn_conditions[guild_id] = condition
        return condition

    def _reserve_play_turn(self, guild_id: int) -> int:
        ticket = self._play_next_ticket.get(guild_id, 0) + 1
        self._play_next_ticket[guild_id] = ticket
        self._play_commit_ticket.setdefault(guild_id, 1)
        self._play_turn_condition(guild_id)
        return ticket

    async def _wait_play_turn(self, guild_id: int, ticket: int) -> None:
        condition = self._play_turn_condition(guild_id)
        async with condition:
            while self._play_commit_ticket.get(guild_id, 1) != ticket:
                await condition.wait()

    async def _finish_play_turn(self, guild_id: int) -> None:
        condition = self._play_turn_condition(guild_id)
        async with condition:
            self._play_commit_ticket[guild_id] = self._play_commit_ticket.get(guild_id, 1) + 1
            if self._play_commit_ticket[guild_id] > self._play_next_ticket.get(guild_id, 0):
                self._play_next_ticket.pop(guild_id, None)
                self._play_commit_ticket.pop(guild_id, None)
            self._play_turn_conditions.pop(guild_id, None)
            condition.notify_all()

    async def _resolve_play_track(self, query: str, requester: str, requester_id: int):
        if Config.AUDIO_BACKEND in {"lavalink", "wavelink"}:
            backend = create_audio_backend("lavalink")
            try:
                if isinstance(backend, LavalinkAudioBackend):
                    track = await backend.resolve_track_info(
                        query,
                        requester=requester,
                        requester_id=requester_id,
                    )
                    if track:
                        return [track]
            finally:
                await backend.close()
        if is_text_search(query):
            return await SourceResolver.resolve_choices(query, requester, requester_id, n=1)
        return await SourceResolver.resolve(query, requester, requester_id)

    def _notify_dj_state_change(self, guild_id: int) -> None:
        controller = get_dj_access_controller()
        if controller:
            controller.publish_player_update(guild_id)

    def _need_voice(self, inter: discord.Interaction) -> Optional[discord.VoiceChannel]:
        return inter.user.voice.channel if inter.user.voice else None

    def _get_cancel_event(self, guild_id: int) -> asyncio.Event:
        ev = asyncio.Event()
        self._batch_cancel[guild_id] = ev
        return ev

    def _trigger_cancel(self, guild_id: int):
        ev = self._batch_cancel.get(guild_id)
        if ev:
            ev.set()

    def _is_duplicate_play(self, guild_id: int, query: str) -> bool:
        now = time.monotonic()
        normalized = (query or "").strip().lower()
        if not normalized:
            return False
        key = (guild_id, normalized)
        last = self._play_debounce.get(key, 0.0)
        self._play_debounce[key] = now
        self._play_debounce_gc_counter += 1
        if self._play_debounce_gc_counter % _PLAY_DEBOUNCE_GC_EVERY == 0:
            cutoff = now - (_PLAY_DEBOUNCE_WINDOW_SECONDS * _PLAY_DEBOUNCE_CLEANUP_MULTIPLIER)
            stale = [k for k, ts in self._play_debounce.items() if ts < cutoff]
            for stale_key in stale:
                self._play_debounce.pop(stale_key, None)
        return (now - last) <= _PLAY_DEBOUNCE_WINDOW_SECONDS

    async def _warmup_track_stream_url(self, track) -> None:
        if not track or track.stream_url or not track.webpage_url:
            return
        async with self._warmup_sem:
            t0 = time.perf_counter()
            url = await SourceResolver.resolve_fresh_url(track)
            elapsed = (time.perf_counter() - t0) * 1000
            if url and not track.stream_url:
                track.stream_url = url
                log.debug(tag("WARMUP", f"{b(track.title)}  {ms(elapsed)}"))

    async def _autoplay_refill(self, player: MusicPlayer, seed_track) -> int:
        if not seed_track:
            return 0

        raw_artist = (getattr(seed_track, "artist", "") or "").strip()
        # Euristica semplice: se il resolver salva più artisti separati da virgola,
        # autoplay usa il primo come seed principale.
        seed_artist = raw_artist.split(",")[0].strip() if raw_artist else ""
        requester = getattr(seed_track, "requester", "Autoplay")
        requester_id = int(getattr(seed_track, "requester_id", 0) or 0)
        existing_urls = {
            (getattr(t, "webpage_url", "") or "").strip()
            for t in ([player.current] + player.queue.items + list(player.queue.history))
            if t
        }

        added = 0
        try:
            if seed_artist:
                gen = SourceResolver.resolve_artist_stream(
                    seed_artist, requester, requester_id, limit=_AUTOPLAY_REFILL_LIMIT
                )
                async for track in gen:
                    url = (getattr(track, "webpage_url", "") or "").strip()
                    if not url or url in existing_urls:
                        continue
                    if not player.queue.put(track):
                        break
                    existing_urls.add(url)
                    added += 1
                    if added >= _AUTOPLAY_REFILL_LIMIT:
                        break
            else:
                query = f"{seed_track.title} audio"
                tracks = await SourceResolver.resolve(query, requester, requester_id)
                for track in tracks:
                    url = (getattr(track, "webpage_url", "") or "").strip()
                    if not url or url in existing_urls:
                        continue
                    if not player.queue.put(track):
                        break
                    existing_urls.add(url)
                    added += 1
                    if added >= _AUTOPLAY_REFILL_LIMIT:
                        break
        except Exception as exc:
            log.warning(tag("WARN", f"autoplay refill errore: {exc}"))
            return 0

        if added > 0:
            who = seed_artist or seed_track.title
            log.info(tag("QUEUE", f"Autoplay refill  +{added}  seed={b(who)}"))
            player._notify_state_change()
        return added

    async def _ensure_voice_client(
        self,
        inter: discord.Interaction,
        target_channel: discord.VoiceChannel,
        *,
        allow_move: bool = False,
    ) -> discord.VoiceClient:
        vc = inter.guild.voice_client
        if not vc:
            return await target_channel.connect()
        if allow_move and vc.channel != target_channel:
            await vc.move_to(target_channel)
        return vc


    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        g = member.guild
        if member.id == self.bot.user.id:
            if before.channel and not after.channel:
                p = self._players.get(g.id)
                self._cancel_empty_task(g.id)
                ended = await voice_session_ended(g, g.voice_client)
                # A new /play may have installed a different player meanwhile.
                if ended and self._players.get(g.id) is p:
                    self._players.pop(g.id, None)
                    if p:
                        p.stop()
                    self._trigger_cancel(g.id)
                    log.info(tag("VOICE", f"session ended guild_id={g.id}"))
                else:
                    log.info(tag("VOICE", f"player preserved after voice transition guild_id={g.id}"))
                self._notify_dj_state_change(g.id)
            elif before.channel and after.channel and before.channel != after.channel:
                p = self._players.get(g.id)
                if p:
                    if not [m for m in after.channel.members if not m.bot]:
                        self._schedule_empty_disconnect(g)
                    else:
                        self._cancel_empty_task(g.id)
            return
        vc = g.voice_client
        if not vc or not vc.channel:
            return
        if before.channel != vc.channel and after.channel != vc.channel:
            return
        if not [m for m in vc.channel.members if not m.bot]:
            self._schedule_empty_disconnect(g)
        else:
            self._cancel_empty_task(g.id)

    def _schedule_empty_disconnect(self, g):
        self._cancel_empty_task(g.id)
        self._empty_ch_tasks[g.id] = asyncio.create_task(self._empty_channel_disconnect(g))

    def _cancel_empty_task(self, guild_id: int):
        task = self._empty_ch_tasks.pop(guild_id, None)
        if task and not task.done():
            task.cancel()

    async def _empty_channel_disconnect(self, g):
        await asyncio.sleep(Config.EMPTY_CH_TIMEOUT)
        vc = g.voice_client
        if not vc:
            self._empty_ch_tasks.pop(g.id, None)
            return
        if [m for m in vc.channel.members if not m.bot]:
            self._empty_ch_tasks.pop(g.id, None)
            return
        if vc.is_paused():
            self._empty_ch_tasks.pop(g.id, None)
            return
        p = self._players.pop(g.id, None)
        if p:
            p.stop()
        self._trigger_cancel(g.id)
        if vc.is_connected():
            await vc.disconnect()
        self._empty_ch_tasks.pop(g.id, None)

    @app_commands.command(name="join", description="Fai entrare il bot nel tuo canale vocale (o quello di un utente)")
    @app_commands.describe(utente="Utente di cui entrare nel canale (default: il tuo)")
    async def join(self, inter: discord.Interaction, utente: Optional[discord.Member] = None):
        target = utente or inter.user
        if not target.voice or not target.voice.channel:
            msg = f"{target.mention} non è in nessun canale vocale." if utente else "Devi essere in un canale vocale!"
            return await inter.response.send_message(embed=error_embed(msg), ephemeral=True)
        vc_ch = target.voice.channel
        vc = inter.guild.voice_client
        if vc:
            if vc.channel == vc_ch:
                return await inter.response.send_message(embed=error_embed(f"Sono già in **{vc_ch.name}**!"), ephemeral=True)
            await vc.move_to(vc_ch)
        else:
            await vc_ch.connect()
        await inter.response.send_message(embed=success_embed(f"Entrato in **{vc_ch.name}**."), ephemeral=True)
        log.info(tag("JOIN", f"{guild(inter.guild.name)}  →  {ch(vc_ch.name)}  (da {user(str(inter.user))})"))

    @app_commands.command(name="play", description="Riproduci da YouTube, Spotify, SoundCloud o testo (risultato diretto)")
    @app_commands.describe(query="Link o titolo della canzone / playlist / album")
    async def play(self, inter: discord.Interaction, query: str):
        t_cmd = time.perf_counter()
        query = normalize_url_like(query)
        if not query:
            return await inter.response.send_message(
                embed=error_embed("Inserisci un link o una query valida."),
                ephemeral=True,
            )
        if self._is_duplicate_play(inter.guild_id, query):
            return await inter.response.send_message(
                embed=error_embed(
                    f"Richiesta duplicata rilevata: attendi ~{_PLAY_DEBOUNCE_WINDOW_SECONDS:.1f}s prima di rilanciare **/play**."
                ),
                ephemeral=True,
            )

        try:
            await inter.response.defer()
        except discord.NotFound:
            log.warning(tag("CMD", f"/play interaction scaduta prima del defer  {b(query)}"))
            return

        vc = inter.guild.voice_client
        if vc and vc.channel:
            vc_ch = vc.channel
        else:
            vc_ch = self._need_voice(inter)
            if not vc_ch:
                return await inter.edit_original_response(
                    embed=error_embed("Devi essere in un canale vocale per usare questo comando!"),
                )

        if is_spotify_artist_url(query):
            return await inter.edit_original_response(
                embed=error_embed(
                    "I link artista di Spotify non sono supportati qui.\n"
                    "Usa il comando `/artistshuffle` per riprodurre la radio di un artista! 🎨"
                ),
            )

        is_spotify_query = bool(spotify_kind(query))
        if is_spotify_query and not Config.SPOTIFY_CLIENT_ID:
            return await inter.edit_original_response(
                embed=error_embed("Per Spotify configura SPOTIFY_CLIENT_ID nel .env"),
            )

        if _is_yt_channel_url(query):
            return await inter.edit_original_response(
                embed=error_embed("I link di canali YouTube non sono supportati."),
            )

        is_multi = is_multi_url(query)
        ticket = self._reserve_play_turn(inter.guild_id)

        if is_multi:
            try:
                vc, meta = await asyncio.gather(
                    self._ensure_voice_client(inter, vc_ch),
                    fetch_playlist_meta(query),
                )
            except Exception as e:
                log.exception("Playlist resolve error")
                await self._wait_play_turn(inter.guild_id, ticket)
                try:
                    return await inter.edit_original_response(embed=error_embed("Errore: " + str(e)))
                finally:
                    await self._finish_play_turn(inter.guild_id)
            nome, total = meta
            log.info(tag("CMD", f"/play playlist  {b(nome)}  total={total}  ({b(query)})"))

            gen    = SourceResolver.resolve_stream(query, inter.user.display_name, inter.user.id)
            await self._start_batch_stream(
                inter, vc, gen,
                nome=nome, total=total, ticket=ticket,
            )
            return

        player = self._player(inter.guild_id, inter.channel)

        if is_text_search(query):
            turn_started = False
            t0 = time.perf_counter()
            try:
                vc, results = await asyncio.gather(
                    self._ensure_voice_client(inter, vc_ch),
                    self._resolve_play_track(query, inter.user.display_name, inter.user.id),
                )
            except Exception as e:
                log.exception("resolve_choices error")
                await self._wait_play_turn(inter.guild_id, ticket)
                try:
                    return await inter.edit_original_response(embed=error_embed(str(e)))
                finally:
                    await self._finish_play_turn(inter.guild_id)
            try:
                await self._wait_play_turn(inter.guild_id, ticket)
                turn_started = True
                log.info(tag("CMD", f"/play direct  {b(query)}  {ms((time.perf_counter()-t0)*1000)}"))
                if not results:
                    return await inter.edit_original_response(
                        embed=error_embed(f"Nessuna traccia trovata per: **{query}**")
                    )
                track     = results[0]
                was_empty = not player.queue and not player.current
                position  = 0 if was_empty else (len(player.queue) + 1)
                if not player.enqueue(track):
                    return await inter.edit_original_response(
                        embed=error_embed(f"Coda piena (max {Config.MAX_QUEUE} tracce).")
                    )
                t_after_resolve = time.perf_counter()
                response_task = asyncio.create_task(inter.edit_original_response(
                    embed=queue_notification_embed(track, position, inter.user)
                ))
                if was_empty:
                    t_playback = time.perf_counter()
                    await start_if_idle(player, vc, was_empty)
                    log.debug(tag("PERF", f"/play direct autostart  {ms((time.perf_counter()-t_playback)*1000)}"))
                await response_task
                if not was_empty:
                    t_playback = time.perf_counter()
                    await start_if_idle(player, vc, was_empty)
                    log.debug(tag("PERF", f"/play direct autostart  {ms((time.perf_counter()-t_playback)*1000)}"))
                log.debug(tag("PERF", f"/play direct post-resolve  {ms((time.perf_counter()-t_after_resolve)*1000)}"))
                log.info(tag("PERF", f"/play direct total={ms((time.perf_counter()-t_cmd)*1000)}"))
            finally:
                if turn_started:
                    await self._finish_play_turn(inter.guild_id)

        else:
            turn_started = False
            t0 = time.perf_counter()
            try:
                vc, tracks = await asyncio.gather(
                    self._ensure_voice_client(inter, vc_ch),
                    self._resolve_play_track(query, inter.user.display_name, inter.user.id),
                )
            except Exception as e:
                log.exception("Resolve error")
                await self._wait_play_turn(inter.guild_id, ticket)
                try:
                    return await inter.edit_original_response(embed=error_embed("Errore: " + str(e)))
                finally:
                    await self._finish_play_turn(inter.guild_id)
            try:
                await self._wait_play_turn(inter.guild_id, ticket)
                turn_started = True

                if not tracks:
                    return await inter.edit_original_response(
                        embed=error_embed(f"Nessuna traccia trovata per: **{query}**")
                    )
                was_empty = not player.queue and not player.current
                position  = 0 if was_empty else (len(player.queue) + 1)
                added     = player.enqueue_many(tracks)
                if added == 1:
                    await inter.edit_original_response(
                        embed=queue_notification_embed(tracks[0], position, inter.user)
                    )
                else:
                    await inter.edit_original_response(embed=batch_added_embed(added, inter.user))
                await start_if_idle(player, vc, was_empty)
                log.info(tag("PERF", f"/play resolve total={ms((time.perf_counter()-t_cmd)*1000)}"))
            finally:
                if turn_started:
                    await self._finish_play_turn(inter.guild_id)

    @app_commands.command(name="search", description="Cerca una canzone e scegli la versione giusta tra i risultati")
    @app_commands.describe(query="Titolo o artista da cercare")
    async def search(self, inter: discord.Interaction, query: str):
        vc_ch = self._need_voice(inter)
        if not vc_ch:
            return await inter.response.send_message(
                embed=error_embed("Devi essere in un canale vocale!"), ephemeral=True
            )
        await inter.response.defer(ephemeral=True)
        t0 = time.perf_counter()
        try:
            results = await SourceResolver.resolve_choices(
                query, inter.user.display_name, inter.user.id, n=7
            )
        except Exception as e:
            log.exception("resolve_choices error")
            return await inter.followup.send(embed=error_embed(str(e)), ephemeral=True)
        log.info(tag("CMD", f"/search  {b(query)}  {ms((time.perf_counter()-t0)*1000)}"))
        if not results:
            return await inter.followup.send(
                embed=error_embed(f"Nessun risultato per: **{query}**"), ephemeral=True
            )
        player = self._player(inter.guild_id, inter.channel)
        embed = search_results_embed(query)
        view = PlaySelectView(player, results, inter.channel, inter.user, vc_ch, query)
        await inter.followup.send(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="versions", description="Scegli una versione alternativa della traccia corrente")
    async def versions(self, inter: discord.Interaction):
        p = self._players.get(inter.guild_id)
        if not p or not p.current:
            return await inter.response.send_message(
                embed=error_embed("Nessuna traccia in riproduzione."), ephemeral=True
            )
        await inter.response.defer(ephemeral=True)
        track = p.current
        search_query = (getattr(track, "origin_query", "") or "").strip()
        if not search_query:
            artist = (track.artist or "").split(",")[0].strip()
            search_query = f"{track.title} {artist}".strip()
        try:
            results = await SourceResolver.resolve_choices(
                search_query,
                track.requester, track.requester_id, n=5,
            )
        except Exception as e:
            log.exception("versions resolve_choices error")
            return await inter.followup.send(embed=error_embed(str(e)), ephemeral=True)
        if not results:
            return await inter.followup.send(
                embed=error_embed("Nessuna alternativa trovata."), ephemeral=True
            )
        embed = versions_embed(track.title)
        await inter.followup.send(embed=embed, view=VersionView(p, results), ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))
