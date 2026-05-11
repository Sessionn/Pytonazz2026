from __future__ import annotations
import logging
from typing import TYPE_CHECKING

import discord

if TYPE_CHECKING:
    from core.player import MusicPlayer

log = logging.getLogger("pitonazz.player_view")


class PlayerView(discord.ui.View):
    def __init__(self, player: "MusicPlayer"):
        super().__init__(timeout=None)
        self.player = player
        self._build()

    def _build(self):
        self.clear_items()
        p = self.player

        # Row 0 — controlli principali
        self._add(discord.ui.Button(emoji="⏮️", style=discord.ButtonStyle.secondary,
                                    custom_id="prev",   row=0), self._cb_prev)
        if p.is_paused:
            self._add(discord.ui.Button(emoji="▶️", label="Riprendi",
                                        style=discord.ButtonStyle.success,
                                        custom_id="toggle", row=0), self._cb_toggle)
        else:
            self._add(discord.ui.Button(emoji="⏸️", label="Pausa",
                                        style=discord.ButtonStyle.primary,
                                        custom_id="toggle", row=0), self._cb_toggle)
        self._add(discord.ui.Button(emoji="⏭️", style=discord.ButtonStyle.secondary,
                                    custom_id="skip",   row=0), self._cb_skip)
        self._add(discord.ui.Button(emoji="⏹️", style=discord.ButtonStyle.danger,
                                    custom_id="stop",   row=0), self._cb_stop)

        # Row 1 — loop + shuffle
        loop_mode = p.queue.loop_mode
        _loop_cfg = {
            "off":   ("🔁", "Loop: OFF",   discord.ButtonStyle.secondary),
            "track": ("🔂", "Loop: TRACK", discord.ButtonStyle.success),
            "queue": ("🔁", "Loop: QUEUE", discord.ButtonStyle.primary),
        }
        em, lb, st = _loop_cfg[loop_mode]
        self._add(discord.ui.Button(emoji=em, label=lb, style=st,
                                    custom_id="loop", row=1), self._cb_loop)

        shuffle_style = discord.ButtonStyle.success if p.queue.shuffle_mode else discord.ButtonStyle.secondary
        shuffle_label = "Shuffle: ON" if p.queue.shuffle_mode else "Shuffle: OFF"
        self._add(discord.ui.Button(emoji="🔀", label=shuffle_label,
                                    style=shuffle_style,
                                    custom_id="shuffle", row=1), self._cb_shuffle)

        # Row 2 — coda
        self._add(discord.ui.Button(emoji="📝", label="Coda",
                                    style=discord.ButtonStyle.secondary,
                                    custom_id="queue_show", row=2), self._cb_queue)

    def _add(self, btn: discord.ui.Button, cb):
        btn.callback = cb
        self.add_item(btn)

    async def _aggiorna(self, interaction: discord.Interaction):
        from embeds.music_embeds import now_playing_embed
        self._build()
        await interaction.response.edit_message(
            embed=now_playing_embed(self.player), view=self
        )

    async def _cb_toggle(self, interaction: discord.Interaction):
        if self.player.is_paused:
            self.player.resume()
        else:
            self.player.pause()
        await self._aggiorna(interaction)

    async def _cb_skip(self, interaction: discord.Interaction):
        await interaction.response.defer()
        skipped_title = self.player.current.title if self.player.current else "Sconosciuta"
        self.player.skip()
        await interaction.channel.send(
            embed=discord.Embed(
                description=f"⏭️ **{skipped_title}** saltata da {interaction.user.mention}",
                color=0x5865F2,
            )
        )

    async def _cb_stop(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await self.player._delete_player_msg()
        self.player.stop()
        music_cog = interaction.client.cogs.get("Music")
        if music_cog:
            music_cog._cancel_empty_task(interaction.guild_id)
            music_cog._players.pop(interaction.guild_id, None)
        vc = interaction.guild.voice_client
        if vc:
            try:
                await vc.disconnect()
            except (asyncio.TimeoutError, Exception):
                # Su host remoti il graceful disconnect può andare in timeout;
                # force=True forza la pulizia locale senza attendere l'ack di Discord.
                try:
                    await vc.disconnect(force=True)
                except Exception as e:
                    log.warning("_cb_stop: disconnect forzato fallito: %s", e)
        await interaction.channel.send(
            embed=discord.Embed(
                description=f"⏹️ Riproduzione interrotta da {interaction.user.mention}",
                color=0xFF0000,
            )
        )

    async def _cb_loop(self, interaction: discord.Interaction):
        modes = ["off", "track", "queue"]
        cur   = self.player.queue.loop_mode
        self.player.queue.loop_mode = modes[(modes.index(cur) + 1) % 3]
        await self._aggiorna(interaction)

    async def _cb_shuffle(self, interaction: discord.Interaction):
        self.player.queue.shuffle_mode = not self.player.queue.shuffle_mode
        if self.player.queue.shuffle_mode and len(self.player.queue) > 1:
            self.player.queue.shuffle()
        await self._aggiorna(interaction)

    async def _cb_prev(self, interaction: discord.Interaction):
        try:
            prev = self.player.queue.history.pop()
        except IndexError:
            await interaction.response.send_message("Nessuna traccia precedente.", ephemeral=True)
            return
        if self.player.current:
            self.player.queue.prepend(self.player.current)
        self.player.queue.prepend(prev)
        self.player.skip()
        await interaction.response.defer()

    async def _cb_queue(self, interaction: discord.Interaction):
        from embeds.music_embeds import queue_embed
        from views.queue_view import QueueView
        p = self.player
        if not p.current and not p.queue:
            await interaction.response.send_message(
                embed=discord.Embed(description="📬 La coda è vuota.", color=0x5865F2),
                ephemeral=True
            )
            return
        view = QueueView(p, page=0)
        await interaction.response.send_message(
            embed=queue_embed(p, 0), view=view
        )
        try:
            view._message = await interaction.original_response()
        except Exception:
            pass
