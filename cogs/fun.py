import asyncio
import logging
import random
from datetime import timedelta
from typing import Optional
import io

import discord
from discord import app_commands
from discord.ext import commands

from core.log_colors import tag, b, user
from core.quote_card import build_quote_card

log = logging.getLogger("pitonazz.fun")

_POLL_EMOJIS   = ["1\ufe0f\u20e3", "2\ufe0f\u20e3", "3\ufe0f\u20e3", "4\ufe0f\u20e3"]
_MAX_QUOTE_LEN = 280

# Camere roulette: numeri cerchiati aperti (estratta) e filled (chiuse)
_CHAMBER_OPEN   = ["\u2460", "\u2461", "\u2462", "\u2463", "\u2464", "\u2465"]
_CHAMBER_CLOSED = ["\u278a", "\u278b", "\u278c", "\u278d", "\u278e", "\u278f"]


def _cylinder_display(chamber: int, dead: bool) -> str:
    result = []
    for i in range(6):
        if i + 1 == chamber:
            dot = "\U0001f534" if dead else "\U0001f7e2"
            result.append(f"{dot}{_CHAMBER_OPEN[i]}")
        else:
            result.append(_CHAMBER_CLOSED[i])
    return "  ".join(result)


_8BALL_SI = [
    ("S\u00ec.",                                                                    0x2ecc71),
    ("Ovviamente s\u00ec. Perch\u00e9 chiedi?",                                    0x2ecc71),
    ("S\u00ec, ma probabilmente te ne pentirai.",                                  0x27ae60),
    ("Gi\u00e0 fatto, gi\u00e0 deciso: s\u00ec.",                                  0x2ecc71),
    ("Le stelle dicono s\u00ec. Le stelle sono idiote, ma stavolta ci prendono.", 0x27ae60),
    ("S\u00ec. Non ringraziare.",                                                  0x2ecc71),
    ("Tutto porta a s\u00ec. Anche tu, se ci pensi.",                             0x27ae60),
]
_8BALL_NO = [
    ("No.",                                                          0xe74c3c),
    ("Assolutamente no.",                                            0xe74c3c),
    ("No. E smettila di sperare.",                                   0xc0392b),
    ("L'universo ha riso alla tua domanda. La risposta \u00e8 no.",  0xe74c3c),
    ("No. E francamente meno male.",                                 0xc0392b),
    ("Mai. Neanche in un'altra vita.",                               0xe74c3c),
    ("No. Il confine \u00e8 chiaro.",                                 0xc0392b),
]
_8BALL_VAGO = [
    ("Non lo so e onestamente non mi importa.",                            0x95a5a6),
    ("Forse. Ma probabile che non cambi nulla.",                           0x7f8c8d),
    ("Dipende da quanti errori sei disposto a fare.",                      0x95a5a6),
    ("La risposta esiste. Non \u00e8 per te.",                             0x7f8c8d),
    ("Chiedi a qualcuno che ci tiene.",                                    0x95a5a6),
    ("Nebbia totale. Buona fortuna.",                                      0x7f8c8d),
    ("Possibile. Come quasi tutto. Non \u00e8 utile come risposta, lo so.", 0x95a5a6),
]
_8BALL_LABELS = {
    "si":   ("POSITIVO", "\U0001f7e2", _8BALL_SI),
    "no":   ("NEGATIVO", "\U0001f534", _8BALL_NO),
    "vago": ("INCERTO",  "\u26aa",     _8BALL_VAGO),
}
_8BALL_OUTCOMES = ["si"] * 7 + ["no"] * 7 + ["vago"] * 7


# Context menu definito a livello di modulo (non dentro la classe)
@app_commands.context_menu(name="Citazione")
async def citazione_context(inter: discord.Interaction, message: discord.Message):
    testo = message.content
    if not testo:
        return await inter.response.send_message(
            "\u274c Il messaggio non contiene testo da citare.", ephemeral=True
        )
    if len(testo) > _MAX_QUOTE_LEN:
        testo = testo[:_MAX_QUOTE_LEN] + "\u2026"
    utente = message.author
    avatar_url = utente.display_avatar.url if hasattr(utente, "display_avatar") else None
    nome = utente.display_name if hasattr(utente, "display_name") else str(utent