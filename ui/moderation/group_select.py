from __future__ import annotations

from typing import Optional

import discord


class GroupSelectView(discord.ui.View):
    """Menu a tendina per selezionare un gruppo da cui rimuovere la pena."""

    def __init__(
        self,
        *,
        groups: dict,
        guild: discord.Guild,
    ):
        super().__init__(timeout=120)
        self.groups = groups
        self.guild = guild
        self.result: Optional[int] = None

        options = []
        for group_id, info in groups.items():
            names = []
            for uid in info["members"]:
                member = guild.get_member(uid)
                names.append(member.display_name if member else f"ID:{uid}")
            label = info.get("label") or ", ".join(names[:3]) + ("..." if len(names) > 3 else "")
            options.append(
                discord.SelectOption(
                    label=label[:100],
                    value=str(group_id),
                    description=f"{len(info['members'])} utent{'e' if len(info['members']) == 1 else 'i'}",
                )
            )

        select = discord.ui.Select(
            placeholder="Seleziona il gruppo da liberare...",
            min_values=1,
            max_values=1,
            options=options[:25],
        )
        select.callback = self._on_select
        self.add_item(select)

    async def _on_select(self, interaction: discord.Interaction):
        self.result = int(interaction.data["values"][0])
        self.stop()
        await interaction.response.defer()
