"""
cogs/dev_cache.py

Comando sviluppatore per gestire la Query Cache a runtime.

Utilizzo (prefix !dev cache <sub>):
  on        — abilita la cache a runtime
  off       — disabilita la cache a runtime
  status    — stato attuale + variabili ENV
  stats     — statistiche dettagliate sul DB
  clear     — svuota il database (con conferma)
  prune     — invalida righe scadute (TTL)
  inspect   — mostra come viene normalizzata una query e se ha un hit in DB

Riservato ai DEV_IDS configurati in Config.
"""

import discord
from discord.ext import commands

from config import Config


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
        dev_ids = getattr(Config, "DEV_IDS", []) or []
        return ctx.author.id in dev_ids

    # ------------------------------------------------------------------ group
    @commands.group(name="dev", invoke_without_command=True)
    async def dev(self, ctx: commands.Context) -> None:
        await ctx.send_help(ctx.command)

    @dev.group(name="cache", invoke_without_command=True)
    async def dev_cache(self, ctx: commands.Context) -> None:
        if not self._is_authorized(ctx):
            await ctx.reply("\u26d4 Non autorizzato.", mention_author=False)
            return
        await ctx.reply(
            "**Sottocomandi disponibili:**\n"
            "`on` `off` `status` `stats` `clear` `prune` `inspect <query>`",
            mention_author=False,
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
                "\u274c `QUERY_CACHE_DB_PATH` non impostato nell'env.",
                mention_author=False,
            )
            return

        qc = _get_qc()
        if qc is None:
            Config.QUERY_CACHE_ENABLED = True
            import core.source_resolver as _sr
            _sr._qc_instance = None
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

        db_path = getattr(Config, "QUERY_CACHE_DB_PATH", "") or "(non impostato)"
        enabled = getattr(Config, "QUERY_CACHE_ENABLED", False)
        ttl     = getattr(Config, "QUERY_CACHE_TTL_DAYS", 30)
        max_e   = getattr(Config, "QUERY_CACHE_MAX_ENTRIES", 10_000)
        qc      = _get_qc()
        running = qc is not None and qc.enabled

        color = 0x57F287 if running else 0xED4245
        embed = discord.Embed(title="\U0001f4be Query Cache — Status", color=color)
        embed.add_field(
            name="Config (ENV)",
            value="\u2705 abilitata" if enabled else "\u274c disabilitata",
            inline=True,
        )
        embed.add_field(
            name="Runtime",
            value="\U0001f7e2 attiva" if running else "\U0001f534 non attiva",
            inline=True,
        )
        embed.add_field(name="DB Path",     value=f"`{db_path}`",    inline=False)
        embed.add_field(name="TTL",         value=f"{ttl} giorni",  inline=True)
        embed.add_field(name="Max entries", value=f"{max_e:,}",      inline=True)
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

        s   = qc.stats()
        top = s.get("top_song")
        top_str = f"{top['title']} ({top['hit_count']} hit)" if top else "N/A"

        embed = discord.Embed(title="\U0001f4be Query Cache — Stats", color=0x5865F2)
        embed.add_field(name="Entries totali", value=f"{s['total_entries']:,}", inline=True)
        embed.add_field(name="Entries valide", value=f"{s['valid_entries']:,}", inline=True)
        embed.add_field(name="Alias",          value=f"{s['aliases']:,}",       inline=True)
        embed.add_field(name="Hit totali",     value=f"{s['total_hits']:,}",    inline=True)
        embed.add_field(name="DB size",        value=f"{s['db_size_kb']} KB",  inline=True)
        embed.add_field(name="TTL",            value=f"{s['ttl_days']}d",       inline=True)
        embed.add_field(name="Canzone top",    value=top_str,                   inline=False)
        embed.set_footer(text=s["db_path"])
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
        await ctx.reply(
            f"\U0001f5d1\ufe0f Cache svuotata — **{deleted}** righe eliminate.",
            mention_author=False,
        )

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
            f"\u23f3 Pruning completato — **{invalidated}** righe scadute invalidate.",
            mention_author=False,
        )

    # ------------------------------------------------------------------ inspect
    @dev_cache.command(name="inspect")
    async def cache_inspect(self, ctx: commands.Context, *, query: str = "") -> None:
        """Mostra come viene normalizzata una query e se esiste un hit in DB."""
        if not self._is_authorized(ctx):
            await ctx.reply("\u26d4 Non autorizzato.", mention_author=False)
            return
        if not query:
            await ctx.reply("Uso: `!dev cache inspect <query>`", mention_author=False)
            return
        qc = _get_qc()
        if qc is None or not qc.enabled:
            await ctx.reply("\u274c Cache non attiva.", mention_author=False)
            return

        info = qc.inspect(query)
        found = info["found"]
        row   = info.get("row") or {}

        color = 0x57F287 if found else 0xFEE75C
        embed = discord.Embed(
            title=f"\U0001f50e Cache Inspect",
            color=color,
        )
        embed.add_field(name="Query raw",      value=f"`{info['query_raw']}`",     inline=False)
        embed.add_field(name="Canonical key",  value=f"`{info['canonical_key']}`", inline=True)
        embed.add_field(name="Variant tag",    value=f"`{info['variant_tag'] or '(nessuno)'}`", inline=True)
        embed.add_field(name="Hit in DB",      value="\u2705 Si" if found else "\u274c No", inline=True)

        if found:
            duration = row.get("duration", 0)
            mm, ss = divmod(duration, 60)
            embed.add_field(name="Titolo",     value=row.get("title", "N/A"),   inline=True)
            embed.add_field(name="Artista",    value=row.get("artist", "N/A"),  inline=True)
            embed.add_field(name="Durata",     value=f"{mm}:{ss:02d}",          inline=True)
            embed.add_field(name="Source",     value=row.get("source", "N/A"),  inline=True)
            embed.add_field(name="Hit count",  value=str(row.get("hit_count", 0)), inline=True)
            embed.add_field(name="Last used",  value=row.get("last_used", "N/A"), inline=True)
            embed.add_field(
                name="URL",
                value=f"[link]({row.get('webpage_url', '')})",
                inline=False,
            )

        await ctx.reply(embed=embed, mention_author=False)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(DevCache(bot))
