"""
cogs/dev.py

Comandi riservati ai developer/owner del bot.
Espone tutti i comandi slash originali + gruppo /cache per la cache query.
"""

import asyncio
import io
import json
import logging
import os
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from config import Config
from core.bot_config import cfg
from core.ai_client import invalidate_prompt_cache
from core.ai_runtime import clear_conversation_memory
from core.constants import TYPE_MAP, STAT_MAP, TYPE_LABEL, STATUS_LABEL, UNDISABLEABLE, command_slug
from core.log_colors import tag, b, hi, user
from core.paths import (
    BOT_CONFIG_PATH,
    BIRTHDAYS_PATH,
    CUSTOM_STATUSES_PATH,
    WELCOME_CONFIG_PATH,
    WELCOME_IMAGES_DIR,
)
from core.permissions import owner_check, dev_check

log = logging.getLogger("pitonazz.dev")

BACKUP_FILES = [
    BOT_CONFIG_PATH,
    CUSTOM_STATUSES_PATH,
    WELCOME_CONFIG_PATH,
    BIRTHDAYS_PATH,
]
_MAX_RESTORE_BYTES = 10 * 1024 * 1024  # 10 MB
_OWN = "\U0001f527"
_CTX_ICON = "\U0001f4cb"


def _load_custom() -> list:
    if not CUSTOM_STATUSES_PATH.exists():
        return []
    try:
        return json.loads(CUSTOM_STATUSES_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_custom(data: list):
    CUSTOM_STATUSES_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _check_cache_env() -> list[str]:
    """
    Controlla che le variabili minime per la cache siano presenti.
    Ritorna lista di variabili mancanti (vuota = tutto OK).
    """
    missing = []
    if not Config.DB_PATH:
        missing.append("DB_PATH")
    return missing


class Dev(commands.Cog):
    COG_ICON = "\U0001f527"
    COG_LABEL = "Sviluppo"
    COG_TYPE = "dev"

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @staticmethod
    def _norm_cmd_name(name: str) -> str:
        return command_slug(name)

    def _iter_command_entries(self):
        def walk(item):
            if isinstance(item, app_commands.ContextMenu):
                yield item, item.name, True
                return
            if isinstance(item, app_commands.Command):
                qn = getattr(item, "qualified_name", item.name)
                yield item, command_slug(qn), False
                return
            if isinstance(item, app_commands.Group):
                for sub in item.commands:
                    yield from walk(sub)

        for cmd in self.bot.tree.get_commands():
            yield from walk(cmd)

    async def cog_app_command_error(
        self, inter: discord.Interaction, error: app_commands.AppCommandError
    ):
        if isinstance(error, app_commands.CheckFailure):
            if not inter.response.is_done():
                await inter.response.send_message(
                    "\u274c Non hai i permessi per usare questo comando.",
                    ephemeral=True,
                )
        else:
            log.error(tag("DEV", f"command error \u2192 {error}"))

    # ── OWNER ONLY ────────────────────────────────────────────────────────────

    @app_commands.command(name="restart", description=f"{_OWN} \U0001f451 Riavvia il bot")
    @owner_check
    async def restart(self, inter: discord.Interaction):
        await inter.response.send_message("\U0001f504 Riavvio in corso...", ephemeral=True)
        log.info(tag("DEV", f"restart richiesto da {user(str(inter.user))}"))
        await self.bot.close()
        python = sys.executable
        os.execv(python, [python] + sys.argv)

    @app_commands.command(name="sync", description=f"{_OWN} \U0001f451 Risincronizza i comandi slash")
    @app_commands.describe(clear_global="Cancella prima i comandi globali (rimuove duplicati)")
    @owner_check
    async def sync(self, inter: discord.Interaction, clear_global: bool = False):
        await inter.response.defer(ephemeral=True)
        lines = []
        if clear_global:
            self.bot.tree.clear_commands(guild=None)
            await self.bot.tree.sync()
            lines.append("\U0001f5d1\ufe0f Comandi **globali** cancellati.")
            log.info(tag("DEV", "sync \u2014 comandi globali cancellati"))
        if Config.GUILD_IDS:
            for gid in Config.GUILD_IDS:
                g = discord.Object(id=gid)
                self.bot.tree.copy_global_to(guild=g)
                synced = await self.bot.tree.sync(guild=g)
                guild_obj = self.bot.get_guild(gid)
                name = guild_obj.name if guild_obj else str(gid)
                lines.append(f"\u2705 **{name}**: {len(synced)} comandi.")
                log.info(tag("DEV", f"sync \u2192 {b(name)} {len(synced)} comandi"))
        else:
            synced = await self.bot.tree.sync()
            lines.append(f"\u2705 Sync globale: **{len(synced)}** comandi.")
            log.info(tag("DEV", f"sync globale \u2192 {b(len(synced))} comandi"))
        await inter.followup.send("\n".join(lines), ephemeral=True)

    @app_commands.command(name="maintenance", description=f"{_OWN} \U0001f451 Attiva/disattiva modalit\u00e0 manutenzione")
    @app_commands.describe(attiva="True = solo owner usa il bot, False = tutti")
    @owner_check
    async def maintenance(self, inter: discord.Interaction, attiva: bool):
        await cfg.set_maintenance(attiva)
        if attiva:
            await self.bot.apply_maintenance_presence()
        else:
            await self.bot.restore_presence_after_maintenance()
        stato = (
            "\U0001f6a7 **MANUTENZIONE ATTIVA** \u2014 solo tu puoi usare i comandi."
            if attiva
            else "\u2705 Manutenzione **disattivata** \u2014 bot accessibile a tutti."
        )
        state_label = "True" if attiva else "False"
        log.info(tag("DEV", f"maintenance \u2192 {b(state_label)}"))
        await inter.response.send_message(stato, ephemeral=True)

    @app_commands.command(name="backupconfig", description=f"{_OWN} \U0001f451 Esporta la configurazione del bot in un file ZIP")
    @owner_check
    async def backupconfig(self, inter: discord.Interaction):
        await inter.response.defer(ephemeral=True)
        buf = io.BytesIO()
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        included = []
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for fpath in BACKUP_FILES:
                if fpath.exists():
                    zf.write(fpath, fpath.name)
                    included.append(fpath.name)
                    log.info(tag("BACKUP", f"incluso: {b(fpath.name)}"))
                else:
                    if fpath.resolve() == BIRTHDAYS_PATH.resolve():
                        zf.writestr(fpath.name, "{}\n")
                        included.append(fpath.name)
                        log.info(tag("BACKUP", f"incluso (vuoto): {b(fpath.name)}"))
                        continue
                    log.info(tag("BACKUP", f"non trovato (skip): {b(fpath.name)}"))
            if WELCOME_IMAGES_DIR.exists():
                for img in WELCOME_IMAGES_DIR.iterdir():
                    if img.is_file():
                        arc_name = f"welcome_images/{img.name}"
                        zf.write(img, arc_name)
                        included.append(arc_name)
                        log.info(tag("BACKUP", f"incluso: {b(arc_name)}"))
            meta = {
                "timestamp": ts,
                "bot": str(self.bot.user),
                "guilds": len(self.bot.guilds),
                "files": included,
            }
            zf.writestr("backup_info.json", json.dumps(meta, indent=2))
        buf.seek(0)
        filename = f"pytonazz_backup_{ts}.zip"
        file = discord.File(buf, filename=filename)
        log.info(tag("BACKUP", f"backup esportato: {b(filename)} ({len(included)} file)"))
        file_list = ", ".join(f"`{f}`" for f in included) or "*nessuno*"
        await inter.followup.send(
            f"\u2705 Backup esportato: `{filename}`\n"
            f"\U0001f4e6 Contiene ({len(included)}): {file_list}",
            file=file,
            ephemeral=True,
        )

    @app_commands.command(name="restoreconfig", description=f"{_OWN} \U0001f451 Ripristina la configurazione da un file ZIP di backup")
    @app_commands.describe(backup="File ZIP generato da /backupconfig")
    @owner_check
    async def restoreconfig(self, inter: discord.Interaction, backup: discord.Attachment):
        await inter.response.defer(ephemeral=True)
        if not backup.filename.endswith(".zip"):
            return await inter.followup.send("\u274c Devi allegare un file `.zip` generato da `/backupconfig`.", ephemeral=True)
        if backup.size > _MAX_RESTORE_BYTES:
            return await inter.followup.send(
                f"\u274c File troppo grande (max {_MAX_RESTORE_BYTES // 1024 // 1024} MB).",
                ephemeral=True,
            )
        data = await backup.read()
        buf = io.BytesIO(data)
        restored = []
        try:
            with zipfile.ZipFile(buf, "r") as zf:
                names = zf.namelist()
                for fpath in BACKUP_FILES:
                    if fpath.name in names:
                        content = zf.read(fpath.name)
                        fpath.parent.mkdir(parents=True, exist_ok=True)
                        fpath.write_bytes(content)
                        restored.append(fpath.name)
                        log.info(tag("RESTORE", f"ripristinato: {b(fpath.name)}"))
                for name in names:
                    if name.startswith("welcome_images/") and not name.endswith("/"):
                        img_name = Path(name).name
                        dest = WELCOME_IMAGES_DIR / img_name
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        dest.write_bytes(zf.read(name))
                        restored.append(name)
                        log.info(tag("RESTORE", f"ripristinato: {b(name)}"))
        except zipfile.BadZipFile:
            return await inter.followup.send("\u274c File ZIP non valido o corrotto.", ephemeral=True)
        cfg.reload()
        log.info(tag("RESTORE", f"ripristinati {b(len(restored))} file"))
        await inter.followup.send(
            f"\u2705 Configurazione ripristinata!\n"
            f"File ripristinati: {', '.join(f'`{r}`' for r in restored)}\n"
            "\u26a0\ufe0f Fai `/restart` per applicare tutte le modifiche.",
            ephemeral=True,
        )

    # ── DEV ───────────────────────────────────────────────────────────────────

    @app_commands.command(name="disable_command", description=f"{_OWN} Disabilita un comando slash a runtime")
    @app_commands.describe(comando="Comando da disabilitare")
    @dev_check
    async def disablecommand(self, inter: discord.Interaction, comando: str):
        comando = self._norm_cmd_name(comando)
        if comando in UNDISABLEABLE:
            return await inter.response.send_message(
                f"\u274c `/{comando}` \u00e8 protetto e non pu\u00f2 essere disabilitato.", ephemeral=True
            )
        ok = await cfg.disable_command(comando)
        if not ok:
            return await inter.response.send_message(
                f"\u26a0\ufe0f `/{comando}` era gi\u00e0 disabilitato.", ephemeral=True
            )
        log.info(tag("DEV", f"disable {b(comando)}"))
        await inter.response.send_message(
            f"\U0001f6ab `/{comando}` **disabilitato**.\n*(Usa `/enable_command` per riattivarlo)*",
            ephemeral=True,
        )

    @disablecommand.autocomplete("comando")
    async def _autocomplete_disable(self, inter: discord.Interaction, current: str):
        disabled = {self._norm_cmd_name(n) for n in cfg.disabled_commands}
        current = self._norm_cmd_name(current)
        cmds = [
            qn for _, qn, is_ctx in self._iter_command_entries()
            if not is_ctx
            and self._norm_cmd_name(qn) not in disabled
            and self._norm_cmd_name(qn) not in UNDISABLEABLE
            and current in self._norm_cmd_name(qn)
        ]
        return [app_commands.Choice(name=n, value=n) for n in sorted(cmds)[:25]]

    @app_commands.command(name="enable_command", description=f"{_OWN} Riabilita un comando slash disabilitato")
    @app_commands.describe(comando="Comando da riabilitare")
    @dev_check
    async def enablecommand(self, inter: discord.Interaction, comando: str):
        comando = self._norm_cmd_name(comando)
        ok = await cfg.enable_command(comando)
        if not ok:
            return await inter.response.send_message(
                f"\u26a0\ufe0f `/{comando}` non era disabilitato.", ephemeral=True
            )
        log.info(tag("DEV", f"enable {b(comando)}"))
        await inter.response.send_message(f"\u2705 `/{comando}` **riabilitato**.", ephemeral=True)

    @enablecommand.autocomplete("comando")
    async def _autocomplete_enable(self, inter: discord.Interaction, current: str):
        current = self._norm_cmd_name(current)
        disabled = cfg.disabled_commands
        cmds = [n for n in disabled if current in self._norm_cmd_name(n)]
        return [app_commands.Choice(name=n, value=n) for n in sorted(cmds)[:25]]

    @app_commands.command(name="command_list", description=f"{_OWN} Panoramica comandi: abilitati, disabilitati e protetti")
    @dev_check
    async def commandlist(self, inter: discord.Interaction):
        disabled_set = {self._norm_cmd_name(n) for n in cfg.disabled_commands}
        all_cmds = sorted(
            list(self._iter_command_entries()),
            key=lambda x: self._norm_cmd_name(x[1]),
        )
        enabled_lines, disabled_lines, protected_lines = [], [], []
        for _, name, is_ctx in all_cmds:
            norm_name = self._norm_cmd_name(name)
            prefix = _CTX_ICON if is_ctx else "/"
            label = f"`{prefix}{name}`"
            if norm_name in UNDISABLEABLE:
                protected_lines.append(f"\U0001f512 {label}")
            elif norm_name in disabled_set:
                disabled_lines.append(f"\U0001f6ab {label}")
            else:
                enabled_lines.append(f"\u2705 {label}")
        embed = discord.Embed(
            title=f"\U0001f4cb Comandi del bot ({len(all_cmds)} foglia)",
            color=0x5865F2,
        )
        embed.add_field(name=f"\u2705 Abilitati ({len(enabled_lines)})", value="\n".join(enabled_lines) or "*Nessuno*", inline=False)
        embed.add_field(name=f"\U0001f6ab Disabilitati ({len(disabled_lines)})", value="\n".join(disabled_lines) or "*Nessuno*", inline=False)
        embed.add_field(name=f"\U0001f512 Protetti \u2014 non disabilitabili ({len(protected_lines)})", value="\n".join(protected_lines) or "*Nessuno*", inline=False)
        embed.set_footer(text="Context menu contrassegnati con \U0001f4cb")
        log.info(tag("DEV", f"command_list totale={len(all_cmds)} disabilitati={len(disabled_lines)}"))
        await inter.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="set_log_channel", description=f"{_OWN} Imposta il canale per gli errori del bot")
    @app_commands.describe(canale="Canale testo dove inviare gli errori (ometti per disattivare)")
    @dev_check
    async def setlogchannel(self, inter: discord.Interaction, canale: Optional[discord.TextChannel] = None):
        if canale is None:
            await cfg.set_log_channel(None)
            log.info(tag("DEV", "set_log_channel \u2192 rimosso"))
            await inter.response.send_message("\U0001f515 Log channel **rimosso**.", ephemeral=True)
        else:
            await cfg.set_log_channel(canale.id)
            log.info(tag("DEV", f"set_log_channel \u2192 #{canale.name} ({canale.id})"))
            await inter.response.send_message(
                f"\u2705 Errori del bot inviati in {canale.mention}", ephemeral=True
            )

    @app_commands.command(name="tts_volume", description=f"{_OWN} Cambia il volume del TTS (0.1 \u2013 3.0)")
    @app_commands.describe(valore="Moltiplicatore volume: 1.0 = originale")
    @dev_check
    async def ttsvolume(self, inter: discord.Interaction, valore: app_commands.Range[float, 0.1, 3.0]):
        await cfg.set_tts_volume(valore)
        bar = "\u2588" * int(valore / 0.3) + "\u2591" * max(0, 10 - int(valore / 0.3))
        log.info(tag("TTS", f"volume aggiornato \u2192 {b(valore)}x (persistente)"))
        await inter.response.send_message(
            f"\U0001f50a Volume TTS: **{valore}x** `{bar[:10]}`\n*(salvato, sopravvive ai restart)*",
            ephemeral=True,
        )

    # ── STATUS gruppo ─────────────────────────────────────────────────────────

    status = app_commands.Group(name="status", description=f"{_OWN} Gestione attivit\u00e0/status del bot")

    @status.command(name="add", description=f"{_OWN} Aggiunge un'attivit\u00e0 alla rotazione")
    @app_commands.describe(tipo="Tipo di attivit\u00e0", nome="Testo", stato="Stato del bot")
    @app_commands.choices(tipo=[
        app_commands.Choice(name="\U0001f3ae Giocando a", value="playing"),
        app_commands.Choice(name="\U0001f4fa Guardando", value="watching"),
        app_commands.Choice(name="\U0001f3b5 Ascoltando", value="listening"),
        app_commands.Choice(name="\U0001f3c6 Gareggiando in", value="competing"),
        app_commands.Choice(name="\U0001f4ac Stato custom", value="custom"),
    ])
    @app_commands.choices(stato=[
        app_commands.Choice(name="\U0001f7e2 Online", value="online"),
        app_commands.Choice(name="\U0001f7e1 Inattivo", value="idle"),
        app_commands.Choice(name="\U0001f534 Non disturbare", value="dnd"),
        app_commands.Choice(name="\u26ab Invisibile", value="invisible"),
    ])
    @dev_check
    async def status_add(self, inter: discord.Interaction, tipo: str, nome: str, stato: str = "online"):
        data = _load_custom()
        data.append({"type": tipo, "name": nome, "status": stato})
        _save_custom(data)
        self.bot.reload_status_list()
        log.info(tag("STATUS", f"add {b(nome)} tipo={tipo} stato={stato} totale={len(self.bot._status_list)}"))
        await inter.response.send_message(
            f"\u2705 **{TYPE_LABEL.get(tipo, tipo)} {nome}** aggiunto | {STATUS_LABEL.get(stato, stato)}\n"
            f"Rotazione: **{len(self.bot._status_list)}** voci totali.",
            ephemeral=True,
        )

    @status.command(name="remove", description=f"{_OWN} Rimuove un'attivit\u00e0 custom dalla rotazione")
    @app_commands.describe(indice="Indice custom da /status list (parte da 0; il primo della lista custom \u00e8 0)")
    @dev_check
    async def status_remove(self, inter: discord.Interaction, indice: int):
        data = _load_custom()
        if not data:
            return await inter.response.send_message("\u274c Nessuna attivit\u00e0 custom da rimuovere.", ephemeral=True)
        if not (0 <= indice < len(data)):
            return await inter.response.send_message(f"\u274c Indice non valido. Custom: 0\u2013{len(data)-1}", ephemeral=True)
        removed = data.pop(indice)
        _save_custom(data)
        self.bot.reload_status_list()
        log.info(tag("STATUS", f"remove {b(removed['name'])} rotazione={len(self.bot._status_list)}"))
        await inter.response.send_message(
            f"\U0001f5d1\ufe0f Rimosso: **{removed['name']}** | Rotazione: **{len(self.bot._status_list)}** voci.",
            ephemeral=True,
        )

    @status.command(name="edit", description=f"{_OWN} Modifica un'attivit\u00e0 custom esistente")
    @app_commands.describe(
        indice="Indice custom da /status list (parte da 0)",
        nome="Nuovo testo (lascia vuoto per non modificare)",
        tipo="Nuovo tipo",
        stato="Nuovo stato",
    )
    @app_commands.choices(tipo=[
        app_commands.Choice(name="\U0001f3ae Giocando a", value="playing"),
        app_commands.Choice(name="\U0001f4fa Guardando", value="watching"),
        app_commands.Choice(name="\U0001f3b5 Ascoltando", value="listening"),
        app_commands.Choice(name="\U0001f3c6 Gareggiando in", value="competing"),
        app_commands.Choice(name="\U0001f4ac Stato custom", value="custom"),
    ])
    @app_commands.choices(stato=[
        app_commands.Choice(name="\U0001f7e2 Online", value="online"),
        app_commands.Choice(name="\U0001f7e1 Inattivo", value="idle"),
        app_commands.Choice(name="\U0001f534 Non disturbare", value="dnd"),
        app_commands.Choice(name="\u26ab Invisibile", value="invisible"),
    ])
    @dev_check
    async def status_edit(
        self, inter: discord.Interaction,
        indice: int,
        nome: Optional[str] = None,
        tipo: Optional[str] = None,
        stato: Optional[str] = None,
    ):
        data = _load_custom()
        if not data:
            return await inter.response.send_message("\u274c Nessuna attivit\u00e0 custom da modificare.", ephemeral=True)
        if not (0 <= indice < len(data)):
            return await inter.response.send_message(f"\u274c Indice non valido. Custom: 0\u2013{len(data)-1}", ephemeral=True)
        if nome is None and tipo is None and stato is None:
            return await inter.response.send_message("\u274c Specifica almeno un campo da modificare.", ephemeral=True)
        entry = data[indice]
        old = dict(entry)
        if nome is not None: entry["name"] = nome
        if tipo is not None: entry["type"] = tipo
        if stato is not None: entry["status"] = stato
        _save_custom(data)
        self.bot.reload_status_list()
        log.info(tag("STATUS", f"edit #{indice} {b(old['name'])} \u2192 {b(entry['name'])} tipo={entry['type']} stato={entry['status']}"))
        await inter.response.send_message(
            f"\u270f\ufe0f **#{indice}** modificato:\n"
            f"Nome: `{old['name']}` \u2192 **{entry['name']}**\n"
            f"Tipo: `{old['type']}` \u2192 **{entry['type']}**\n"
            f"Stato: `{old['status']}` \u2192 **{entry['status']}**",
            ephemeral=True,
        )

    @status.command(name="list", description=f"{_OWN} Mostra tutte le attivit\u00e0 in rotazione")
    @dev_check
    async def status_list(self, inter: discord.Interaction):
        from assets.status_messages import STATUS_CYCLE
        custom = _load_custom()
        lines = []
        for i, e in enumerate(STATUS_CYCLE):
            s = STATUS_LABEL.get(e.get("status", "online"), e.get("status", ""))
            tipo = e["type"].name if hasattr(e["type"], "name") else str(e["type"])
            suffix = " *(default)*" if i == 0 else ""
            lines.append(f"**{i}.** `{tipo}` {e['name']} \u2014 {s}{suffix}")
        base_count = len(STATUS_CYCLE)
        for i, e in enumerate(custom):
            s = STATUS_LABEL.get(e.get("status", "online"), e.get("status", ""))
            tipo = e["type"] if isinstance(e["type"], str) else e["type"].name
            lines.append(f"**{base_count + i}.** `{tipo}` {e['name']} \u2014 {s}")
        embed = discord.Embed(
            title=f"\U0001f3a4 Rotazione attivit\u00e0 ({len(self.bot._status_list)} voci)",
            description="\n".join(lines) or "Nessuna attivit\u00e0.",
            color=0x5865F2,
        )
        embed.set_footer(text="Indici 0\u2013N default (non rimovibili). Usa /status remove per i custom.")
        await inter.response.send_message(embed=embed, ephemeral=True)

    @status.command(name="set", description=f"{_OWN} Imposta subito uno stato (non aggiunto alla rotazione)")
    @app_commands.describe(tipo="Tipo", nome="Testo", stato="Stato")
    @app_commands.choices(tipo=[
        app_commands.Choice(name="\U0001f3ae Giocando a", value="playing"),
        app_commands.Choice(name="\U0001f4fa Guardando", value="watching"),
        app_commands.Choice(name="\U0001f3b5 Ascoltando", value="listening"),
        app_commands.Choice(name="\U0001f3c6 Gareggiando in", value="competing"),
        app_commands.Choice(name="\U0001f4ac Stato custom", value="custom"),
    ])
    @app_commands.choices(stato=[
        app_commands.Choice(name="\U0001f7e2 Online", value="online"),
        app_commands.Choice(name="\U0001f7e1 Inattivo", value="idle"),
        app_commands.Choice(name="\U0001f534 Non disturbare", value="dnd"),
        app_commands.Choice(name="\u26ab Invisibile", value="invisible"),
    ])
    @dev_check
    async def status_set(self, inter: discord.Interaction, tipo: str, nome: str, stato: str = "online"):
        act_type = TYPE_MAP.get(tipo, discord.ActivityType.playing)
        activity = (
            discord.CustomActivity(name=nome)
            if act_type == discord.ActivityType.custom
            else discord.Activity(type=act_type, name=nome)
        )
        await self.bot.change_presence(activity=activity, status=STAT_MAP.get(stato, discord.Status.online))
        log.info(tag("STATUS", f"set {b(nome)} tipo={tipo} stato={stato}"))
        await inter.response.send_message(
            f"\u2705 **{TYPE_LABEL.get(tipo, tipo)} {nome}** | {STATUS_LABEL.get(stato, stato)}\n"
            "*(Verr\u00e0 sovrascritto al prossimo ciclo)*",
            ephemeral=True,
        )

    @status.command(name="interval", description=f"{_OWN} Cambia l'intervallo della rotazione status")
    @app_commands.describe(secondi="Intervallo in secondi (minimo 10)")
    @dev_check
    async def status_interval(self, inter: discord.Interaction, secondi: int):
        if secondi < 10:
            return await inter.response.send_message("\u274c Minimo 10 secondi.", ephemeral=True)
        await cfg.set_status_interval(secondi)
        self.bot.cycle_status.change_interval(seconds=secondi)
        minuti = secondi / 60
        log.info(tag("STATUS", f"interval {b(secondi)}s ({minuti:.1f} min) \u2014 salvato"))
        await inter.response.send_message(
            f"\u23f1\ufe0f Intervallo aggiornato: **{secondi}s** ({minuti:.1f} min)\n*(salvato, sopravvive ai restart)*",
            ephemeral=True,
        )

    # ── Altri comandi dev ─────────────────────────────────────────────────────

    @app_commands.command(name="say", description=f"{_OWN} Fai parlare il bot in un canale")
    @app_commands.describe(testo="Messaggio da inviare", canale="Canale destinazione (default: corrente)")
    @dev_check
    async def say(self, inter: discord.Interaction, testo: str, canale: Optional[discord.TextChannel] = None):
        dest = canale or inter.channel
        try:
            await dest.send(testo)
        except discord.Forbidden:
            log.warning(tag("DEV", f"say Forbidden #{dest.name}"))
            return await inter.response.send_message(
                f"\u274c Non ho i permessi per scrivere in {dest.mention}.", ephemeral=True
            )
        log.info(tag("DEV", f"say \u2192 #{dest.name} {hi(repr(testo[:60]))}"))
        await inter.response.send_message(f"\u2705 Inviato in {dest.mention}", ephemeral=True)

    @app_commands.command(name="announce", description=f"{_OWN} Manda un annuncio con embed in un canale")
    @app_commands.describe(titolo="Titolo embed", testo="Corpo del messaggio", canale="Canale destinazione")
    @dev_check
    async def announce(self, inter: discord.Interaction, titolo: str, testo: str, canale: Optional[discord.TextChannel] = None):
        dest = canale or inter.channel
        embed = discord.Embed(title=titolo, description=testo, color=0x5865F2)
        embed.set_footer(text=f"Annuncio di {inter.user.display_name}")
        try:
            await dest.send(embed=embed)
        except discord.Forbidden:
            log.warning(tag("DEV", f"announce Forbidden #{dest.name}"))
            return await inter.response.send_message(
                f"\u274c Non ho i permessi per scrivere in {dest.mention}.", ephemeral=True
            )
        log.info(tag("DEV", f"announce \u2192 #{dest.name} titolo={b(titolo)}"))
        await inter.response.send_message(f"\u2705 Annuncio inviato in {dest.mention}", ephemeral=True)

    @app_commands.command(name="cog_list", description=f"{_OWN} Lista di tutti i cog caricati")
    @dev_check
    async def coglist(self, inter: discord.Interaction):
        cogs = sorted(self.bot.cogs.keys())
        righe = [f"\U0001f9e9 `{c}`" for c in cogs]
        embed = discord.Embed(
            title=f"Cog caricati ({len(cogs)})",
            description="\n".join(righe),
            color=0x2f3136,
        )
        await inter.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="ai_reset", description=f"{_OWN} Azzera la memoria conversazionale dell'AI")
    @app_commands.describe(canale="Canale da resettare (default: tutti)")
    @dev_check
    async def ai_reset(self, inter: discord.Interaction, canale: Optional[discord.TextChannel] = None):
        invalidate_prompt_cache()
        if canale:
            _ = clear_conversation_memory(canale.id)
            log.info(tag("AI", f"ai_reset canale=#{canale.name} da {user(str(inter.user))}"))
            await inter.response.send_message(
                f"\U0001f9f9 Memoria AI resettata per {canale.mention}.", ephemeral=True
            )
        else:
            count = clear_conversation_memory()
            log.info(tag("AI", f"ai_reset TUTTI ({count} canali) da {user(str(inter.user))}"))
            await inter.response.send_message(
                f"\U0001f9f9 Memoria AI resettata per **{count}** canali.", ephemeral=True
            )

    @app_commands.command(name="debug", description=f"{_OWN} Attiva/disattiva il livello log DEBUG a runtime")
    @app_commands.describe(stato="on = DEBUG enrichment Spotify, off = INFO")
    @app_commands.choices(stato=[
        app_commands.Choice(name="\U0001f7e2 on \u2014 abilita DEBUG", value="on"),
        app_commands.Choice(name="\U0001f534 off \u2014 torna a INFO", value="off"),
    ])
    @dev_check
    async def debug(self, inter: discord.Interaction, stato: str):
        level = logging.DEBUG if stato.lower() == "on" else logging.INFO
        logging.getLogger("pitonazz.spotify_enrich").setLevel(level)
        label = "DEBUG \U0001f7e2" if level == logging.DEBUG else "INFO \U0001f534"
        log.info(tag("DEV", f"log level \u2192 {b(label)} (from {user(str(inter.user))})"))
        await inter.response.send_message(
            f"\U0001f527 Livello log impostato a **{label}**\n"
            + (
                "Vedrai ora solo i dettagli DEBUG dell'enrichment Spotify."
                if level == logging.DEBUG
                else "Logger enrichment Spotify tornato a INFO."
            ),
            ephemeral=True,
        )

    # ── CACHE gruppo (/cache on|off|status|stats|clear) ───────────────────────

    cache = app_commands.Group(name="cache", description=f"{_OWN} Gestione cache query musicali")

    @cache.command(name="on", description=f"{_OWN} Abilita la cache query a runtime")
    @dev_check
    async def cache_on(self, inter: discord.Interaction):
        missing = _check_cache_env()
        if missing:
            return await inter.response.send_message(
                f"\u26a0\ufe0f Impossibile abilitare la cache.\n"
                f"Variabili mancanti nel `.env`: `{'`, `'.join(missing)}`",
                ephemeral=True,
            )
        try:
            import core.cache_db as cdb
            cdb.init()
        except Exception as e:
            return await inter.response.send_message(f"\u274c Errore inizializzazione DB: `{e}`", ephemeral=True)
        Config.CACHE_ENABLED = True
        log.info(tag("DEV", f"cache abilitata da {b(str(inter.user))}"))
        await inter.response.send_message("\u2705 Cache **abilitata**.", ephemeral=True)

    @cache.command(name="off", description=f"{_OWN} Disabilita la cache query a runtime (i dati restano)")
    @dev_check
    async def cache_off(self, inter: discord.Interaction):
        Config.CACHE_ENABLED = False
        log.info(tag("DEV", f"cache disabilitata da {b(str(inter.user))}"))
        await inter.response.send_message("\u23f8\ufe0f Cache **disabilitata**. I dati restano nel DB.", ephemeral=True)

    @cache.command(name="status", description=f"{_OWN} Mostra lo stato attuale della cache")
    @dev_check
    async def cache_status(self, inter: discord.Interaction):
        enabled = Config.CACHE_ENABLED
        env_ok = not _check_cache_env()
        icon = "\u2705" if enabled else "\u23f8\ufe0f"
        env_icon = "\u2705" if env_ok else "\u26a0\ufe0f variabili mancanti"
        lines = [
            f"{icon} Cache runtime: **{'ON' if enabled else 'OFF'}**",
            f"DB path      : `{Config.DB_PATH}`",
            f"TTL          : {Config.CACHE_TTL_DAYS} giorni",
            f"Max entries  : {Config.CACHE_MAX_ENTRIES}",
            f"Env valido   : {env_icon}",
        ]
        await inter.response.send_message("\n".join(lines), ephemeral=True)

    @cache.command(name="stats", description=f"{_OWN} Statistiche del DB cache (voci, hit, alias)")
    @dev_check
    async def cache_stats(self, inter: discord.Interaction):
        if not Config.CACHE_ENABLED:
            return await inter.response.send_message("\u26a0\ufe0f Cache non abilitata.", ephemeral=True)
        try:
            import core.cache_db as cdb
            s = cdb.stats()
        except Exception as e:
            return await inter.response.send_message(f"\u274c Errore lettura stats: `{e}`", ephemeral=True)
        lines = [
            "\U0001f4ca **Cache stats**",
            f"Voci valide : {s['total']}",
            f"Hit totali  : {s['hits']}",
            f"Alias       : {s['aliases']}",
        ]
        await inter.response.send_message("\n".join(lines), ephemeral=True)

    @cache.command(name="clear", description=f"{_OWN} Svuota il DB della cache")
    @dev_check
    async def cache_clear(self, inter: discord.Interaction):
        if not Config.CACHE_ENABLED:
            return await inter.response.send_message("\u26a0\ufe0f Cache non abilitata.", ephemeral=True)
        try:
            import core.cache_db as cdb
            n = cdb.clear()
        except Exception as e:
            return await inter.response.send_message(f"\u274c Errore clear: `{e}`", ephemeral=True)
        await inter.response.send_message(f"\U0001f9f9 Cache svuotata: **{n}** voci eliminate.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Dev(bot))
