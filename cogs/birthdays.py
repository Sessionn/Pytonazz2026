"""Sistema compleanni per Pitonazz.

Gruppo: /bday
  /bday set            <giorno> <mese> [anno]             — chiunque (solo il proprio)
  /bday adminset       <@utente> <giorno> <mese> [anno]  — 👑 admin
  /bday remove                                           — chiunque (solo il proprio)
  /bday adminremove    <@utente>                          — 👑 admin
  /bday check          [@utente]                         — chiunque
  /bday list                                             — chiunque
  /bday channel        [#canale]                         — 👑 admin
  /bday test                                             — 👑 admin
  /bday tags                                             — 👑 admin
  /bday messages_set                                     — 👑 admin
  /bday messages_add                                     — 👑 admin
  /bday messages_remove                                  — 👑 admin
  /bday messages_list                                    — 👑 admin

I messaggi automatici sono solo plain text e vengono scelti da una lista JSON
configurabile per server.
"""
from __future__ import annotations

import asyncio
import calendar
import logging
import random
from datetime import date, datetime
from typing import Optional
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands, tasks

from core.birthday_store import (
    set_birthday,
    remove_birthday,
    get_birthday,
    get_all_birthdays,
    set_channel,
    get_channel,
    get_todays_birthdays,
    get_list_message_id,
    set_list_message_id,
    get_wish_messages,
    set_wish_messages,
    add_wish_message,
    remove_wish_message,
)
from core.cmd_perm import perm
from core.log_colors import tag, b, user

log = logging.getLogger("pitonazz.birthdays")

_BIRTHDAY_TIMEZONE = ZoneInfo("Europe/Rome")

_CROWN = "👑"
_MAX_REMOVED_PREVIEW = 120

_MONTHS_IT = [
    "", "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
    "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre",
]
_MONTHS_IT_CAP = [
    "", "Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno",
    "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre",
]
_MONTH_CHOICES = [
    app_commands.Choice(name=_MONTHS_IT_CAP[i], value=i)
    for i in range(1, 13)
]

sent_today: dict[int, set[int]] = {}
sent_cache_day: date | None = None

_TAGS_EMBED = (
    discord.Embed(
        title="🏷️ Placeholder — compleanni (plain text)",
        description="Usabili nei messaggi di auguri configurati in `/bday messages_set` o `/bday messages_add`.",
        color=0x5865F2,
    )
    .add_field(
        name="Utente",
        value=(
            "`{mention}` — menzione cliccabile\n"
            "`{name}` — username\n"
            "`{display_name}` — nickname server"
        ),
        inline=True,
    )
    .add_field(
        name="Compleanno",
        value=(
            "`{age}` — età numerica (se anno presente)\n"
            "`{years}` — alias di `{age}`\n"
            "`{guild}` — nome server"
        ),
        inline=True,
    )
    .add_field(
        name="Note",
        value=(
            "- Messaggi inviati come **testo semplice** (no embed).\n"
            "- Puoi includere menzioni/tag direttamente nel testo.\n"
            "- Ogni riga in `messages_set` è un messaggio diverso."
        ),
        inline=False,
    )
)


class _SafeFormatMap(dict):
    """Preserva i placeholder mancanti senza sollevare KeyError."""
    def __missing__(self, key):
        return "{" + key + "}"


def _format_date(day: int, month: int, year: Optional[int]) -> str:
    return f"{day} {_MONTHS_IT[month]}" + (f" {year}" if year else "")


def _safe_date(year: int, month: int, day: int) -> date:
    """Ritorna una data valida; se non esiste usa il giorno 28 (es. 30 febbraio)."""
    try:
        return date(year, month, day)
    except ValueError:
        return date(year, month, 28)


def _days_until(day: int, month: int, today: date) -> int:
    next_bd = _safe_date(today.year, month, day)
    if next_bd < today:
        next_bd = _safe_date(today.year + 1, month, day)
    return (next_bd - today).days


def _pick_wish(member: discord.Member, age: Optional[int], templates: list[str]) -> str:
    pool = [t.strip() for t in templates if t and t.strip()]
    default = (
        "🎂 Tanti auguri {mention}! Oggi compi {age} anni! 🎉"
        if age is not None
        else "🎂 Tanti auguri {mention}! 🎉"
    )
    template = random.choice(pool) if pool else default
    mapping = _SafeFormatMap(
        {
            "mention": member.mention,
            "name": member.name,
            "display_name": member.display_name,
            "guild": member.guild.name,
            "age": "" if age is None else str(age),
            "years": "" if age is None else str(age),
        }
    )
    try:
        msg = template.format_map(mapping).strip()
    except Exception:
        msg = template
    return msg or default.format_map(mapping)


