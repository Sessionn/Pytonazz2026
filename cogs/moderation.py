import logging
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands

from config import Config
from core.log_colors import tag, b, user, ch

log = logging.getLogger("pitonazz.moderation")

_BULK_CUTOFF = timedelta(weeks=2)
_CROWN = "👑"


class Moderation(commands.Cog):
    COG_ICON  = "🛡️"
    COG_LABEL = "Moderazione"
    COG_TYPE  = "admin"

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @staticmethod
    def _can_moderate(actor: discord.Member, target: discord.Member) -> bool:
        return actor.guild.owner_id == actor.id or actor.top_role > target.top_role

    @staticmethod
    def _bot_can_moderate(bot_member: discord.Member | None, target: discord.Member) -> bool:
        return bool(bot_member and bot_member.top_role > target.top_role)

    async def cog_app_command_error(self, inter: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            if not inter.response.is_done():
                await inter.response.send_message(
                    "❌ Non hai i permessi necessari per usare questo comando.", ephemeral=True
                )
        elif isinstance(error, app_commands.CheckFailure):
            if not inter.response.is_done():
                await inter.response.send_message(
                    "❌ Solo il proprietario del bot può usare questo comando.", ephemeral=True
                )
        else:
            log.error(tag("MOD", f"command error → {error}"))
            if not inter.response.is_done():
                await inter.response.send_message(f"❌ Errore: `{error}`", ephemeral=True)

    # ──────────────────────────────────────────────────────────────
    # /purge
    # ──────────────────────────────────────────────────────────────

    @app_commands.command(name="purge", description=f"{_CROWN} Elimina un numero di messaggi dal canale")
    @app_commands.describe(quantita="Messaggi da eliminare (1-100)")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def purge(
        self,
        inter: discord.Interaction,
        quantita: app_commands.Range[int, 1, 100],
    ):
        await inter.response.defer(ephemeral=True)
        cutoff  = discord.utils.utcnow() - _BULK_CUTOFF
        deleted = await inter.channel.purge(
            limit=quantita,
            check=lambda m: m.created_at > cutoff,
            oldest_first=False,
            bulk=True,
        )
        msg = f"🗑️ Eliminati **{len(deleted)}** messaggi."
        if len(deleted) < quantita:
            msg += "\n*(Alcuni saltati perché più vecchi di 14 giorni — limite Discord)*"
        await inter.followup.send(msg, ephemeral=True)
        log.info(tag("MOD", f"purge  {b(len(deleted))} msg  {ch(inter.channel.name)}  da {user(str(inter.user))}"))

    # ──────────────────────────────────────────────────────────────
    # /ruolo  (migrato da cogs/roles.py)
    # ──────────────────────────────────────────────────────────────

    @app_commands.command(
        name="ruolo",
        description=f"{_CROWN} Assegna o rimuovi un ruolo a un utente",
    )
    @app_commands.describe(
        utente="Utente a cui assegnare / rimuovere il ruolo",
        ruolo="Ruolo da assegnare o rimuovere",
    )
    @app_commands.checks.has_permissions(manage_roles=True)
    async def ruolo(
        self,
        inter: discord.Interaction,
        utente: discord.Member,
        ruolo: discord.Role,
    ):
        bot_member = inter.guild.me
        if ruolo >= bot_member.top_role:
            return await inter.response.send_message(
                embed=discord.Embed(
                    description=(
                        f"❌ Non posso gestire il ruolo **{ruolo.name}** perché è pari o superiore "
                        f"al mio ruolo più alto (**{bot_member.top_role.name}**). "
                        "Sposta il mio ruolo sopra di esso nelle impostazioni del server."
                    ),
                    color=0xFF5555,
                ),
                ephemeral=True,
            )

        try:
            if ruolo in utente.roles:
                await utente.remove_roles(ruolo, reason=f"Rimosso da {inter.user}")
                azione = "rimosso"
                colore = 0xFF5555
                emoji  = "🟥"
            else:
                await utente.add_roles(ruolo, reason=f"Assegnato da {inter.user}")
                azione = "assegnato"
                colore = 0x57F287
                emoji  = "🟢"

            log.info(tag("MOD", f"/ruolo  {b(ruolo.name)}  {azione}  →  {b(utente.display_name)}"))
            await inter.response.send_message(
                embed=discord.Embed(
                    description=f"{emoji} Ruolo **{ruolo.name}** {azione} a {utente.mention}.",
                    color=colore,
                ),
                ephemeral=True,
            )

        except discord.Forbidden:
            log.warning(tag("MOD", f"/ruolo Forbidden: {b(ruolo.name)} su {b(utente.display_name)}"))
            await inter.response.send_message(
                embed=discord.Embed(
                    description=(
                        f"❌ Permesso negato per il ruolo **{ruolo.name}**. "
                        "Assicurati che il mio ruolo sia sopra di esso e che io abbia il permesso **Gestisci ruoli**."
                    ),
                    color=0xFF5555,
                ),
                ephemeral=True,
            )

    @app_commands.command(name="kick", description=f"{_CROWN} Espelle un utente dal server")
    @app_commands.describe(utente="Utente da espellere", motivo="Motivo (opzionale)")
    @app_commands.default_permissions(kick_members=True)
    @app_commands.checks.has_permissions(kick_members=True)
    async def kick(self, inter: discord.Interaction, utente: discord.Member, motivo: str = "Nessun motivo specificato"):
        if utente.id == inter.user.id:
            return await inter.response.send_message("❌ Non puoi espellere te stesso.", ephemeral=True)
        if utente.id == inter.guild.owner_id:
            return await inter.response.send_message("❌ Non puoi espellere il proprietario del server.", ephemeral=True)
        if not self._can_moderate(inter.user, utente):
            return await inter.response.send_message("❌ Non puoi moderare questo utente (gerarchia ruoli).", ephemeral=True)
        if not self._bot_can_moderate(inter.guild.me, utente):
            return await inter.response.send_message("❌ Non posso moderare questo utente (gerarchia ruoli).", ephemeral=True)
        try:
            await utente.kick(reason=f"{motivo} | da {inter.user}")
            await inter.response.send_message(f"👢 {utente.mention} espulso.\nMotivo: {motivo}", ephemeral=True)
            log.info(tag("MOD", f"kick {user(str(utente))} da {user(str(inter.user))} motivo={b(motivo)}"))
        except discord.Forbidden:
            await inter.response.send_message("❌ Permessi insufficienti per espellere questo utente.", ephemeral=True)
        except discord.HTTPException as exc:
            await inter.response.send_message(f"❌ Errore durante il kick: `{exc}`", ephemeral=True)

    @app_commands.command(name="ban", description=f"{_CROWN} Banna un utente dal server")
    @app_commands.describe(utente="Utente da bannare", motivo="Motivo (opzionale)")
    @app_commands.default_permissions(ban_members=True)
    @app_commands.checks.has_permissions(ban_members=True)
    async def ban(self, inter: discord.Interaction, utente: discord.Member, motivo: str = "Nessun motivo specificato"):
        if utente.id == inter.user.id:
            return await inter.response.send_message("❌ Non puoi bannare te stesso.", ephemeral=True)
        if utente.id == inter.guild.owner_id:
            return await inter.response.send_message("❌ Non puoi bannare il proprietario del server.", ephemeral=True)
        if not self._can_moderate(inter.user, utente):
            return await inter.response.send_message("❌ Non puoi moderare questo utente (gerarchia ruoli).", ephemeral=True)
        if not self._bot_can_moderate(inter.guild.me, utente):
            return await inter.response.send_message("❌ Non posso moderare questo utente (gerarchia ruoli).", ephemeral=True)
        try:
            await inter.guild.ban(utente, reason=f"{motivo} | da {inter.user}", delete_message_days=0)
            await inter.response.send_message(f"🔨 {utente.mention} bannato.\nMotivo: {motivo}", ephemeral=True)
            log.info(tag("MOD", f"ban {user(str(utente))} da {user(str(inter.user))} motivo={b(motivo)}"))
        except discord.Forbidden:
            await inter.response.send_message("❌ Permessi insufficienti per bannare questo utente.", ephemeral=True)
        except discord.HTTPException as exc:
            await inter.response.send_message(f"❌ Errore durante il ban: `{exc}`", ephemeral=True)

    @app_commands.command(name="timeout", description=f"{_CROWN} Applica un timeout temporaneo a un utente")
    @app_commands.describe(
        utente="Utente da mutare temporaneamente",
        minuti="Durata in minuti (1-10080)",
        motivo="Motivo (opzionale)",
    )
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.checks.has_permissions(moderate_members=True)
    async def timeout(
        self,
        inter: discord.Interaction,
        utente: discord.Member,
        minuti: app_commands.Range[int, 1, 10080],
        motivo: str = "Nessun motivo specificato",
    ):
        if utente.id == inter.user.id:
            return await inter.response.send_message("❌ Non puoi applicare timeout a te stesso.", ephemeral=True)
        if utente.id == inter.guild.owner_id:
            return await inter.response.send_message("❌ Non puoi applicare timeout al proprietario del server.", ephemeral=True)
        if not self._can_moderate(inter.user, utente):
            return await inter.response.send_message("❌ Non puoi moderare questo utente (gerarchia ruoli).", ephemeral=True)
        if not self._bot_can_moderate(inter.guild.me, utente):
            return await inter.response.send_message("❌ Non posso moderare questo utente (gerarchia ruoli).", ephemeral=True)
        until = discord.utils.utcnow() + timedelta(minutes=int(minuti))
        try:
            await utente.timeout(until, reason=f"{motivo} | da {inter.user}")
            await inter.response.send_message(
                f"⏱️ Timeout applicato a {utente.mention} per **{minuti}** minuti.\nMotivo: {motivo}",
                ephemeral=True,
            )
            log.info(tag("MOD", f"timeout {user(str(utente))} {b(str(minuti))}m da {user(str(inter.user))}"))
        except discord.Forbidden:
            await inter.response.send_message("❌ Permessi insufficienti per applicare timeout.", ephemeral=True)
        except discord.HTTPException as exc:
            await inter.response.send_message(f"❌ Errore durante il timeout: `{exc}`", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Moderation(bot))
