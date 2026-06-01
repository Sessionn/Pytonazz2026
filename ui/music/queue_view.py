from __future__ import annotations

import discord


class QueueView(discord.ui.View):
    PER_PAGE = 10

    def __init__(self, player, page: int = 0):
        super().__init__(timeout=120)
        self.player = player
        self.page = page
        self._message = None
        self._build()

    def _total_pages(self) -> int:
        n = len(self.player.queue)
        return max(1, (n + self.PER_PAGE - 1) // self.PER_PAGE)

    def _build(self):
        self.clear_items()
        total = self._total_pages()

        prev = discord.ui.Button(
            emoji="◀️",
            style=discord.ButtonStyle.secondary,
            custom_id="qprev",
            disabled=(self.page == 0),
            row=0,
        )
        prev.callback = self._cb_prev
        self.add_item(prev)

        if total > 2:
            start = max(0, self.page - 1)
            end = min(total, start + 3)
            if end - start < 3:
                start = max(0, end - 3)
            for idx in range(start, end):
                btn = discord.ui.Button(
                    label=str(idx + 1),
                    style=(discord.ButtonStyle.primary if idx == self.page else discord.ButtonStyle.secondary),
                    custom_id="qpage_" + str(idx),
                    row=0,
                )
                btn.callback = self._make_page_cb(idx)
                self.add_item(btn)

        nxt = discord.ui.Button(
            emoji="▶️",
            style=discord.ButtonStyle.secondary,
            custom_id="qnext",
            disabled=(self.page >= total - 1),
            row=0,
        )
        nxt.callback = self._cb_next
        self.add_item(nxt)

        close = discord.ui.Button(
            emoji="✖️",
            label="Chiudi",
            style=discord.ButtonStyle.danger,
            custom_id="qclose",
            row=1,
        )
        close.callback = self._cb_close
        self.add_item(close)

    def _make_page_cb(self, page_num: int):
        async def cb(interaction: discord.Interaction):
            self.page = page_num
            await self._aggiorna(interaction)

        return cb

    async def _aggiorna(self, interaction: discord.Interaction):
        from ui.music.embeds import queue_embed

        self._build()
        await interaction.response.edit_message(embed=queue_embed(self.player, self.page), view=self)

    async def _cb_prev(self, interaction: discord.Interaction):
        self.page = max(0, self.page - 1)
        await self._aggiorna(interaction)

    async def _cb_next(self, interaction: discord.Interaction):
        self.page = min(self._total_pages() - 1, self.page + 1)
        await self._aggiorna(interaction)

    async def _cb_close(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            await interaction.message.delete()
        except discord.HTTPException:
            pass

    async def on_timeout(self):
        if self._message:
            try:
                await self._message.edit(view=None)
            except Exception:
                pass
