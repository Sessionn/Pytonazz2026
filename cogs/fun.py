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


class Fun(commands.Cog):
    COG_ICON  = "\U0001f3b2"
    COG_LABEL = "Divertimento"
    COG_TYPE  = "public"

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── /roulette ────────────────────────────────────────────────────────────
    @app_commands.command(
        name="roulette",
        description="\U0001f52b Roulette russa: 1/6 di probabilit\u00e0 di essere mutato per 5 minuti",
    )
    async def roulette(self, inter: discord.Interaction):
        if not inter.guild or not isinstance(inter.user, discord.Member):
            return await inter.response.send_message(
                "❌ Questo comando è disponibile solo in un server.",
                ephemeral=True,
            )

        await inter.response.send_message(
            embed=discord.Embed(
                title="\U0001f52b  Roulette Russa",
                description=f"{inter.user.mention} preme il grilletto...",
                color=0xf0c040,
            )
        )
        await asyncio.sleep(1.8)

        bullet  = random.randint(1, 6)
        chamber = random.randint(1, 6)
        dead    = (bullet == chamber)

        forbidden = False
        if dead:
            me = inter.guild.me
            can_timeout = bool(
                me
                and me.guild_permissions.moderate_members
                and inter.user != inter.guild.owner
                and inter.user.top_role < me.top_role
            )
            if not can_timeout:
                forbidden = True
                log.warning(tag("CMD", f"roulette BANG {user(str(inter.user))} permessi/gerarchia insufficienti"))
            else:
                try:
                    await inter.user.timeout(
                        discord.utils.utcnow() + timedelta(minutes=5),
                        reason="Roulette russa",
                    )
                    log.info(tag("CMD", f"roulette BANG {user(str(inter.user))} cam={chamber} mutato 5min"))
                except discord.Forbidden:
                    forbidden = True
                    log.warning(tag("CMD", f"roulette BANG {user(str(inter.user))} Forbidden"))
        else:
            log.info(tag("CMD", f"roulette click {user(str(inter.user))} cam={chamber}"))

        await inter.edit_original_response(
            embed=_roulette_result_embed(inter.user, chamber, dead, forbidden)
        )

    # ── /poll ─────────────────────────────────────────────────────────────────
    @app_commands.command(name="poll", description="\U0001f4ca Crea un sondaggio con 2-4 opzioni")
    @app_commands.describe(
        domanda="La domanda del sondaggio",
        opzione1="Prima opzione",
        opzione2="Seconda opzione",
        opzione3="Terza opzione (opzionale)",
        opzione4="Quarta opzione (opzionale)",
    )
    async def poll(
        self,
        inter: discord.Interaction,
        domanda: str,
        opzione1: str,
        opzione2: str,
        opzione3: Optional[str] = None,
        opzione4: Optional[str] = None,
    ):
        # Verifica permessi prima di inviare il poll
        if inter.guild:
            me = inter.guild.me
            ch_perms = inter.channel.permissions_for(me)
            if not ch_perms.add_reactions:
                return await inter.response.send_message(
                    "\u274c Non ho il permesso di aggiungere reazioni in questo canale. Il sondaggio non pu\u00f2 essere creato.",
                    ephemeral=True,
                )

        opzioni = [o for o in [opzione1, opzione2, opzione3, opzione4] if o]
        righe   = "\n".join(f"{_POLL_EMOJIS[i]}  {o}" for i, o in enumerate(opzioni))
        embed   = discord.Embed(title=f"\U0001f4ca {domanda}", description=righe, color=0x5865F2)
        embed.set_footer(text=f"Sondaggio di {inter.user.display_name}")
        log.info(tag("CMD", f"poll {user(str(inter.user))} opzioni={len(opzioni)} {b(repr(domanda[:50]))}"))
        await inter.response.send_message(embed=embed)
        msg = await inter.original_response()
        for i in range(len(opzioni)):
            try:
                await msg.add_reaction(_POLL_EMOJIS[i])
            except discord.Forbidden:
                log.warning(tag("WARN", f"poll reazione Forbidden ch={b(inter.channel_id)}"))
                # Rimuovi il poll già pubblicato per evitare UI rotta
                try:
                    await msg.delete()
                except Exception:
                    pass
                await inter.followup.send(
                    "\u26a0\ufe0f Non ho il permesso di aggiungere reazioni. Il sondaggio \u00e8 stato rimosso.",
                    ephemeral=True,
                )
                return
            except discord.HTTPException as e:
                log.warning(tag("WARN", f"poll reazione HTTPException {b(e)}"))
                try:
                    await msg.delete()
                except (discord.NotFound, discord.Forbidden, discord.HTTPException) as del_exc:
                    log.warning(tag("WARN", f"poll cleanup fallito: {del_exc}"))
                await inter.followup.send(
                    "⚠️ Errore durante l'aggiunta delle reazioni. Il sondaggio è stato rimosso.",
                    ephemeral=True,
                )
                return

    # ── /8ball ────────────────────────────────────────────────────────────────
    @app_commands.command(name="8ball", description="\U0001f3b1 Fai una domanda all'oracolo")
    @app_commands.describe(domanda="La tua domanda")
    async def eightball(self, inter: discord.Interaction, domanda: str):
        outcome = random.choice(_8BALL_OUTCOMES)
        label, dot, pool = _8BALL_LABELS[outcome]
        testo, colore = random.choice(pool)
        log.info(tag("CMD", f"8ball {user(str(inter.user))} esito={b(label)}"))
        embed = discord.Embed(color=colore)
        embed.set_author(name="\U0001f3b1  La sfera ha parlato", icon_url=inter.user.display_avatar.url)
        embed.add_field(name="\U0001f4ac Domanda",  value=f"*{domanda}*",  inline=False)
        embed.add_field(name=f"{dot} {label}",     value=f"**{testo}**", inline=False)
        embed.set_footer(text=f"chiesto da {inter.user.mention}")
        await inter.response.send_message(embed=embed)

    # ── /citazione ────────────────────────────────────────────────────────────
    @app_commands.command(name="citazione", description="Genera una card citazione elegante")
    @app_commands.describe(
        testo="La frase da citare",
        utente="Utente a cui attribuire la citazione (usa la sua pfp)",
        autore="Nome personalizzato (opzionale)",
    )
    async def citazione(
        self,
        inter: discord.Interaction,
        testo: str,
        utente: Optional[discord.Member] = None,
        autore: str = "",
    ):
        if len(testo) > _MAX_QUOTE_LEN:
            return await inter.response.send_message(
                f"\u274c Testo troppo lungo (max {_MAX_QUOTE_LEN} caratteri).",
                ephemeral=True,
            )
        await inter.response.defer()
        target      = utente or inter.user
        author_name = autore or target.display_name
        avatar_url  = str(target.display_avatar.with_format("png").with_size(1024))
        server_name = inter.guild.name if inter.guild else ""
        img_bytes   = await build_quote_card(
            text=testo,
            author=author_name,
            avatar_url=avatar_url,
            server_name=server_name,
        )
        log.info(tag("CMD", f"/citazione {b(author_name)} {len(testo)} car."))
        await inter.followup.send(
            file=discord.File(fp=io.BytesIO(img_bytes), filename="citazione.png")
        )


