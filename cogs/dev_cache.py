"""
dev_cache.py — Comandi dev per gestire il song cache DB.
Accessibili solo all'owner. Comandi slash: /cache-status, /cache-stats,
/cache-prune, /cache-invalidate, /cache-clear, /cache-export.
"""
import logging
import tempfile
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from core.log_colors import tag, b, user
from core.permissions import owner_check
import core.cache_db as cache_db
import core.cache_report as cache_report

log = logging.getLogger("pitonazz.dev_cache")

_C_OK     = 0x2ECC71
_C_WARN   = 0xF39C12
_C_ERR    = 0xE74C3C
_C_INFO   = 0x3498DB
_C_PURPLE = 0x9B59B6
_OWN = "\U0001f5c4\ufe0f"


class DevCache(commands.Cog):
    """Comandi owner per il song cache database."""

    COG_ICON  = "\U0001f5c4\ufe0f"
    COG_LABEL = "Cache DB"
    COG_TYPE  = "dev"

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_app_command_error(
        self, inter: discord.Interaction, error: app_commands.AppCommandError
    ):
        if isinstance(error, app_commands.CheckFailure):
            if not inter.response.is_done():
                await inter.response.send_message(
                    "\u274c Solo il proprietario pu\u00f2 usare questo comando.", ephemeral=True
                )
        else:
            log.error(tag("DEV_CACHE", f"command error \u2192 {error}"))

    @app_commands.command(
        name="cache-status",
        description=f"{_OWN} Mostra lo stato del song cache DB",
    )
    @owner_check
    async def cache_status(self, inter: discord.Interaction):
        enabled = cache_db.is_enabled()
        color   = _C_OK if enabled else _C_WARN
        icon    = "\u2705" if enabled else "\u26a0\ufe0f"
        state   = "**Abilitato**" if enabled else "**Disabilitato**"
        embed = discord.Embed(
            title=f"{_OWN} Song Cache \u2014 Stato",
            color=color,
            description=f"{icon} Cache: {state}",
        )
        if not enabled:
            embed.add_field(
                name="Come abilitare",
                value="Aggiungi `CACHE_ENABLED=true` nel `.env` e riavvia il bot.",
                inline=False,
            )
        await inter.response.send_message(embed=embed, ephemeral=True)
        log.info(tag("DEV_CACHE", f"status  by={user(str(inter.user))}"))

    @app_commands.command(
        name="cache-stats",
        description=f"{_OWN} Statistiche del song cache DB",
    )
    @owner_check
    async def cache_stats(self, inter: discord.Interaction):
        s = cache_db.stats()
        if not s.get("enabled"):
            await inter.response.send_message(
                embed=discord.Embed(
                    title=f"{_OWN} Cache Stats",
                    description="\u26a0\ufe0f Cache disabilitata.",
                    color=_C_WARN,
                ),
                ephemeral=True,
            )
            return
        if "error" in s:
            await inter.response.send_message(
                embed=discord.Embed(
                    title="\u274c Errore lettura stats",
                    description=f"`{s['error']}`",
                    color=_C_ERR,
                ),
                ephemeral=True,
            )
            return
        top = s.get("top_query")
        top_str = (
            f"`{top['query_raw']}` \u2014 {top['hit_count']} hits"
            if top else "N/D"
        )
        embed = discord.Embed(
            title=f"{_OWN} Song Cache \u2014 Statistiche",
            color=_C_PURPLE,
        )
        embed.add_field(name="\U0001f4e6 Entry totali",  value=str(s["total"]),      inline=True)
        embed.add_field(name="\u2705 Entry valide",       value=str(s["valid"]),      inline=True)
        embed.add_field(name="\U0001f517 Alias",          value=str(s["aliases"]),    inline=True)
        embed.add_field(name="\U0001f3af Hits totali",    value=str(s["hits_total"]), inline=True)
        embed.add_field(name="\U0001f4be Dimensione DB",  value=f"{s['size_kb']} KB", inline=True)
        embed.add_field(name="\U0001f3c6 Query top",      value=top_str,              inline=False)
        embed.set_footer(text=f"Path: {s['db_path']}")
        await inter.response.send_message(embed=embed, ephemeral=True)
        log.info(tag("DEV_CACHE", f"stats  by={user(str(inter.user))}"))

    @app_commands.command(
        name="cache-prune",
        description=f"{_OWN} Rimuovi entry scadute o in eccesso dal DB",
    )
    @app_commands.describe(
        max_entries="Numero massimo di entry da mantenere (default 500)",
        ttl_days="Giorni prima che una entry scada (default 30)",
    )
    @owner_check
    async def cache_prune(
        self,
        inter: discord.Interaction,
        max_entries: app_commands.Range[int, 10, 10000] = 500,
        ttl_days:    app_commands.Range[int, 1,  365]   = 30,
    ):
        removed = cache_db.prune_lru(max_entries=max_entries, ttl_days=ttl_days)
        color = _C_WARN if removed else _C_OK
        desc  = (
            f"\U0001f5d1\ufe0f Rimosse **{removed}** entry."
            if removed
            else "\u2705 Nessuna entry da rimuovere."
        )
        embed = discord.Embed(
            title=f"{_OWN} Cache \u2014 Prune",
            description=desc,
            color=color,
        )
        embed.set_footer(text=f"max_entries={max_entries}  ttl={ttl_days}d")
        await inter.response.send_message(embed=embed, ephemeral=True)
        log.info(tag("DEV_CACHE",
            f"prune  removed={b(str(removed))}  "
            f"max={max_entries}  ttl={ttl_days}d  "
            f"by={user(str(inter.user))}"
        ))

    @app_commands.command(
        name="cache-invalidate",
        description=f"{_OWN} Invalida una singola entry della cache per query",
    )
    @app_commands.describe(query="La query da invalidare (es: 'Time in a Bottle')")
    @owner_check
    async def cache_invalidate(self, inter: discord.Interaction, query: str):
        ok = cache_db.invalidate(query)
        if ok:
            embed = discord.Embed(
                title=f"{_OWN} Cache \u2014 Invalidata",
                description=f"\u2705 Entry per `{query}` segnata come non valida.",
                color=_C_OK,
            )
        else:
            embed = discord.Embed(
                title=f"{_OWN} Cache \u2014 Non trovata",
                description=f"\u26a0\ufe0f Nessuna entry trovata per `{query}`.",
                color=_C_WARN,
            )
        await inter.response.send_message(embed=embed, ephemeral=True)
        log.info(tag("DEV_CACHE",
            f"invalidate  {b(query)}  ok={ok}  by={user(str(inter.user))}"
        ))

    @app_commands.command(
        name="cache-clear",
        description=f"{_OWN} Svuota COMPLETAMENTE il song cache DB",
    )
    @app_commands.describe(confirm="Scrivi 'CONFERMA' per procedere")
    @owner_check
    async def cache_clear(self, inter: discord.Interaction, confirm: str):
        if confirm.strip().upper() != "CONFERMA":
            await inter.response.send_message(
                embed=discord.Embed(
                    title="\u274c Operazione annullata",
                    description="Scrivi esattamente `CONFERMA` per svuotare il DB.",
                    color=_C_ERR,
                ),
                ephemeral=True,
            )
            return
        removed = cache_db.clear_all()
        embed = discord.Embed(
            title=f"{_OWN} Cache \u2014 Svuotata",
            description=f"\U0001f5d1\ufe0f Eliminate **{removed}** entry dal DB.",
            color=_C_ERR,
        )
        await inter.response.send_message(embed=embed, ephemeral=True)
        log.warning(tag("DEV_CACHE",
            f"CLEAR ALL  removed={b(str(removed))}  by={user(str(inter.user))}"
        ))

    @app_commands.command(
        name="cache-export",
        description=f"{_OWN} Esporta il DB come file HTML e lo allega qui",
    )
    @owner_check
    async def cache_export(self, inter: discord.Interaction):
        if not cache_db.is_enabled():
            await inter.response.send_message(
                embed=discord.Embed(
                    title="\u26a0\ufe0f Cache disabilitata",
                    description="Abilita la cache nel `.env` per usare questo comando.",
                    color=_C_WARN,
                ),
                ephemeral=True,
            )
            return

        await inter.response.defer(ephemeral=True)

        try:
            tmp = Path(tempfile.mktemp(suffix="_cache_report.html"))
            cache_report.export_to_file(tmp)
            size_kb = round(tmp.stat().st_size / 1024, 1)

            embed = discord.Embed(
                title=f"{_OWN} Cache \u2014 Export",
                description="\U0001f4ce Report allegato. Aprilo nel browser per vedere le tabelle.",
                color=_C_INFO,
            )
            embed.set_footer(text=f"Dimensione: {size_kb} KB")

            await inter.followup.send(
                embed=embed,
                file=discord.File(str(tmp), filename="cache_report.html"),
                ephemeral=True,
            )
            log.info(tag("DEV_CACHE",
                f"export  {b(str(size_kb) + ' KB')}  by={user(str(inter.user))}"
            ))
        except Exception as e:
            log.error(tag("DEV_CACHE", f"export ERROR  {e}"))
            await inter.followup.send(
                embed=discord.Embed(
                    title="\u274c Errore export",
                    description=f"`{e}`",
                    color=_C_ERR,
                ),
                ephemeral=True,
            )
        finally:
            if tmp.exists():
                tmp.unlink(missing_ok=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(DevCache(bot))
