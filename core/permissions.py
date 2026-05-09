"""
core/permissions.py
-------------------
Helper di permessi condivisi tra tutti i cog.

Livelli:
  owner_check  → solo OWNER_ID (o app owner Discord).
                 Per comandi irreversibili: restart, sync, maintenance,
                 backup/restore, ecc.

  dev_check    → chiunque sia in DEV_IDS (include sempre l'owner).
                 Per comandi di gestione quotidiana: status, say,
                 commandlist, log channel, volume, ecc.

  admin_check  → utenti con permesso "Amministratore" Discord (o dev/owner).
                 Per comandi di moderazione server: purge, ruolo, ecc.
                 Corrisponde al badge 🛡️ in help.py.

  perm()       → decorator che marca la callback con il livello
                 di visibilità usato da help.py per il badge.
"""
import discord
from discord import app_commands
from config import Config
from core.cmd_perm import perm


# ── check functions ───────────────────────────────────────────────────────────

async def _is_owner(inter: discord.Interaction) -> bool:
    """True solo per OWNER_ID o per il proprietario dell'applicazione Discord."""
    if Config.OWNER_ID and inter.user.id == Config.OWNER_ID:
        return True
    return await inter.client.is_owner(inter.user)


async def _is_dev(inter: discord.Interaction) -> bool:
    """True per chiunque in DEV_IDS (che include sempre l'owner)."""
    if inter.user.id in Config.DEV_IDS:
        return True
    return await inter.client.is_owner(inter.user)


async def _is_admin(inter: discord.Interaction) -> bool:
    """True per dev/owner OPPURE per utenti con permesso Amministratore nel server."""
    # Dev e owner bypassano sempre
    if inter.user.id in Config.DEV_IDS:
        return True
    if await inter.client.is_owner(inter.user):
        return True
    # Controllo permesso Discord nativo
    if isinstance(inter.user, discord.Member):
        return inter.user.guild_permissions.administrator
    return False


# ── decorators ────────────────────────────────────────────────────────────────

owner_check = app_commands.check(_is_owner)
dev_check   = app_commands.check(_is_dev)
admin_check = app_commands.check(_is_admin)
