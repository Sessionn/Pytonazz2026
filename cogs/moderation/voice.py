"""VoiceCommands: implementation shared by the public Moderation facade."""
from __future__ import annotations
import logging
import discord
from discord import app_commands
from core.log_colors import tag, user
from core.moderation.utils import resolve_members
from core.permissions import admin_check, perm
from ui.moderation import GroupSelectView
from discord.ext import commands
log = logging.getLogger("pitonazz.moderation")

_CROWN = "👑"


class VoiceCommands(commands.Cog):
    @app_commands.command(name="museruola", description=f"{_CROWN} Muta permanentemente il microfono di uno o più utenti")
    @app_commands.describe(utenti="Utenti da mutare, separati da spazio (menzioni o ID)")
    @perm("admin")
    @admin_check
    async def museruola(self, inter: discord.Interaction, utenti: str):
        await inter.response.defer(ephemeral=True)
        gid = inter.guild.id
        if gid not in self._muted_mic:
            self._muted_mic[gid] = set()

        members = await resolve_members(inter.guild, utenti)
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
            members = await resolve_members(inter.guild, utenti)

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

        members = await resolve_members(inter.guild, utenti)
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
            members = await resolve_members(inter.guild, utenti)
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

        view = GroupSelectView(groups=groups, guild=inter.guild)
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
