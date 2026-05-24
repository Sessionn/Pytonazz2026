import asyncio
import logging
from datetime import timedelta
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks

from config import Config
from core.isolation_registry import load_quarantine_groups, save_quarantine_groups
from core.log_colors import tag, b, user, ch
from core.permissions import admin_check, perm

log = logging.getLogger("pitonazz.moderation")

_BULK_CUTOFF = timedelta(weeks=2)
_CROWN = "👑"

# Prefisso interno per riconoscere i canali quarantena creati dal bot
_QUARANTINE_PREFIX = "quarantena"


# ── Strutture dati sessione ──────────────────────────────────────────────────
#
# _deafened_groups[guild_id] = {
#     group_id (int, timestamp): {
#         "members": set[int],          # user IDs
#         "label":   str,               # etichetta leggibile
#     }
# }
#
# _quarantine_groups[guild_id] = {
#     group_id (int, timestamp): {
#         "members":      set[int],     # user IDs
#         "channel_id":   int,          # ID canale quarantena
#         "base_name":    str,          # nome base canale
#         "pre_channels": {uid: int},   # canale in cui erano PRIMA dell'isolamento
#     }
# }
#
# Per i singoli utenti vengono usati gli stessi dict con group_id = uid
# e "members" = {uid}.  Questo semplifica tutta la logica.
# ────────────────────────────────────────────────────────────────────────────


class _GroupSelectView(discord.ui.View):
    """Menu a tendina per selezionare un gruppo da cui rimuovere la pena.

    Viene usato sia da jenniserpi_off che da isolamento_off quando
    viene invocato senza argomenti (o con 'menu').
    """

    def __init__(
        self,
        *,
        groups: dict,           # {group_id: {"members": set, "label": str, ...}}
        guild: discord.Guild,
        mode: str,              # "jenny" | "isolamento"
        cog: "Moderation",
    ):
        super().__init__(timeout=120)
        self.groups = groups
        self.guild  = guild
        self.mode   = mode
        self.cog    = cog
        self.result: Optional[int] = None  # group_id scelto

        options = []
        for gid_key, info in groups.items():
            nomi = []
            for uid in info["members"]:
                m = guild.get_member(uid)
                nomi.append(m.display_name if m else f"ID:{uid}")
            label = info.get("label") or ", ".join(nomi[:3]) + ("…" if len(nomi) > 3 else "")
            options.append(discord.SelectOption(
                label=label[:100],
                value=str(gid_key),
                description=f"{len(info['members'])} utent{'e' if len(info['members'])==1 else 'i'}",
            ))

        select = discord.ui.Select(
            placeholder="Seleziona il gruppo da liberare…",
            min_values=1,
            max_values=1,
            options=options[:25],
        )
        select.callback = self._on_select
        self.add_item(select)

    async def _on_select(self, interaction: discord.Interaction):
        self.result = int(interaction.data["values"][0])
        self.stop()
        await interaction.response.defer()


