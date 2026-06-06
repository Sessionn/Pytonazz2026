import logging

import discord
from discord import app_commands
from discord.ext import commands

from core.audio_filters import get_filter_preset
from embeds.music_embeds import error_embed, success_embed

log = logging.getLogger("pitonazz.filters")


class Filters(commands.Cog):
    COG_ICON = "🎚️"
    COG_LABEL = "Filtri Audio"
    COG_TYPE = "public"

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _get_player(self, guild_id: int):
        for cog in self.bot.cogs.values():
            if hasattr(cog, "_players"):
                return cog._players.get(guild_id)
        return None

    async def _apply_named_filter(self, inter: discord.Interaction, filtro: str):
        await inter.response.defer(ephemeral=True)
        p = self._get_player(inter.guild_id)
        if not p:
            return await inter.followup.send(
                embed=error_embed("Nessun player attivo. Avvia una riproduzione prima."),
                ephemeral=True,
            )
        if not p.current:
            return await inter.followup.send(
                embed=error_embed("Nessuna traccia in riproduzione."),
                ephemeral=True,
            )
        _, label = get_filter_preset(filtro)
        await p.set_filter(filtro)
        await inter.followup.send(
            embed=success_embed(f"Filtro: **{label}**\nRiprende dal punto corrente."),
            ephemeral=True,
        )

    @app_commands.command(name="filteroff", description="Disattiva i filtri audio")
    async def filter_off(self, inter: discord.Interaction):
        await inter.response.defer(ephemeral=True)
        p = self._get_player(inter.guild_id)
        if not p:
            return await inter.followup.send(
                embed=error_embed("Nessun player attivo. Avvia una riproduzione prima."),
                ephemeral=True,
            )
        p.reset_live_mixer()
        await inter.followup.send(
            embed=success_embed("Mixer resettato: filtri, FX, EQ e tone riportati allo stato neutro."),
            ephemeral=True,
        )

    @app_commands.command(name="nightcore", description="Applica il filtro Nightcore")
    async def filter_nightcore(self, inter: discord.Interaction):
        await self._apply_named_filter(inter, "nightcore")

    @app_commands.command(name="vaporwave", description="Applica il filtro Vaporwave")
    async def filter_vaporwave(self, inter: discord.Interaction):
        await self._apply_named_filter(inter, "vaporwave")

    @app_commands.command(name="audio8d", description="Applica il filtro 8D Audio")
    async def filter_8d(self, inter: discord.Interaction):
        await self._apply_named_filter(inter, "8d")

    @app_commands.command(name="bassboost", description="Applica il filtro Bass Boost")
    async def filter_bassboost(self, inter: discord.Interaction):
        await self._apply_named_filter(inter, "bassboost")

    @app_commands.command(name="trebleboost", description="Applica il filtro Treble Boost")
    async def filter_trebleboost(self, inter: discord.Interaction):
        await self._apply_named_filter(inter, "trebleboost")

    @app_commands.command(name="vocalboost", description="Applica il filtro Vocal Boost")
    async def filter_vocalboost(self, inter: discord.Interaction):
        await self._apply_named_filter(inter, "vocalboost")

    @app_commands.command(name="radio", description="Applica il filtro Radio / Phone")
    async def filter_radio(self, inter: discord.Interaction):
        await self._apply_named_filter(inter, "radio")

    @app_commands.command(name="nightmode", description="Applica il filtro Night Mode")
    async def filter_night(self, inter: discord.Interaction):
        await self._apply_named_filter(inter, "night")


async def setup(bot: commands.Bot):
    await bot.add_cog(Filters(bot))
