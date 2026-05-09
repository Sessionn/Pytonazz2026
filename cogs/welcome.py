"""Sistema Welcome / Goodbye + AutoRole — rimpiazzo di MEE6.

Gruppo /welcome  (👑 tutti i sotto-comandi richiedono manage_guild):
  /welcome channel  <#canale>
  /welcome toggle
  /welcome set
  /welcome field remove <indice>
  /welcome field list
  /welcome reset
  /welcome preview
  /welcome status

Gruppo /goodbye  (👑 idem):
  Stessi sotto-comandi + parametro plain_text in /goodbye set.
  Se plain_text=True invia un messaggio semplice invece dell'embed.

Nota: /welcome set ha lo stesso parametro plain_text di /goodbye set.

Comandi standalone (👑 manage_guild):
  /tags
  /autorole set
  /autorole remove
  /autorole status

── Gestione immagini ────────────────────────────────────────────────────────
Gli upload via attachment Discord vengono scaricati su disco immediatamente
(prima che l'URL ephemeral scada, ~1-2h) in:

  data/welcome_images/<guild_id>_<event>_<slot>.<ext>

Slot disponibili: image, thumbnail, footer_icon, author_icon
Il nome file è fisso per guild+event+slot → sovrascrittura automatica,
zero duplicati, zero accumulo.

Nel JSON viene salvato un sentinel "__local:<slot>__" invece dell'URL.
Al join, _build_embed_and_files() legge il file da disco e lo allega
come discord.File con embed.set_image(url="attachment://<filename>").

Gli URL esterni (non upload) continuano a funzionare invariati.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from core.welcome_store import (
    get_config, set_field, reset_config,
    add_embed_field, remove_embed_field,
    get_auto_role, set_auto_role,
)
from core.log_colors import tag, b, user
from core.paths import WELCOME_IMAGES_DIR

log = logging.getLogger("pitonazz.welcome")

_CROWN      = "👑"
_NONE_WORDS = {"none", "nessuno", "nessuna", "-", ""}
_MAX_FIELDS = 25

# Directory dove vengono salvate le immagini locali
_IMG_DIR = WELCOME_IMAGES_DIR

_TAGS_EMBED = (
    discord.Embed(
        title="🏷️ Placeholder & Markdown — welcome/goodbye",
        description=(
            "Usabili in **title**, **description**, **footer**, **author name** "
            "e nei **field name/value** di `/welcome set` e `/goodbye set`."
        ),
        color=0x5865F2,
    )
    .add_field(
        name="Utente",
        value=(
            "`{mention}` — @menzione cliccabile\n"
            "`{name}` — username puro (es. *mario*)\n"
            "`{display_name}` — nickname sul server"
        ),
        inline=True,
    )
    .add_field(
        name="Server",
        value=(
            "`{guild}` — nome del server\n"
            "`{count}` — n\u00b0 membri attuali"
        ),
        inline=True,
    )
    .add_field(
        name="Markdown Discord",
        value=(
            "`**testo**` \u2192 **grassetto**\n"
            "`*testo*` \u2192 *corsivo*\n"
            "`__testo__` \u2192 sottolineato\n"
            "`~~testo~~` \u2192 ~~barrato~~"
        ),
        inline=False,
    )
    .add_field(
        name="Esempio",
        value="`\U0001f91d {mention} benvenuto/a in **{guild}**! Siamo in {count}.`",
        inline=False,
    )
    .set_footer(text="Usabile anche nei field name/value di /welcome set e /goodbye set")
)

_CHECK = "\u2705"
_CROSS = "\u274c"

# Slot immagine riconosciuti nell'embed
_IMAGE_SLOTS = ("image", "thumbnail", "footer_icon", "author_icon")


def _event_toggle_embed(event: str, enabled: bool) -> discord.Embed:
    label = "Benvenuto" if event == "welcome" else "Addio"
    state = "🟢 ON" if enabled else "🔴 OFF"
    return _ok(f"{label}: **{state}**")


class _EventToggleSelect(discord.ui.Select):
    def __init__(self, guild_id: int, event: str, owner_id: int):
        self._guild_id = guild_id
        self._event = event
        self._owner_id = owner_id
        enabled = bool(get_config(guild_id, event).get("enabled", True))
        options = [
            discord.SelectOption(label="🟢 ON", value="on", default=enabled),
            discord.SelectOption(label="🔴 OFF", value="off", default=not enabled),
        ]
        super().__init__(
            placeholder=f"Seleziona stato {event}",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, inter: discord.Interaction):
        if inter.user.id != self._owner_id:
            return await inter.response.send_message(
                "Solo chi ha aperto questo menu può modificarlo.",
                ephemeral=True,
            )
        enabled = self.values[0] == "on"
        set_field(self._guild_id, self._event, "enabled", enabled)
        await inter.response.edit_message(
            embed=_event_toggle_embed(self._event, enabled),
            view=_EventToggleView(self._guild_id, self._event, self._owner_id),
        )


class _EventToggleView(discord.ui.View):
    def __init__(self, guild_id: int, event: str, owner_id: int):
        super().__init__(timeout=180)
        self.add_item(_EventToggleSelect(guild_id, event, owner_id))


# ── image storage helpers ──────────────────────────────────────────────────────

def _local_key(slot: str) -> str:
    """Sentinel salvato nel JSON per indicare un'immagine locale."""
    return f"__local:{slot}__"