class Moderation(commands.Cog):
    COG_ICON  = "🛡️"
    COG_LABEL = "Moderazione"
    COG_TYPE  = "admin"

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # guild_id -> {user_id: bool}  — utenti con microfono mutato via /museruola
        self._muted_mic: dict[int, set[int]] = {}
        # guild_id -> {group_key: {"members": set, "label": str}}
        self._deafened_groups: dict[int, dict[int, dict]] = {}
        # guild_id -> {group_key: {"members": set, "channel_id": int, "base_name": str, "pre_channels": dict}}
        self._quarantine_groups: dict[int, dict[int, dict]] = load_quarantine_groups()

    def _save_quarantine_state(self) -> None:
        try:
            save_quarantine_groups(self._quarantine_groups)
        except OSError as exc:
            log.warning(tag("MOD", f"isolation registry save failed: {exc}"))

    # ── Helpers gerarchia ─────────────────────────────────────────

    @staticmethod
    def _can_moderate(actor: discord.Member, target: discord.Member) -> bool:
        return actor.guild.owner_id == actor.id or actor.top_role > target.top_role

    @staticmethod
    def _bot_can_moderate(bot_member: Optional[discord.Member], target: discord.Member) -> bool:
        return bool(bot_member and bot_member.top_role > target.top_role)

    # ── Helpers state interni ─────────────────────────────────────

    def _all_deafened_uids(self, gid: int) -> set[int]:
        """Restituisce tutti gli user ID attualmente sordati in una guild."""
        result = set()
        for info in self._deafened_groups.get(gid, {}).values():
            result |= info["members"]
        return result

    def _all_quarantined_uids(self, gid: int) -> dict[int, int]:
        """Restituisce {uid: channel_id} per tutti gli utenti in quarantena."""
        result = {}
        for info in self._quarantine_groups.get(gid, {}).values():
            for uid in info["members"]:
                result[uid] = info["channel_id"]
        return result

    def _group_for_uid_quarantine(self, gid: int, uid: int) -> Optional[int]:
        """Restituisce il group_key del gruppo quarantena che contiene uid."""
        for gkey, info in self._quarantine_groups.get(gid, {}).items():
            if uid in info["members"]:
                return gkey
        return None

    def _group_for_uid_jenny(self, gid: int, uid: int) -> Optional[int]:
        """Restituisce il group_key del gruppo jenniserpi che contiene uid."""
        for gkey, info in self._deafened_groups.get(gid, {}).items():
            if uid in info["members"]:
                return gkey
        return None

    def cog_load(self):
        self._quarantine_watchdog.start()

    def cog_unload(self):
        self._quarantine_watchdog.cancel()

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

    # ── Watchdog quarantena ───────────────────────────────────────

    @tasks.loop(seconds=60)
    async def _quarantine_watchdog(self):
        for guild in self.bot.guilds:
            gid = guild.id
            q_groups = self._quarantine_groups.get(gid, {})
            if not q_groups:
                continue

            changed = False
            for gkey, info in list(q_groups.items()):
                cid       = info["channel_id"]
                base_name = info["base_name"]
                target_ch = guild.get_channel(cid)

                if target_ch is None:
                    # Canale eliminato: ricrealo
                    log.info(tag("MOD", f"watchdog: canale quarantena (id={cid}) mancante — ricreazione '{base_name}'"))
                    new_ch = await self._get_or_create_quarantine_channel(guild, base_name)
                    if new_ch is None:
                        log.warning(tag("MOD", f"watchdog: impossibile ricreare canale per gruppo {gkey}"))
                        continue
                    info["channel_id"] = new_ch.id
                    target_ch = new_ch
                    changed = True
                    log.info(tag("MOD", f"watchdog: canale ricreato {ch(new_ch.name)} (id={new_ch.id})"))

                # Ributta gli utenti fuori canale
                for uid in info["members"]:
                    member = guild.get_member(uid)
                    if not member:
                        continue
                    if member.voice and member.voice.channel and member.voice.channel.id != target_ch.id:
                        try:
                            await member.move_to(target_ch, reason="Watchdog quarantena — utente fuori canale")
                            log.info(tag("MOD", f"watchdog: ributtato {user(str(member))} in {ch(target_ch.name)}"))
                        except (discord.Forbidden, discord.HTTPException):
                            pass

            # Elimina canali quarantena orfani
            active_cids = {info["channel_id"] for info in q_groups.values()}
            known_bases = {info["base_name"] for info in q_groups.values()} | {_QUARANTINE_PREFIX}
            for vc in list(guild.voice_channels):
                is_q = any(vc.name == b2 or vc.name.startswith(b2 + "-") for b2 in known_bases)
                if not is_q or vc.id in active_cids:
                    continue
                if len(vc.members) == 0:
                    try:
                        await vc.delete(reason="Watchdog quarantena — canale orfano vuoto")
                        log.info(tag("MOD", f"watchdog: canale orfano #{vc.name} eliminato"))
                    except (discord.Forbidden, discord.HTTPException) as exc:
                        log.warning(tag("MOD", f"watchdog: impossibile eliminare #{vc.name}: {exc}"))

            if changed:
                self._save_quarantine_state()

    @_quarantine_watchdog.before_loop
    async def _before_watchdog(self):
        await self.bot.wait_until_ready()

    # ── Listener quarantena ───────────────────────────────────────

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ):
        gid = member.guild.id
        q_map = self._all_quarantined_uids(gid)
        if member.id not in q_map:
            return

        target_channel_id = q_map[member.id]

        if after.channel is None:
            return
        if after.channel.id == target_channel_id:
            return

        # Cerca il gruppo per aggiornare il channel_id se il canale è stato eliminato
        gkey = self._group_for_uid_quarantine(gid, member.id)
        target_ch = member.guild.get_channel(target_channel_id)

        if target_ch is None and gkey is not None:
            info = self._quarantine_groups[gid][gkey]
            base_name = info["base_name"]
            log.info(tag("MOD", f"on_voice: canale quarantena eliminato — ricreazione '{base_name}'"))
            target_ch = await self._get_or_create_quarantine_channel(member.guild, base_name)
            if target_ch is None:
                log.warning(tag("MOD", f"on_voice: impossibile ricreare canale — watchdog riproverà"))
                return
            info["channel_id"] = target_ch.id
            self._save_quarantine_state()
            log.info(tag("MOD", f"on_voice: canale ricreato: {ch(target_ch.name)}"))

        if target_ch is None:
            return

        try:
            await asyncio.sleep(0.3)
            await member.move_to(target_ch, reason="Quarantena attiva — spostamento non autorizzato")
            log.info(tag("MOD", f"on_voice: ributtato {user(str(member))} in {ch(target_ch.name)}"))
        except (discord.Forbidden, discord.HTTPException):
            pass

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        if not isinstance(channel, discord.VoiceChannel):
            return
        guild = channel.guild
        q_groups = self._quarantine_groups.get(guild.id, {})
        if not q_groups:
            return

        changed = False
        for gkey, info in list(q_groups.items()):
            if info.get("channel_id") != channel.id:
                continue
            base_name = info.get("base_name") or _QUARANTINE_PREFIX
            log.info(tag("MOD", f"channel_delete: quarantine channel {channel.id} missing, recreating '{base_name}'"))
            new_ch = await self._get_or_create_quarantine_channel(guild, base_name)
            if new_ch is None:
                log.warning(tag("MOD", f"channel_delete: cannot recreate quarantine channel for group {gkey}"))
                continue
            info["channel_id"] = new_ch.id
            changed = True

            for uid in info.get("members", set()):
                member = guild.get_member(uid)
                if member and member.voice and member.voice.channel:
                    try:
                        await member.move_to(new_ch, reason="Quarantine channel recreated")
                    except (discord.Forbidden, discord.HTTPException):
                        pass

        if changed:
            self._save_quarantine_state()

    # ── Listener re-deaf/re-mute ──────────────────────────────────

    @commands.Cog.listener("on_voice_state_update")
    async def _enforce_punishments(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ):
        if after.channel is None:
            return
        gid = member.guild.id
        needs_mute = member.id in self._muted_mic.get(gid, set())
        needs_deaf = member.id in self._all_deafened_uids(gid)
        if not needs_mute and not needs_deaf:
            return
        kwargs = {}
        if needs_mute and before.mute and not after.mute:
            kwargs["mute"] = True
        if needs_deaf and before.deaf and not after.deaf:
            kwargs["deafen"] = True
        if kwargs:
            try:
                await asyncio.sleep(0.2)
                await member.edit(**kwargs, reason="Sessione punitiva attiva — re-applicazione")
            except (discord.Forbidden, discord.HTTPException):
                pass

    @commands.Cog.listener("on_voice_state_update")
    async def _apply_on_join(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ):
        if after.channel is None:
            return
        if before.channel is not None and before.channel == after.channel:
            return
        gid = member.guild.id
        needs_mute = member.id in self._muted_mic.get(gid, set())
        needs_deaf = member.id in self._all_deafened_uids(gid)
        kwargs = {}
        if needs_mute and not after.mute:
            kwargs["mute"] = True
        if needs_deaf and not after.deaf:
            kwargs["deafen"] = True
        if kwargs:
            try:
                await member.edit(**kwargs, reason="Sessione punitiva attiva (auto-applica al join)")
            except (discord.Forbidden, discord.HTTPException):
                pass

    # ── /purge ────────────────────────────────────────────────────

    @app_commands.command(name="purge", description=f"{_CROWN} Elimina un numero di messaggi dal canale")
    @app_commands.describe(quantita="Messaggi da eliminare (1-100)")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def purge(self, inter: discord.Interaction, quantita: app_commands.Range[int, 1, 100]):
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

    @app_commands.command(name="ruolo", description=f"{_CROWN} Assegna o rimuovi un ruolo a un utente")
    @app_commands.describe(utente="Utente", ruolo="Ruolo da assegnare o rimuovere")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def ruolo(self, inter: discord.Interaction, utente: discord.Member, ruolo: discord.Role):
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
                azione, colore, emoji = "rimosso", 0xFF5555, "🟥"
            else:
                await utente.add_roles(ruolo, reason=f"Assegnato da {inter.user}")
                azione, colore, emoji = "assegnato", 0x57F287, "🟢"
            log.info(tag("MOD", f"/ruolo  {b(ruolo.name)}  {azione}  →  {b(utente.display_name)}"))
            await inter.response.send_message(
                embed=discord.Embed(
                    description=f"{emoji} Ruolo **{ruolo.name}** {azione} a {utente.mention}.",
                    color=colore,
                ),
                ephemeral=True,
            )
        except discord.Forbidden:
            await inter.response.send_message(
                embed=discord.Embed(
                    description=f"❌ Permesso negato per il ruolo **{ruolo.name}**.",
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

    @app_commands.command(name="museruola", description=f"{_CROWN} Muta permanentemente il microfono di uno o più utenti")
    @app_commands.describe(utenti="Utenti da mutare, separati da spazio (menzioni o ID)")
    @perm("admin")
    @admin_check
    async def museruola(self, inter: discord.Interaction, utenti: str):
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
    async def museruola_off(self, inter: discord.Interaction, utenti: str):
        await inter.response.defer(ephemeral=True)
        gid = inter.guild.id
        muted = self._muted_mic.get(gid, set())

        if utenti.strip().lower() == "all":
            members = [inter.guild.get_member(uid) for uid in list(muted)]
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

        embed = discord.Embed(title="🔇 Sessioni punitive attive", color=0xE67E22)

        if muted:
            nomi = []
            for uid in muted:
                m = inter.guild.get_member(uid)
                nomi.append(m.display_name if m else f"ID:{uid}")
            embed.add_field(name="🎙️ Museruola (mic muto)", value="\n".join(nomi), inline=False)
        else:
            embed.add_field(name="🎙️ Museruola (mic muto)", value="*Nessuno*", inline=False)

        deaf_uids = self._all_deafened_uids(gid)
        if deaf_uids:
            nomi = []
            for uid in deaf_uids:
                m = inter.guild.get_member(uid)
                nomi.append(m.display_name if m else f"ID:{uid}")
            embed.add_field(name="🔕 Jenni Serpi (audio sordo)", value="\n".join(nomi), inline=False)
        else:
            embed.add_field(name="🔕 Jenni Serpi (audio sordo)", value="*Nessuno*", inline=False)

        await inter.response.send_message(embed=embed, ephemeral=True)

    # ── /jenniserpi ───────────────────────────────────────────────
    #
    # Supporta singolo utente O gruppo (utenti multipli separati da spazio).
    # Un gruppo viene registrato come un'unità unica (group_key = timestamp).
    # jenniserpi_off senza argomenti mostra il menu a tendina con i gruppi attivi.

    @app_commands.command(
        name="jenniserpi",
        description=f"{_CROWN} Sorda permanentemente l'audio di uno o più utenti (finché non rimosso)",
    )
    @app_commands.describe(utenti="Utenti da sordare, separati da spazio (menzioni o ID)")
    @perm("admin")
    @admin_check
    async def jenniserpi(self, inter: discord.Interaction, utenti: str):
        await inter.response.defer(ephemeral=True)
        gid = inter.guild.id
        if gid not in self._deafened_groups:
            self._deafened_groups[gid] = {}

        members = await self._resolve_members(inter.guild, utenti)
        if not members:
            return await inter.followup.send("❌ Nessun utente valido trovato.", ephemeral=True)

        # Genera un group_key univoco (timestamp int)
        import time
        group_key = int(time.time() * 1000)

        applied, skipped = [], []
        for m in members:
            if m.voice and m.voice.channel:
                try:
                    await m.edit(deafen=True, reason=f"/jenniserpi da {inter.user}")
                    applied.append(m.display_name)
                except discord.Forbidden:
                    skipped.append(f"{m.display_name} (permesso negato)")
            else:
                applied.append(f"{m.display_name} (sessione attiva, si applica al join VC)")

        nomi_label = ", ".join(m.display_name for m in members)
        self._deafened_groups[gid][group_key] = {
            "members": {m.id for m in members},
            "label":   nomi_label if len(members) > 1 else members[0].display_name,
        }

        tipo = "Gruppo" if len(members) > 1 else "Utente"
        lines = [f"🔕 **Jenni Serpi attiva** [{tipo}] per {len(applied)} utent{'e' if len(applied)==1 else 'i'}."]
        if applied:
            lines.append("✅ " + ", ".join(applied))
        if skipped:
            lines.append("⚠️ Saltati: " + ", ".join(skipped))
        lines.append("\nUsa `/jenniserpi_off` per rimuovere (con menu se ci sono gruppi).")
        await inter.followup.send("\n".join(lines), ephemeral=True)
        log.info(tag("MOD", f"/jenniserpi [key={group_key}] → {[m.display_name for m in members]} da {user(str(inter.user))}"))

    @app_commands.command(
        name="jenniserpi_off",
        description=f"{_CROWN} Rimuove la sordina jenni serpi da un utente, un gruppo o tutti",
    )
    @app_commands.describe(
        utenti="Utenti/menzioni (opzionale). Ometti per menu a tendina gruppi. 'all' per tutti."
    )
    @perm("admin")
    @admin_check
    async def jenniserpi_off(self, inter: discord.Interaction, utenti: str = ""):
        gid = inter.guild.id
        groups = self._deafened_groups.get(gid, {})

        # ── Caso: all ──
        if utenti.strip().lower() == "all":
            await inter.response.defer(ephemeral=True)
            all_uids = self._all_deafened_uids(gid)
            self._deafened_groups.pop(gid, None)
            removed = []
            for uid in all_uids:
                m = inter.guild.get_member(uid)
                if m:
                    if m.voice and m.voice.channel:
                        try:
                            await m.edit(deafen=False, reason="/jenniserpi_off all")
                        except (discord.Forbidden, discord.HTTPException):
                            pass
                    removed.append(m.display_name)
            await inter.followup.send(f"🔊 Jenni Serpi rimossa da tutti: {', '.join(removed) or '—'}", ephemeral=True)
            log.info(tag("MOD", f"/jenniserpi_off all da {user(str(inter.user))}"))
            return

        # ── Caso: utenti specificati ──
        if utenti.strip():
            await inter.response.defer(ephemeral=True)
            members = await self._resolve_members(inter.guild, utenti)
            if not members:
                return await inter.followup.send("❌ Nessun utente valido trovato.", ephemeral=True)
            removed = []
            for m in members:
                gkey = self._group_for_uid_jenny(gid, m.id)
                if gkey is not None:
                    groups[gkey]["members"].discard(m.id)
                    if not groups[gkey]["members"]:
                        groups.pop(gkey)
                if m.voice and m.voice.channel:
                    try:
                        await m.edit(deafen=False, reason=f"/jenniserpi_off da {inter.user}")
                    except (discord.Forbidden, discord.HTTPException):
                        pass
                removed.append(m.display_name)
            await inter.followup.send(f"🔊 Jenni Serpi rimossa da: {', '.join(removed)}", ephemeral=True)
            log.info(tag("MOD", f"/jenniserpi_off {removed} da {user(str(inter.user))}"))
            return

        # ── Caso: nessun argomento → menu a tendina ──
        if not groups:
            return await inter.response.send_message("ℹ️ Nessuna sessione Jenni Serpi attiva.", ephemeral=True)

        view = _GroupSelectView(groups=groups, guild=inter.guild, mode="jenny", cog=self)
        await inter.response.send_message(
            "🔕 Seleziona il gruppo da liberare dalla sordina:",
            view=view,
            ephemeral=True,
        )
        await view.wait()
        if view.result is None:
            return  # timeout o nessuna selezione

        chosen_key = view.result
        info = groups.pop(chosen_key, None)
        if info is None:
            return await inter.edit_original_response(content="⚠️ Gruppo non trovato (già rimosso?).", view=None)

        removed = []
        for uid in info["members"]:
            m = inter.guild.get_member(uid)
            if m:
                if m.voice and m.voice.channel:
                    try:
                        await m.edit(deafen=False, reason=f"/jenniserpi_off (menu) da {inter.user}")
                    except (discord.Forbidden, discord.HTTPException):
                        pass
                removed.append(m.display_name)

        await inter.edit_original_response(
            content=f"🔊 Jenni Serpi rimossa dal gruppo: {', '.join(removed) or '—'}",
            view=None,
        )
        log.info(tag("MOD", f"/jenniserpi_off [menu key={chosen_key}] {removed} da {user(str(inter.user))}"))

    @app_commands.command(
        name="jenniserpi_gruppi",
        description=f"{_CROWN} Mostra i componenti di ogni gruppo Jenni Serpi attivo",
    )
    @perm("admin")
    @admin_check
    async def jenniserpi_gruppi(self, inter: discord.Interaction):
        gid = inter.guild.id
        groups = self._deafened_groups.get(gid, {})
        if not groups:
            return await inter.response.send_message("ℹ️ Nessuna sessione Jenni Serpi attiva.", ephemeral=True)

        embed = discord.Embed(title="🔕 Gruppi Jenni Serpi attivi", color=0xE67E22)
        for i, (gkey, info) in enumerate(groups.items(), 1):
            nomi = []
            for uid in info["members"]:
                m = inter.guild.get_member(uid)
                nomi.append(m.mention if m else f"ID:{uid}")
            embed.add_field(
                name=f"Gruppo {i} — {info.get('label', '—')}",
                value="\n".join(nomi) or "—",
                inline=False,
            )
        await inter.response.send_message(embed=embed, ephemeral=True)

    # ── /isolamento ───────────────────────────────────────────────
    #
    # Supporta singolo utente O gruppo.
    # Al termine dell'isolamento l'admin sceglie: disconnetti oppure rimetti
    # gli utenti nel canale in cui erano prima.

    @app_commands.command(
        name="isolamento",
        description=f"{_CROWN} Isola uno o più utenti in un canale vocale dedicato",
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
        if gid not in self._quarantine_groups:
            self._quarantine_groups[gid] = {}

        members = await self._resolve_members(inter.guild, utenti)
        if not members:
            return await inter.followup.send("❌ Nessun utente valido trovato.", ephemeral=True)

        q_channel = await self._get_or_create_quarantine_channel(inter.guild, nome_canale)
        if q_channel is None:
            return await inter.followup.send(
                "❌ Non riesco a creare il canale di quarantena. Controlla che il bot abbia i permessi **Gestisci canali**.",
                ephemeral=True,
            )

        import time
        group_key = int(time.time() * 1000)

        # Registra i canali precedenti per poter ripristinare
        pre_channels: dict[int, Optional[int]] = {}
        for m in members:
            pre_channels[m.id] = m.voice.channel.id if (m.voice and m.voice.channel) else None

        placed, waiting = [], []
        for m in members:
            if m.voice and m.voice.channel:
                try:
                    await m.move_to(q_channel, reason=f"/isolamento da {inter.user}")
                    placed.append(m.display_name)
                except discord.Forbidden:
                    waiting.append(f"{m.display_name} (forbidden — sessione registrata)")
            else:
                waiting.append(f"{m.display_name} (non in VC — sessione registrata, si applica al join)")

        nomi_label = ", ".join(m.display_name for m in members)
        self._quarantine_groups[gid][group_key] = {
            "members":      {m.id for m in members},
            "channel_id":   q_channel.id,
            "base_name":    nome_canale,
            "label":        nomi_label if len(members) > 1 else members[0].display_name,
            "pre_channels": pre_channels,
        }
        self._save_quarantine_state()

        tipo = "Gruppo" if len(members) > 1 else "Utente"
        lines = [f"🔒 **Isolamento attivo** [{tipo}] nel canale **#{q_channel.name}**"]
        if placed:
            lines.append("✅ Spostati ora: " + ", ".join(placed))
        if waiting:
            lines.append("⏳ In attesa di join VC: " + ", ".join(waiting))
        lines.append("\nUsa `/isolamento_off` per liberare (con menu se ci sono gruppi).")
        await inter.followup.send("\n".join(lines), ephemeral=True)
        log.info(tag("MOD", f"/isolamento [key={group_key}] #{q_channel.name} → {[m.display_name for m in members]} da {user(str(inter.user))}"))

    @app_commands.command(
        name="isolamento_off",
        description=f"{_CROWN} Libera uno o più utenti dalla quarantena",
    )
    @app_commands.describe(
        utenti="Utenti/menzioni (opzionale). Ometti per menu a tendina gruppi. 'all' per tutti.",
        ripristina_canale="Rimetti gli utenti nel canale in cui erano prima (default: no = disconnetti)",
    )
    @perm("admin")
    @admin_check
    async def isolamento_off(
        self,
        inter: discord.Interaction,
        utenti: str = "",
        ripristina_canale: bool = False,
    ):
        gid = inter.guild.id
        q_groups = self._quarantine_groups.get(gid, {})

        # ── Helper interno: libera un singolo group_key ──
        async def _free_group(gkey: int, reason_user: str) -> tuple[list[str], set[int]]:
            """Rimuove il gruppo, sposta/disconnette gli utenti e
            restituisce (nomi_liberati, channel_ids_da_controllare)."""
            info = q_groups.pop(gkey, None)
            if not info:
                return [], set()
            self._save_quarantine_state()
            cid_set = {info["channel_id"]}
            liberated = []
            for uid in info["members"]:
                m = inter.guild.get_member(uid)
                if not m:
                    continue
                if m.voice and m.voice.channel:
                    if ripristina_canale:
                        prev_cid = info["pre_channels"].get(uid)
                        prev_ch  = inter.guild.get_channel(prev_cid) if prev_cid else None
                        if prev_ch:
                            try:
                                await m.move_to(prev_ch, reason=f"/isolamento_off (ripristino) da {reason_user}")
                            except (discord.Forbidden, discord.HTTPException):
                                # Fallback: disconnetti
                                try:
                                    await m.move_to(None, reason="Isolamento terminato — ripristino fallito")
                                except (discord.Forbidden, discord.HTTPException):
                                    pass
                        else:
                            # Canale precedente non disponibile: disconnetti
                            try:
                                await m.move_to(None, reason="Isolamento terminato")
                            except (discord.Forbidden, discord.HTTPException):
                                pass
                    else:
                        # Disconnetti normalmente
                        afk_ch = inter.guild.afk_channel
                        try:
                            if afk_ch:
                                await m.move_to(afk_ch, reason="Isolamento terminato")
                            else:
                                await m.move_to(None, reason="Isolamento terminato")
                        except (discord.Forbidden, discord.HTTPException):
                            pass
                liberated.append(m.display_name)
            return liberated, cid_set

        async def _delete_orphan_channels(cid_set: set[int]):
            still_used = {info["channel_id"] for info in q_groups.values()}
            for cid in cid_set:
                if cid in still_used:
                    continue
                q_ch = inter.guild.get_channel(cid)
                if q_ch is None:
                    continue
                for occupant in list(q_ch.members):
                    try:
                        afk_ch = inter.guild.afk_channel
                        if afk_ch:
                            await occupant.move_to(afk_ch, reason="Canale quarantena in chiusura")
                        else:
                            await occupant.move_to(None, reason="Canale quarantena in chiusura")
                    except (discord.Forbidden, discord.HTTPException):
                        pass
                await asyncio.sleep(0.5)
                try:
                    await q_ch.delete(reason="Isolamento terminato — canale eliminato automaticamente")
                    log.info(tag("MOD", f"canale quarantena #{q_ch.name} eliminato dopo isolamento_off"))
                except (discord.Forbidden, discord.HTTPException) as exc:
                    log.warning(tag("MOD", f"impossibile eliminare #{q_ch.name}: {exc}"))

        # ── Caso: all ──
        if utenti.strip().lower() == "all":
            await inter.response.defer(ephemeral=True)
            all_keys = list(q_groups.keys())
            all_liberated, all_cids = [], set()
            for gkey in all_keys:
                lib, cids = await _free_group(gkey, str(inter.user))
                all_liberated.extend(lib)
                all_cids |= cids
            await _delete_orphan_channels(all_cids)
            suffix = " (ripristino canale)" if ripristina_canale else " (disconnessi)"
            await inter.followup.send(
                f"🔓 Liberati tutti{suffix}: {', '.join(all_liberated) or '—'}",
                ephemeral=True,
            )
            log.info(tag("MOD", f"/isolamento_off all da {user(str(inter.user))}"))
            return

        # ── Caso: utenti specificati ──
        if utenti.strip():
            await inter.response.defer(ephemeral=True)
            members = await self._resolve_members(inter.guild, utenti)
            if not members:
                return await inter.followup.send("❌ Nessun utente valido trovato.", ephemeral=True)

            cid_set_total = set()
            liberated_names = []
            for m in members:
                gkey = self._group_for_uid_quarantine(gid, m.id)
                if gkey is None:
                    continue
                info = q_groups.get(gkey)
                if not info:
                    continue
                cid_set_total.add(info["channel_id"])
                # Rimuovi solo questo utente dal gruppo
                info["members"].discard(m.id)
                if not info["members"]:
                    q_groups.pop(gkey, None)
                self._save_quarantine_state()

                if m.voice and m.voice.channel:
                    if ripristina_canale:
                        prev_cid = info["pre_channels"].get(m.id)
                        prev_ch  = inter.guild.get_channel(prev_cid) if prev_cid else None
                        try:
                            if prev_ch:
                                await m.move_to(prev_ch, reason=f"/isolamento_off da {inter.user}")
                            else:
                                await m.move_to(None, reason="Isolamento terminato")
                        except (discord.Forbidden, discord.HTTPException):
                            pass
                    else:
                        try:
                            afk_ch = inter.guild.afk_channel
                            if afk_ch:
                                await m.move_to(afk_ch, reason="Isolamento terminato")
                            else:
                                await m.move_to(None, reason="Isolamento terminato")
                        except (discord.Forbidden, discord.HTTPException):
                            pass
                liberated_names.append(m.display_name)

            await _delete_orphan_channels(cid_set_total)
            suffix = " (ripristino canale)" if ripristina_canale else ""
            await inter.followup.send(
                f"🔓 Liberati{suffix}: {', '.join(liberated_names) or '—'}",
                ephemeral=True,
            )
            log.info(tag("MOD", f"/isolamento_off {liberated_names} da {user(str(inter.user))}"))
            return

        # ── Caso: nessun argomento → menu a tendina ──
        if not q_groups:
            return await inter.response.send_message("ℹ️ Nessun utente in isolamento.", ephemeral=True)

        view = _GroupSelectView(groups=q_groups, guild=inter.guild, mode="isolamento", cog=self)
        await inter.response.send_message(
            "🔒 Seleziona il gruppo da liberare dall'isolamento:",
            view=view,
            ephemeral=True,
        )
        await view.wait()
        if view.result is None:
            return

        chosen_key = view.result
        liberated, cid_set = await _free_group(chosen_key, str(inter.user))
        await _delete_orphan_channels(cid_set)
        suffix = " (ripristino canale)" if ripristina_canale else ""
        await inter.edit_original_response(
            content=f"🔓 Gruppo liberato{suffix}: {', '.join(liberated) or '—'}",
            view=None,
        )
        log.info(tag("MOD", f"/isolamento_off [menu key={chosen_key}] {liberated} da {user(str(inter.user))}"))

    @app_commands.command(
        name="isolamento_lista",
        description=f"{_CROWN} Mostra gli utenti attualmente in quarantena",
    )
    @perm("admin")
    @admin_check
    async def isolamento_lista(self, inter: discord.Interaction):
        gid = inter.guild.id
        q_groups = self._quarantine_groups.get(gid, {})

        embed = discord.Embed(title="🔒 Utenti in quarantena", color=0xE67E22)
        if not q_groups:
            embed.description = "*Nessun utente in quarantena.*"
        else:
            for i, (gkey, info) in enumerate(q_groups.items(), 1):
                ch_obj   = inter.guild.get_channel(info["channel_id"])
                ch_name  = f"#{ch_obj.name}" if ch_obj else f"⚠️ canale eliminato (id:{info['channel_id']})"
                nomi = []
                for uid in info["members"]:
                    m = inter.guild.get_member(uid)
                    nomi.append(m.display_name if m else f"ID:{uid}")
                tipo = "Gruppo" if len(info["members"]) > 1 else "Singolo"
                embed.add_field(
                    name=f"[{tipo}] {info.get('label', '—')} → {ch_name}",
                    value="\n".join(nomi) or "—",
                    inline=False,
                )

        await inter.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="isolamento_gruppi",
        description=f"{_CROWN} Mostra i componenti di ogni gruppo di isolamento attivo",
    )
    @perm("admin")
    @admin_check
    async def isolamento_gruppi(self, inter: discord.Interaction):
        gid = inter.guild.id
        q_groups = self._quarantine_groups.get(gid, {})
        if not q_groups:
            return await inter.response.send_message("ℹ️ Nessuna sessione di isolamento attiva.", ephemeral=True)

        embed = discord.Embed(title="🔒 Gruppi di isolamento attivi", color=0xE67E22)
        for i, (gkey, info) in enumerate(q_groups.items(), 1):
            ch_obj  = inter.guild.get_channel(info["channel_id"])
            ch_name = f"#{ch_obj.name}" if ch_obj else f"⚠️ canale eliminato"
            nomi = []
            for uid in info["members"]:
                m = inter.guild.get_member(uid)
                prev_cid  = info["pre_channels"].get(uid)
                prev_ch   = inter.guild.get_channel(prev_cid) if prev_cid else None
                prev_name = f" *(era in #{prev_ch.name})*" if prev_ch else ""
                nomi.append((m.mention if m else f"ID:{uid}") + prev_name)
            embed.add_field(
                name=f"Gruppo {i} — {info.get('label', '—')} [{ch_name}]",
                value="\n".join(nomi) or "—",
                inline=False,
            )
        await inter.response.send_message(embed=embed, ephemeral=True)

    # ── Helpers interni ───────────────────────────────────────────

    @staticmethod
    async def _resolve_members(guild: discord.Guild, raw: str) -> list[discord.Member]:
        found = []
        for token in raw.split():
            clean = token.strip("<@!>").strip()
            if not clean or not clean.isdigit():
                if clean:
                    log.debug(tag("MOD", f"_resolve_members: token non numerico ignorato: {clean!r}"))
                continue
            uid = int(clean)
            m = guild.get_member(uid)
            if m is None:
                try:
                    m = await guild.fetch_member(uid)
                except discord.NotFound:
                    log.warning(tag("MOD", f"_resolve_members: utente ID {uid} non trovato nel server"))
                except discord.HTTPException as exc:
                    log.warning(tag("MOD", f"_resolve_members: errore fetch ID {uid}: {exc}"))
            if m and m not in found:
                found.append(m)
        return found

    @staticmethod
    async def _get_or_create_quarantine_channel(
        guild: discord.Guild,
        base_name: str,
    ) -> Optional[discord.VoiceChannel]:
        for ch_obj in guild.voice_channels:
            if ch_obj.name == base_name or ch_obj.name.startswith(base_name + "-"):
                return ch_obj

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
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(connect=False, view_channel=True),
                guild.me: discord.PermissionOverwrite(connect=True, move_members=True, view_channel=True),
            }
            return await guild.create_voice_channel(
                name=final_name,
                overwrites=overwrites,
                reason="Creazione canale quarantena automatica",
            )
        except (discord.Forbidden, discord.HTTPException):
            return None


async def setup(bot: commands.Bot):
    await bot.add_cog(Moderation(bot))
