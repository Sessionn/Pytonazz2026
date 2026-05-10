"""
cogs/dev.py

Comandi riservati ai developer/owner del bot.
Attuamente espone:
  !dev cache <on|off|status|stats|clear>
"""

import logging

import discord
from discord.ext import commands

from config import Config
from core.log_colors import tag, b, hi, _BGRN, _BRED, _BYEL

log = logging.getLogger("pitonazz.dev")


def _is_dev(ctx: commands.Context) -> bool:
    return ctx.author.id in Config.DEV_IDS


class DevCog(commands.Cog, name="Dev"):
    """Strumenti di sviluppo e debug (solo dev)."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        # stato runtime della cache (inizialmente segue la config)
        self._cache_runtime: bool = Config.CACHE_ENABLED

    # ── Guard ──────────────────────────────────────────────────────────────

    async def cog_check(self, ctx: commands.Context) -> bool:  # type: ignore[override]
        if not _is_dev(ctx):
            await ctx.reply("\u274c Non hai i permessi per usare questo comando.", mention_author=False)
            return False
        return True

    # ── !dev ───────────────────────────────────────────────────────────────

    @commands.group(name="dev", invoke_without_command=True)
    async def dev_group(self, ctx: commands.Context) -> None:
        """Gruppo comandi dev. Usa !dev <sottocomando>."""
        await ctx.reply(
            "Sottocomandi disponibili: `cache on/off/status/stats/clear`",
            mention_author=False,
        )

    # ── !dev cache ─────────────────────────────────────────────────────────

    @dev_group.group(name="cache", invoke_without_command=True)
    async def cache_group(self, ctx: commands.Context) -> None:
        """Gestione cache query. Usa !dev cache <on|off|status|stats|clear>."""
        await ctx.reply(
            "Sottocomandi disponibili: `on` `off` `status` `stats` `clear`",
            mention_author=False,
        )

    # ── !dev cache on ──────────────────────────────────────────────────────

    @cache_group.command(name="on")
    async def cache_on(self, ctx: commands.Context) -> None:
        """Abilita la cache a runtime."""
        missing = _check_cache_env()
        if missing:
            await ctx.reply(
                f"\u26a0\ufe0f Impossibile abilitare la cache.\n"
                f"Variabili mancanti nel `.env`: `{'`, `'.join(missing)}`",
                mention_author=False,
            )
            return

        # forza l'init del DB
        try:
            import core.cache_db as cdb
            cdb.init()
        except Exception as e:
            await ctx.reply(f"\u274c Errore inizializzazione DB: `{e}`", mention_author=False)
            return

        Config.CACHE_ENABLED = True
        self._cache_runtime = True
        log.info(tag("DEV", f"cache abilitata da {b(str(ctx.author))}"))
        await ctx.reply("\u2705 Cache **abilitata**.", mention_author=False)

    # ── !dev cache off ─────────────────────────────────────────────────────

    @cache_group.command(name="off")
    async def cache_off(self, ctx: commands.Context) -> None:
        """Disabilita la cache a runtime (non elimina i dati)."""
        Config.CACHE_ENABLED = False
        self._cache_runtime = False
        log.info(tag("DEV", f"cache disabilitata da {b(str(ctx.author))}"))
        await ctx.reply("\u23f8\ufe0f Cache **disabilitata**. I dati restano nel DB.", mention_author=False)

    # ── !dev cache status ──────────────────────────────────────────────────

    @cache_group.command(name="status")
    async def cache_status(self, ctx: commands.Context) -> None:
        """Mostra lo stato attuale della cache."""
        enabled = Config.CACHE_ENABLED
        env_ok  = not _check_cache_env()
        icon    = "\u2705" if enabled else "\u23f8\ufe0f"
        lines = [
            f"{icon} Cache runtime: **{'ON' if enabled else 'OFF'}**",
            f"DB path      : `{Config.DB_PATH}`",
            f"TTL          : {Config.CACHE_TTL_DAYS} giorni",
            f"Max entries  : {Config.CACHE_MAX_ENTRIES}",
            f"Env valido   : {'\u2705' if env_ok else '\u26a0\ufe0f variabili mancanti'}",
        ]
        await ctx.reply("\n".join(lines), mention_author=False)

    # ── !dev cache stats ───────────────────────────────────────────────────

    @cache_group.command(name="stats")
    async def cache_stats(self, ctx: commands.Context) -> None:
        """Statistiche del DB (totale voci, hit, alias)."""
        if not Config.CACHE_ENABLED:
            await ctx.reply("\u26a0\ufe0f Cache non abilitata.", mention_author=False)
            return
        try:
            import core.cache_db as cdb
            s = cdb.stats()
        except Exception as e:
            await ctx.reply(f"\u274c Errore lettura stats: `{e}`", mention_author=False)
            return
        lines = [
            f"\U0001f4ca **Cache stats**",
            f"Voci valide : {s['total']}",
            f"Hit totali  : {s['hits']}",
            f"Alias       : {s['aliases']}",
        ]
        await ctx.reply("\n".join(lines), mention_author=False)

    # ── !dev cache clear ───────────────────────────────────────────────────

    @cache_group.command(name="clear")
    async def cache_clear(self, ctx: commands.Context) -> None:
        """Svuota il DB della cache."""
        if not Config.CACHE_ENABLED:
            await ctx.reply("\u26a0\ufe0f Cache non abilitata.", mention_author=False)
            return
        try:
            import core.cache_db as cdb
            n = cdb.clear()
        except Exception as e:
            await ctx.reply(f"\u274c Errore clear: `{e}`", mention_author=False)
            return
        await ctx.reply(f"\U0001f9f9 Cache svuotata: **{n}** voci eliminate.", mention_author=False)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _check_cache_env() -> list[str]:
    """
    Controlla che le variabili minime per la cache siano presenti.
    Ritorna lista di variabili mancanti (vuota = tutto OK).
    """
    missing = []
    # DB_PATH ha un default (cache.db), quindi non e' obbligatorio.
    # CACHE_ENABLED deve essere true per procedere.
    if not Config.DB_PATH:
        missing.append("DB_PATH")
    return missing


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(DevCog(bot))
