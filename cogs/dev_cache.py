"""cogs/dev_cache.py

Comandi slash riservati all'owner per gestire il sistema di cache query.

Subcomandi:
  /cache on       - abilita la cache a runtime (richiede ENV corrette)
  /cache off      - disabilita la cache a runtime
  /cache status   - mostra stato attuale + config ENV
  /cache stats    - statistiche DB (entry totali, hit count, top brani)
  /cache clear    - svuota il DB (con conferma)
"""
from __future__ import annotations

import logging
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from config import Config
from core.log_colors import tag, b, user as _user
from core.permissions import owner_check

log = logging.getLogger("pitonazz.dev_cache")

_OWN = "🗄️"


def _cache_env_ok() -> tuple[bool, str]:
    """Controlla che le variabili ENV necessarie siano presenti.
    Ritorna (True, "") se ok, (False, motivo) altrimenti."""
    if not Config.QUERY_CACHE_DB_PATH:
        return False, "`QUERY_CACHE_DB_PATH` non impostato nel .env"
    return True, ""


def _get_qc():
    """Restituisce il singleton QueryCache oppure None."""
    try:
        from core.source_resolver import _get_query_cache
        return _get_query_cache()
    except Exception as e:
        log.debug(tag("DEV_CACHE", f"_get_qc: {e}"))
        return None


class DevCache(commands.Cog):
    """Comandi dev per il sistema di cache query musicali."""

    COG_ICON  = "🗄️"
    COG_LABEL = "Cache Query"
    COG_TYPE  = "dev"

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_app_command_error(
        self, inter: discord.Interaction, error: app_commands.AppCommandError
    ):
        if isinstance(error, app_commands.CheckFailure):
            if not inter.response.is_done():
                await inter.response.send_message(
                    "❌ Solo il proprietario del bot può usare questo comando.",
                    ephemeral=True,
                )
        else:
            log.error(tag("DEV_CACHE", f"command error → {error}"))

    # ── Gruppo slash ─────────────────────────────────────────────────────────────
    cache = app_commands.Group(
        name="cache",
        description=f"{_OWN} Gestione cache query musicali (owner only)",
    )

    # ── /cache on ────────────────────────────────────────────────────────────────
    @cache.command(name="on", description=f"{_OWN} Abilita la cache query a runtime")
    @owner_check
    async def cache_on(self, inter: discord.Interaction):
        await inter.response.defer(ephemeral=True)

        env_ok, env_err = _cache_env_ok()
        if not env_ok:
            return await inter.followup.send(
                f"❌ Impossibile abilitare la cache: {env_err}", ephemeral=True
            )

        if Config.QUERY_CACHE_ENABLED:
            return await inter.followup.send(
                "ℹ️ La cache è **già abilitata**.", ephemeral=True
            )

        Config.QUERY_CACHE_ENABLED = True
        qc = _get_qc()
        if qc is None:
            Config.QUERY_CACHE_ENABLED = False
            return await inter.followup.send(
                "❌ Cache abilitata nella config ma il DB non è inizializzabile.\n"
                "Controlla `QUERY_CACHE_DB_PATH` e i permessi del file.",
                ephemeral=True,
            )

        log.info(tag("DEV_CACHE", f"cache abilitata da {_user(str(inter.user))}"))
        await inter.followup.send(
            "✅ Cache **abilitata**.\n"
            f"📁 DB: `{Config.QUERY_CACHE_DB_PATH}`\n"
            f"⏱️ TTL: `{Config.QUERY_CACHE_TTL_DAYS}` giorni · "
            f"🔢 Max entries: `{Config.QUERY_CACHE_MAX_ENTRIES}`",
            ephemeral=True,
        )

    # ── /cache off ───────────────────────────────────────────────────────────────
    @cache.command(name="off", description=f"{_OWN} Disabilita la cache query a runtime")
    @owner_check
    async def cache_off(self, inter: discord.Interaction):
        if not Config.QUERY_CACHE_ENABLED:
            return await inter.response.send_message(
                "ℹ️ La cache è **già disabilitata**.", ephemeral=True
            )
        Config.QUERY_CACHE_ENABLED = False
        log.info(tag("DEV_CACHE", f"cache disabilitata da {_user(str(inter.user))}"))
        await inter.response.send_message(
            "⏸️ Cache **disabilitata**. Le query torneranno al fetch normale.",
            ephemeral=True,
        )

    # ── /cache status ─────────────────────────────────────────────────────────────
    @cache.command(name="status", description=f"{_OWN} Mostra stato cache + config ENV")
    @owner_check
    async def cache_status(self, inter: discord.Interaction):
        enabled = Config.QUERY_CACHE_ENABLED
        env_ok, env_err = _cache_env_ok()
        qc = _get_qc() if enabled else None
        db_live = qc is not None

        status_icon = "🟢" if (enabled and db_live) else ("🟡" if enabled else "🔴")
        status_text = (
            "Attiva e connessa"
            if (enabled and db_live)
            else ("Abilitata ma DB non raggiungibile" if enabled else "Disabilitata")
        )

        lines = [
            f"**{status_icon} Stato cache:** {status_text}",
            "",
            "**Config ENV**",
            f"• `QUERY_CACHE_ENABLED` = `{enabled}`",
            f"• `QUERY_CACHE_DB_PATH` = `{Config.QUERY_CACHE_DB_PATH or '—'}`",
            f"• `QUERY_CACHE_TTL_DAYS` = `{Config.QUERY_CACHE_TTL_DAYS}`",
            f"• `QUERY_CACHE_MAX_ENTRIES` = `{Config.QUERY_CACHE_MAX_ENTRIES}`",
        ]
        if not env_ok:
            lines.append(f"\n⚠️ {env_err}")

        await inter.response.send_message("\n".join(lines), ephemeral=True)

    # ── /cache stats ──────────────────────────────────────────────────────────────
    @cache.command(
        name="stats",
        description=f"{_OWN} Statistiche DB: entry totali, hit count, top brani",
    )
    @owner_check
    async def cache_stats(self, inter: discord.Interaction):
        await inter.response.defer(ephemeral=True)

        qc = _get_qc()
        if qc is None:
            return await inter.followup.send(
                "❌ Cache non disponibile (disabilitata o DB non inizializzato).",
                ephemeral=True,
            )

        try:
            stats = qc.stats()
        except Exception as e:
            return await inter.followup.send(
                f"❌ Errore lettura stats: `{e}`", ephemeral=True
            )

        total      = stats.get("total_entries", 0)
        total_hits = stats.get("total_hits", 0)
        aliases    = stats.get("total_aliases", 0)
        top: list[dict] = stats.get("top_tracks", [])

        lines = [
            f"**🗄️ Cache Stats**",
            f"• Entry totali: **{total}**",
            f"• Alias totali: **{aliases}**",
            f"• Hit totali: **{total_hits}**",
        ]

        if top:
            lines.append("")
            lines.append("**🔝 Top 10 brani più richiesti**")
            for i, row in enumerate(top[:10], 1):
                title  = (row.get("title") or "—")[:50]
                artist = (row.get("artist") or "")[:30]
                hits   = row.get("hit_count", 0)
                label  = f"{title} — {artist}" if artist else title
                lines.append(f"`{i:2d}.` {label}  ·  **{hits}** hit")

        await inter.followup.send("\n".join(lines), ephemeral=True)

    # ── /cache clear ──────────────────────────────────────────────────────────────
    @cache.command(
        name="clear",
        description=f"{_OWN} Svuota il DB della cache (operazione irreversibile)",
    )
    @owner_check
    async def cache_clear(self, inter: discord.Interaction):
        """Mostra un bottone di conferma prima di procedere."""
        view = _ConfirmClearView(inter.user.id)
        await inter.response.send_message(
            "⚠️ **Sei sicuro?** Questa operazione elimina **tutte** le entry in cache.\n"
            "Non è reversibile.",
            view=view,
            ephemeral=True,
        )


