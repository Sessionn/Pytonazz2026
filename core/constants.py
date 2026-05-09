"""
Costanti condivise tra main.py, dev.py e altri moduli.
"""
import discord

TYPE_MAP: dict[str, discord.ActivityType] = {
    "playing":   discord.ActivityType.playing,
    "watching":  discord.ActivityType.watching,
    "listening": discord.ActivityType.listening,
    "competing": discord.ActivityType.competing,
    "custom":    discord.ActivityType.custom,
}

STAT_MAP: dict[str, discord.Status] = {
    "online":    discord.Status.online,
    "idle":      discord.Status.idle,
    "dnd":       discord.Status.dnd,
    "invisible": discord.Status.invisible,
}

TYPE_LABEL: dict[str, str] = {
    "playing":   "🎮 Giocando a",
    "watching":  "📺 Guardando",
    "listening": "🎵 Ascoltando",
    "competing": "🏆 Gareggiando in",
    "custom":    "💬 Custom",
}

STATUS_LABEL: dict[str, str] = {
    "online":    "🟢 Online",
    "idle":      "🟡 Inattivo",
    "dnd":       "🔴 Non disturbare",
    "invisible": "⚫ Invisibile",
}

# Comandi che non possono essere disabilitati dall'owner.
# Fonte unica: importata sia da main.py che da cogs/dev.py
UNDISABLEABLE: frozenset[str] = frozenset({
    "disablecommand", "enablecommand", "commandlist", "sync", "restart",
    "maintenance", "coglist", "help", "help-dev",
})


def command_slug(name: str) -> str:
    """Normalizza un nome comando (anche qualificato) in formato underscore."""
    return "_".join(str(name).strip().lower().split())
