"""
cogs/dev_cache.py

Comando sviluppatore per gestire la Query Cache a runtime.

Utilizzo:
  !dev cache on        — abilita la cache (richiede DB configurato)
  !dev cache off       — disabilita la cache
  !dev cache status    — mostra se e' abilitata e verifica ENV
  !dev cache stats     — statistiche dettagliate sul DB
  !dev cache clear     — svuota il database
  !dev cache prune     — invalida righe scadute (TTL)

Il comando e' riservato agli owner (Config.OWNER_IDS) o ai guild owner.
"""

import discord
from discord.ext import commands

from config import Config


def _cache_available() -> bool:
    """Restituisce True se le variabili ENV minime per la cache sono presenti."""
    return bool(getattr(Config, "QUERY_CACHE_ENABLED", False)) or bool(
        getattr(Config, "QUERY_CACHE_DB_PATH", "")
    )


def _get_qc():
    """Accede al singleton QueryCache tramite il resolver (lazy init)."""
    try:
        from core.source_resolver import _get_query_cache
        return _get_query_cache()
    except Exception:
        return None


class DevCache(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    def _is_authorized(self, ctx: commands.Context) -> bool:
        owner_ids = getattr(Config, "OWNER_IDS", [])
        if ctx.author.id in owner_ids:
            return True
        if ctx.guild and ctx.guild.owner_id == ctx.author.id:
            return True
        return False

    @commands.group(name="dev", invoke_without_command=True)
    async def dev(self, ctx: commands.Context) -> None:
        await ctx.send_help(ctx.command)

    @dev.group(name="cache", invoke_without_command=True)
    async def dev_cache(self, ctx: commands.Context) -> None:
        if not self._is_authorized(ctx):
            await ctx.reply("\u26d4 Non autorizzato.", mention_author=False)
            return
        await ctx.send(
            "Sottocomandi disponibili: `on` `off` `status` `stats` `clear` `prune`"
        )

    # ------------------------------------------------------------------ on
    @dev_cache.command(name="on")
    async def cache_on(self, ctx: commands.Context) -> None:
        if not self._is_authorized(ctx):
            await ctx.reply("\u26d4 Non autorizzato.", mention_author=False)
            return

        db_path = getattr(Config, "QUERY_CACHE_DB_PATH", "")
        if not db_path:
            await ctx.reply(
                "\u274c `QUERY_CACHE_DB_PATH` non impostato nell'env. "
                "Configura la variabile e riavvia.",
                mention_author=False,
            )
            return

        qc = _get_qc()
        if qc is None:
            # Forza abilitazione runtime
            Config.QUERY_CACHE_ENABLED = True
            import core.source_resolver as _sr
            _sr._qc_instance = None  # reset singleton
            qc = _get_qc()

        if qc is not None:
            qc.enabled = True
            await ctx.reply("\u2705 Query Cache **abilitata**.", mention_author=False)
        else:
            await ctx.reply(
                "\u274c Impossibile inizializzare la cache. Controlla i log.",
                mention_author=False,
            )

    # ------------------------------------------------------------------ off
    @dev_cache.command(name="off")
    async def cache_off(self, ctx: commands.Context) -> None:
        if not self._is_authorized(ctx):
            await ctx.reply("\u26d4 Non autorizzato.", mention_author=False)
            return
        qc = _get_qc()
        if qc is not None:
            qc.enabled = False
        Config.QUERY_CACHE_ENABLED = False
        await ctx.reply("\u23f8\ufe0f Query Cache **disabilitata**.", mention_author=False)

    # ------------------------------------------------------------------ status
    @dev_cache.command(name="status")
    async def cache_status(self, ctx: commands.Context) -> None:
        if not self._is_authorized(ctx):
            await ctx.reply("\u26d4 Non autorizzato.", mention_author=False)
            return

        db_path  = getattr(Config, "QUERY_CACHE_DB_PATH", "") or "(non impostato)"
        enabled  = getattr(Config, "QUERY_CACHE_ENABLED", False)
        ttl      = getattr(Config, "QUERY_CACHE_TTL_DAYS", 30)
        max_e    = getattr(Config, "QUERY_CACHE_MAX_ENTRIES", 10_000)
        qc       = _get_qc()
        instance = "attivo" if (qc and qc.enabled) else "non attivo"

        embed = discord.Embed(title="\U0001f4be Query Cache - Status", color=0x5865F2)
        embed.add_field(name="Stato config (ENV)",  value="\u2705 abilitata" if enabled else "\u274c disabilitata", inline=True)
        embed.add_field(name="Singleton",           value=instance, inline=True)
        embed.add_field(name="DB Path",             value=f"`{db_path}`", inline=False)
        embed.add_field(name="TTL",                 value=f"{ttl} giorni", inline=True)
        embed.add_field(name="Max entries",         value=f"{max_e:,}", inline=True)
        await ctx.reply(embed=embed, mention_author=False)

    # ------------------------------------------------------------------ stats
    @dev_cache.command(name="stats")
    async def cache_stats(self, ctx: commands.Context) -> None:
        if not self._is_authorized(ctx):
            await ctx.reply("\u26d4 Non autorizzato.", mention_author=False)
            return
        qc = _get_qc()
        if qc is None or not qc.enabled:
            await ctx.reply("\u274c Cache non attiva.", mention_author=False)
            return

        s = qc.stats()
        top = s.get("top_song")
        top_str = f"{top['title']} ({top['hit_count']} hit)" if top else "N/A"

        embed = discord.Embed(title="\U0001f4be Query Cache - Stats", color=0x57F287)
        embed.add_field(name="Entries totali",  value=f"{s['total_entries']:,}",  inline=True)
        embed.add_field(name="Entries valide",  value=f"{s['valid_entries']:,}",  inline=True)
        embed.add_field(name="Alias",           value=f"{s['aliases']:,}",        inline=True)
        embed.add_field(name="Hit totali",      value=f"{s['total_hits']:,}",     inline=True)
        embed.add_field(name="DB size",         value=f"{s['db_size_kb']} KB",   inline=True)
        embed.add_field(name="Canzone top",     value=top_str,                    inline=False)
        await ctx.reply(embed=embed, mention_author=False)

    # ------------------------------------------------------------------ clear
    @dev_cache.command(name="clear")
    async def cache_clear(self, ctx: commands.Context) -> None:
        if not self._is_authorized(ctx):
            await ctx.reply("\u26d4 Non autorizzato.", mention_author=False)
            return
        qc = _get_qc()
        if qc is None or not qc.enabled:
            await ctx.reply("\u274c Cache non attiva.", mention_author=False)
            return
        deleted = qc.clear()
        await ctx.reply(f"\U0001f5d1\ufe0f Cache svuotata. **{deleted}** righe eliminate.", mention_author=False)

    # ------------------------------------------------------------------ prune
    @dev_cache.command(name="prune")
    async def cache_prune(self, ctx: commands.Context) -> None:
        if not self._is_authorized(ctx):
            await ctx.reply("\u26d4 Non autorizzato.", mention_author=False)
            return
        qc = _get_qc()
        if qc is None or not qc.enabled:
            await ctx.reply("\u274c Cache non attiva.", mention_author=False)
            return
        invalidated = qc.prune_stale()
        await ctx.reply(
            f"\u23f3 Pruning completato. **{invalidated}** righe scadute invalidate.",
            mention_author=False,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(DevCache(bot))
