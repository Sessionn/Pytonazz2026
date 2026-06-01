"""Cog /help — solo Cog e autocomplete.

Tutta la logica di raccolta comandi è in core/help_utils.py.
Tutti gli embed sono costruiti da embeds/help_embeds.py.
Le Views (UI interattiva) sono in views/help_views.py.
"""
from __future__ import annotations

from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from core.help_utils import (
    is_dev, is_admin,
    all_commands_flat, build_all_pages,
    get_cog_meta, cmd_full_name, cmd_perm,
    PERM_BADGES, DESC_PREFIX_MARKERS,
)
from ui.help.embeds import (
    build_command_embed,
    build_home_embed,
)
from ui.help.views import _CategorySelectView
from core.permissions import dev_check


# ── Cog ──────────────────────────────────────────────────────────────────

class Help(commands.Cog):
    COG_ICON  = "📚"
    COG_LABEL = "Aiuto"
    COG_TYPE  = "public"

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_app_command_error(
        self,
        inter: discord.Interaction,
        error: app_commands.AppCommandError,
    ):
        if isinstance(error, app_commands.CheckFailure):
            if inter.response.is_done():
                await inter.followup.send(
                    "❌ Non hai i permessi per usare questo comando.",
                    ephemeral=True,
                )
            else:
                await inter.response.send_message(
                    "❌ Non hai i permessi per usare questo comando.",
                    ephemeral=True,
                )
            return
        raise error

    async def _autocomplete_comando(
        self,
        inter: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        _dev   = is_dev(inter.user.id)
        _admin = is_admin(inter)
        choices = []
        current_lower = current.lower().lstrip("/")
        for cmd in sorted(all_commands_flat(self.bot, _dev, _admin), key=lambda c: cmd_full_name(c)):
            name = cmd_full_name(cmd)
            if current_lower in name.lower():
                choices.append(app_commands.Choice(name=f"/{name}", value=name))
            if len(choices) >= 25:
                break
        return choices

    @app_commands.command(name="help", description="Mostra i comandi disponibili")
    @app_commands.describe(comando="Nome del comando specifico (opzionale)")
    @app_commands.autocomplete(comando=_autocomplete_comando)
    async def help_cmd(self, inter: discord.Interaction, comando: Optional[str] = None):
        _dev   = is_dev(inter.user.id)
        _admin = is_admin(inter)

        if comando:
            match = next(
                (c for c in all_commands_flat(self.bot, _dev, _admin)
                 if cmd_full_name(c).lower() == comando.lower().lstrip("/")),
                None,
            )
            if not match:
                return await inter.response.send_message(
                    embed=discord.Embed(
                        description=f"❌ Comando `{comando}` non trovato.",
                        color=0xED4245,
                    ),
                    ephemeral=True,
                )
            return await inter.response.send_message(
                embed=build_command_embed(match, self.bot, get_cog_meta, cmd_perm, PERM_BADGES, DESC_PREFIX_MARKERS),
                ephemeral=True,
            )

        all_pages = build_all_pages(self.bot, include_dev=False, _is_dev=_dev, _is_admin=_admin)
        home      = build_home_embed(all_pages, include_dev=False, bot=self.bot, cog_meta_fn=get_cog_meta)
        view      = _CategorySelectView(all_pages, inter.user.id, include_dev=False, bot=self.bot)
        await inter.response.send_message(embed=home, view=view, ephemeral=True)

    @app_commands.command(name="devhelp", description="🔧 Comandi tecnici del bot")
    @dev_check
    async def help_dev_cmd(self, inter: discord.Interaction):
        all_pages = build_all_pages(self.bot, include_dev=True, _is_dev=True, _is_admin=True)
        home      = build_home_embed(all_pages, include_dev=True, bot=self.bot, cog_meta_fn=get_cog_meta)
        view      = _CategorySelectView(all_pages, inter.user.id, include_dev=True, bot=self.bot)
        await inter.response.send_message(embed=home, view=view, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Help(bot))
