"""Moderation extension: lifecycle and orchestration; commands live in sibling modules."""
from .isolation import IsolationCommands

from .voice import VoiceCommands

from .standard import StandardCommands

import asyncio
import logging
from datetime import timedelta
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks

from core.moderation.isolation_registry import load_quarantine_groups
from core.log_colors import tag, user, ch
from core.moderation.state import (
    all_deafened_uids,
    all_quarantined_uids,
    group_for_uid,
    save_quarantine_state,
)
from core.moderation.utils import get_or_create_quarantine_channel

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


class Moderation(IsolationCommands, VoiceCommands, StandardCommands, commands.Cog):
    COG_ICON  = "🛡️"
    COG_LABEL = "Moderazione"
    COG_TYPE  = "admin"

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # guild_id -> {user_id: bool}  — utenti con microfono mutato via /museruola
        state = getattr(bot, '_pytonazz_moderation_session', None)
        if state is None:
            state = ({}, {}, load_quarantine_groups())
            bot._pytonazz_moderation_session = state
        self._muted_mic: dict[int, set[int]] = state[0]
        # guild_id -> {group_key: {"members": set, "label": str}}
        self._deafened_groups: dict[int, dict[int, dict]] = state[1]
        # guild_id -> {group_key: {"members": set, "channel_id": int, "base_name": str, "pre_channels": dict}}
        self._quarantine_groups: dict[int, dict[int, dict]] = state[2]

    def _save_quarantine_state(self) -> None:
        save_quarantine_state(self._quarantine_groups, log)


    # ── Helpers state interni ─────────────────────────────────────

    def _all_deafened_uids(self, gid: int) -> set[int]:
        """Restituisce tutti gli user ID attualmente sordati in una guild."""
        return all_deafened_uids(self._deafened_groups.get(gid, {}))

    def _all_quarantined_uids(self, gid: int) -> dict[int, int]:
        """Restituisce {uid: channel_id} per tutti gli utenti in quarantena."""
        return all_quarantined_uids(self._quarantine_groups.get(gid, {}))

    def _group_for_uid_quarantine(self, gid: int, uid: int) -> Optional[int]:
        """Restituisce il group_key del gruppo quarantena che contiene uid."""
        return group_for_uid(self._quarantine_groups.get(gid, {}), uid)

    def _group_for_uid_jenny(self, gid: int, uid: int) -> Optional[int]:
        """Restituisce il group_key del gruppo jenniserpi che contiene uid."""
        return group_for_uid(self._deafened_groups.get(gid, {}), uid)

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
                    new_ch = await get_or_create_quarantine_channel(guild, base_name)
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
            target_ch = await get_or_create_quarantine_channel(member.guild, base_name)
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
            new_ch = await get_or_create_quarantine_channel(guild, base_name)
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





    # ── /kick ─────────────────────────────────────────────────────

    # /ban


    # /timeout




    # ── /jenniserpi ───────────────────────────────────────────────
    #
    # Supporta singolo utente O gruppo (utenti multipli separati da spazio).
    # Un gruppo viene registrato come un'unità unica (group_key = timestamp).
    # jenniserpi_off senza argomenti mostra il menu a tendina con i gruppi attivi.


    # ── /isolamento ───────────────────────────────────────────────
    #
    # Supporta singolo utente O gruppo.
    # Al termine dell'isolamento l'admin sceglie: disconnetti oppure rimetti
    # gli utenti nel canale in cui erano prima.


    # ── Helpers interni ───────────────────────────────────────────


async def setup(bot: commands.Bot):
    await bot.add_cog(Moderation(bot))
