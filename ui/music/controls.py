from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import discord

import core.cache_db as cache_db
from config import Config
from core.log_colors import tag
from ui.music.embeds import error_embed, queue_notification_embed, success_embed

if TYPE_CHECKING:
    from core.music.player import MusicPlayer

log = logging.getLogger("pitonazz.music_controls")


def progress_bar(current: int, total: int, width: int = 18) -> str:
    if total > 0:
        filled = min(width, int(width * current / total))
        pct = int(100 * current / total)
        bar = "#" * filled + "-" * (width - filled)
        return f"`{bar}` {current}/{total} ({pct}%)"
    dots = "." * ((current % 3) + 1)
    return f"`caricamento{dots}` {current} tracce"


def batch_loading_embed(nome: str, requester: discord.Member, current: int = 0, total: int = 0) -> discord.Embed:
    return discord.Embed(
        description=(
            f"Caricamento tracce di **{nome}** in corso...\n"
            f"{progress_bar(current, total)}\n"
            f"Da {requester.mention}"
        ),
        color=0x5865F2,
    )


def batch_done_embed(nome: str, total: int, requester: discord.Member) -> discord.Embed:
    return discord.Embed(
        description=(
            f"Completato: **{total}** tracce di **{nome}** caricate in coda.\n"
            f"Da {requester.mention}"
        ),
        color=0x57F287,
    )


def batch_cancelled_embed(nome: str, loaded: int, requester: discord.Member) -> discord.Embed:
    return discord.Embed(
        description=(
            f"Caricamento **{nome}** annullato.\n"
            f"Gia in coda: **{loaded}** tracce.\n"
            f"Da {requester.mention}"
        ),
        color=0xFF6B6B,
    )


def autoplay_status_embed(enabled: bool) -> discord.Embed:
    state = "ON" if enabled else "OFF"
    return success_embed(f"Autoplay: **{state}**")


async def start_if_idle(
    player: "MusicPlayer",
    vc: discord.VoiceClient,
    was_empty: bool = False,
) -> None:
    # `was_empty` remains accepted for backward compatibility with call sites
    # that decide playback based on pre-enqueue state during batch/direct adds.
    if not (vc.is_playing() or vc.is_paused()) and player.queue:
        await player.play_next()


class AutoplaySelect(discord.ui.Select):
    def __init__(self, player: "MusicPlayer", owner_id: int):
        self.player = player
        self.owner_id = owner_id
        enabled = bool(getattr(player, "autoplay_enabled", False))
        options = [
            discord.SelectOption(label="ON", value="on", default=enabled),
            discord.SelectOption(label="OFF", value="off", default=not enabled),
        ]
        super().__init__(
            placeholder="Seleziona autoplay",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, inter: discord.Interaction):
        if inter.user.id != self.owner_id:
            return await inter.response.send_message(
                "Solo chi ha aperto questo menu puo modificarlo.",
                ephemeral=True,
            )
        self.player.autoplay_enabled = self.values[0] == "on"
        self.player._notify_state_change()
        await inter.response.edit_message(
            embed=autoplay_status_embed(self.player.autoplay_enabled),
            view=AutoplayView(self.player, self.owner_id),
        )
        await self.player._update_msg_inplace()


class AutoplayView(discord.ui.View):
    def __init__(self, player: "MusicPlayer", owner_id: int):
        super().__init__(timeout=180)
        self.add_item(AutoplaySelect(player, owner_id))


class CancelBatchView(discord.ui.View):
    def __init__(self, cancel_event: asyncio.Event, requester_id: int):
        super().__init__(timeout=600)
        self._cancel_event = cancel_event
        self._requester_id = requester_id
        self._already_clicked = False

    @discord.ui.button(label="Annulla caricamento", style=discord.ButtonStyle.danger)
    async def cancel_btn(self, inter: discord.Interaction, button: discord.ui.Button):
        if inter.user.id != self._requester_id:
            return await inter.response.send_message(
                "Solo chi ha avviato il caricamento puo annullarlo.",
                ephemeral=True,
            )
        if self._already_clicked:
            return await inter.response.send_message("Gia annullato.", ephemeral=True)
        self._already_clicked = True
        self._cancel_event.set()
        button.disabled = True
        button.label = "Annullato"
        await inter.response.edit_message(view=self)

    def stop_view(self):
        for child in self.children:
            child.disabled = True  # type: ignore[attr-defined]
        self.stop()


