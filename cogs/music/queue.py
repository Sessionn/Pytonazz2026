"""QueueCommands: implementation shared by the public Music facade."""
from __future__ import annotations
import logging
import discord
from discord import app_commands
from ui.music.controls import AutoplayView, autoplay_status_embed
from ui.music.embeds import error_embed, history_embed, queue_embed, skipped_track_embed, skipto_result_embed, stopped_embed, success_embed
from ui.music.queue_view import QueueView
from core.log_colors import tag, guild, user
from discord.ext import commands
log = logging.getLogger("pitonazz.music")


class QueueCommands(commands.Cog):
    @app_commands.command(name="skip", description="Salta la traccia corrente")
    async def skip(self, inter: discord.Interaction):
        p = self._players.get(inter.guild_id)
        if not p or not p.current:
            return await inter.response.send_message(
                embed=error_embed("Niente in riproduzione!"), ephemeral=True
            )
        skipped_title = p.current.title
        p.skip()
        await inter.response.send_message(embed=skipped_track_embed(skipped_title, inter.user))


    @app_commands.command(name="seek", description="Vai avanti/indietro di N secondi (es. +10 o -15)")
    @app_commands.describe(secondi="Secondi relativi (negativo = indietro, positivo = avanti)")
    async def seek(self, inter: discord.Interaction, secondi: app_commands.Range[int, -600, 600]):
        p = self._players.get(inter.guild_id)
        if not p or not p.current:
            return await inter.response.send_message(
                embed=error_embed("Niente in riproduzione!"), ephemeral=True
            )
        if secondi == 0:
            return await inter.response.send_message(
                embed=error_embed("Specifica un valore diverso da 0."), ephemeral=True
            )
        await inter.response.defer(ephemeral=True)
        ok = await p.seek_relative(float(secondi))
        if not ok:
            return await inter.edit_original_response(
                embed=error_embed("Seek non e' disponibile in questo momento.")
            )
        sign = "+" if secondi > 0 else ""
        await inter.edit_original_response(
            embed=success_embed(f"Seek applicato: **{sign}{secondi}s** (ora a ~`{int(p.position)}s`).")
        )


    @app_commands.command(name="skipto", description="Salta direttamente a una traccia specifica in coda")
    @app_commands.describe(posizione="Posizione in coda (1 = prossima traccia)")
    async def skipto(self, inter: discord.Interaction, posizione: app_commands.Range[int, 1, 500]):
        p = self._players.get(inter.guild_id)
        if not p or not p.current:
            return await inter.response.send_message(
                embed=error_embed("Niente in riproduzione!"), ephemeral=True
            )
        if posizione > len(p.queue):
            return await inter.response.send_message(
                embed=error_embed(f"La coda ha solo **{len(p.queue)}** tracce."), ephemeral=True
            )
        removed = p.skip_to(posizione - 1)
        p.skip()
        await inter.response.send_message(embed=skipto_result_embed(removed, inter.user))


    @app_commands.command(name="pause", description="Pausa")
    async def pause(self, inter: discord.Interaction):
        p = self._players.get(inter.guild_id)
        if not p or not p.current:
            return await inter.response.send_message(
                embed=error_embed("Niente in riproduzione!"), ephemeral=True
            )
        p.pause()
        await inter.response.send_message(embed=success_embed("In pausa."), ephemeral=True)


    @app_commands.command(name="resume", description="Riprendi")
    async def resume(self, inter: discord.Interaction):
        p = self._players.get(inter.guild_id)
        if not p:
            return await inter.response.send_message(
                embed=error_embed("Niente da riprendere!"), ephemeral=True
            )
        p.resume()
        await inter.response.send_message(embed=success_embed("Riproduzione ripresa."), ephemeral=True)


    @app_commands.command(name="autoplay", description="Attiva/disattiva autoplay quando la coda finisce")
    async def autoplay(self, inter: discord.Interaction):
        p = self._players.get(inter.guild_id)
        if not p:
            return await inter.response.send_message(
                embed=error_embed("Nessun player attivo."), ephemeral=True
            )
        await inter.response.send_message(
            embed=autoplay_status_embed(p.autoplay_enabled),
            view=AutoplayView(p, inter.user.id),
            ephemeral=True,
        )


    @app_commands.command(name="stop", description="Ferma, svuota la coda e disconnetti")
    async def stop(self, inter: discord.Interaction):
        p  = self._players.get(inter.guild_id)
        vc = inter.guild.voice_client
        if not p and not vc:
            return await inter.response.send_message(
                embed=error_embed("Niente da fermare!"), ephemeral=True
            )
        self._trigger_cancel(inter.guild_id)
        if p:
            await p._delete_player_msg()
            p.stop()
            self._players.pop(inter.guild_id, None)
        self._cancel_empty_task(inter.guild_id)
        if vc:
            await vc.disconnect()
        await inter.response.send_message(embed=stopped_embed(inter.user))
        log.info(tag("DISC", f"{guild(inter.guild.name)}  stop da {user(str(inter.user))}"))


    @app_commands.command(name="clearqueue", description="Svuota la coda (traccia corrente continua)")
    async def clearqueue(self, inter: discord.Interaction):
        p = self._players.get(inter.guild_id)
        if not p or not len(p.queue):
            return await inter.response.send_message(
                embed=error_embed("La coda e' gia vuota."), ephemeral=True
            )
        count = p.clear_queue()
        await inter.response.send_message(
            embed=success_embed(f"Coda svuotata: **{count}** tracce rimosse."), ephemeral=True
        )


    @app_commands.command(name="queue", description="Visualizza la coda con navigazione")
    async def queue_cmd(self, inter: discord.Interaction):
        p = self._players.get(inter.guild_id)
        if not p or (not p.current and not p.queue):
            return await inter.response.send_message(
                embed=error_embed("La coda e' vuota."), ephemeral=True
            )
        view = QueueView(p, page=0)
        await inter.response.send_message(embed=queue_embed(p, 0), view=view)
        view._message = await inter.original_response()


    @app_commands.command(name="nowplaying", description="Mostra la traccia corrente con i controlli")
    async def nowplaying(self, inter: discord.Interaction):
        p = self._players.get(inter.guild_id)
        if not p or not p.current:
            return await inter.response.send_message(
                embed=error_embed("Niente in riproduzione!"), ephemeral=True
            )
        await inter.response.defer()
        await inter.delete_original_response()
        await p.send_player_message(inter.channel)


    @app_commands.command(name="loop", description="Modalita loop")
    @app_commands.choices(modalita=[
        app_commands.Choice(name="Off", value="off"),
        app_commands.Choice(name="Traccia", value="track"),
        app_commands.Choice(name="Coda", value="queue"),
    ])
    async def loop(self, inter: discord.Interaction, modalita: str):
        p = self._players.get(inter.guild_id)
        if not p:
            return await inter.response.send_message(
                embed=error_embed("Nessun player."), ephemeral=True
            )
        p.set_loop_mode(modalita)
        labels = {"off": "Off", "track": "Traccia", "queue": "Coda"}
        await inter.response.send_message(
            embed=success_embed(f"Loop: **{labels[modalita]}**"), ephemeral=True
        )
        await p._update_msg_inplace()


    @app_commands.command(name="shuffle", description="Attiva/disattiva la modalita shuffle")
    async def shuffle(self, inter: discord.Interaction):
        p = self._players.get(inter.guild_id)
        if not p:
            return await inter.response.send_message(
                embed=error_embed("Nessun player attivo."), ephemeral=True
            )
        shuffle_enabled = p.toggle_shuffle()
        stato = "Shuffle **ON**" if shuffle_enabled else "Shuffle **OFF**"
        await inter.response.send_message(embed=success_embed(stato), ephemeral=True)
        await p._update_msg_inplace()


    @app_commands.command(name="smartshuffle", description="Mischia la coda alternando gli artisti (stile Spotify)")
    async def smartshuffle(self, inter: discord.Interaction):
        p = self._players.get(inter.guild_id)
        if not p or not len(p.queue):
            return await inter.response.send_message(
                embed=error_embed("La coda e' vuota."), ephemeral=True
            )
        p.queue.spotify_shuffle()
        p._notify_state_change()
        await inter.response.send_message(
            embed=success_embed("Coda riordinata stile Spotify! Gli artisti ora si alternano."),
            ephemeral=True,
        )


    @app_commands.command(name="remove", description="Rimuovi una traccia dalla coda")
    @app_commands.describe(posizione="Posizione (1-based)")
    async def remove(self, inter: discord.Interaction, posizione: int):
        p = self._players.get(inter.guild_id)
        if not p:
            return await inter.response.send_message(
                embed=error_embed("Nessun player."), ephemeral=True
            )
        removed = p.remove_from_queue(posizione - 1)
        if removed:
            await inter.response.send_message(
                embed=success_embed(f"Rimosso: **{removed.title}**"), ephemeral=True
            )
        else:
            await inter.response.send_message(
                embed=error_embed("Posizione non valida!"), ephemeral=True
            )


    @app_commands.command(name="move", description="Sposta una traccia in coda da una posizione a un'altra")
    @app_commands.describe(da="Posizione attuale della traccia (1-based)", a="Nuova posizione (1-based)")
    async def move(self, inter: discord.Interaction, da: int, a: int):
        p = self._players.get(inter.guild_id)
        if not p or not len(p.queue):
            return await inter.response.send_message(
                embed=error_embed("La coda e' vuota."), ephemeral=True
            )
        n = len(p.queue)
        if not (1 <= da <= n and 1 <= a <= n):
            return await inter.response.send_message(
                embed=error_embed(f"Posizioni non valide. La coda ha **{n}** tracce."), ephemeral=True
            )
        if da == a:
            return await inter.response.send_message(
                embed=error_embed("La traccia e' gia in quella posizione."), ephemeral=True
            )
        track = p.move_queue_track(da - 1, a - 1)
        if track:
            await inter.response.send_message(
                embed=success_embed(f"**{track.title}** spostata da pos. **{da}** -> **{a}**"),
                ephemeral=True,
            )
        else:
            await inter.response.send_message(
                embed=error_embed("Impossibile spostare la traccia."), ephemeral=True
            )


    @app_commands.command(name="history", description="Ultime 10 tracce riprodotte")
    async def history(self, inter: discord.Interaction):
        p = self._players.get(inter.guild_id)
        if not p or not p.queue.history:
            return await inter.response.send_message(
                embed=error_embed("Nessuna cronologia."), ephemeral=True
            )
        hist = list(reversed(list(p.queue.history)[-10:]))
        await inter.response.send_message(embed=history_embed(hist))


    @app_commands.command(name="disconnect", description="Disconnetti il bot dal canale vocale")
    async def disconnect(self, inter: discord.Interaction):
        vc = inter.guild.voice_client
        if not vc:
            return await inter.response.send_message(
                embed=error_embed("Non sono in nessun canale vocale."), ephemeral=True
            )
        self._trigger_cancel(inter.guild_id)
        p = self._players.pop(inter.guild_id, None)
        if p:
            p.stop()
        self._cancel_empty_task(inter.guild_id)
        await vc.disconnect()
        await inter.response.send_message(embed=success_embed("Disconnesso."), ephemeral=True)
        log.info(tag("DISC", f"{guild(inter.guild.name)}  disconnect da {user(str(inter.user))}"))
