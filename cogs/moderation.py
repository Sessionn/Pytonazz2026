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

# ── Stato runtime in-memory ────────────────────────────────────────────────────
# {guild_id: {user_id: True}}
_muted_mic:   dict[int, dict[int, bool]] = {}
_muted_audio: dict[int, dict[int, bool]] = {}

# {guild_id: {user_id: channel_id}}  — channel_id = ID canale quarantena assegnato
_quarantined: dict[int, dict[int, int]] = {}

# {guild_id: str}  — nome personalizzabile del canale quarantena
_quarantine_channel_name: dict[int, str] = {}
_DEFAULT_QUARANTINE_NAME = "quarantena"


class Moderation(commands.Cog):
    COG_ICON  = "🛡️"
    COG_LABEL = "Moderazione"
    COG_TYPE  = "admin"

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── Helpers ────────────────────────────────────────────────────────────────

    @staticmethod
    def _can_moderate(actor: discord.Member, target: discord.Member) -> bool:
        return actor.guild.owner_id == actor.id or actor.top_role > target.top_role

    @staticmethod
    def _bot_can_moderate(bot_member: Optional[discord.Member], target: discord.Member) -> bool:
        return bool(bot_member and bot_member.top_role > target.top_role)

    async def _get_or_create_quarantine_channel(
        self, guild: discord.Guild, number: int
    ) -> discord.VoiceChannel:
        """Recupera o crea il canale vocale di quarantena numerato."""
        base_name = _quarantine_channel_name.get(guild.id, _DEFAULT_QUARANTINE_NAME)
        ch_name   = f"{base_name}-{number}"
        existing  = discord.utils.get(guild.voice_channels, name=ch_name)
        if existing:
            return existing
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                connect=False,
                move_members=False,
            ),
            guild.me: discord.PermissionOverwrite(
                connect=True,
                move_members=True,
            ),
        }
        channel = await guild.create_voice_channel(
            ch_name,
            overwrites=overwrites,
            reason="Canale quarantena automatico",
        )
        log.info(tag("MOD", f"creato canale quarantena {b(ch_name)} su {b(guild.name)}"))
        return channel

    def _next_quarantine_number(self, guild_id: int) -> int:
        """Ritorna il numero più basso disponibile per il canale di quarantena."""
        used_ids = set(_quarantined.get(guild_id, {}).values())
        # teniamo il mapping number→channel_id tramite name lookup
        # usiamo semplicemente un counter incrementale per questa run
        existing_numbers = set()
        guild = self.bot.get_guild(guild_id)
        if guild:
            base_name = _quarantine_channel_name.get(guild_id, _DEFAULT_QUARANTINE_NAME)
            for vc in guild.voice_channels:
                if vc.name.startswith(base_name + "-"):
                    suffix = vc.name[len(base_name) + 1:]
                    if suffix.isdigit():
                        existing_numbers.add(int(suffix))
        n = 1
        while n in existing_numbers:
            n += 1
        return n

    # ── Error handler ──────────────────────────────────────────────────────────

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

    # ── Listener: gestisce isolamento + ri-applicazione mute/deafen al rejoin ──

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ):
        guild_id  = member.guild.id
        member_id = member.id

        # ── Re-applica mute mic al rejoin ────────────────────────────────────
        if after.channel and _muted_mic.get(guild_id, {}).get(member_id):
            if not after.mute:
                try:
                    await member.edit(mute=True, reason="Museruola attiva")
                except discord.Forbidden:
                    pass

        # ── Re-applica deafen al rejoin ──────────────────────────────────────
        if after.channel and _muted_audio.get(guild_id, {}).get(member_id):
            if not after.deaf:
                try:
                    await member.edit(deafen=True, reason="Jenni Serpi attiva")
                except discord.Forbidden:
                    pass

        # ── Isolamento: ributta dentro se esce dal canale assegnato ─────────
        q_map = _quarantined.get(guild_id, {})
        if member_id not in q_map:
            return

        target_channel_id = q_map[member_id]
        target_channel    = member.guild.get_channel(target_channel_id)
        if not target_channel:
            return

        # L'utente ha quittato: non possiamo fare niente, aspettiamo il rejoin
        if after.channel is None:
            return

        # L'utente è già nel canale giusto
        if after.channel.id == target_channel_id:
            return

        # L'utente ha tentato di spostarsi in altro canale → ributta
        await asyncio.sleep(0.3)
        try:
            await member.move_to(target_channel, reason="Isolamento attivo")
            log.info(tag("MOD", f"isolamento: ributtato {b(member.display_name)} in {b(target_channel.name)}"))
        except (discord.Forbidden, discord.HTTPException):
            pass

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
    # /ruolo
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

    # ──────────────────────────────────────────────────────────────
    # /kick  /ban  /timeout
    # ──────────────────────────────────────────────────────────────

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

    # ──────────────────────────────────────────────────────────────
    # /museruola — muta microfono (server mute)
    # ──────────────────────────────────────────────────────────────

    @app_commands.command(
        name="museruola",
        description=f"{_CROWN} Muta il microfono a uno o più utenti (server mute persistente)",
    )
    @app_commands.describe(
        utenti="Menzioni degli utenti da mutare (separati da spazio)",
        rimuovi="Passa True per rimuovere la museruola invece di applicarla",
    )
    @perm("admin")
    @admin_check
    async def museruola(
        self,
        inter: discord.Interaction,
        utenti: str,
        rimuovi: bool = False,
    ):
        await inter.response.defer(ephemeral=True)
        guild_id = inter.guild.id
        _muted_mic.setdefault(guild_id, {})

        members = _resolve_members(inter.guild, utenti)
        if not members:
            return await inter.followup.send("❌ Nessun utente valido trovato nella stringa fornita.", ephemeral=True)

        results = []
        for member in members:
            if rimuovi:
                _muted_mic[guild_id].pop(member.id, None)
                if member.voice:
                    try:
                        await member.edit(mute=False, reason=f"Museruola rimossa da {inter.user}")
                    except discord.Forbidden:
                        pass
                results.append(f"🔊 {member.mention} — museruola **rimossa**")
                log.info(tag("MOD", f"museruola RIMOSSA  {b(member.display_name)}  da {user(str(inter.user))}"))
            else:
                _muted_mic[guild_id][member.id] = True
                if member.voice:
                    try:
                        await member.edit(mute=True, reason=f"Museruola da {inter.user}")
                    except discord.Forbidden:
                        pass
                results.append(f"🔇 {member.mention} — microfono **mutato**")
                log.info(tag("MOD", f"museruola  {b(member.display_name)}  da {user(str(inter.user))}"))

        await inter.followup.send("\n".join(results), ephemeral=True)

    # ──────────────────────────────────────────────────────────────
    # /jenniserpi — sorda audio (server deafen)
    # ──────────────────────────────────────────────────────────────

    @app_commands.command(
        name="jenniserpi",
        description=f"{_CROWN} Sorda l'audio a uno o più utenti (server deafen persistente)",
    )
    @app_commands.describe(
        utenti="Menzioni degli utenti da sordare (separati da spazio)",
        rimuovi="Passa True per rimuovere il deafen invece di applicarlo",
    )
    @perm("admin")
    @admin_check
    async def jenniserpi(
        self,
        inter: discord.Interaction,
        utenti: str,
        rimuovi: bool = False,
    ):
        await inter.response.defer(ephemeral=True)
        guild_id = inter.guild.id
        _muted_audio.setdefault(guild_id, {})

        members = _resolve_members(inter.guild, utenti)
        if not members:
            return await inter.followup.send("❌ Nessun utente valido trovato nella stringa fornita.", ephemeral=True)

        results = []
        for member in members:
            if rimuovi:
                _muted_audio[guild_id].pop(member.id, None)
                if member.voice:
                    try:
                        await member.edit(deafen=False, reason=f"Jenni Serpi rimossa da {inter.user}")
                    except discord.Forbidden:
                        pass
                results.append(f"🔊 {member.mention} — audio **riattivato**")
                log.info(tag("MOD", f"jenniserpi RIMOSSA  {b(member.display_name)}  da {user(str(inter.user))}"))
            else:
                _muted_audio[guild_id][member.id] = True
                if member.voice:
                    try:
                        await member.edit(deafen=True, reason=f"Jenni Serpi da {inter.user}")
                    except discord.Forbidden:
                        pass
                results.append(f"🔕 {member.mention} — audio **sordato**")
                log.info(tag("MOD", f"jenniserpi  {b(member.display_name)}  da {user(str(inter.user))}"))

        await inter.followup.send("\n".join(results), ephemeral=True)

    # ──────────────────────────────────────────────────────────────
    # /isolamento — sposta in canale dedicato + blocca uscita
    # ──────────────────────────────────────────────────────────────

    @app_commands.command(
        name="isolamento",
        description=f"{_CROWN} Isola uno o più utenti in un canale vocale dedicato (quarantena)",
    )
    @app_commands.describe(
        utenti="Menzioni degli utenti da isolare (separati da spazio)",
        nome_canale="Nome base del canale quarantena (default: quarantena)",
        rimuovi="Passa True per liberare gli utenti dall'isolamento",
    )
    @perm("admin")
    @admin_check
    async def isolamento(
        self,
        inter: discord.Interaction,
        utenti: str,
        nome_canale: Optional[str] = None,
        rimuovi: bool = False,
    ):
        await inter.response.defer(ephemeral=True)
        guild    = inter.guild
        guild_id = guild.id

        if nome_canale:
            _quarantine_channel_name[guild_id] = nome_canale.strip()

        _quarantined.setdefault(guild_id, {})

        members = _resolve_members(guild, utenti)
        if not members:
            return await inter.followup.send("❌ Nessun utente valido trovato nella stringa fornita.", ephemeral=True)

        results = []
        for member in members:
            if rimuovi:
                _quarantined[guild_id].pop(member.id, None)
                results.append(f"🔓 {member.mention} — **liberato** dall'isolamento")
                log.info(tag("MOD", f"isolamento RIMOSSO  {b(member.display_name)}  da {user(str(inter.user))}"))
            else:
                n       = self._next_quarantine_number(guild_id)
                q_ch    = await self._get_or_create_quarantine_channel(guild, n)
                _quarantined[guild_id][member.id] = q_ch.id
                if member.voice:
                    try:
                        await member.move_to(q_ch, reason=f"Isolamento da {inter.user}")
                    except (discord.Forbidden, discord.HTTPException):
                        pass
                results.append(f"🔒 {member.mention} — isolato in **{q_ch.name}**")
                log.info(tag("MOD", f"isolamento  {b(member.display_name)} → {b(q_ch.name)}  da {user(str(inter.user))}"))

        await inter.followup.send("\n".join(results), ephemeral=True)

    # ── Alias /quarantena ──────────────────────────────────────────

    @app_commands.command(
        name="quarantena",
        description=f"{_CROWN} Alias di /isolamento — isola utenti in canale dedicato",
    )
    @app_commands.describe(
        utenti="Menzioni degli utenti da isolare (separati da spazio)",
        nome_canale="Nome base del canale quarantena (default: quarantena)",
        rimuovi="Passa True per liberare gli utenti dall'isolamento",
    )
    @perm("admin")
    @admin_check
    async def quarantena(
        self,
        inter: discord.Interaction,
        utenti: str,
        nome_canale: Optional[str] = None,
        rimuovi: bool = False,
    ):
        await self.isolamento.callback(self, inter, utenti=utenti, nome_canale=nome_canale, rimuovi=rimuovi)

    # ──────────────────────────────────────────────────────────────
    # /lista_isolati — mostra utenti in quarantena
    # ──────────────────────────────────────────────────────────────

    @app_commands.command(
        name="lista_isolati",
        description=f"{_CROWN} Mostra gli utenti attualmente in isolamento/quarantena",
    )
    @perm("admin")
    @admin_check
    async def lista_isolati(self, inter: discord.Interaction):
        guild_id = inter.guild.id
        q_map    = _quarantined.get(guild_id, {})

        if not q_map:
            return await inter.response.send_message("✅ Nessun utente in isolamento.", ephemeral=True)

        lines = []
        for uid, cid in q_map.items():
            member  = inter.guild.get_member(uid)
            channel = inter.guild.get_channel(cid)
            name    = member.mention if member else f"<@{uid}>"
            ch_name = channel.name if channel else f"canale-{cid}"
            lines.append(f"🔒 {name} → **{ch_name}**")

        embed = discord.Embed(
            title="🔒 Utenti in isolamento",
            description="\n".join(lines),
            color=0xE67E22,
        )
        await inter.response.send_message(embed=embed, ephemeral=True)

    # ──────────────────────────────────────────────────────────────
    # /lista_mutati — mostra utenti con museruola / jenni serpi attive
    # ──────────────────────────────────────────────────────────────

    @app_commands.command(
        name="lista_mutati",
        description=f"{_CROWN} Mostra gli utenti con museruola e/o jenni serpi attive",
    )
    @perm("admin")
    @admin_check
    async def lista_mutati(self, inter: discord.Interaction):
        guild_id = inter.guild.id
        mic_map  = _muted_mic.get(guild_id, {})
        aud_map  = _muted_audio.get(guild_id, {})

        all_ids = set(mic_map) | set(aud_map)
        if not all_ids:
            return await inter.response.send_message("✅ Nessun utente con sanzioni vocali attive.", ephemeral=True)

        lines = []
        for uid in sorted(all_ids):
            member = inter.guild.get_member(uid)
            name   = member.mention if member else f"<@{uid}>"
            flags  = []
            if mic_map.get(uid):
                flags.append("🔇 museruola")
            if aud_map.get(uid):
                flags.append("🔕 jenni serpi")
            lines.append(f"{name} — {', '.join(flags)}")

        embed = discord.Embed(
            title="🔇 Utenti con sanzioni vocali",
            description="\n".join(lines),
            color=0xED4245,
        )
        await inter.response.send_message(embed=embed, ephemeral=True)


# ── Helper module-level ───────────────────────────────────────────────────────

def _resolve_members(guild: discord.Guild, utenti_str: str) -> list[discord.Member]:
    """
    Risolve una stringa di menzioni/ID/username in una lista di Member.
    Accetta: <@id>, <@!id>, ID numerico, username, display_name.
    """
    found = []
    tokens = utenti_str.split()
    for token in tokens:
        token = token.strip()
        if not token:
            continue
        # Menzione Discord standard: <@123> o <@!123>
        if token.startswith("<@") and token.endswith(">"):
            raw = token[2:-1].lstrip("!")
            if raw.isdigit():
                m = guild.get_member(int(raw))
                if m and m not in found:
                    found.append(m)
            continue
        # ID numerico puro
        if token.isdigit():
            m = guild.get_member(int(token))
            if m and m not in found:
                found.append(m)
            continue
        # Username o display_name (case-insensitive)
        token_lower = token.lower()
        for member in guild.members:
            if member.name.lower() == token_lower or member.display_name.lower() == token_lower:
                if member not in found:
                    found.append(member)
                break
    return found


async def setup(bot: commands.Bot):
    await bot.add_cog(Moderation(bot))
