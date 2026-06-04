import io
import logging
import random
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from core.log_colors import tag, user
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
    ("S\u00ec, e pure con una facilit\u00e0 offensiva.",                           0x2ecc71),
    ("Verde pieno. Vai e fai danni.",                                              0x27ae60),
    ("Confermo. Eri tu quello lento ad arrivarci.",                                0x2ecc71),
    ("S\u00ec, ma fallo con una faccia convinta almeno.",                          0x27ae60),
    ("La risposta \u00e8 s\u00ec. Il piano invece \u00e8 discutibile.",            0x2ecc71),
    ("Assolutamente s\u00ec. Per una volta il caos collabora.",                    0x27ae60),
    ("S\u00ec. Sorprendentemente il destino oggi non ti odia.",                    0x2ecc71),
    ("Mi esce un s\u00ec cos\u00ec forte che quasi mi preoccupa.",                 0x27ae60),
    ("S\u00ec, e anche abbastanza presto.",                                         0x2ecc71),
    ("S\u00ec. Non so come, ma s\u00ec.",                                           0x27ae60),
    ("Le probabilit\u00e0 ti fanno l'occhiolino. S\u00ec.",                        0x2ecc71),
    ("S\u00ec, ma non montarti troppo la testa.",                                  0x27ae60),
    ("Approvato. Timbro, firma e caos amministrativo.",                            0x2ecc71),
    ("S\u00ec. E stavolta pure senza plot twist immediato.",                       0x27ae60),
    ("S\u00ec, sembra proprio una di quelle rare volte buone.",                    0x2ecc71),
    ("Convergono tutti i segnali utili: s\u00ec.",                                 0x27ae60),
    ("S\u00ec. L'universo ha detto 'ci sta'.",                                      0x2ecc71),
    ("S\u00ec, ma evita di rovinarlo parlando troppo.",                            0x27ae60),
    ("Decisamente s\u00ec. Anche il mio lato tossico approva.",                    0x2ecc71),
    ("S\u00ec. Hai pescato il timeline meno imbarazzante.",                        0x27ae60),
    ("Verdetto positivo. Puoi procedere con moderata superbia.",                   0x2ecc71),
    ("S\u00ec. Non chiedermi altre garanzie per\u00f2.",                           0x27ae60),
    ("S\u00ec, e quasi mi d\u00e0 fastidio ammetterlo.",                           0x2ecc71),
    ("Il cosmo ha annuito. Male, ma ha annuito.",                                  0x27ae60),
    ("S\u00ec. Vai sereno, o almeno fai finta.",                                   0x2ecc71),
    ("Mi sa di s\u00ec pesante.",                                                  0x27ae60),
    ("S\u00ec, con bonus fortuna da NPC secondario.",                              0x2ecc71),
    ("S\u00ec. Se fallisci, la colpa sar\u00e0 artistica.",                        0x27ae60),
    ("S\u00ec, e pure con stile se non improvvisi troppo.",                        0x2ecc71),
    ("L'algoritmo del fato dice s\u00ec. Inquietante ma utile.",                   0x27ae60),
]
_8BALL_NO = [
    ("No.",                                                          0xe74c3c),
    ("Assolutamente no.",                                            0xe74c3c),
    ("No. E smettila di sperare.",                                   0xc0392b),
    ("L'universo ha riso alla tua domanda. La risposta \u00e8 no.",  0xe74c3c),
    ("No. E francamente meno male.",                                 0xc0392b),
    ("Mai. Neanche in un'altra vita.",                               0xe74c3c),
    ("No. Il confine \u00e8 chiaro.",                                 0xc0392b),
    ("No, e non c'\u00e8 neanche margine per negoziare.",             0xe74c3c),
    ("No. Te lo boccio con una cattiveria elegante.",                 0xc0392b),
    ("Direi no, con una punta di piet\u00e0.",                        0xe74c3c),
    ("No. Il destino ha proprio chiuso la porta.",                    0xc0392b),
    ("No, e forse ti ha salvato da una figuraccia.",                  0xe74c3c),
    ("No. Questa timeline puzza gi\u00e0 abbastanza cos\u00ec.",      0xc0392b),
    ("No, non oggi, non domani, non con quel piano.",                 0xe74c3c),
    ("Risposta breve: no. Risposta lunga: sempre no.",                0xc0392b),
    ("No. E guarda che il cosmo raramente \u00e8 cos\u00ec netto.",   0xe74c3c),
    ("Respinto. Con timbro rosso e giudizio passivo-aggressivo.",     0xc0392b),
    ("No. Hai proprio bussato alla porta sbagliata.",                 0xe74c3c),
    ("No, e il bello \u00e8 che lo sapevi gi\u00e0.",                 0xc0392b),
    ("Direzione sconsigliata. Tradotto: no.",                         0xe74c3c),
    ("No. Mossa brutta, energia peggiore.",                           0xc0392b),
    ("No, e nemmeno con un boost di fortuna improvvisa.",             0xe74c3c),
    ("Negativo. Il fato ha mandato direttamente il secchio.",         0xc0392b),
    ("No. Sarebbe una pessima side quest.",                           0xe74c3c),
    ("No, e pure con un certo disgusto.",                             0xc0392b),
    ("La risposta \u00e8 no e il silenzio successivo \u00e8 pesante.",0xe74c3c),
    ("No. Stavolta l'intuizione ti sta urlando contro.",              0xc0392b),
    ("Assenza totale di benedizione cosmica: no.",                    0xe74c3c),
    ("No. Il multiverso ha votato compatto.",                         0xc0392b),
    ("No, ma apprezzo il coraggio mal riposto.",                      0xe74c3c),
    ("No. Anche la versione pi\u00f9 ottimista di me ha rinunciato.", 0xc0392b),
    ("No, e sarebbe il caso di non insistere.",                       0xe74c3c),
    ("Niente da fare. Sipario.",                                      0xc0392b),
    ("No. Hai chiesto male e pure al momento sbagliato.",             0xe74c3c),
    ("No, ma se vuoi posso dirlo pi\u00f9 drammaticamente.",          0xc0392b),
    ("No. Il sistema ha risposto con una smorfia.",                   0xe74c3c),
    ("Verdetto ostile: no secco.",                                    0xc0392b),
]
_8BALL_VAGO = [
    ("Non lo so e onestamente non mi importa.",                            0x95a5a6),
    ("Forse. Ma probabile che non cambi nulla.",                           0x7f8c8d),
    ("Dipende da quanti errori sei disposto a fare.",                      0x95a5a6),
    ("La risposta esiste. Non \u00e8 per te.",                             0x7f8c8d),
    ("Chiedi a qualcuno che ci tiene.",                                    0x95a5a6),
    ("Nebbia totale. Buona fortuna.",                                      0x7f8c8d),
    ("Possibile. Come quasi tutto. Non \u00e8 utile come risposta, lo so.", 0x95a5a6),
    ("Forse s\u00ec, forse no, forse ti sei spiegato male.",                0x7f8c8d),
    ("Situazione fumosa. Mi piace poco.",                                  0x95a5a6),
    ("I segnali sono misti. Un po' come le tue idee.",                     0x7f8c8d),
    ("Potrebbe andare. Potrebbe anche esplodere piano.",                   0x95a5a6),
    ("Non abbastanza chiaro per un verdetto serio.",                       0x7f8c8d),
    ("La palla gira, riflette e poi svia il discorso.",                    0x95a5a6),
    ("Forse. Dipende da dettagli che stai sicuramente ignorando.",         0x7f8c8d),
    ("Ci sono troppe variabili e troppo poca dignit\u00e0.",               0x95a5a6),
    ("Boh ragionato.",                                                     0x7f8c8d),
    ("In teoria s\u00ec, in pratica vedo caos.",                           0x95a5a6),
    ("Possibilit\u00e0 aperta, esito discutibile.",                        0x7f8c8d),
    ("La risposta oggi ha deciso di venire vestita da nebbia.",            0x95a5a6),
    ("Meh. Non abbastanza bene per un s\u00ec, non abbastanza male per un no.", 0x7f8c8d),
    ("La situazione \u00e8 scivolosa. Tipo sapone metafisico.",            0x95a5a6),
    ("Potrei dirti forse e sembrerei pure competente.",                    0x7f8c8d),
    ("Domanda complicata, energia confusa.",                               0x95a5a6),
    ("Sto ricevendo statico, dubbi e una lieve delusione.",                0x7f8c8d),
    ("Esito non determinato. Classico caso da arrangiati.",               0x95a5a6),
    ("Niente certezza. Solo atmosfera.",                                   0x7f8c8d),
    ("Forse, ma non con l'eleganza che speri.",                            0x95a5a6),
    ("La mia risposta \u00e8 un'alzata di spalle cosmica.",               0x7f8c8d),
    ("Pu\u00f2 darsi. Anche no. Utile, vero?",                             0x95a5a6),
    ("Quadrante grigio. Tutto molto poetico e poco pratico.",              0x7f8c8d),
    ("Direi di aspettare, ma tanto non lo farai.",                         0x95a5a6),
    ("Le opzioni sono aperte e il destino sta procrastinando.",            0x7f8c8d),
    ("Mi esce un forse molto burocratico.",                                0x95a5a6),
    ("Non \u00e8 il momento di avere certezze. Che peccato.",              0x7f8c8d),
    ("La verit\u00e0 c'\u00e8, ma sta evitando il contatto visivo.",       0x95a5a6),
    ("Risposta grigia, vibrazioni caotiche, esito sospeso.",               0x7f8c8d),
    ("Forse. Porta pazienza o porta casco.",                               0x95a5a6),
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
        embed = discord.Embed(color=colore)
        embed.set_author(name=f"{emoji} {label}")
        embed.add_field(name="Domanda", value=domanda, inline=False)
        embed.add_field(name="Risposta", value=f"**{testo}**", inline=False)
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
