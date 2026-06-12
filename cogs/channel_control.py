import logging

import discord
from discord import app_commands
from discord.ext import commands

from core.bot_config import cfg
from core.log_colors import tag
from core.permissions import admin_check, perm

log = logging.getLogger("pitonazz.channel_control")

_ICON = "\U0001f451"
_CONTROL_LABELS = {
    "bot_commands_only": "Solo comandi bot",
    "no_bot_commands": "Blocca comandi bot",
}


class ChannelControl(commands.Cog):
    COG_ICON = _ICON
    COG_LABEL = "Controlli canale"
    COG_TYPE = "admin"

    channel_control = app_commands.Group(
        name="channel_control",
        description=f"{_ICON} Gestione controlli modulari sui canali",
    )

    @channel_control.command(name="set", description=f"{_ICON} Imposta un controllo su un canale")
    @app_commands.describe(canale="Canale da controllare", controllo="Tipo di controllo")
    @app_commands.choices(controllo=[
        app_commands.Choice(name="Solo comandi bot", value="bot_commands_only"),
        app_commands.Choice(name="Blocca comandi bot", value="no_bot_commands"),
    ])
    @perm("admin")
    @admin_check
    async def set_control(
        self,
        inter: discord.Interaction,
        canale: discord.TextChannel,
        controllo: str,
    ):
        changed = await cfg.set_channel_control(inter.guild_id, canale.id, controllo)
        label = _CONTROL_LABELS.get(controllo, controllo)
        suffix = "impostato" if changed else "gia impostato"
        log.info(tag("CHANCTL", f"set #{canale.name} -> {controllo}"))
        await inter.response.send_message(
            f"\u2705 {canale.mention}: **{label}** {suffix}.",
            ephemeral=True,
        )

    @channel_control.command(name="remove", description=f"{_ICON} Rimuovi il controllo da un canale")
    @app_commands.describe(canale="Canale da liberare")
    @perm("admin")
    @admin_check
    async def remove_control(self, inter: discord.Interaction, canale: discord.TextChannel):
        removed = await cfg.remove_channel_control(inter.guild_id, canale.id)
        if not removed:
            return await inter.response.send_message(
                f"\u26a0\ufe0f {canale.mention} non aveva controlli configurati.",
                ephemeral=True,
            )
        log.info(tag("CHANCTL", f"remove #{canale.name}"))
        await inter.response.send_message(
            f"\u2705 Controllo rimosso da {canale.mention}.",
            ephemeral=True,
        )

    @channel_control.command(name="list", description=f"{_ICON} Mostra i controlli canale configurati")
    @perm("admin")
    @admin_check
    async def list_controls(self, inter: discord.Interaction):
        controls = cfg.channel_controls_for_guild(inter.guild_id)
        if not controls:
            return await inter.response.send_message(
                "\U0001f4cb Nessun controllo canale configurato.",
                ephemeral=True,
            )
        lines = []
        for channel_id, control in sorted(controls.items()):
            channel = inter.guild.get_channel(channel_id) if inter.guild else None
            channel_label = channel.mention if channel else f"`{channel_id}`"
            lines.append(f"{channel_label} -> **{_CONTROL_LABELS.get(control, control)}**")
        embed = discord.Embed(
            title="\U0001f4cb Controlli canale",
            description="\n".join(lines),
            color=0x5865F2,
        )
        await inter.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(ChannelControl())
