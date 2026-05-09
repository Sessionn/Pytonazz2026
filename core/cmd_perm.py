"""
cmd_perm  —  flag di visibilità per-comando nell'help.

Uso nel cog:
    from core.cmd_perm import perm

    @bday.command(name="adminset", description="...")
    @perm("admin")            # <-- questo è tutto
    async def bday_adminset(self, inter, ...):
        ...

Valori accettati:
    "public"  — visibile a tutti (default se il flag manca)
    "admin"   — visibile solo a chi ha Gestisci server (o dev)
    "dev"     — visibile solo al dev del bot

Come funziona:
    `perm()` scrive l'attributo `_cmd_perm` direttamente sulla funzione
    wrapped del comando. `help.py` lo legge con `_cmd_perm(cmd)` che
    fa fallback a COG_TYPE se l'attributo non è presente.
    Nessuna modifica a discord.py — puro attributo extra sulla funzione.
"""
from __future__ import annotations
from typing import Literal

# Gerarchia visibilità help: owner > dev > admin > public
PermLevel = Literal["public", "admin", "dev", "owner"]


def perm(level: PermLevel):
    """
    Decorator da applicare DOPO @<group>.command() / @app_commands.command().

    Esempio corretto (l'ordine conta — perm viene applicato per primo,
    prima ancora che discord.py wrappa la funzione):

        @bday.command(name="adminset", description="...")
        @perm("admin")
        async def bday_adminset(self, inter, ...):
            ...

    Il decorator non altera il comportamento del comando: aggiunge
    solo l'attributo `_cmd_perm` sulla callback della funzione.
    """
    def decorator(func_or_cmd):
        # Funziona sia se applicato sulla funzione grezza
        # sia se per sbaglio applicato dopo il wrap di discord.py
        target = getattr(func_or_cmd, "callback", func_or_cmd)
        target._cmd_perm = level
        return func_or_cmd
    return decorator
