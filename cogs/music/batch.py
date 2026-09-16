"""BatchCommands: implementation shared by the public Music facade."""
from __future__ import annotations
import asyncio
import logging
import time
from typing import AsyncIterable, Optional
import discord
from discord import app_commands
from config import Config
from core.source_resolver import SourceResolver
from ui.music.controls import CancelBatchView, batch_cancelled_embed, batch_done_embed, batch_loading_embed, start_if_idle
from ui.music.embeds import error_embed, queue_notification_embed
from core.log_colors import tag, b, ms
from discord.ext import commands
log = logging.getLogger("pitonazz.music")

_QUEUE_PROGRESS_STEP = 10

_BATCH_WARMUP_LIMIT = 8


class BatchCommands(commands.Cog):
    async def _start_batch_stream(
        self,
        inter: discord.Interaction,
        vc: discord.VoiceClient,
        gen: AsyncIterable,
        *,
        nome: str,
        total: int,
        ticket: int,
        do_spotify_shuffle: bool = False,
    ):
        cancel_event = self._get_cancel_event(inter.guild_id)
        cancel_view = CancelBatchView(cancel_event, inter.user.id)

        try:
            await inter.edit_original_response(
                embed=batch_loading_embed(nome, inter.user, current=0, total=total),
                view=cancel_view,
            )
        except Exception:
            await self._wait_play_turn(inter.guild_id, ticket)
            await self._finish_play_turn(inter.guild_id)
            raise
        await self._load_batch(
            inter, vc, gen,
            nome=nome, total=total,
            ticket=ticket,
            cancel_event=cancel_event,
            do_spotify_shuffle=do_spotify_shuffle,
            keep_loading_embed=True,
            cancel_view=cancel_view,
        )


    async def _load_batch(
        self,
        inter: discord.Interaction,
        vc: discord.VoiceClient,
        gen,
        nome: str,
        total: int,
        ticket: int,
        cancel_event: asyncio.Event,
        do_spotify_shuffle: bool = False,
        keep_loading_embed: bool = False,
        cancel_view: Optional["CancelBatchView"] = None,
    ):
        player = self._player(inter.guild_id, inter.channel)
        turn_started = False

        try:
            first = await gen.__anext__()
        except StopAsyncIteration:
            await self._wait_play_turn(inter.guild_id, ticket)
            try:
                return await inter.edit_original_response(
                    embed=error_embed(f"Nessuna traccia trovata per: **{nome}**"), view=None
                )
            finally:
                await self._finish_play_turn(inter.guild_id)
        except Exception as e:
            log.exception("_load_batch: errore prima traccia")
            await self._wait_play_turn(inter.guild_id, ticket)
            try:
                return await inter.edit_original_response(embed=error_embed("Errore: " + str(e)), view=None)
            finally:
                await self._finish_play_turn(inter.guild_id)

        await self._wait_play_turn(inter.guild_id, ticket)
        turn_started = True
        was_empty = not player.queue and not player.current
        position = 0 if was_empty else (len(player.queue) + 1)
        if not player.queue.put(first):
            await self._finish_play_turn(inter.guild_id)
            turn_started = False
            return await inter.edit_original_response(
                embed=error_embed(f"Coda piena (max {Config.MAX_QUEUE} tracce)."),
                view=None,
            )
        log.info(tag("QUEUE", f"[001] {b(first.title)}  —  {first.source}  (prima traccia)"))
        if turn_started:
            await self._finish_play_turn(inter.guild_id)
        turn_started = False
        if not was_empty:
            asyncio.create_task(self._warmup_track_stream_url(first))

        if cancel_view is None:
            cancel_view = CancelBatchView(cancel_event, inter.user.id)

        if keep_loading_embed:
            # La risposta originale è già la barra progresso mostrata dal
            # chiamante: aggiorniamo view con il cancel_view appena creato.
            await inter.edit_original_response(
                embed=batch_loading_embed(nome, inter.user, current=1, total=total),
                view=cancel_view,
            )
            load_msg = await inter.original_response()
            await inter.channel.send(embed=queue_notification_embed(
                first,
                position,
                inter.user,
                collection_name=nome,
                collection_total=total,
            ))
        else:
            await inter.edit_original_response(
                embed=queue_notification_embed(
                    first,
                    position,
                    inter.user,
                    collection_name=nome,
                    collection_total=total,
                )
            )
            load_msg = await inter.channel.send(
                embed=batch_loading_embed(nome, inter.user, current=1, total=total),
                view=cancel_view,
            )

        await start_if_idle(player, vc, was_empty)

        asyncio.create_task(self._fill_queue(
            gen, player, inter.channel,
            nome=nome, requester=inter.user,
            load_msg=load_msg, first_already_added=True,
            do_spotify_shuffle=do_spotify_shuffle, total=total,
            edit_load_msg=not keep_loading_embed,
            inter=inter if keep_loading_embed else None,
            cancel_event=cancel_event,
            cancel_view=cancel_view,
        ))
        if turn_started:
            await self._finish_play_turn(inter.guild_id)


    async def _fill_queue(
        self,
        gen,
        player,
        channel,
        nome: str = "",
        requester: discord.Member = None,
        load_msg: discord.Message = None,
        first_already_added: bool = False,
        do_spotify_shuffle: bool = False,
        total: int = 0,
        edit_load_msg: bool = True,
        inter: discord.Interaction = None,
        cancel_event: asyncio.Event = None,
        cancel_view: "CancelBatchView" = None,
    ):
        """Carica tracce in coda aggiornando la progress bar. Rispetta cancel_event."""
        player._loading_count += 1
        count        = 0
        added_so_far = 1 if first_already_added else 0
        UPDATE_EVERY = 3
        cancelled    = False
        t_batch      = time.perf_counter()

        try:
            async for track in gen:
                if cancel_event and cancel_event.is_set():
                    cancelled = True
                    log.info(tag("QUEUE", f"fill_queue annullato  [{nome}]  dopo {added_so_far} tracce"))
                    break

                if not player.queue.put(track):
                    log.warning(tag("WARN", f"Coda piena (MAX_QUEUE={Config.MAX_QUEUE}), tracce scartate"))
                    break
                count        += 1
                added_so_far += 1
                log.debug(tag("QUEUE", f"[{count+1:03d}] {b(track.title)}  -  {track.source}"))
                if added_so_far <= _BATCH_WARMUP_LIMIT:
                    asyncio.create_task(self._warmup_track_stream_url(track))
                if added_so_far % _QUEUE_PROGRESS_STEP == 0:
                    pct = f"{(100 * added_so_far / total):.0f}%" if total > 0 else "in corso"
                    log.info(tag("QUEUE", f"Progress  [{nome}]  {b(str(added_so_far))} tracce  ({pct})"))

                if requester and count % UPDATE_EVERY == 0:
                    loading_embed = batch_loading_embed(
                        nome, requester, current=added_so_far, total=total
                    )
                    try:
                        if edit_load_msg and load_msg:
                            await load_msg.edit(embed=loading_embed)
                        elif inter:
                            await inter.edit_original_response(embed=loading_embed, view=cancel_view)
                    except Exception:
                        pass

        except Exception as e:
            log.error(tag("ERR", f"fill_queue: {e}"))
        finally:
            player._loading_count -= 1
            if player._loading_count == 0 and not player.current and not player.queue:
                player._arm_idle()

        if do_spotify_shuffle and not cancelled and len(player.queue) > 1:
            player.queue.spotify_shuffle()

        total_loaded = count + 1 if first_already_added else count
        elapsed = ms((time.perf_counter() - t_batch) * 1000)
        state = "annullato" if cancelled else "completato"
        log.info(tag("QUEUE", f"Batch {state}  [{nome}]  {b(str(total_loaded))} tracce  {elapsed}"))

        if cancel_view:
            cancel_view.stop_view()

        if cancelled:
            final_embed = batch_cancelled_embed(nome or "Playlist", total_loaded, requester) if requester                 else discord.Embed(description=f"Caricamento annullato. **{total_loaded}** tracce in coda.", color=0xFF6B6B)
        else:
            final_embed = batch_done_embed(nome or "Playlist", total_loaded, requester) if requester                 else discord.Embed(description=f"Aggiunte **{total_loaded}** tracce in coda.", color=0x57F287)

        try:
            if edit_load_msg and load_msg:
                await load_msg.edit(embed=final_embed, view=None)
            elif inter:
                await inter.edit_original_response(embed=final_embed, view=None)
            else:
                await channel.send(embed=final_embed)
        except Exception:
            await channel.send(embed=final_embed)
        player._notify_state_change()


    @app_commands.command(
        name="artistshuffle",
        description="Emula la radio artista di Spotify: top tracks + raccomandazioni, mischiati in modo intelligente"
    )
    @app_commands.describe(nome="Nome dell'artista", quantita="Quante tracce (1-50, default 20)")
    async def artistshuffle(
        self, inter: discord.Interaction,
        nome: str,
        quantita: app_commands.Range[int, 1, 50] = 20
    ):
        await inter.response.defer()

        vc_ch = self._need_voice(inter)
        if not vc_ch:
            return await inter.edit_original_response(
                embed=error_embed("Devi essere in un canale vocale!")
            )

        vc = await self._ensure_voice_client(inter, vc_ch, allow_move=True)

        gen = SourceResolver.resolve_artist_stream(
            nome, inter.user.display_name, inter.user.id, limit=quantita
        )

        await self._start_batch_stream(
            inter, vc, gen,
            nome=nome, total=quantita,
            do_spotify_shuffle=True,
        )
