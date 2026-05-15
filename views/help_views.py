"""Views per il comando /help.

Contiene _CategoryPagesView e _CategorySelectView,
estratte da cogs/help.py per separare la logica di UI
dalla definizione del Cog.
"""
from __future__ import annotations

import discord

from core.help_utils import get_cog_meta
from embeds.help_embeds import build_home_embed


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
