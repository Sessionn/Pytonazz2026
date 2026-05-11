import asyncio
import logging
from datetime import timedelta
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from config import Config
from core.log_colors import tag, b, user, ch
from core.permissions import admin_check, perm

log = logging.getLogger("pitonazz.moderation")

_BULK_CUTOFF = timedelta(weeks=2)
_CROWN = "👑"


class Moderation(commands.Cog):
    COG_ICON  = "🛡️"
    COG_LABEL = "Moderazione"
    COG_TYPE  = "admin"

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # guild_id -> {user_id: channel_id}  — utenti in quarantena attiva
        self._quarantined: dict[int, dict[int, int]] = {}
        # guild_id -> {user_id: True}  — utenti con microfono mutato via /museruola
        self._muted_mic: dict[int, set[int]] = {}
        # guild_id -> {user_id: True}  — utenti sordati via /jenniserpi
        self._deafened: dict[int, set[int]] = {}

    # ── Helpers gerarchia ─────────────────────────────────────────

    @staticmethod
    def _can_moderate(actor: discord.Member, target: discord.Member) -> bool:
        return actor.guild.owner_id == actor.id or actor.top_role > target.top_role

    @staticmethod
    def _bot_can_moderate(bot_member: Optional[discord.Member], target: discord.Member) -> bool:
        return bool(bot_member and bot_member.top_role > target.top_role)

    # ── Errori ────────────────────────────────────────────────────

    async def cog_app_command_error(self, inter: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            if not inter.response.is_done():
                await inter.response.send_message(
                    "❌ Non hai i permessi necessari per usare questo comando.", ephemeral=True
                )
        elif isinstance(error, app_commands.CheckFailure):
            if not inter.response.is_done():
                await inter.response.send_message(
                    "❌ Non hai i permessi per usare questo comando.", ephemeral=True
                )
        else:
            log.error(tag("MOD", f"command error → {error}"))
            if not inter.response.is_done():
                await inter.response.send_message(f"❌ Errore: `{error}`", ephemeral=True)

    # ── Listener quarantena ───────────────────────────────────────

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ):
        gid = member.guild.id
        quarantine_map = self._quarantined.get(gid, {})
        if member.id not in quarantine_map:
            return
        target_channel_id = quarantine_map[member.id]

        # L'utente ha lasciato il server (quit): non fare nulla,
        # ma la sessione rimane attiva — se rientra verrà ributtato.
        if after.channel is None:
            return

        # L'utente è già nel canale corretto.
        if after.channel.id == target_channel_id:
            return

        # L'utente ha tentato di spostarsi: riportarlo dentro.
        target_ch = member.guild.get_channel(target_channel_id)
        if target_ch is None:
            # Il canale quarantena è stato eliminato: rimuovi la sessione.
            quarantine_map.pop(member.id, None)
            return
        try:
            await asyncio.sleep(0.3)  # piccolo delay per evitare loop API
            await member.move_to(target_ch, reason="Quarantena attiva — spostamento non autorizzato")
            log.info(tag("MOD", f"quarantena ributtato {user(str(member))} in {ch(target_ch.name)}"))
        except discord.Forbidden:
            pass
        except discord.HTTPException:
            pass

    # ── /purge ────────────────────────────────────────────────────

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

    # ── /ruolo ────────────────────────────────────────────────────

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

    # ── /kick ─────────────────────────────────────────────────────

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

    # ── /ban ──────────────────────────────────────────────────────

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

    # ── /timeout ──────────────────────────────────────────────────

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

    # ── /museruola ────────────────────────────────────────────────
    # Muta il microfono vocale dell'utente a livello server.
    # La sessione rimane attiva finché non disabilitata con /museruola_off.
    # Funziona anche se l'utente non è in VC al momento: appena entra,
    # il listener on_voice_state_update applica il mute.

    @app_commands.command(name="museruola", description=f"{_CROWN} Muta permanentemente il microfono di uno o più utenti (finché non rimosso)")
    @app_commands.describe(
        utenti="Utenti da mutare, separati da spazio (menzioni o ID)",
    )
    @perm("admin")
    @admin_check
    async def museruola(
        self,
        inter: discord.Interaction,
        utenti: str,
    ):
        await inter.response.defer(ephemeral=True)
        gid = inter.guild.id
        if gid not in self._muted_mic:
            self._muted_mic[gid] = set()

        members = await self._resolve_members(inter.guild, utenti)
        if not members:
            return await inter.followup.send("❌ Nessun utente valido trovato.", ephemeral=True)

        applied, skipped = [], []
        for m in members:
            self._muted_mic[gid].add(m.id)
            if m.voice and m.voice.channel:
                try:
                    await m.edit(mute=True, reason=f"/museruola da {inter.user}")
                    applied.append(m.display_name)
                except discord.Forbidden:
                    skipped.append(f"{m.display_name} (permesso negato)")
            else:
                applied.append(f"{m.display_name} (sessione attiva, si applica al join VC)")

        lines = [f"🔇 **Museruola attiva** per {len(applied)} utenti."]
        if applied:
            lines.append("✅ " + ", ".join(applied))
        if skipped:
            lines.append("⚠️ Saltati: " + ", ".join(skipped))
        lines.append("\nUsa `/museruola_off` per rimuovere.")
        await inter.followup.send("\n".join(lines), ephemeral=True)
        log.info(tag("MOD", f"/museruola → {[m.display_name for m in members]} da {user(str(inter.user))}"))

    @app_commands.command(name="museruola_off", description=f"{_CROWN} Rimuove la museruola da uno o più utenti")
    @app_commands.describe(utenti="Utenti da smutare, separati da spazio (menzioni o ID). 'all' per tutti.")
    @perm("admin")
    @admin_check
    async def museruola_off(
        self,
        inter: discord.Interaction,
        utenti: str,
    ):
        await inter.response.defer(ephemeral=True)
        gid = inter.guild.id
        muted = self._muted_mic.get(gid, set())

        if utenti.strip().lower() == "all":
            targets_ids = list(muted)
            members = [inter.guild.get_member(uid) for uid in targets_ids]
            members = [m for m in members if m]
        else:
            members = await self._resolve_members(inter.guild, utenti)

        if not members:
            return await inter.followup.send("❌ Nessun utente valido trovato.", ephemeral=True)

        removed = []
        for m in members:
            muted.discard(m.id)
            if m.voice and m.voice.channel:
                try:
                    await m.edit(mute=False, reason=f"/museruola_off da {inter.user}")
                except discord.Forbidden:
                    pass
            removed.append(m.display_name)

        await inter.followup.send(f"🔊 Museruola rimossa da: {', '.join(removed)}", ephemeral=True)
        log.info(tag("MOD", f"/museruola_off → {removed} da {user(str(inter.user))}"))

    @app_commands.command(name="museruola_lista", description=f"{_CROWN} Mostra gli utenti con museruola o sordina attiva")
    @perm("admin")
    @admin_check
    async def museruola_lista(self, inter: discord.Interaction):
        gid = inter.guild.id
        muted = self._muted_mic.get(gid, set())
        deaf  = self._deafened.get(gid, set())

        embed = discord.Embed(title="🔇 Sessioni punitive attive", color=0xE67E22)

        if muted:
            nomi = []
            for uid in muted:
                m = inter.guild.get_member(uid)
                nomi.append(m.display_name if m else f"ID:{uid}")
            embed.add_field(name="🎙️ Museruola (mic muto)", value="\n".join(nomi), inline=False)
        else:
            embed.add_field(name="🎙️ Museruola (mic muto)", value="*Nessuno*", inline=False)

        if deaf:
            nomi = []
            for uid in deaf:
                m = inter.guild.get_member(uid)
                nomi.append(m.display_name if m else f"ID:{uid}")
            embed.add_field(name="🔕 Jenni Serpi (audio sordo)", value="\n".join(nomi), inline=False)
        else:
            embed.add_field(name="🔕 Jenni Serpi (audio sordo)", value="*Nessuno*", inline=False)

        await inter.response.send_message(embed=embed, ephemeral=True)

    # ── /jenniserpi ───────────────────────────────────────────────
    # Sorda l'audio dell'utente a livello server (non sente nulla in VC).

    @app_commands.command(name="jenniserpi", description=f"{_CROWN} Sorda permanentemente l'audio di uno o più utenti (finché non rimosso)")
    @app_commands.describe(utenti="Utenti da sordare, separati da spazio (menzioni o ID)")
    @perm("admin")
    @admin_check
    async def jenniserpi(
        self,
        inter: discord.Interaction,
        utenti: str,
    ):
        await inter.response.defer(ephemeral=True)
        gid = inter.guild.id
        if gid not in self._deafened:
            self._deafened[gid] = set()

        members = await self._resolve_members(inter.guild, utenti)
        if not members:
            return await inter.followup.send("❌ Nessun utente valido trovato.", ephemeral=True)

        applied, skipped = [], []
        for m in members:
            self._deafened[gid].add(m.id)
            if m.voice and m.voice.channel:
                try:
                    await m.edit(deafen=True, reason=f"/jenniserpi da {inter.user}")
                    applied.append(m.display_name)
                except discord.Forbidden:
                    skipped.append(f"{m.display_name} (permesso negato)")
            else:
                applied.append(f"{m.display_name} (sessione attiva, si applica al join VC)")

        lines = [f"🔕 **Jenni Serpi attiva** per {len(applied)} utenti."]
        if applied:
            lines.append("✅ " + ", ".join(applied))
        if skipped:
            lines.append("⚠️ Saltati: " + ", ".join(skipped))
        lines.append("\nUsa `/jenniserpi_off` per rimuovere.")
        await inter.followup.send("\n".join(lines), ephemeral=True)
        log.info(tag("MOD", f"/jenniserpi → {[m.display_name for m in members]} da {user(str(inter.user))}"))

    @app_commands.command(name="jenniserpi_off", description=f"{_CROWN} Rimuove la sordina jenni serpi da uno o più utenti")
    @app_commands.describe(utenti="Utenti da de-sordare, separati da spazio (menzioni o ID). 'all' per tutti.")
    @perm("admin")
    @admin_check
    async def jenniserpi_off(
        self,
        inter: discord.Interaction,
        utenti: str,
    ):
        await inter.response.defer(ephemeral=True)
        gid = inter.guild.id
        deaf_set = self._deafened.get(gid, set())

        if utenti.strip().lower() == "all":
            members = [inter.guild.get_member(uid) for uid in list(deaf_set)]
            members = [m for m in members if m]
        else:
            members = await self._resolve_members(inter.guild, utenti)

        if not members:
            return await inter.followup.send("❌ Nessun utente valido trovato.", ephemeral=True)

        removed = []
        for m in members:
            deaf_set.discard(m.id)
            if m.voice and m.voice.channel:
                try:
                    await m.edit(deafen=False, reason=f"/jenniserpi_off da {inter.user}")
                except discord.Forbidden:
                    pass
            removed.append(m.display_name)

        await inter.followup.send(f"🔊 Jenni Serpi rimossa da: {', '.join(removed)}", ephemeral=True)
        log.info(tag("MOD", f"/jenniserpi_off → {removed} da {user(str(inter.user))}"))

    # ── Listener mic/deaf al join VC ──────────────────────────────
    # Separato dal listener quarantena per chiarezza.
    # Riapplica mute/deaf quando l'utente entra in un canale vocale.

    @commands.Cog.listener("on_voice_state_update")
    async def _apply_on_join(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ):
        # Solo quando entra in un canale (non già gestito da before)
        if after.channel is None:
            return
        if before.channel is not None and before.channel == after.channel:
            return

        gid = member.guild.id
        needs_mute  = member.id in self._muted_mic.get(gid, set())
        needs_deaf  = member.id in self._deafened.get(gid, set())

        kwargs = {}
        if needs_mute and not after.mute:
            kwargs["mute"] = True
        if needs_deaf and not after.deaf:
            kwargs["deafen"] = True

        if kwargs:
            try:
                await member.edit(**kwargs, reason="Sessione punitiva attiva (auto-applica)")
            except (discord.Forbidden, discord.HTTPException):
                pass

    # ── /isolamento ───────────────────────────────────────────────

    @app_commands.command(
        name="isolamento",
        description=f"{_CROWN} Sposta uno o più utenti in un canale di quarantena dedicato (rimangono finché non liberati)",
    )
    @app_commands.describe(
        utenti="Utenti da isolare, separati da spazio (menzioni o ID)",
        nome_canale="Nome base del canale quarantena (default: quarantena)",
    )
    @perm("admin")
    @admin_check
    async def isolamento(
        self,
        inter: discord.Interaction,
        utenti: str,
        nome_canale: str = "quarantena",
    ):
        await inter.response.defer(ephemeral=True)
        gid = inter.guild.id
        if gid not in self._quarantined:
            self._quarantined[gid] = {}

        members = await self._resolve_members(inter.guild, utenti)
        if not members:
            return await inter.followup.send("❌ Nessun utente valido trovato.", ephemeral=True)

        # Cerca o crea il canale quarantena
        q_channel = await self._get_or_create_quarantine_channel(inter.guild, nome_canale)
        if q_channel is None:
            return await inter.followup.send(
                "❌ Non riesco a creare il canale di quarantena. Controlla che il bot abbia i permessi **Gestisci canali**.",
                ephemeral=True,
            )

        placed, waiting = [], []
        for m in members:
            self._quarantined[gid][m.id] = q_channel.id
            if m.voice and m.voice.channel:
                try:
                    await m.move_to(q_channel, reason=f"/isolamento da {inter.user}")
                    placed.append(m.display_name)
                except discord.Forbidden:
                    waiting.append(f"{m.display_name} (forbidden — sessione registrata)")
            else:
                waiting.append(f"{m.display_name} (non in VC — sessione registrata, si applica al join)")

        lines = [f"🔒 **Isolamento attivo** nel canale **#{q_channel.name}**"]
        if placed:
            lines.append("✅ Spostati ora: " + ", ".join(placed))
        if waiting:
            lines.append("⏳ In attesa di join VC: " + ", ".join(waiting))
        lines.append("\nUsa `/isolamento_off` per liberare gli utenti.")
        await inter.followup.send("\n".join(lines), ephemeral=True)
        log.info(tag("MOD", f"/isolamento #{q_channel.name} → {[m.display_name for m in members]} da {user(str(inter.user))}"))

    @app_commands.command(name="isolamento_off", description=f"{_CROWN} Libera uno o più utenti dalla quarantena")
    @app_commands.describe(utenti="Utenti da liberare, separati da spazio (menzioni o ID). 'all' per tutti.")
    @perm("admin")
    @admin_check
    async def isolamento_off(
        self,
        inter: discord.Interaction,
        utenti: str,
    ):
        await inter.response.defer(ephemeral=True)
        gid = inter.guild.id
        q_map = self._quarantined.get(gid, {})

        if utenti.strip().lower() == "all":
            members = [inter.guild.get_member(uid) for uid in list(q_map.keys())]
            members = [m for m in members if m]
        else:
            members = await self._resolve_members(inter.guild, utenti)

        if not members:
            return await inter.followup.send("❌ Nessun utente valido trovato.", ephemeral=True)

        liberated = []
        for m in members:
            q_map.pop(m.id, None)
            liberated.append(m.display_name)

        await inter.followup.send(f"🔓 Liberati dalla quarantena: {', '.join(liberated)}", ephemeral=True)
        log.info(tag("MOD", f"/isolamento_off → {liberated} da {user(str(inter.user))}"))

    @app_commands.command(name="isolamento_lista", description=f"{_CROWN} Mostra gli utenti attualmente in quarantena")
    @perm("admin")
    @admin_check
    async def isolamento_lista(self, inter: discord.Interaction):
        gid = inter.guild.id
        q_map = self._quarantined.get(gid, {})

        embed = discord.Embed(title="🔒 Utenti in quarantena", color=0xE67E22)
        if not q_map:
            embed.description = "*Nessun utente in quarantena.*"
        else:
            righe = []
            for uid, cid in q_map.items():
                m = inter.guild.get_member(uid)
                nome = m.display_name if m else f"ID:{uid}"
                ch_obj = inter.guild.get_channel(cid)
                ch_name = f"#{ch_obj.name}" if ch_obj else f"canale:{cid}"
                righe.append(f"**{nome}** → {ch_name}")
            embed.description = "\n".join(righe)

        await inter.response.send_message(embed=embed, ephemeral=True)

    # ── Helpers interni ───────────────────────────────────────────

    @staticmethod
    async def _resolve_members(guild: discord.Guild, raw: str) -> list[discord.Member]:
        """Risolve una stringa di menzioni/ID separati da spazio in una lista di Member."""
        found = []
        for token in raw.split():
            token = token.strip("<@!>")
            if not token.isdigit():
                continue
            m = guild.get_member(int(token))
            if m is None:
                try:
                    m = await guild.fetch_member(int(token))
                except (discord.NotFound, discord.HTTPException):
                    pass
            if m and m not in found:
                found.append(m)
        return found

    @staticmethod
    async def _get_or_create_quarantine_channel(
        guild: discord.Guild,
        base_name: str,
    ) -> Optional[discord.VoiceChannel]:
        """Trova o crea un canale vocale di quarantena con nome base_name[-N]."""
        # Cerca canale esistente (usa nome esatto o con suffisso numerico)
        for ch_obj in guild.voice_channels:
            if ch_obj.name == base_name or ch_obj.name.startswith(base_name + "-"):
                return ch_obj

        # Crea nuovo canale
        # Trova il numero progressivo non usato
        existing_nums = set()
        for ch_obj in guild.voice_channels:
            if ch_obj.name.startswith(base_name + "-"):
                suffix = ch_obj.name[len(base_name) + 1:]
                if suffix.isdigit():
                    existing_nums.add(int(suffix))

        if not existing_nums:
            final_name = base_name
        else:
            n = 1
            while n in existing_nums:
                n += 1
            final_name = f"{base_name}-{n}"

        try:
            # Permessi: nessuno può muoversi autonomamente fuori
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(
                    connect=False,
                    view_channel=True,
                ),
                guild.me: discord.PermissionOverwrite(
                    connect=True,
                    move_members=True,
                    view_channel=True,
                ),
            }
            return await guild.create_voice_channel(
                name=final_name,
                overwrites=overwrites,
                reason="Creazione canale quarantena automatica",
            )
        except discord.Forbidden:
            return None
        except discord.HTTPException:
            return None


async def setup(bot: commands.Bot):
    await bot.add_cog(Moderation(bot))
