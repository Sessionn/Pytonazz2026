"""IsolationCommands: implementation shared by the public Moderation facade."""
from __future__ import annotations
import asyncio
import logging
from typing import Optional
import discord
from discord import app_commands
from core.log_colors import tag, user
from core.moderation.utils import get_or_create_quarantine_channel, resolve_members
from core.permissions import admin_check, perm
from ui.moderation import GroupSelectView
from discord.ext import commands
log = logging.getLogger("pitonazz.moderation")

_CROWN = "👑"


class IsolationCommands(commands.Cog):
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

        members = await resolve_members(inter.guild, utenti)
        if not members:
            return await inter.followup.send("❌ Nessun utente valido trovato.", ephemeral=True)

        q_channel = await get_or_create_quarantine_channel(inter.guild, nome_canale)
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
            members = await resolve_members(inter.guild, utenti)
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

        view = GroupSelectView(groups=q_groups, guild=inter.guild)
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
