"""Cog /help — solo Cog, Views e autocomplete.

Tutta la logica di raccolta comandi è in core/help_utils.py.
Tutti gli embed sono costruiti da embeds/help_embeds.py.
"""
from __future__ import annotations

from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from core.help_utils import (
    is_dev, is_admin,
    all_commands_flat, build_all_pages,
    get_cog_meta, cmd_full_name, cmd_perm,
    PERM_BADGES, DESC_PREFIX_MARKERS,
)
from embeds.help_embeds import (
    build_command_embed,
    build_home_embed,
)
from core.permissions import dev_check, perm


# ── Views ────────────────────────────────────────────────────────────────

class _CategoryPagesView(discord.ui.View):
    def __init__(self, pages, author_id, category_label, all_pages, include_dev, bot):
        super().__init__(timeout=120)
        self.pages          = pages
        self.author_id      = author_id
        self.category_label = category_label
        self.all_pages      = all_pages
        self.include_dev    = include_dev
        self.bot            = bot
        self.current        = 0
        self._stamp_footers()
        self._update_buttons()

    def _stamp_footers(self):
        total = len(self.pages)
        for i, p in enumerate(self.pages):
            p.set_footer(text=f"{self.category_label} · Pagina {i+1}/{total} · ◄ ► per navigare")

    def _update_buttons(self):
        self.prev_btn.disabled = self.current == 0
        self.next_btn.disabled = self.current == len(self.pages) - 1

    async def _go(self, inter: discord.Interaction, page: int):
        if inter.user.id != self.author_id:
            return await inter.response.send_message("Non è il tuo help.", ephemeral=True)
        self.current = page
        self._update_buttons()
        await inter.response.edit_message(embed=self.pages[self.current], view=self)

    @discord.ui.button(emoji="◀️", style=discord.ButtonStyle.primary)
    async def prev_btn(self, inter, _):
        await self._go(inter, self.current - 1)

    @discord.ui.button(emoji="▶️", style=discord.ButtonStyle.primary)
    async def next_btn(self, inter, _):
        await self._go(inter, self.current + 1)

    @discord.ui.button(label="🏠 Home", style=discord.ButtonStyle.secondary)
    async def home_btn(self, inter: discord.Interaction, _):
        if inter.user.id != self.author_id:
            return await inter.response.send_message("Non è il tuo help.", ephemeral=True)
        home = build_home_embed(self.all_pages, self.include_dev, self.bot, get_cog_meta)
        view = _CategorySelectView(self.all_pages, self.author_id, self.include_dev, self.bot)
        await inter.response.edit_message(embed=home, view=view)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


class _CategorySelectView(discord.ui.View):
    def __init__(self, all_pages, author_id, include_dev, bot):
        super().__init__(timeout=120)
        self.all_pages   = all_pages
        self.author_id   = author_id
        self.include_dev = include_dev
        self.bot         = bot
        self._build_select()

    def _build_select(self):
        options = []
        for key, pages in self.all_pages.items():
            icon, label = get_cog_meta(self.bot, key)
            count = sum(len(p.fields) for p in pages)
            options.append(discord.SelectOption(
                label=label,
                value=key,
                emoji=icon,
                description=f"{count} comandi",
            ))
        if not options:
            return
        select = discord.ui.Select(
            placeholder="💬 Scegli una categoria...",
            options=options[:25],
        )
        select.callback = self._on_select
        self.add_item(select)

    async def _on_select(self, inter: discord.Interaction):
        if inter.user.id != self.author_id:
            return await inter.response.send_message("Non è il tuo help.", ephemeral=True)
        values = (inter.data or {}).get("values", [])
        if not values:
            return await inter.response.send_message("Selezione non valida.", ephemeral=True)
        key   = values[0]
        pages = self.all_pages.get(key, [])
        if not pages:
            return await inter.response.send_message("Categoria vuota.", ephemeral=True)
        _, label = get_cog_meta(self.bot, key)
        view = _CategoryPagesView(pages, self.author_id, label, self.all_pages, self.include_dev, self.bot)
        await inter.response.edit_message(embed=pages[0], view=view)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


# ── Cog ──────────────────────────────────────────────────────────────────

class Help(commands.Cog):
    COG_ICON  = "📚"
    COG_LABEL = "Aiuto"
    COG_TYPE  = "public"

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _autocomplete_comando(
        self,
        inter: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        _dev   = is_dev(inter.user.id)
        _admin = is_admin(inter)
        choices = []
        current_lower = current.lower().lstrip("/")
        for cmd in sorted(all_commands_flat(self.bot, _dev, _admin), key=lambda c: cmd_full_name(c)):
            name = cmd_full_name(cmd)
            if current_lower in name.lower():
                choices.append(app_commands.Choice(name=f"/{name}", value=name))
            if len(choices) >= 25:
                break
        return choices

    @app_commands.command(name="help", description="Mostra i comandi disponibili")
    @app_commands.describe(comando="Nome del comando specifico (opzionale)")
    @app_commands.autocomplete(comando=_autocomplete_comando)
    async def help_cmd(self, inter: discord.Interaction, comando: Optional[str] = None):
        _dev   = is_dev(inter.user.id)
        _admin = is_admin(inter)

        if comando:
            match = next(
                (c for c in all_commands_flat(self.bot, _dev, _admin)
                 if cmd_full_name(c).lower() == comando.lower().lstrip("/")),
                None,
            )
            if not match:
                return await inter.response.send_message(
                    embed=discord.Embed(
                        description=f"❌ Comando `{comando}` non trovato.",
                        color=0xED4245,
                    ),
                    ephemeral=True,
                )
            return await inter.response.send_message(
                embed=build_command_embed(match, self.bot, get_cog_meta, cmd_perm, PERM_BADGES, DESC_PREFIX_MARKERS),
                ephemeral=True,
            )

        all_pages = build_all_pages(self.bot, include_dev=False, _is_dev=_dev, _is_admin=_admin)
        home      = build_home_embed(all_pages, include_dev=False, bot=self.bot, cog_meta_fn=get_cog_meta)
        view      = _CategorySelectView(all_pages, inter.user.id, include_dev=False, bot=self.bot)
        await inter.response.send_message(embed=home, view=view, ephemeral=True)

    @app_commands.command(name="devhelp", description="🔧 Comandi tecnici del bot")
    @dev_check
    async def help_dev_cmd(self, inter: discord.Interaction):
        all_pages = build_all_pages(self.bot, include_dev=True, _is_dev=True, _is_admin=True)
        home      = build_home_embed(all_pages, include_dev=True, bot=self.bot, cog_meta_fn=get_cog_meta)
        view      = _CategorySelectView(all_pages, inter.user.id, include_dev=True, bot=self.bot)
        await inter.response.send_message(embed=home, view=view, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Help(bot))
