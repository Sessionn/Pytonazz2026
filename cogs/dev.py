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
_OWN = "🔧"
_CTX_ICON = "📋"


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


class Dev(commands.Cog):
    COG_ICON  = "🔧"
    COG_LABEL = "Sviluppo"
    COG_TYPE  = "dev"

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
                    "❌ Non hai i permessi per usare questo comando.",
                    ephemeral=True,
                )
        else:
            log.error(tag("DEV", f"command error → {error}"))

    # ── OWNER ONLY — comandi irreversibili/pericolosi ─────────────────────────

    @app_commands.command(name="restart", description=f"{_OWN} 👑 Riavvia il bot")
    @owner_check
    async def restart(self, inter: discord.Interaction):
        await inter.response.send_message("🔄 Riavvio in corso...", ephemeral=True)
        log.info(tag("DEV", f"restart richiesto da {user(str(inter.user))}"))
        await self.bot.close()
        python = sys.executable
        os.execv(python, [python] + sys.argv)

    @app_commands.command(name="sync", description=f"{_OWN} 👑 Risincronizza i comandi slash")
    @app_commands.describe(clear_global="Cancella prima i comandi globali (rimuove duplicati)")
    @owner_check
    async def sync(self, inter: discord.Interaction, clear_global: bool = False):
        await inter.response.defer(ephemeral=True)
        lines = []
        if clear_global:
            self.bot.tree.clear_commands(guild=None)
            await self.bot.tree.sync()
            lines.append("🗑️ Comandi **globali** cancellati.")
            log.info(tag("DEV", "sync — comandi globali cancellati"))
        if Config.GUILD_IDS:
            for gid in Config.GUILD_IDS:
                g = discord.Object(id=gid)
                self.bot.tree.copy_global_to(guild=g)
                synced = await self.bot.tree.sync(guild=g)
                guild_obj = self.bot.get_guild(gid)
                name = guild_obj.name if guild_obj else str(gid)
                lines.append(f"✅ **{name}**: {len(synced)} comandi.")
                log.info(tag("DEV", f"sync → {b(name)}  {len(synced)} comandi"))
        else:
            synced = await self.bot.tree.sync()
            lines.append(f"✅ Sync globale: **{len(synced)}** comandi.")
            log.info(tag("DEV", f"sync globale → {b(len(synced))} comandi"))
        await inter.followup.send("\n".join(lines), ephemeral=True)

    @app_commands.command(name="maintenance", description=f"{_OWN} 👑 Attiva/disattiva modalità manutenzione")
    @app_commands.describe(attiva="True = solo owner usa il bot, False = tutti")
    @owner_check
    async def maintenance(self, inter: discord.Interaction, attiva: bool):
        await cfg.set_maintenance(attiva)
        if attiva:
            await self.bot.apply_maintenance_presence()
        else:
            await self.bot.apply_next_status()
        stato = "🚧 **MANUTENZIONE ATTIVA** — solo tu puoi usare i comandi." if attiva \
               else "✅ Manutenzione **disattivata** — bot accessibile a tutti."
        log.info(tag("DEV", f"maintenance → {b(attiva)}"))
        await inter.response.send_message(stato, ephemeral=True)

    @app_commands.command(name="backup config", description=f"{_OWN} 👑 Esporta la configurazione del bot in un file ZIP")
    @owner_check
    async def backupconfig(self, inter: discord.Interaction):
        await inter.response.defer(ephemeral=True)
        buf = io.BytesIO()
        ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
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
        log.info(tag("BACKUP", f"backup esportato: {b(filename)}  ({len(included)} file)"))
        file_list = ", ".join(f"`{f}`" for f in included) or "*nessuno*"
        await inter.followup.send(
            f"✅ Backup esportato: `{filename}`\n"
            f"📦 Contiene ({len(included)}): {file_list}",
            file=file,
            ephemeral=True,
        )

    @app_commands.command(name="restore config", description=f"{_OWN} 👑 Ripristina la configurazione da un file ZIP di backup")
    @app_commands.describe(backup="File ZIP generato da /backup config")
    @owner_check
    async def restoreconfig(self, inter: discord.Interaction, backup: discord.Attachment):
        await inter.response.defer(ephemeral=True)
        if not backup.filename.endswith(".zip"):
            return await inter.followup.send("❌ Devi allegare un file `.zip` generato da `/backup config`.", ephemeral=True)
        if backup.size > _MAX_RESTORE_BYTES:
            return await inter.followup.send(
                f"❌ File troppo grande (max {_MAX_RESTORE_BYTES // 1024 // 1024} MB).",
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
            return await inter.followup.send("❌ File ZIP non valido o corrotto.", ephemeral=True)
        cfg.reload()
        log.info(tag("RESTORE", f"ripristinati {b(len(restored))} file"))
        await inter.followup.send(
            f"✅ Configurazione ripristinata!\n"
            f"File ripristinati: {', '.join(f'`{r}`' for r in restored)}\n"
            "⚠️ Fai `/restart` per applicare tutte le modifiche.",
            ephemeral=True,
        )

    # ── DEV — comandi di gestione quotidiana ──────────────────────────────────

    @app_commands.command(name="disable command", description=f"{_OWN} Disabilita un comando slash a runtime")
    @app_commands.describe(comando="Comando da disabilitare")
    @dev_check
    async def disablecommand(self, inter: discord.Interaction, comando: str):
        comando = self._norm_cmd_name(comando)
        if comando in UNDISABLEABLE:
            return await inter.response.send_message(
                f"❌ `/{comando}` è protetto e non può essere disabilitato.", ephemeral=True
            )
        ok = await cfg.disable_command(comando)
        if not ok:
            return await inter.response.send_message(
                f"⚠️ `/{comando}` era già disabilitato.", ephemeral=True
            )
        log.info(tag("DEV", f"disable  {b(comando)}"))
        await inter.response.send_message(
            f"🚫 `/{comando}` **disabilitato**.\n*(Usa `/enable command` per riattivarlo)*",
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

    @app_commands.command(name="enable command", description=f"{_OWN} Riabilita un comando slash disabilitato")
    @app_commands.describe(comando="Comando da riabilitare")
    @dev_check
    async def enablecommand(self, inter: discord.Interaction, comando: str):
        comando = self._norm_cmd_name(comando)
        ok = await cfg.enable_command(comando)
        if not ok:
            return await inter.response.send_message(
                f"⚠️ `/{comando}` non era disabilitato.", ephemeral=True
            )
        log.info(tag("DEV", f"enable  {b(comando)}"))
        await inter.response.send_message(f"✅ `/{comando}` **riabilitato**.", ephemeral=True)

    @enablecommand.autocomplete("comando")
    async def _autocomplete_enable(self, inter: discord.Interaction, current: str):
        current = self._norm_cmd_name(current)
        disabled = cfg.disabled_commands
        cmds = [n for n in disabled if current in self._norm_cmd_name(n)]
        return [app_commands.Choice(name=n, value=n) for n in sorted(cmds)[:25]]

    @app_commands.command(name="command list", description=f"{_OWN} Panoramica comandi: abilitati, disabilitati e protetti")
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
            label  = f"`{prefix}{name}`"
            if norm_name in UNDISABLEABLE:
                protected_lines.append(f"🔒 {label}")
            elif norm_name in disabled_set:
                disabled_lines.append(f"🚫 {label}")
            else:
                enabled_lines.append(f"✅ {label}")
        embed = discord.Embed(
            title=f"📋 Comandi del bot  ({len(all_cmds)} foglia)",
            color=0x5865F2,
        )
        embed.add_field(name=f"✅ Abilitati ({len(enabled_lines)})",                        value="\n".join(enabled_lines)   or "*Nessuno*", inline=False)
        embed.add_field(name=f"🚫 Disabilitati ({len(disabled_lines)})",                  value="\n".join(disabled_lines)  or "*Nessuno*", inline=False)
        embed.add_field(name=f"🔒 Protetti — non disabilitabili ({len(protected_lines)})", value="\n".join(protected_lines) or "*Nessuno*", inline=False)
        embed.set_footer(text="Context menu contrassegnati con 📋")
        log.info(tag("DEV", f"command list  totale={len(all_cmds)}  disabilitati={len(disabled_lines)}"))
        await inter.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="set log channel", description=f"{_OWN} Imposta il canale per gli errori del bot")
    @app_commands.describe(canale="Canale testo dove inviare gli errori (ometti per disattivare)")
    @dev_check
    async def setlogchannel(self, inter: discord.Interaction, canale: Optional[discord.TextChannel] = None):
        if canale is None:
            await cfg.set_log_channel(None)
            log.info(tag("DEV", "set log channel → rimosso"))
            await inter.response.send_message("🔕 Log channel **rimosso**.", ephemeral=True)
        else:
            await cfg.set_log_channel(canale.id)
            log.info(tag("DEV", f"set log channel → #{canale.name} ({canale.id})"))
            await inter.response.send_message(
                f"✅ Errori del bot inviati in {canale.mention}", ephemeral=True
            )

    @app_commands.command(name="tts volume", description=f"{_OWN} Cambia il volume del TTS (0.1 – 3.0)")
    @app_commands.describe(valore="Moltiplicatore volume: 1.0 = originale")
    @dev_check
    async def ttsvolume(self, inter: discord.Interaction, valore: app_commands.Range[float, 0.1, 3.0]):
        await cfg.set_tts_volume(valore)
        bar = "█" * int(valore / 0.3) + "░" * max(0, 10 - int(valore / 0.3))
        log.info(tag("TTS", f"volume aggiornato → {b(valore)}x (persistente)"))
        await inter.response.send_message(
            f"🔊 Volume TTS: **{valore}x** `{bar[:10]}`\n*(salvato, sopravvive ai restart)*",
            ephemeral=True,
        )

    # ── STATUS gruppo ─────────────────────────────────────────────────────────

    status = app_commands.Group(name="status", description=f"{_OWN} Gestione attività/status del bot")

    @status.command(name="add", description=f"{_OWN} Aggiunge un'attività alla rotazione")
    @app_commands.describe(tipo="Tipo di attività", nome="Testo", stato="Stato del bot")
    @app_commands.choices(tipo=[
        app_commands.Choice(name="🎮 Giocando a",    value="playing"),
        app_commands.Choice(name="📺 Guardando",      value="watching"),
        app_commands.Choice(name="🎵 Ascoltando",     value="listening"),
        app_commands.Choice(name="🏆 Gareggiando in", value="competing"),
        app_commands.Choice(name="💬 Stato custom",   value="custom"),
    ])
    @app_commands.choices(stato=[
        app_commands.Choice(name="🟢 Online",         value="online"),
        app_commands.Choice(name="🟡 Inattivo",       value="idle"),
        app_commands.Choice(name="🔴 Non disturbare", value="dnd"),
        app_commands.Choice(name="⚫ Invisibile",      value="invisible"),
    ])
    @dev_check
    async def status_add(self, inter: discord.Interaction, tipo: str, nome: str, stato: str = "online"):
        data = _load_custom()
        data.append({"type": tipo, "name": nome, "status": stato})
        _save_custom(data)
        self.bot.reload_status_list()
        log.info(tag("STATUS", f"add  {b(nome)}  tipo={tipo}  stato={stato}  totale={len(self.bot._status_list)}"))
        await inter.response.send_message(
            f"✅ **{TYPE_LABEL.get(tipo, tipo)} {nome}** aggiunto | {STATUS_LABEL.get(stato, stato)}\n"
            f"Rotazione: **{len(self.bot._status_list)}** voci totali.",
            ephemeral=True,
        )

    @status.command(name="remove", description=f"{_OWN} Rimuove un'attività custom dalla rotazione")
    @app_commands.describe(indice="Numero custom da /status list (a partire da 0; lo 0 è il default)")
    @dev_check
    async def status_remove(self, inter: discord.Interaction, indice: int):
        data = _load_custom()
        if not data:
            return await inter.response.send_message("❌ Nessuna attività custom da rimuovere.", ephemeral=True)
        if not (0 <= indice < len(data)):
            return await inter.response.send_message(f"❌ Indice non valido. Custom: 0–{len(data)-1}", ephemeral=True)
        removed = data.pop(indice)
        _save_custom(data)
        self.bot.reload_status_list()
        log.info(tag("STATUS", f"remove  {b(removed['name'])}  rotazione={len(self.bot._status_list)}"))
        await inter.response.send_message(
            f"🗑️ Rimosso: **{removed['name']}** | Rotazione: **{len(self.bot._status_list)}** voci.",
            ephemeral=True,
        )

    @status.command(name="edit", description=f"{_OWN} Modifica un'attività custom esistente")
    @app_commands.describe(
        indice="Numero custom da /status list (a partire da 0)",
        nome="Nuovo testo (lascia vuoto per non modificare)",
        tipo="Nuovo tipo",
        stato="Nuovo stato",
    )
    @app_commands.choices(tipo=[
        app_commands.Choice(name="🎮 Giocando a",    value="playing"),
        app_commands.Choice(name="📺 Guardando",      value="watching"),
        app_commands.Choice(name="🎵 Ascoltando",     value="listening"),
        app_commands.Choice(name="🏆 Gareggiando in", value="competing"),
        app_commands.Choice(name="💬 Stato custom",   value="custom"),
    ])
    @app_commands.choices(stato=[
        app_commands.Choice(name="🟢 Online",         value="online"),
        app_commands.Choice(name="🟡 Inattivo",       value="idle"),
        app_commands.Choice(name="🔴 Non disturbare", value="dnd"),
        app_commands.Choice(name="⚫ Invisibile",      value="invisible"),
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
            return await inter.response.send_message("❌ Nessuna attività custom da modificare.", ephemeral=True)
        if not (0 <= indice < len(data)):
            return await inter.response.send_message(f"❌ Indice non valido. Custom: 0–{len(data)-1}", ephemeral=True)
        if nome is None and tipo is None and stato is None:
            return await inter.response.send_message("❌ Specifica almeno un campo da modificare.", ephemeral=True)
        entry = data[indice]
        old   = dict(entry)
        if nome  is not None: entry["name"]   = nome
        if tipo  is not None: entry["type"]   = tipo
        if stato is not None: entry["status"] = stato
        _save_custom(data)
        self.bot.reload_status_list()
        log.info(tag("STATUS", f"edit #{indice}  {b(old['name'])} → {b(entry['name'])}  tipo={entry['type']}  stato={entry['status']}"))
        await inter.response.send_message(
            f"✏️ **#{indice}** modificato:\n"
            f"Nome: `{old['name']}` → **{entry['name']}**\n"
            f"Tipo: `{old['type']}` → **{entry['type']}**\n"
            f"Stato: `{old['status']}` → **{entry['status']}**",
            ephemeral=True,
        )

    @status.command(name="list", description=f"{_OWN} Mostra tutte le attività in rotazione")
    @dev_check
    async def status_list(self, inter: discord.Interaction):
        from assets.status_messages import STATUS_CYCLE
        custom = _load_custom()
        lines = []
        for i, e in enumerate(STATUS_CYCLE):
            s    = STATUS_LABEL.get(e.get("status", "online"), e.get("status", ""))
            tipo = e["type"].name if hasattr(e["type"], "name") else str(e["type"])
            lines.append(f"**{i}.** `{tipo}` {e['name']} — {s} *(default)*")
        for i, e in enumerate(custom):
            s    = STATUS_LABEL.get(e.get("status", "online"), e.get("status", ""))
            tipo = e["type"] if isinstance(e["type"], str) else e["type"].name
            lines.append(f"**{len(STATUS_CYCLE)+i}.** `{tipo}` {e['name']} — {s}")
        embed = discord.Embed(
            title=f"🎤 Rotazione attività ({len(self.bot._status_list)} voci)",
            description="\n".join(lines) or "Nessuna attività.",
            color=0x5865F2,
        )
        embed.set_footer(text="Gli indici da 0 a N-1 sono i default, quelli successivi sono custom. Usa /status remove <indice> per rimuovere.")
        await inter.response.send_message(embed=embed, ephemeral=True)

    @status.command(name="set", description=f"{_OWN} Imposta subito uno stato (non aggiunto alla rotazione)")
    @app_commands.describe(tipo="Tipo", nome="Testo", stato="Stato")
    @app_commands.choices(tipo=[
        app_commands.Choice(name="🎮 Giocando a",    value="playing"),
        app_commands.Choice(name="📺 Guardando",      value="watching"),
        app_commands.Choice(name="🎵 Ascoltando",     value="listening"),
        app_commands.Choice(name="🏆 Gareggiando in", value="competing"),
        app_commands.Choice(name="💬 Stato custom",   value="custom"),
    ])
    @app_commands.choices(stato=[
        app_commands.Choice(name="🟢 Online",         value="online"),
        app_commands.Choice(name="🟡 Inattivo",       value="idle"),
        app_commands.Choice(name="🔴 Non disturbare", value="dnd"),
        app_commands.Choice(name="⚫ Invisibile",      value="invisible"),
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
        log.info(tag("STATUS", f"set  {b(nome)}  tipo={tipo}  stato={stato}"))
        await inter.response.send_message(
            f"✅ **{TYPE_LABEL.get(tipo, tipo)} {nome}** | {STATUS_LABEL.get(stato, stato)}\n"
            "*(Verrà sovrascritto al prossimo ciclo)*",
            ephemeral=True,
        )

    @status.command(name="interval", description=f"{_OWN} Cambia l'intervallo della rotazione status")
    @app_commands.describe(secondi="Intervallo in secondi (minimo 10)")
    @dev_check
    async def status_interval(self, inter: discord.Interaction, secondi: int):
        if secondi < 10:
            return await inter.response.send_message("❌ Minimo 10 secondi.", ephemeral=True)
        await cfg.set_status_interval(secondi)
        self.bot.cycle_status.change_interval(seconds=secondi)
        minuti = secondi / 60
        log.info(tag("STATUS", f"interval  {b(secondi)}s ({minuti:.1f} min)  — salvato"))
        await inter.response.send_message(
            f"⏱️ Intervallo aggiornato: **{secondi}s** ({minuti:.1f} min)\n*(salvato, sopravvive ai restart)*",
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
            log.warning(tag("DEV", f"say Forbidden  #{dest.name}"))
            return await inter.response.send_message(
                f"❌ Non ho i permessi per scrivere in {dest.mention}.", ephemeral=True
            )
        log.info(tag("DEV", f"say  → #{dest.name}  {hi(repr(testo[:60]))}"))
        await inter.response.send_message(f"✅ Inviato in {dest.mention}", ephemeral=True)

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
            log.warning(tag("DEV", f"announce Forbidden  #{dest.name}"))
            return await inter.response.send_message(
                f"❌ Non ho i permessi per scrivere in {dest.mention}.", ephemeral=True
            )
        log.info(tag("DEV", f"announce  → #{dest.name}  titolo={b(titolo)}"))
        await inter.response.send_message(f"✅ Annuncio inviato in {dest.mention}", ephemeral=True)

    @app_commands.command(name="cog list", description=f"{_OWN} Lista di tutti i cog caricati")
    @dev_check
    async def coglist(self, inter: discord.Interaction):
        cogs = sorted(self.bot.cogs.keys())
        righe = [f"🧩 `{c}`" for c in cogs]
        embed = discord.Embed(
            title=f"Cog caricati ({len(cogs)})",
            description="\n".join(righe),
            color=0x2f3136,
        )
        await inter.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="ai reset", description=f"{_OWN} Azzera la memoria conversazionale dell'AI")
    @app_commands.describe(canale="Canale da resettare (default: tutti)")
    @dev_check
    async def ai_reset(self, inter: discord.Interaction, canale: Optional[discord.TextChannel] = None):
        invalidate_prompt_cache()
        if canale:
            _ = clear_conversation_memory(canale.id)
            log.info(tag("AI", f"ai reset  canale=#{canale.name}  da {user(str(inter.user))}"))
            await inter.response.send_message(
                f"🧹 Memoria AI resettata per {canale.mention}.", ephemeral=True
            )
        else:
            count = clear_conversation_memory()
            log.info(tag("AI", f"ai reset  TUTTI ({count} canali)  da {user(str(inter.user))}"))
            await inter.response.send_message(
                f"🧹 Memoria AI resettata per **{count}** canali.", ephemeral=True
            )

    @app_commands.command(name="debug", description=f"{_OWN} Attiva/disattiva il livello log DEBUG a runtime")
    @app_commands.describe(stato="on = DEBUG enrichment Spotify, off = INFO")
    @app_commands.choices(stato=[
        app_commands.Choice(name="🟢 on — abilita DEBUG",  value="on"),
        app_commands.Choice(name="🔴 off — torna a INFO",  value="off"),
    ])
    @dev_check
    async def debug(self, inter: discord.Interaction, stato: str):
        level = logging.DEBUG if stato.lower() == "on" else logging.INFO
        logging.getLogger("pitonazz.spotify_enrich").setLevel(level)
        label = "DEBUG 🟢" if level == logging.DEBUG else "INFO 🔴"
        log.info(tag("DEV", f"log level → {b(label)}  (from {user(str(inter.user))})"))
        await inter.response.send_message(
            f"🔧 Livello log impostato a **{label}**\n"
            + (
                "Vedrai ora solo i dettagli DEBUG dell'enrichment Spotify."
                if level == logging.DEBUG
                else "Logger enrichment Spotify tornato a INFO."
            ),
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Dev(bot))