# ── Helper embed roulette ─────────────────────────────────────────────────────
def _roulette_result_embed(
    member: discord.Member | discord.User,
    chamber: int,
    dead: bool,
    forbidden: bool,
) -> discord.Embed:
    cylinder = _cylinder_display(chamber, dead)
    if dead and not forbidden:
        embed = discord.Embed(
            title="\U0001f4a5  BANG!",
            description=(
                f"{member.mention} ha premuto il grilletto...\n"
                f"La camera **#{chamber}** era carica.\n\n"
                f"{cylinder}\n\n"
                f"\U0001f507 **Mutato per 5 minuti.**"
            ),
            color=0xe74c3c,
        )
        embed.set_footer(text="Meglio non tentare la fortuna...")
    elif dead and forbidden:
        embed = discord.Embed(
            title="\U0001f4a5  BANG! (mancanza di permessi)",
            description=(
                f"{member.mention} ha premuto il grilletto...\n"
                f"La camera **#{chamber}** era carica.\n\n"
                f"{cylinder}\n\n"
                "\u26a0\ufe0f Non ho i permessi per applicare il timeout."
            ),
            color=0xe67e22,
        )
        embed.set_footer(text="Avresti dovuto essere mutato, ma sono le mie mani a essere legate.")
    else:
        embed = discord.Embed(
            title="\U0001f995  Click.",
            description=(
                f"{member.mention} ha premuto il grilletto...\n"
                f"La camera **#{chamber}** era vuota.\n\n"
                f"{cylinder}\n\n"
                "\U0001f7e2 **Sei salvo.**"
            ),
            color=0x2ecc71,
        )
        embed.set_footer(text="Sei salvo. Per ora.")
    return embed


async def setup(bot: commands.Bot):
    await bot.add_cog(Fun(bot))
