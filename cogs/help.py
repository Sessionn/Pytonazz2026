from __future__ import annotations

import logging
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from core.constants import command_slug
from core.log_colors import tag, b, user

log = logging.getLogger("pitonazz.help")


def _cmd_full_name(cmd) -> str:
    """Ritorna il nome completo del comando come lo mostra Discord (es. 'bday messages_remove').
    Usa qualified_name nativo di discord.py per coerenza con il dropdown e l'embed."""
    return getattr(cmd, "qualified_name", cmd.name)


def _cmd_slug(cmd) -> str:
    """Versione slug per confronti interni (spazi → underscore, lowercase)."""
    return command_slug(getattr(cmd, "qualified_name", cmd.name))


def _is_hidden(cmd) -> bool:
    return getattr(cmd, "hidden", False)


def _iter_all_commands(cog: commands.Cog):
    """Itera su tutti i comandi app_commands di un cog, inclusi i subcommand."""
    for cmd in cog.get_app_commands():
        if isinstance(cmd, app_commands.Group):
            for sub in cmd.commands:
                yield sub
        else:
            yield cmd


class HelpCog(commands.Cog):
    COG_ICON  = "\u2753"
    COG_LABEL = "Aiuto"
    COG_TYPE  = "public"

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _get_cogs_with_commands(self) -> list[tuple[commands.Cog, list]]:
        result = []
        for cog in self.bot.cogs.values():
            if getattr(cog, "COG_TYPE", None) not in ("public", "dev"):
                continue
            cmds = [c for c in _iter_all_commands(cog) if not _is_hidden(c)]
            if cmds:
                result.append((cog, cmds))
        return result

    @app_commands.command(name="help", description="\u2753 Mostra i comandi disponibili")
    @app_commands.describe(comando="Nome del comando di cui vuoi i dettagli (opzionale)")
    async def help_command(
        self,
        inter: discord.Interaction,
        comando: Optional[str] = None,
    ):
        await inter.response.defer(ephemeral=True)

        if comando:
            await self._send_command_detail(inter, comando)
        else:
            await self._send_overview(inter)

    async def _send_overview(self, inter: discord.Interaction):
        cogs_cmds = self._get_cogs_with_commands()
        if not cogs_cmds:
            return await inter.followup.send("Nessun comando disponibile.", ephemeral=True)

        options = []
        for cog, cmds in cogs_cmds:
            icon  = getattr(cog, "COG_ICON",  "\u2022")
            label = getattr(cog, "COG_LABEL", type(cog).__name__)
            options.append(
                discord.SelectOption(
                    label=f"{icon} {label}",
                    value=type(cog).__name__,
                    description=f"{len(cmds)} comand{'o' if len(cmds)==1 else 'i'}",
                )
            )

        view = HelpView(self.bot, options, cogs_cmds)
        embed = _overview_embed(cogs_cmds)
        await inter.followup.send(embed=embed, view=view, ephemeral=True)

    async def _send_command_detail(self, inter: discord.Interaction, nome: str):
        needle = command_slug(nome)
        for cog, cmds in self._get_cogs_with_commands():
            for cmd in cmds:
                if _cmd_slug(cmd) == needle:
                    embed = _command_detail_embed(cmd, cog)
                    return await inter.followup.send(embed=embed, ephemeral=True)
        await inter.followup.send(
            f"\u274c Comando `{nome}` non trovato. Usa `/help` senza parametri per la lista completa.",
            ephemeral=True,
        )

    @help_command.autocomplete("comando")
    async def comando_autocomplete(
        self, inter: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        choices = []
        for cog, cmds in self._get_cogs_with_commands():
            for cmd in cmds:
                name = _cmd_full_name(cmd)
                slug = _cmd_slug(cmd)
                if current.lower() in name.lower():
                    choices.append(app_commands.Choice(name=name, value=slug))
        return choices[:25]


class HelpView(discord.ui.View):
    def __init__(self, bot, options, cogs_cmds):
        super().__init__(timeout=120)
        self.bot = bot
        self.cogs_cmds = {type(cog).__name__: (cog, cmds) for cog, cmds in cogs_cmds}
        select = discord.ui.Select(
            placeholder="Scegli una categoria...",
            options=options,
        )
        select.callback = self._on_select
        self.add_item(select)

    async def _on_select(self, inter: discord.Interaction):
        cog_name = inter.data["values"][0]
        cog, cmds = self.cogs_cmds.get(cog_name, (None, []))
        if not cog:
            return await inter.response.send_message("Categoria non trovata.", ephemeral=True)
        embed = _cog_commands_embed(cog, cmds)
        await inter.response.edit_message(embed=embed, view=self)


def _overview_embed(cogs_cmds) -> discord.Embed:
    embed = discord.Embed(
        title="\u2753 Comandi disponibili",
        description="Scegli una categoria dal men\u00f9 qui sotto per vedere i comandi.",
        color=0x5865F2,
    )
    for cog, cmds in cogs_cmds:
        icon  = getattr(cog, "COG_ICON",  "\u2022")
        label = getattr(cog, "COG_LABEL", type(cog).__name__)
        names = ", ".join(f"`/{_cmd_full_name(c)}`" for c in cmds[:5])
        if len(cmds) > 5:
            names += f" e altri {len(cmds)-5}..."
        embed.add_field(name=f"{icon} {label}", value=names, inline=False)
    return embed


def _cog_commands_embed(cog, cmds) -> discord.Embed:
    icon  = getattr(cog, "COG_ICON",  "\u2022")
    label = getattr(cog, "COG_LABEL", type(cog).__name__)
    embed = discord.Embed(
        title=f"{icon} {label}",
        color=0x5865F2,
    )
    for cmd in cmds:
        name = _cmd_full_name(cmd)
        desc = getattr(cmd, "description", "") or ""
        embed.add_field(name=f"/{name}", value=desc or "Nessuna descrizione.", inline=False)
    return embed


def _command_detail_embed(cmd, cog) -> discord.Embed:
    icon  = getattr(cog, "COG_ICON",  "\u2022")
    label = getattr(cog, "COG_LABEL", type(cog).__name__)
    name  = _cmd_full_name(cmd)
    embed = discord.Embed(
        title=f"/{name}",
        description=getattr(cmd, "description", "") or "Nessuna descrizione.",
        color=0x5865F2,
    )
    embed.set_footer(text=f"{icon} {label}")
    params = getattr(cmd, "_params", {}) or {}
    if params:
        lines = []
        for pname, param in params.items():
            req = "" if getattr(param, "required", True) else " *(opzionale)*"
            desc = getattr(param, "description", "") or ""
            lines.append(f"`{pname}`{req} — {desc}")
        embed.add_field(name="Parametri", value="\n".join(lines), inline=False)
    return embed


async def setup(bot: commands.Bot):
    await bot.add_cog(HelpCog(bot))
