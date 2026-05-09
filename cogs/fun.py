import asyncio
import io
import logging
import random
from datetime import timedelta
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from core.log_colors import tag, b, user
from core.quote_card import build_quote_card

log = logging.getLogger("pitonazz.fun")

_POLL_EMOJIS   = ["1\ufe0f\u20e3", "2\ufe0f\u20e3", "3\ufe0f\u20e3", "4\ufe0f\u20e3"]
_MAX_QUOTE_LEN = 280

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


# Context menu definito a livello di modulo
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
    nome = utente.display_name if hasattr(utente, "display_name") else str(utente)
    log.info(tag("CMD", f"citazione_ctx {user(str(inter.user))} su msg di {user(nome)}"))
    await inter.response.defer()
    try:
        img_bytes = await build_quote_card(testo, nome, avatar_url)
        await inter.followup.send(
            file=discord.File(fp=io.BytesIO(img_bytes), filename="citazione.png"),
        )
    except Exception as e:
        log.error(tag("CMD", f"citazione_ctx errore: {e}"), exc_info=True)
        await inter.followup.send("\u274c Errore durante la generazione della citazione.", ephemeral=True)


class Fun(commands.Cog):
    COG_ICON  = "\U0001f3b2"
    COG_LABEL = "Divertimento"
    COG_TYPE  = "fun"

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        bot.tree.add_command(citazione_context)

    def cog_unload(self):
        self.bot.tree.remove_command("Citazione", type=discord.AppCommandType.message)

    # ── 8ball ───────────────────────────────────────────────────────────────────────

    @app_commands.command(name="8ball", description="\U0001f3b1 Fai una domanda all'8-Ball")
    @app_commands.describe(domanda="La domanda da porre")
    async def ball8(self, inter: discord.Interaction, domanda: str):
        key     = random.choice(_8BALL_OUTCOMES)
        label, emoji, pool = _8BALL_LABELS[key]
        testo, colore = random.choice(pool)
        embed = discord.Embed(
            description=f"**{testo}**",
            color=colore,
        )
        embed.set_author(name=f"{emoji} {label}")
        embed.add_field(name="Domanda", value=domanda, inline=False)
        log.info(tag("CMD", f"8ball  {user(str(inter.user))}  \u2192  {label}"))
        await inter.response.send_message(embed=embed)

    # ── Citazione slash ────────────────────────────────────────────────────────

    @app_commands.command(name="citazione", description="\U0001f4dc Genera una citazione in stile card")
    @app_commands.describe(
        testo="Testo della citazione",
        autore="Nome custom dell'autore (default: il tuo nome)",
        utente="Usa avatar e nome di un utente Discord specifico",
        immagine_url="URL di un'immagine custom da usare come avatar nella card",
    )
    async def citazione(
        self,
        inter: discord.Interaction,
        testo: str,
        autore: Optional[str] = None,
        utente: Optional[discord.Member] = None,
        immagine_url: Optional[str] = None,
    ):
        if len(testo) > _MAX_QUOTE_LEN:
            testo = testo[:_MAX_QUOTE_LEN] + "\u2026"

        # Priorità: utente Discord > immagine_url custom > avatar invocante
        if utente is not None:
            nome = autore or utente.display_name
            avatar_url = utente.display_avatar.url
            log.info(tag("CMD", f"citazione {user(str(inter.user))} autore={nome} [utente Discord: {utente}]"))
        elif immagine_url is not None:
            nome = autore or inter.user.display_name
            avatar_url = immagine_url
            log.info(tag("CMD", f"citazione {user(str(inter.user))} autore={nome} [immagine custom]"))
        else:
            nome = autore or inter.user.display_name
            avatar_url = inter.user.display_avatar.url if not autore else None
            log.info(tag("CMD", f"citazione {user(str(inter.user))} autore={nome}"))

        await inter.response.defer()
        try:
            img_bytes = await build_quote_card(testo, nome, avatar_url)
            await inter.followup.send(
                file=discord.File(fp=io.BytesIO(img_bytes), filename="citazione.png")
            )
        except Exception as e:
            log.error(tag("CMD", f"citazione errore: {e}"), exc_info=True)
            await inter.followup.send("\u274c Errore durante la generazione della citazione.", ephemeral=True)

    # ── Roulette ────────────────────────────────────────────────────────────────

    @app_commands.command(name="roulette", description="\U0001f52b Roulette russa: 1 colpo su 6")
    async def roulette(self, inter: discord.Interaction):
        chamber = random.randint(1, 6)
        dead    = chamber == 1
        display = _cylinder_display(chamber, dead)
        if dead:
            embed = discord.Embed(
                title="\U0001f4a5 BANG!",
                description=f"{inter.user.mention} ha premuto il grilletto e... **ERA IL COLPO**!\n\n{display}",
                color=0xe74c3c,
            )
        else:
            embed = discord.Embed(
                title="\U0001f4a8 Click.",
                description=f"{inter.user.mention} ha premuto il grilletto... **camera vuota**.\n\n{display}",
                color=0x2ecc71,
            )
        log.info(tag("CMD", f"roulette  {user(str(inter.user))}  chamber={chamber}  dead={dead}"))
        await inter.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Fun(bot))
