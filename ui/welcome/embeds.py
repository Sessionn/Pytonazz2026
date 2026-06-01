from __future__ import annotations

import discord


def ok_embed(message: str) -> discord.Embed:
    return discord.Embed(description=message, color=0x57F287)


def err_embed(message: str) -> discord.Embed:
    return discord.Embed(description=f"❌ {message}", color=0xED4245)


def info_embed(message: str) -> discord.Embed:
    return discord.Embed(description=message, color=0x5865F2)


def status_embed(enabled: bool, label: str) -> discord.Embed:
    state = "ON" if enabled else "OFF"
    icon = "🟢" if enabled else "🔴"
    return ok_embed(f"{label}: **{icon} {state}**")