def _build_list_embeds(guild: discord.Guild, all_bdays: dict) -> list[discord.Embed]:
    today = date.today()
    now_year = today.year

    rows: list[tuple[int, int, int, str, Optional[int]]] = []
    for uid_str, e in all_bdays.items():
        member = guild.get_member(int(uid_str))
        mention = member.mention if member else f"<@{uid_str}>"
        age_now = (now_year - e["year"]) if e.get("year") else None
        this_year_birthday_date = _safe_date(today.year, e["month"], e["day"])
        age_next = (age_now + 1) if age_now and this_year_birthday_date < today else age_now
        days = _days_until(e["day"], e["month"], today)
        rows.append((days, e["month"], e["day"], mention, age_next))

    rows.sort(key=lambda r: r[0])

    blocks: list[str] = []
    i = 0
    while i < len(rows):
        days, month, day, mention, age_next = rows[i]
        bd_date = _safe_date(today.year, month, day)
        bd_year = today.year + 1 if bd_date < today else today.year
        date_str = f"{day:02d} {_MONTHS_IT_CAP[month]} {bd_year}"

        if days == 0:
            label = " — **oggi 🎂**"
        elif days == 1:
            label = " — *domani*"
        elif days <= 7:
            label = f" — *tra {days} giorni*"
        else:
            label = ""

        members_on_day: list[str] = []
        while i < len(rows) and rows[i][1] == month and rows[i][2] == day:
            _, _, _, m_mention, m_age = rows[i]
            members_on_day.append(f"{m_mention}" + (f" **({m_age})**" if m_age else ""))
            i += 1

        blocks.append(f"**{date_str}**{label}\n" + "\n".join(members_on_day))

    if not blocks:
        return []

    page = 10
    chunks = [blocks[j:j + page] for j in range(0, len(blocks), page)]
    embeds: list[discord.Embed] = []
    total_pages = len(chunks)
    for idx, chunk in enumerate(chunks):
        title = "🎂 Prossimi compleanni"
        if total_pages > 1:
            title += f"  ·  {idx + 1}/{total_pages}"
        embed = discord.Embed(
            title=title,
            description="\n\n".join(chunk),
            color=0x5865F2,
        )
        embeds.append(embed)
    return embeds


async def _refresh_list_in_channel(guild: discord.Guild) -> None:
    channel_id = get_channel(guild.id)
    if not channel_id:
        return
    channel = guild.get_channel(channel_id)
    if not channel:
        return
    all_bdays = get_all_birthdays(guild.id)
    embeds = _build_list_embeds(guild, all_bdays)
    if not embeds:
        return
    old_msg_id = get_list_message_id(guild.id)
    if old_msg_id:
        try:
            old_msg = await channel.fetch_message(old_msg_id)
            await old_msg.delete()
        except (discord.NotFound, discord.HTTPException):
            pass
    new_msg = await channel.send(embed=embeds[0])
    set_list_message_id(guild.id, new_msg.id)
    log.info(tag("BDAY", f"Lista aggiornata  id={new_msg.id}  [{b(guild.name)}]"))