# ── Confirm view ──────────────────────────────────────────────────────────────────────
class _ConfirmClearView(discord.ui.View):
    def __init__(self, owner_id: int):
        super().__init__(timeout=30)
        self.owner_id = owner_id

    async def interaction_check(self, inter: discord.Interaction) -> bool:
        if inter.user.id != self.owner_id:
            await inter.response.send_message(
                "❌ Solo chi ha lanciato il comando può confermare.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(
        label="Sì, svuota",
        style=discord.ButtonStyle.danger,
        emoji="🗑️",
    )
    async def confirm(self, inter: discord.Interaction, button: discord.ui.Button):
        qc = _get_qc()
        if qc is None:
            await inter.response.edit_message(
                content="❌ Cache non disponibile.", view=None
            )
            return
        try:
            deleted = qc.clear()
        except Exception as e:
            await inter.response.edit_message(
                content=f"❌ Errore durante la pulizia: `{e}`", view=None
            )
            return
        log.info(tag("DEV_CACHE", f"clear: {deleted} entry eliminate da {_user(str(inter.user))}"))
        await inter.response.edit_message(
            content=f"✅ Cache svuotata: **{deleted}** entry eliminate.",
            view=None,
        )
        self.stop()

    @discord.ui.button(
        label="Annulla",
        style=discord.ButtonStyle.secondary,
        emoji="✖️",
    )
    async def cancel(self, inter: discord.Interaction, button: discord.ui.Button):
        await inter.response.edit_message(
            content="↩️ Operazione annullata.", view=None
        )
        self.stop()


async def setup(bot: commands.Bot):
    await bot.add_cog(DevCache(bot))
