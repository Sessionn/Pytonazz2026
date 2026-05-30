from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from config import Config
from core.dj_role_store import get_dj_role, set_dj_role
from embeds.music_embeds import error_embed, success_embed


class DJ(commands.Cog):
    COG_ICON = "🎛️"
    COG_LABEL = "DJ Console"
    COG_TYPE = "admin"

    dj = app_commands.Group(name="dj", description="Gestione accesso console DJ")

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @dj.command(name="setrole", description="Imposta il ruolo autorizzato alla console DJ")
    @app_commands.describe(ruolo="Ruolo DJ autorizzato")
    async def setrole(self, inter: discord.Interaction, ruolo: discord.Role):
        if not inter.user.guild_permissions.manage_guild:
            return await inter.response.send_message(
                embed=error_embed("Servono i permessi Gestisci Server."),
                ephemeral=True,
            )
        set_dj_role(inter.guild_id, ruolo.id)
        await inter.response.send_message(
            embed=success_embed(f"Ruolo DJ impostato su **{ruolo.name}**."),
            ephemeral=True,
        )

    @dj.command(name="clearrole", description="Rimuove il ruolo autorizzato alla console DJ")
    async def clearrole(self, inter: discord.Interaction):
        if not inter.user.guild_permissions.manage_guild:
            return await inter.response.send_message(
                embed=error_embed("Servono i permessi Gestisci Server."),
                ephemeral=True,
            )
        set_dj_role(inter.guild_id, None)
        await inter.response.send_message(
            embed=success_embed("Ruolo DJ rimosso."),
            ephemeral=True,
        )

    @dj.command(name="status", description="Mostra stato accesso console DJ")
    async def status(self, inter: discord.Interaction):
        role_id = get_dj_role(inter.guild_id)
        role = inter.guild.get_role(role_id) if role_id else None
        console_url = (
            f"{Config.DASHBOARD_PUBLIC_BASE_URL}/dj-console?guild_id={inter.guild_id}"
            if Config.DASHBOARD_PUBLIC_BASE_URL
            else "(DASHBOARD_PUBLIC_BASE_URL non configurato)"
        )
        if role:
            description = (
                f"Ruolo DJ: {role.mention}\n"
                f"Console: {console_url}\n"
                "Il pulsante `Console` è disponibile nell'embed musicale."
            )
            embed = discord.Embed(title="🎛️ Stato console DJ", description=description, color=0x57F287)
        else:
            embed = discord.Embed(
                title="🎛️ Stato console DJ",
                description="Nessun ruolo DJ configurato. Usa `/dj setrole` prima di esporre la console.",
                color=0xED4245,
            )
        await inter.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(DJ(bot))