class Birthdays(commands.Cog):
    COG_ICON = "🎂"
    COG_LABEL = "Compleanni"
    COG_TYPE = "public"

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._check_loop.start()

    def cog_unload(self):
        self._check_loop.cancel()

    @tasks.loop(minutes=1)
    async def _check_loop(self):
        global sent_cache_day
        now = datetime.now(_BIRTHDAY_TIMEZONE)
        if now.hour != 0 or now.minute != 0:
            return
        if sent_cache_day != now.date():
            sent_today.clear()
            sent_cache_day = now.date()
        log.info(tag("BDAY", f"Check compleanni {now.date()}"))
        for guild in self.bot.guilds:
            channel_id = get_channel(guild.id)
            if not channel_id:
                continue
            channel = guild.get_channel(channel_id)
            if not channel:
                continue
            entries = get_todays_birthdays(guild.id, now.day, now.month)
            templates = get_wish_messages(guild.id)
            sent = sent_today.setdefault(guild.id, set())
            any_sent = False
            for entry in entries:
                uid = entry["user_id"]
                if uid in sent:
                    continue
                member = guild.get_member(uid)
                if not member:
                    continue
                age = (now.year - entry["year"]) if entry.get("year") else None
                try:
                    wish = _pick_wish(member, age, templates)
                    await channel.send(content=wish)
                    sent.add(uid)
                    any_sent = True
                    log.info(tag("BDAY", f"Auguri → {user(str(member))}  [{b(guild.name)}]"))
                except discord.Forbidden:
                    log.warning(tag("BDAY", f"Permessi mancanti invio auguri  [guild_id={guild.id}]"))
                except discord.HTTPException:
                    log.warning(tag("BDAY", f"HTTP error invio auguri  [guild_id={guild.id}]"))
                except Exception:
                    log.exception(tag("BDAY", f"Errore invio auguri  [guild_id={guild.id}]"))
            if any_sent:
                try:
                    await _refresh_list_in_channel(guild)
                except Exception as e:
                    log.error(tag("BDAY", f"Errore refresh lista: {e}"))

    @_check_loop.before_loop
    async def _before_check(self):
        await self.bot.wait_until_ready()
        now = datetime.now(_BIRTHDAY_TIMEZONE)
        secs = ((24 * 3600) - (now.hour * 3600 + now.minute * 60 + now.second)) % (24 * 3600)
        if secs > 60:
            await asyncio.sleep(secs - 60)
        sent_today.clear()

    bday = app_commands.Group(name="bday", description="🎂 Sistema compleanni")

    @bday.command(name="set", description="Imposta il tuo compleanno")
    @app_commands.describe(
        giorno="Giorno (1-31)",
        mese="Mese (seleziona dalla lista)",
        anno="Anno di nascita (opzionale — mostra l'età negli auguri)",
    )
    @app_commands.choices(mese=_MONTH_CHOICES)
    async def bday_set(
        self,
        inter: discord.Interaction,
        giorno: app_commands.Range[int, 1, 31],
        mese: app_commands.Range[int, 1, 12],
        anno: Optional[int] = None,
    ):
        max_day = calendar.monthrange(anno or 2000, mese)[1]
        if giorno > max_day:
            return await inter.response.send_message(
                embed=self._err(f"Il mese {_MONTHS_IT[mese]} non ha {giorno} giorni."), ephemeral=True
            )
        if anno and (anno < 1900 or anno > datetime.now(_BIRTHDAY_TIMEZONE).year):
            return await inter.response.send_message(
                embed=self._err(f"Anno non valido ({anno})."), ephemeral=True
            )
        set_birthday(inter.guild_id, inter.user.id, giorno, mese, anno)
        date_str = _format_date(giorno, mese, anno)
        log.info(tag("BDAY", f"Set  {user(str(inter.user))}  →  {date_str}"))
        asyncio.create_task(_refresh_list_in_channel(inter.guild))
        await inter.response.send_message(
            embed=self._ok(f"✅ Compleanno impostato: **{date_str}**."), ephemeral=True
        )

    @bday.command(name="adminset", description=f"{_CROWN} Imposta il compleanno di un altro utente")
    @perm("admin")
    @app_commands.describe(
        utente="Utente a cui impostare il compleanno",
        giorno="Giorno (1-31)",
        mese="Mese (seleziona dalla lista)",
        anno="Anno di nascita (opzionale)",
    )
    @app_commands.choices(mese=_MONTH_CHOICES)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def bday_adminset(
        self,
        inter: discord.Interaction,
        utente: discord.Member,
        giorno: app_commands.Range[int, 1, 31],
        mese: app_commands.Range[int, 1, 12],
        anno: Optional[int] = None,
    ):
        max_day = calendar.monthrange(anno or 2000, mese)[1]
        if giorno > max_day:
            return await inter.response.send_message(
                embed=self._err(f"Il mese {_MONTHS_IT[mese]} non ha {giorno} giorni."), ephemeral=True
            )
        if anno and (anno < 1900 or anno > datetime.now(_BIRTHDAY_TIMEZONE).year):
            return await inter.response.send_message(
                embed=self._err(f"Anno non valido ({anno})."), ephemeral=True
            )
        set_birthday(inter.guild_id, utente.id, giorno, mese, anno)
        date_str = _format_date(giorno, mese, anno)
        log.info(tag("BDAY", f"AdminSet  {user(str(inter.user))}  →  {utente}  {date_str}"))
        asyncio.create_task(_refresh_list_in_channel(inter.guild))
        await inter.response.send_message(
            embed=self._ok(f"✅ Compleanno di **{utente.display_name}** impostato: **{date_str}**."),
            ephemeral=True,
        )

    @bday.command(name="remove", description="Rimuovi il tuo compleanno")
    async def bday_remove(self, inter: discord.Interaction):
        existed = remove_birthday(inter.guild_id, inter.user.id)
        if existed:
            asyncio.create_task(_refresh_list_in_channel(inter.guild))
            await inter.response.send_message(
                embed=self._ok("🗑️ Compleanno rimosso."), ephemeral=True
            )
        else:
            await inter.response.send_message(
                embed=self._err("Nessun compleanno registrato per te."), ephemeral=True
            )

    @bday.command(name="adminremove", description=f"{_CROWN} Rimuovi il compleanno di un utente")
    @perm("admin")
    @app_commands.describe(utente="Utente di cui rimuovere il compleanno")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def bday_adminremove(
        self,
        inter: discord.Interaction,
        utente: discord.Member,
    ):
        existed = remove_birthday(inter.guild_id, utente.id)
        if existed:
            asyncio.create_task(_refresh_list_in_channel(inter.guild))
            await inter.response.send_message(
                embed=self._ok(f"🗑️ Compleanno di **{utente.display_name}** rimosso."), ephemeral=True
            )
        else:
            await inter.response.send_message(
                embed=self._err(f"Nessun compleanno registrato per **{utente.display_name}**."),
                ephemeral=True,
            )

    @bday.command(name="check", description="Controlla il compleanno di un utente")
    @app_commands.describe(utente="Utente da controllare (default: te stesso)")
    async def bday_check(self, inter: discord.Interaction, utente: Optional[discord.Member] = None):
        target = utente or inter.user
        entry = get_birthday(inter.guild_id, target.id)
        if not entry:
            return await inter.response.send_message(
                embed=self._err(f"Nessun compleanno registrato per **{target.display_name}**."), ephemeral=True
            )
        date_str = _format_date(entry["day"], entry["month"], entry.get("year"))
        embed = discord.Embed(description=f"🎂 **{target.display_name}** — {date_str}", color=0xf1c40f)
        embed.set_thumbnail(url=target.display_avatar.url)
        await inter.response.send_message(embed=embed)

    @bday.command(name="list", description="Lista dei prossimi compleanni del server")
    async def bday_list(self, inter: discord.Interaction):
        await inter.response.defer()
        all_bdays = get_all_birthdays(inter.guild_id)
        if not all_bdays:
            return await inter.followup.send(embed=self._err("Nessun compleanno registrato in questo server."))
        embeds = _build_list_embeds(inter.guild, all_bdays)
        if not embeds:
            return await inter.followup.send(embed=self._err("Errore nella generazione della lista."))
        old_msg_id = get_list_message_id(inter.guild_id)
        if old_msg_id:
            try:
                old = await inter.channel.fetch_message(old_msg_id)
                await old.delete()
            except (discord.NotFound, discord.HTTPException):
                pass
        first_sent = await inter.followup.send(embed=embeds[0])
        for embed in embeds[1:]:
            await inter.followup.send(embed=embed)
        if first_sent:
            set_list_message_id(inter.guild_id, first_sent.id)

    @bday.command(name="channel", description=f"{_CROWN} Imposta o rimuovi il canale per gli auguri automatici")
    @perm("admin")
    @app_commands.describe(canale="Canale di testo (ometti per disabilitare)")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def bday_channel(self, inter: discord.Interaction, canale: Optional[discord.TextChannel] = None):
        set_channel(inter.guild_id, canale.id if canale else None)
        if not canale:
            set_list_message_id(inter.guild_id, None)
        msg = f"✅ Canale auguri impostato su {canale.mention}." if canale else "🔕 Auguri automatici disabilitati."
        log.info(tag("BDAY", f"channel → {canale}  ({inter.guild.name})"))
        await inter.response.send_message(embed=self._ok(msg), ephemeral=True)

    @bday.command(name="tags", description=f"{_CROWN} Placeholder disponibili per i messaggi compleanno")
    @perm("admin")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def bday_tags(self, inter: discord.Interaction):
        await inter.response.send_message(embed=_TAGS_EMBED, ephemeral=True)

    @bday.command(name="messages_set", description=f"{_CROWN} Sostituisce la lista messaggi (una riga = un messaggio)")
    @perm("admin")
    @app_commands.describe(messaggi="Lista messaggi, separati da invio")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def bday_messages_set(self, inter: discord.Interaction, messaggi: str):
        lines = [x.strip() for x in messaggi.splitlines() if x.strip()]
        saved = set_wish_messages(inter.guild_id, lines)
        await inter.response.send_message(
            embed=self._ok(f"✅ Lista messaggi aggiornata: **{len(saved)}** voci."),
            ephemeral=True,
        )

    @bday.command(name="messages_add", description=f"{_CROWN} Aggiunge un messaggio alla lista")
    @perm("admin")
    @app_commands.describe(messaggio="Messaggio plain text")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def bday_messages_add(self, inter: discord.Interaction, messaggio: str):
        total = add_wish_message(inter.guild_id, messaggio)
        await inter.response.send_message(
            embed=self._ok(f"✅ Messaggio aggiunto. Totale: **{total}**."),
            ephemeral=True,
        )

    @bday.command(name="messages_remove", description=f"{_CROWN} Rimuove un messaggio dalla lista per indice")
    @perm("admin")
    @app_commands.describe(indice="Indice 1-based visibile in /bday messages_list")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def bday_messages_remove(self, inter: discord.Interaction, indice: app_commands.Range[int, 1, 200]):
        removed = remove_wish_message(inter.guild_id, indice)
        if removed is None:
            return await inter.response.send_message(
                embed=self._err("Indice non valido."),
                ephemeral=True,
            )
        await inter.response.send_message(
            embed=self._ok(f"🗑️ Messaggio rimosso: `{removed[:_MAX_REMOVED_PREVIEW]}`"),
            ephemeral=True,
        )

    @bday.command(name="messages_list", description=f"{_CROWN} Mostra la lista messaggi compleanno")
    @perm("admin")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def bday_messages_list(self, inter: discord.Interaction):
        messages = get_wish_messages(inter.guild_id)
        if not messages:
            return await inter.response.send_message(
                embed=self._err("Nessun messaggio configurato. Usa `/bday messages_set` o `/bday messages_add`."),
                ephemeral=True,
            )
        lines = [f"**{i}.** {m}" for i, m in enumerate(messages, start=1)]
        embed = discord.Embed(
            title=f"🎂 Messaggi compleanno ({len(messages)})",
            description="\n".join(lines)[:4000],
            color=0x5865F2,
        )
        await inter.response.send_message(embed=embed, ephemeral=True)

    @bday.command(name="test", description=f"{_CROWN} Simula un messaggio di auguri (anteprima plain text)")
    @perm("admin")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def bday_test(self, inter: discord.Interaction):
        entry = get_birthday(inter.guild_id, inter.user.id)
        age: Optional[int] = None
        if entry and entry.get("year"):
            age = datetime.now(_BIRTHDAY_TIMEZONE).year - entry["year"]
        wish = _pick_wish(inter.user, age, get_wish_messages(inter.guild_id))
        await inter.response.send_message(
            content=f"*(anteprima — solo tu la vedi)*\n{wish}",
            ephemeral=True,
        )

    @bday_adminset.error
    @bday_adminremove.error
    @bday_channel.error
    @bday_tags.error
    @bday_messages_set.error
    @bday_messages_add.error
    @bday_messages_remove.error
    @bday_messages_list.error
    @bday_test.error
    async def _admin_error(self, inter: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await inter.response.send_message(
                embed=self._err("Serve il permesso **Gestisci server** per usare questo comando."),
                ephemeral=True,
            )

    @staticmethod
    def _ok(msg: str) -> discord.Embed:
        return discord.Embed(description=msg, color=0x57F287)

    @staticmethod
    def _err(msg: str) -> discord.Embed:
        return discord.Embed(description=f"❌ {msg}", color=0xe74c3c)


async def setup(bot: commands.Bot):
    await bot.add_cog(Birthdays(bot))