def _is_local(value: str | None) -> str | None:
    """Se value è un sentinel locale, ritorna lo slot; altrimenti None."""
    if value and value.startswith("__local:") and value.endswith("__"):
        return value[8:-2]
    return None


def _local_path(guild_id: int, event: str, slot: str, ext: str = "png") -> Path:
    return _IMG_DIR / f"{guild_id}_{event}_{slot}.{ext}"


def _find_local_file(guild_id: int, event: str, slot: str) -> Path | None:
    """Cerca il file salvato per qualsiasi estensione."""
    for ext in ("png", "jpg", "jpeg", "gif", "webp"):
        p = _local_path(guild_id, event, slot, ext)
        if p.exists():
            return p
    return None


def _delete_local_image(guild_id: int, event: str, slot: str) -> None:
    """Elimina dal disco l'immagine locale per questo guild+event+slot."""
    p = _find_local_file(guild_id, event, slot)
    if p:
        try:
            p.unlink()
            log.debug(tag("WEL", f"deleted local image {p.name}"))
        except Exception as e:
            log.warning(tag("WEL", f"failed to delete {p}: {e}"))


async def _save_local_image(
    guild_id: int,
    event: str,
    slot: str,
    attachment: discord.Attachment,
) -> tuple[str | None, str | None]:
    """
    Scarica l'attachment su disco in data/welcome_images/.
    Ritorna (sentinel_key, None) oppure (None, messaggio_errore).
    """
    if not attachment.content_type or not attachment.content_type.startswith("image/"):
        return None, f"{_CROSS} Il file allegato non è un'immagine."

    # estensione dal content_type (image/png → png)
    ext = attachment.content_type.split("/")[-1].split(";")[0].strip()
    if ext not in ("png", "jpg", "jpeg", "gif", "webp"):
        ext = "png"

    # cancella eventuale vecchio file con estensione diversa
    _delete_local_image(guild_id, event, slot)

    dest = _local_path(guild_id, event, slot, ext)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(attachment.url) as resp:
                if resp.status != 200:
                    return None, f"{_CROSS} Download immagine fallito (HTTP {resp.status})."
                dest.write_bytes(await resp.read())
        log.debug(tag("WEL", f"saved local image {dest.name} ({dest.stat().st_size // 1024} KB)"))
        return _local_key(slot), None
    except Exception as e:
        return None, f"{_CROSS} Errore nel salvataggio immagine: `{e}`"


# ── helpers ────────────────────────────────────────────────────────────────────────

def _resolve(text: Optional[str], member: discord.Member | discord.User) -> Optional[str]:
    if text is None:
        return None
    guild = getattr(member, "guild", None)
    mapping = {
        "mention": member.mention,
        "name": member.name,
        "display_name": member.display_name,
        "guild": guild.name if guild else "Server",
        "count": guild.member_count if guild else 0,
    }
    try:
        return text.format_map(_SafeFormatMap(mapping))
    except Exception as e:
        log.warning(tag("WEL", f"placeholder format error: {e}"))
        return text