class PlaySelect(discord.ui.Select):
    def __init__(self, player: "MusicPlayer", results, channel, requester, vc_ch, original_query: str = ""):
        self.player = player
        self.results = results
        self.channel = channel
        self.requester = requester
        self.vc_ch = vc_ch
        self.original_query = original_query
        options = []
        for index, result in enumerate(results[:7]):
            dur = f"{result.duration//60}:{result.duration%60:02d}" if result.duration else "?:??"
            label = f"{result.title[:80]} [{dur}]"[:100]
            artist = getattr(result, "artist", "") or ""
            desc = artist[:100] if artist else None
            options.append(discord.SelectOption(label=label, value=str(index), description=desc))
        super().__init__(placeholder="Scegli la versione giusta...", options=options)

    async def callback(self, inter: discord.Interaction):
        current_vc_ch = inter.user.voice.channel if inter.user.voice and inter.user.voice.channel else self.vc_ch
        try:
            idx = int(self.values[0])
            chosen = self.results[idx]
        except (ValueError, IndexError):
            return await inter.response.send_message(embed=error_embed("Selezione non valida."), ephemeral=True)
        vc = inter.guild.voice_client
        if not vc:
            vc = await current_vc_ch.connect()
        elif vc.channel != current_vc_ch:
            await vc.move_to(current_vc_ch)
        was_empty = not self.player.queue and not self.player.current
        position = 0 if was_empty else (len(self.player.queue) + 1)
        if self.original_query:
            try:
                cache_db.put(self.original_query, chosen)
            except Exception:
                log.debug(tag("CACHE", "skip manual selection cache"), exc_info=True)
        if not self.player.queue.put(chosen):
            return await inter.response.send_message(
                embed=error_embed(f"Coda piena (max {Config.MAX_QUEUE} tracce)."),
                ephemeral=True,
            )
        self.player._notify_state_change()
        await inter.response.defer()
        await inter.delete_original_response()
        await self.channel.send(embed=queue_notification_embed(chosen, position, self.requester))
        await start_if_idle(self.player, vc)


class PlaySelectView(discord.ui.View):
    def __init__(self, player: "MusicPlayer", results, channel, requester, vc_ch, original_query: str = ""):
        super().__init__(timeout=60)
        self.add_item(PlaySelect(player, results, channel, requester, vc_ch, original_query))


class VersionSelect(discord.ui.Select):
    def __init__(self, player: "MusicPlayer", results: list):
        self.player = player
        self.results = results
        options = []
        for index, result in enumerate(results[:5]):
            dur = f"{result.duration//60}:{result.duration%60:02d}" if result.duration else "?:??"
            label = f"{result.title[:85]} [{dur}]"[:100]
            options.append(discord.SelectOption(label=label, value=str(index)))
        super().__init__(placeholder="Scegli una versione...", options=options)

    async def callback(self, inter: discord.Interaction):
        try:
            idx = int(self.values[0])
            chosen = self.results[idx]
        except (ValueError, IndexError):
            return await inter.response.send_message(embed=error_embed("Selezione non valida."), ephemeral=True)
        self.player.switch_version(chosen)
        await inter.response.edit_message(
            content=f"Passato a: **{chosen.title}**",
            embed=None,
            view=None,
        )


class VersionView(discord.ui.View):
    def __init__(self, player: "MusicPlayer", results: list):
        super().__init__(timeout=60)
        self.add_item(VersionSelect(player, results))