class _SafeFormatMap(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def _build_embed_and_files(
    cfg: dict,
    member: discord.Member | discord.User,
    guild_id: int,
    event: str,
) -> tuple[discord.Embed, list[discord.File]]:
    """
    Costruisce l'embed e la lista di discord.File per le immagini locali.
    Le immagini locali vengono allegate come file e referenziate con
    attachment://<filename> nell'embed.
    """
    files: list[discord.File] = []

    def _resolve_url(field: str, attach_method) -> str | None:
        """
        Risolve un campo URL: se è un sentinel locale apre il file da disco;
        altrimenti usa il valore direttamente come URL remoto.
        """
        val = cfg.get(field)
        if not val:
            return None
        slot = _is_local(val)
        if slot:
            path = _find_local_file(guild_id, event, slot)
            if path:
                f = discord.File(str(path), filename=path.name)
                files.append(f)
                return f"attachment://{path.name}"
            # file locale mancante (es. dopo un reset manuale del disco)
            log.warning(tag("WEL", f"local image missing: {guild_id}/{event}/{slot}"))
            return None
        return val  # URL esterno, usato direttamente

    embed = discord.Embed(
        title=_resolve(cfg.get("title"), member),
        description=_resolve(cfg.get("description"), member),
        color=cfg.get("color", 0x5865F2),
    )

    if cfg.get("footer"):
        footer_icon = _resolve_url("footer_icon_url", None)
        embed.set_footer(text=_resolve(cfg["footer"], member), icon_url=footer_icon)

    thumb_url = _resolve_url("thumbnail_url", None)
    if thumb_url:
        embed.set_thumbnail(url=thumb_url)

    img_url = _resolve_url("image_url", None)
    if img_url:
        embed.set_image(url=img_url)

    if cfg.get("author_name"):
        # FIX: usa None invece di discord.utils.MISSING quando non c'è icon_url.
        # MISSING veniva serializzato come stringa non valida nel payload Discord
        # causando: 400 Bad Request — embeds.0.author.icon_url: Not a well formed URL.
        author_icon = _resolve_url("author_icon_url", None)
        embed.set_author(name=_resolve(cfg["author_name"], member), icon_url=author_icon)

    for f in cfg.get("fields", []):
        embed.add_field(
            name=_resolve(f.get("name", "\u200b"), member),
            value=_resolve(f.get("value", "\u200b"), member),
            inline=f.get("inline", False),
        )

    return embed, files


def _cfg_summary(cfg: dict, event: str) -> discord.Embed:
    fields_text = (
        "\n".join(
            f"**{i+1}.** `{f['name']}` \u2014 {f['value'][:50]}{'...' if len(f['value']) > 50 else ''}"
            + (" *(inline)*" if f.get("inline") else "")
            for i, f in enumerate(cfg.get("fields", []))
        ) or "*nessuno*"
    )
    enabled     = cfg.get("enabled", True)
    abilitato   = _CHECK if enabled else _CROSS
    icon        = "\U0001f7e2" if enabled else "\U0001f534"
    ch_id       = cfg.get("channel_id")
    canale_line = f"**Canale:** <#{ch_id}>" if ch_id else "**Canale:** *non impostato*"
    plain_text  = cfg.get("plain_text", False)
    modo_line   = "**Modo:** messaggio semplice (plain text)" if plain_text else "**Modo:** embed"

    def _display_url(val: str | None) -> str:
        if not val:
            return "*nessuna*"
        slot = _is_local(val)
        return f"*locale ({slot})*" if slot else val

    lines = [
        canale_line,
        f"**Abilitato:** {abilitato}",
        modo_line,
        f"**Titolo:** {cfg.get('title') or '*vuoto*'}",
        f"**Descrizione:** {(cfg.get('description') or '')[:80] or '*vuota*'}",
        f"**Footer:** {cfg.get('footer') or '*nessuno*'}",
        f"**Footer icon:** {_display_url(cfg.get('footer_icon_url'))}",
        f"**Colore:** `#{cfg.get('color', 0):06X}`",
        f"**Thumbnail:** {_display_url(cfg.get('thumbnail_url'))}",
        f"**Immagine:** {_display_url(cfg.get('image_url'))}",
        f"**Author:** {cfg.get('author_name') or '*nessuno*'}",
        f"**Author icon:** {_display_url(cfg.get('author_icon_url'))}",
        f"**Fields ({len(cfg.get('fields', []))}):**\n{fields_text}",
    ]
    return discord.Embed(
        title=f"{icon} Config {event.capitalize()}",
        description="\n".join(lines),
        color=0x5865F2,
    )


def _parse_color(s: str) -> Optional[int]:
    s = s.strip().lstrip("#")
    if len(s) != 6:
        return None
    try:
        return int(s, 16)
    except ValueError:
        return None


def _is_none(v: Optional[str]) -> bool:
    return v is not None and v.strip().lower() in _NONE_WORDS


async def _resolve_image(
    guild_id: int,
    event: str,
    slot: str,
    url: Optional[str],
    upload: Optional[discord.Attachment],
) -> tuple[str | None, str | None]:
    """
    Risolve url/upload per uno slot immagine.

    Priorità: upload > url.
    - upload  → scarica su disco, ritorna (sentinel_key, None)
    - url     → se 'none'/'-'/'' ritorna ('__REMOVE__', None)
              → altrimenti ritorna (url_esterno, None)
    - nessuno → (None, None)
    """
    if upload is not None:
        return await _save_local_image(guild_id, event, slot, upload)
    if url is not None:
        if _is_none(url):
            return "__REMOVE__", None
        return url.strip(), None
    return None, None


def _ok(msg: str)  -> discord.Embed: return discord.Embed(description=msg, color=0x57F287)
def _err(msg: str) -> discord.Embed: return discord.Embed(description=f"{_CROSS} {msg}", color=0xED4245)


# ── Cog ─────────────────────────────────────────────────────────────────────────

class Welcome(commands.Cog):
    COG_ICON  = "👋"
    COG_LABEL = "Benvenuto & Addio"
    COG_TYPE  = "admin"

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── Listeners ────────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        role_id = get_auto_role(member.guild.id)
        if role_id:
            role = member.guild.get_role(role_id)
            if role:
                try:
                    await member.add_roles(role, reason="AutoRole")
                    log.info(tag("WEL", f"autorole  {user(str(member))}  +{b(role.name)}"))
                except discord.Forbidden:
                    log.warning(tag("WEL", f"autorole permesso mancante per {role.name}"))
                except Exception as e:
                    log.error(tag("WEL", f"autorole error: {e}"))
        await self._send_event(member, "welcome")

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        await self._send_event(member, "goodbye")

    async def _send_event(self, member: discord.Member, event: str):
        cfg = get_config(member.guild.id, event)
        if not cfg.get("enabled", True):
            return
        ch_id = cfg.get("channel_id")
        if not ch_id:
            log.debug(tag("WEL", f"{event}: nessun canale impostato per [{member.guild.name}]"))
            return

        channel = member.guild.get_channel(ch_id)
        if not channel:
            try:
                channel = await member.guild.fetch_channel(ch_id)
            except Exception as e:
                log.warning(tag("WEL", f"{event}: canale {ch_id} non trovato [{member.guild.name}] — {e}"))
                return

        try:
            if cfg.get("plain_text", False):
                text = _resolve(cfg.get("description"), member)
                fallback_by_event = {
                    "welcome": f"**{member.display_name}** si è unito al server.",
                    "goodbye": f"**{member.display_name}** ha lasciato il server.",
                }
                fallback = fallback_by_event.get(event, f"**{member.display_name}** evento: {event}")
                await channel.send(content=text or fallback)
            else:
                embed, files = _build_embed_and_files(cfg, member, member.guild.id, event)
                await channel.send(embed=embed, files=files)
            log.info(tag("WEL", f"{event}  {user(str(member))}  [{b(member.guild.name)}]"))
        except Exception as e:
            log.error(tag("WEL", f"_send_event({event}) error: {e}"))

    # ──────────────────────────────────────────────────────────────
    # /tags
    # ──────────────────────────────────────────────────────────────

    @app_commands.command(
        name="tags",
        description=f"{_CROWN} Placeholder e markdown per i messaggi welcome/goodbye",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def cmd_tags(self, inter: discord.Interaction):
        await inter.response.send_message(embed=_TAGS_EMBED, ephemeral=True)

    # ──────────────────────────────────────────────────────────────
    # /welcome
    # ──────────────────────────────────────────────────────────────

    welcome   = app_commands.Group(name="welcome", description=f"{_CROWN} Messaggi di benvenuto")
    wel_field = app_commands.Group(name="field",   description=f"{_CROWN} Gestisci i field dell'embed", parent=welcome)

    @welcome.command(name="channel", description=f"{_CROWN} Imposta il canale di benvenuto")
    @app_commands.describe(canale="Canale di destinazione")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def welcome_channel(self, inter: discord.Interaction, canale: discord.TextChannel):
        set_field(inter.guild_id, "welcome", "channel_id", canale.id)
        await inter.response.send_message(embed=_ok(f"{_CHECK} Canale benvenuto: {canale.mention}"), ephemeral=True)

    @welcome.command(name="toggle", description=f"{_CROWN} Abilita o disabilita il benvenuto")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def welcome_toggle(self, inter: discord.Interaction):
        enabled = bool(get_config(inter.guild_id, "welcome").get("enabled", True))
        await inter.response.send_message(
            embed=_event_toggle_embed("welcome", enabled),
            view=_EventToggleView(inter.guild_id, "welcome", inter.user.id),
            ephemeral=True,
        )

    @welcome.command(name="set", description=f"{_CROWN} Modifica il messaggio di benvenuto")
    @app_commands.describe(
        plain_text          = "True = messaggio semplice, False = embed (default)",
        title               = "Titolo (solo embed)",
        description         = "Testo principale (placeholder → /tags)",
        footer              = "Footer ('none' per rimuovere, solo embed)",
        footer_icon_url     = "URL icona footer ('none' per rimuovere, solo embed)",
        footer_icon_upload  = "Carica icona footer come immagine (solo embed)",
        color               = "Colore bordo in HEX, es. #FF0000 (solo embed)",
        thumbnail_url       = "URL thumbnail ('none' per rimuovere, solo embed)",
        thumbnail_upload    = "Carica thumbnail come immagine (solo embed)",
        image_url           = "URL immagine grande ('none' per rimuovere, solo embed)",
        image_upload        = "Carica immagine grande direttamente (solo embed)",
        author_name         = "Nome author ('none' per rimuovere, solo embed)",
        author_icon_url     = "URL icona author (solo embed)",
        author_icon_upload  = "Carica icona author come immagine (solo embed)",
        field1_name         = "Field 1 — nome",
        field1_value        = "Field 1 — valore",
        field2_name         = "Field 2 — nome",
        field2_value        = "Field 2 — valore",
        field3_name         = "Field 3 — nome",
        field3_value        = "Field 3 — valore",
        field4_name         = "Field 4 — nome",
        field4_value        = "Field 4 — valore",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def welcome_set(
        self, inter: discord.Interaction,
        plain_text:         Optional[bool]               = None,
        title:              Optional[str]                = None,
        description:        Optional[str]                = None,
        footer:             Optional[str]                = None,
        footer_icon_url:    Optional[str]                = None,
        footer_icon_upload: Optional[discord.Attachment] = None,
        color:              Optional[str]                = None,
        thumbnail_url:      Optional[str]                = None,
        thumbnail_upload:   Optional[discord.Attachment] = None,
        image_url:          Optional[str]                = None,
        image_upload:       Optional[discord.Attachment] = None,
        author_name:        Optional[str]                = None,
        author_icon_url:    Optional[str]                = None,
        author_icon_upload: Optional[discord.Attachment] = None,
        field1_name:        Optional[str]                = None,
        field1_value:       Optional[str]                = None,
        field2_name:        Optional[str]                = None,
        field2_value:       Optional[str]                = None,
        field3_name:        Optional[str]                = None,
        field3_value:       Optional[str]                = None,
        field4_name:        Optional[str]                = None,
        field4_value:       Optional[str]                = None,
    ):
        changed_extra: list[str] = []
        if plain_text is not None:
            set_field(inter.guild_id, "welcome", "plain_text", plain_text)
            modo = "messaggio semplice" if plain_text else "embed"
            changed_extra.append(f"**Modo** \u2192 {modo}")

        raw_fields = [
            (field1_name, field1_value),
            (field2_name, field2_value),
            (field3_name, field3_value),
            (field4_name, field4_value),
        ]
        await self._apply_set(
            inter, "welcome",
            title, description, footer,
            footer_icon_url, footer_icon_upload,
            color,
            thumbnail_url, thumbnail_upload,
            image_url, image_upload,
            author_name, author_icon_url, author_icon_upload,
            raw_fields,
            extra_changed=changed_extra,
        )

    @wel_field.command(name="remove", description=f"{_CROWN} Rimuovi un field dall'embed")
    @app_commands.describe(indice="Numero del field (vedi /welcome field list)")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def welcome_field_remove(self, inter: discord.Interaction, indice: int):
        await self._remove_field(inter, "welcome", indice)

    @wel_field.command(name="list", description=f"{_CROWN} Elenca i field dell'embed")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def welcome_field_list(self, inter: discord.Interaction):
        await self._list_fields(inter, "welcome")

    @welcome.command(name="reset", description=f"{_CROWN} Ripristina la configurazione ai valori predefiniti")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def welcome_reset(self, inter: discord.Interaction):
        for slot in _IMAGE_SLOTS:
            _delete_local_image(inter.guild_id, "welcome", slot)
        reset_config(inter.guild_id, "welcome")
        await inter.response.send_message(embed=_ok("\U0001f504 Config benvenuto ripristinata."), ephemeral=True)

    @welcome.command(name="preview", description=f"{_CROWN} Mostra un'anteprima del messaggio")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def welcome_preview(self, inter: discord.Interaction):
        await self._preview(inter, "welcome")

    @welcome.command(name="status", description=f"{_CROWN} Mostra la configurazione attuale")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def welcome_status(self, inter: discord.Interaction):
        await inter.response.send_message(
            embed=_cfg_summary(get_config(inter.guild_id, "welcome"), "welcome"), ephemeral=True
        )

    # ──────────────────────────────────────────────────────────────
    # /goodbye
    # ──────────────────────────────────────────────────────────────

    goodbye   = app_commands.Group(name="goodbye", description=f"{_CROWN} Messaggi di addio")
    bye_field = app_commands.Group(name="field",   description=f"{_CROWN} Gestisci i field dell'embed", parent=goodbye)

    @goodbye.command(name="channel", description=f"{_CROWN} Imposta il canale dei messaggi di addio")
    @app_commands.describe(canale="Canale di destinazione")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def goodbye_channel(self, inter: discord.Interaction, canale: discord.TextChannel):
        set_field(inter.guild_id, "goodbye", "channel_id", canale.id)
        await inter.response.send_message(embed=_ok(f"{_CHECK} Canale addio: {canale.mention}"), ephemeral=True)

    @goodbye.command(name="toggle", description=f"{_CROWN} Abilita o disabilita il messaggio di addio")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def goodbye_toggle(self, inter: discord.Interaction):
        enabled = bool(get_config(inter.guild_id, "goodbye").get("enabled", True))
        await inter.response.send_message(
            embed=_event_toggle_embed("goodbye", enabled),
            view=_EventToggleView(inter.guild_id, "goodbye", inter.user.id),
            ephemeral=True,
        )

    @goodbye.command(name="set", description=f"{_CROWN} Modifica il messaggio di addio")
    @app_commands.describe(
        plain_text          = "True = messaggio semplice, False = embed (default)",
        title               = "Titolo (solo embed)",
        description         = "Testo principale (placeholder → /tags)",
        footer              = "Footer ('none' per rimuovere, solo embed)",
        footer_icon_url     = "URL icona footer ('none' per rimuovere, solo embed)",
        footer_icon_upload  = "Carica icona footer come immagine (solo embed)",
        color               = "Colore bordo in HEX, es. #FF0000 (solo embed)",
        thumbnail_url       = "URL thumbnail ('none' per rimuovere, solo embed)",
        thumbnail_upload    = "Carica thumbnail come immagine (solo embed)",
        image_url           = "URL immagine grande ('none' per rimuovere, solo embed)",
        image_upload        = "Carica immagine grande direttamente (solo embed)",
        author_name         = "Nome author ('none' per rimuovere, solo embed)",
        author_icon_url     = "URL icona author (solo embed)",
        author_icon_upload  = "Carica icona author come immagine (solo embed)",
        field1_name         = "Field 1 — nome",
        field1_value        = "Field 1 — valore",
        field2_name         = "Field 2 — nome",
        field2_value        = "Field 2 — valore",
        field3_name         = "Field 3 — nome",
        field3_value        = "Field 3 — valore",
        field4_name         = "Field 4 — nome",
        field4_value        = "Field 4 — valore",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def goodbye_set(
        self, inter: discord.Interaction,
        plain_text:         Optional[bool]               = None,
        title:              Optional[str]                = None,
        description:        Optional[str]                = None,
        footer:             Optional[str]                = None,
        footer_icon_url:    Optional[str]                = None,
        footer_icon_upload: Optional[discord.Attachment] = None,
        color:              Optional[str]                = None,
        thumbnail_url:      Optional[str]                = None,
        thumbnail_upload:   Optional[discord.Attachment] = None,
        image_url:          Optional[str]                = None,
        image_upload:       Optional[discord.Attachment] = None,
        author_name:        Optional[str]                = None,
        author_icon_url:    Optional[str]                = None,
        author_icon_upload: Optional[discord.Attachment] = None,
        field1_name:        Optional[str]                = None,
        field1_value:       Optional[str]                = None,
        field2_name:        Optional[str]                = None,
        field2_value:       Optional[str]                = None,
        field3_name:        Optional[str]                = None,
        field3_value:       Optional[str]                = None,
        field4_name:        Optional[str]                = None,
        field4_value:       Optional[str]                = None,
    ):
        changed_extra: list[str] = []
        if plain_text is not None:
            set_field(inter.guild_id, "goodbye", "plain_text", plain_text)
            modo = "messaggio semplice" if plain_text else "embed"
            changed_extra.append(f"**Modo** \u2192 {modo}")

        raw_fields = [
            (field1_name, field1_value),
            (field2_name, field2_value),
            (field3_name, field3_value),
            (field4_name, field4_value),
        ]
        await self._apply_set(
            inter, "goodbye",
            title, description, footer,
            footer_icon_url, footer_icon_upload,
            color,
            thumbnail_url, thumbnail_upload,
            image_url, image_upload,
            author_name, author_icon_url, author_icon_upload,
            raw_fields,
            extra_changed=changed_extra,
        )

    @bye_field.command(name="remove", description=f"{_CROWN} Rimuovi un field dall'embed")
    @app_commands.describe(indice="Numero del field (vedi /goodbye field list)")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def goodbye_field_remove(self, inter: discord.Interaction, indice: int):
        await self._remove_field(inter, "goodbye", indice)

    @bye_field.command(name="list", description=f"{_CROWN} Elenca i field dell'embed")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def goodbye_field_list(self, inter: discord.Interaction):
        await self._list_fields(inter, "goodbye")

    @goodbye.command(name="reset", description=f"{_CROWN} Ripristina la configurazione ai valori predefiniti")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def goodbye_reset(self, inter: discord.Interaction):
        for slot in _IMAGE_SLOTS:
            _delete_local_image(inter.guild_id, "goodbye", slot)
        reset_config(inter.guild_id, "goodbye")
        await inter.response.send_message(embed=_ok("\U0001f504 Config addio ripristinata."), ephemeral=True)

    @goodbye.command(name="preview", description=f"{_CROWN} Mostra un'anteprima del messaggio")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def goodbye_preview(self, inter: discord.Interaction):
        await self._preview(inter, "goodbye")

    @goodbye.command(name="status", description=f"{_CROWN} Mostra la configurazione attuale")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def goodbye_status(self, inter: discord.Interaction):
        await inter.response.send_message(
            embed=_cfg_summary(get_config(inter.guild_id, "goodbye"), "goodbye"), ephemeral=True
        )

    # ──────────────────────────────────────────────────────────────
    # /autorole
    # ──────────────────────────────────────────────────────────────

    autorole = app_commands.Group(name="autorole", description=f"{_CROWN} Ruolo automatico ai nuovi membri")

    @autorole.command(name="set", description=f"{_CROWN} Imposta il ruolo da assegnare al join")
    @app_commands.describe(ruolo="Ruolo da assegnare")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def autorole_set(self, inter: discord.Interaction, ruolo: discord.Role):
        if ruolo.managed:
            return await inter.response.send_message(
                embed=_err("I ruoli gestiti da integrazioni non possono essere usati."), ephemeral=True
            )
        if ruolo >= inter.guild.me.top_role:
            return await inter.response.send_message(
                embed=_err(f"**{ruolo.name}** \u00e8 pi\u00f9 alto del ruolo del bot nella gerarchia."), ephemeral=True
            )
        set_auto_role(inter.guild_id, ruolo.id)
        log.info(tag("WEL", f"autorole set  {b(ruolo.name)}  [{inter.guild.name}]"))
        await inter.response.send_message(
            embed=_ok(
                f"{_CHECK} AutoRole: **{ruolo.mention}**\n"
                "Ogni nuovo membro ricever\u00e0 questo ruolo al join."
            ),
            ephemeral=True,
        )

    @autorole.command(name="remove", description=f"{_CROWN} Rimuovi il ruolo automatico")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def autorole_remove(self, inter: discord.Interaction):
        if not get_auto_role(inter.guild_id):
            return await inter.response.send_message(embed=_err("Nessun AutoRole configurato."), ephemeral=True)
        set_auto_role(inter.guild_id, None)
        await inter.response.send_message(embed=_ok("\U0001f5d1\ufe0f AutoRole rimosso."), ephemeral=True)

    @autorole.command(name="status", description=f"{_CROWN} Mostra il ruolo automatico attivo")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def autorole_status(self, inter: discord.Interaction):
        role_id = get_auto_role(inter.guild_id)
        if not role_id:
            return await inter.response.send_message(
                embed=discord.Embed(description="\U0001f515 Nessun AutoRole configurato.", color=0x5865F2),
                ephemeral=True,
            )
        role = inter.guild.get_role(role_id)
        name = role.mention if role else f"*(rimosso, id {role_id})*"
        await inter.response.send_message(
            embed=discord.Embed(description=f"{_CHECK} AutoRole attivo: {name}", color=0x57F287),
            ephemeral=True,
        )

    # ── logica condivisa ──────────────────────────────────────────────────────────────

    async def _apply_set(
        self, inter, event,
        title, description, footer,
        footer_icon_url,    footer_icon_upload,
        color,
        thumbnail_url,      thumbnail_upload,
        image_url,          image_upload,
        author_name,        author_icon_url,    author_icon_upload,
        raw_fields: list[tuple[Optional[str], Optional[str]]],
        extra_changed: list[str] | None = None,
    ):
        await inter.response.defer(ephemeral=True)
        changed: list[str] = list(extra_changed or [])
        errors:  list[str] = []

        if title is not None:
            v = None if _is_none(title) else title
            set_field(inter.guild_id, event, "title", v)
            changed.append(f"**Titolo** \u2192 {v or '*rimosso*'}")

        if description is not None:
            v = None if _is_none(description) else description
            set_field(inter.guild_id, event, "description", v)
            changed.append("**Descrizione** aggiornata")

        if footer is not None:
            v = None if _is_none(footer) else footer
            set_field(inter.guild_id, event, "footer", v)
            changed.append(f"**Footer** \u2192 {v or '*rimosso*'}")

        # footer icon: url o upload
        fi_val, fi_err = await _resolve_image(inter.guild_id, event, "footer_icon", footer_icon_url, footer_icon_upload)
        if fi_err:
            errors.append(fi_err)
        elif fi_val == "__REMOVE__":
            _delete_local_image(inter.guild_id, event, "footer_icon")
            set_field(inter.guild_id, event, "footer_icon_url", None)
            changed.append("**Footer icon** rimossa")
        elif fi_val is not None:
            tipo = "(locale)" if footer_icon_upload else "(url)"
            set_field(inter.guild_id, event, "footer_icon_url", fi_val)
            changed.append(f"**Footer icon** aggiornata {tipo}")

        if color is not None:
            c = _parse_color(color)
            if c is None:
                errors.append(f"{_CROSS} Colore non valido (`{color}`). Usa `#RRGGBB`.")
            else:
                set_field(inter.guild_id, event, "color", c)
                changed.append(f"**Colore** \u2192 `#{c:06X}`")

        # thumbnail: url o upload
        th_val, th_err = await _resolve_image(inter.guild_id, event, "thumbnail", thumbnail_url, thumbnail_upload)
        if th_err:
            errors.append(th_err)
        elif th_val == "__REMOVE__":
            _delete_local_image(inter.guild_id, event, "thumbnail")
            set_field(inter.guild_id, event, "thumbnail_url", None)
            changed.append("**Thumbnail** rimossa")
        elif th_val is not None:
            tipo = "(locale)" if thumbnail_upload else "(url)"
            set_field(inter.guild_id, event, "thumbnail_url", th_val)
            changed.append(f"**Thumbnail** aggiornata {tipo}")

        # immagine grande: url o upload
        img_val, img_err = await _resolve_image(inter.guild_id, event, "image", image_url, image_upload)
        if img_err:
            errors.append(img_err)
        elif img_val == "__REMOVE__":
            _delete_local_image(inter.guild_id, event, "image")
            set_field(inter.guild_id, event, "image_url", None)
            changed.append("**Immagine** rimossa")
        elif img_val is not None:
            tipo = "(locale)" if image_upload else "(url)"
            set_field(inter.guild_id, event, "image_url", img_val)
            changed.append(f"**Immagine** aggiornata {tipo}")

        # author name
        if author_name is not None:
            v = None if _is_none(author_name) else author_name
            set_field(inter.guild_id, event, "author_name", v)
            if not v:
                _delete_local_image(inter.guild_id, event, "author_icon")
                set_field(inter.guild_id, event, "author_icon_url", None)
                changed.append("**Author** rimosso")
            else:
                changed.append(f"**Author** \u2192 {v}")

        # author icon: url o upload
        ai_val, ai_err = await _resolve_image(inter.guild_id, event, "author_icon", author_icon_url, author_icon_upload)
        if ai_err:
            errors.append(ai_err)
        elif ai_val == "__REMOVE__":
            _delete_local_image(inter.guild_id, event, "author_icon")
            set_field(inter.guild_id, event, "author_icon_url", None)
            changed.append("**Author icon** rimossa")
        elif ai_val is not None:
            cfg_now = get_config(inter.guild_id, event)
            if cfg_now.get("author_name"):
                tipo = "(locale)" if author_icon_upload else "(url)"
                set_field(inter.guild_id, event, "author_icon_url", ai_val)
                changed.append(f"**Author icon** aggiornata {tipo}")
            else:
                errors.append(f"{_CROSS} **Author icon** ignorata: imposta prima un `author_name`.")

        cfg = get_config(inter.guild_id, event)
        existing = len(cfg.get("fields", []))

        for i, (fname, fvalue) in enumerate(raw_fields, start=1):
            if fname is None and fvalue is None:
                continue
            if fname is None or fvalue is None:
                errors.append(f"{_CROSS} Field {i}: devi specificare sia **nome** che **valore** insieme.")
                continue
            if existing >= _MAX_FIELDS:
                errors.append(f"{_CROSS} Field {i}: limite massimo di {_MAX_FIELDS} fields raggiunto.")
                break
            add_embed_field(inter.guild_id, event, fname, fvalue, inline=False)
            existing += 1
            changed.append(f"**Field {i}** aggiunto: `{fname}` \u2014 {fvalue[:40]}")

        if not changed and not errors:
            return await inter.followup.send(embed=_err("Nessun campo specificato."), ephemeral=True)

        parts = []
        if changed:
            ev_cap = event.capitalize()
            bullet_lines = "\n".join(f"\u2022 {c}" for c in changed)
            parts.append(f"{_CHECK} Modifiche **{ev_cap}**:\n{bullet_lines}")
        if errors:
            parts.append("\n".join(errors))

        log.info(tag("WEL", f"{event} set [{inter.guild.name}] {changed}"))
        await inter.followup.send(
            embed=discord.Embed(
                description="\n".join(parts),
                color=0x57F287 if not errors else 0xFEE75C,
            ),
            ephemeral=True,
        )

    async def _remove_field(self, inter: discord.Interaction, event: str, indice: int):
        removed = remove_embed_field(inter.guild_id, event, indice)
        if removed is None:
            n = len(get_config(inter.guild_id, event).get("fields", []))
            msg = f"Indice non valido. Fields: 1\u2013{n}" if n else "Nessun field da rimuovere."
            return await inter.response.send_message(embed=_err(msg), ephemeral=True)
        await inter.response.send_message(
            embed=_ok(f"\U0001f5d1\ufe0f Field **#{indice}** rimosso: `{removed['name']}`"),
            ephemeral=True,
        )

    async def _list_fields(self, inter: discord.Interaction, event: str):
        fields = get_config(inter.guild_id, event).get("fields", [])
        if not fields:
            return await inter.response.send_message(
                embed=discord.Embed(description=f"Nessun field per **{event}**.", color=0x5865F2),
                ephemeral=True,
            )
        lines = [
            f"**{i+1}.** `{f['name']}` \u2014 {f['value'][:60]}{'...' if len(f['value']) > 60 else ''}"
            + (" *(inline)*" if f.get("inline") else "")
            for i, f in enumerate(fields)
        ]
        await inter.response.send_message(
            embed=discord.Embed(
                title=f"Fields {event.capitalize()} ({len(fields)}/{_MAX_FIELDS})",
                description="\n".join(lines),
                color=0x5865F2,
            ),
            ephemeral=True,
        )

    async def _preview(self, inter: discord.Interaction, event: str):
        cfg = get_config(inter.guild_id, event)
        if not cfg.get("enabled", True):
            ev_cap = event.capitalize()
            return await inter.response.send_message(
                embed=_err(f"{ev_cap} disabilitato \u2014 usa `/{event} toggle`."),
                ephemeral=True,
            )
        if cfg.get("plain_text", False):
            text = _resolve(cfg.get("description"), inter.user)
            await inter.response.send_message(
                content=f"*\U0001f441\ufe0f Anteprima **{event}** (plain text) \u2014 solo tu la vedi*\n\n{text or '*(nessun testo)*'}",
                ephemeral=True,
            )
        else:
            embed, files = _build_embed_and_files(cfg, inter.user, inter.guild_id, event)
            await inter.response.send_message(
                content=f"*\U0001f441\ufe0f Anteprima **{event}** \u2014 solo tu la vedi*",
                embed=embed,
                files=files,
                ephemeral=True,
            )

    # ── error handler ─────────────────────────────────────────────────────────────

    async def cog_app_command_error(self, inter: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            if not inter.response.is_done():
                await inter.response.send_message(
                    embed=_err("Serve **Gestisci server** per usare questo comando."), ephemeral=True
                )
        else:
            log.error(tag("WEL", f"command error \u2192 {error}"))
            if not inter.response.is_done():
                await inter.response.send_message(embed=_err(f"Errore: `{error}`"), ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Welcome(bot))
