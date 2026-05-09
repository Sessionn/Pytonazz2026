import discord
from discord import app_commands
from discord.ext import commands
from typing import Optional

from config import Config
from core.constants import command_slug
from core.permissions import owner_check, dev_check, perm

PAGE_SIZE = 10

_PRIORITY = ["music", "fun", "birthdays", "welcome", "tts", "moderation", "roles", "quote", "filters"]

# Sottocomandi da nascondere nell'help (formato: qualified_name con spazi, come Discord)
_HIDDEN_CMDS = {
    "welcome field_remove",
    "welcome field_list",
    "goodbye field_remove",
    "goodbye field_list",
}

_PERM_BADGES = {
    "public": ("Tutti gli utenti", 0x5865F2),
    "admin":  ("❔ Richiede **Gestisci server**", 0xE67E22),
    "dev":    ("🔧 Solo **dev bot**", 0x2F3136),
    "owner":  ("👑 Solo **owner bot**", 0x2F3136),
}
_DESC_PREFIX_MARKERS = ("❔", "🔧", "👑")

_BLANK = "\u200b"  # zero-width space

FIELD_MAX = 1024   # limite Discord per field.value
DESC_MAX  = 4096   # limite Discord per embed.description

def _trunc(text: str, limit: int = FIELD_MAX) -> str:
    """Tronca una stringa al limite imposto da Discord, aggiungendo '…' se necessario."""
    if len(text) <= limit:
        return text
    return text[:limit - 1] + "…"

def _clean_desc(text: str) -> str:
    out = text or ""
    for marker in _DESC_PREFIX_MARKERS:
        if out.startswith(marker):
            out = out[len(marker):].strip()
    return out

# ── Helpers identità ───────────────────────────────────────────────────────────────────
def _is_dev(user_id: int) -> bool:
    dev_ids = Config.DEV_IDS
    if not dev_ids:
        return False
    return user_id in dev_ids

def _is_admin(inter: discord.Interaction) -> bool:
    if inter.guild is None:
        return False
    return inter.permissions.manage_guild or inter.permissions.administrator

# ── Helpers cog ──────────────────────────────────────────────────────────────────────────
def _cog_key(cmd) -> Optional[str]:
    if hasattr(cmd, "binding") and cmd.binding:
        return type(cmd.binding).__name__.lower()
    return None

def _get_cog_meta(bot: commands.Bot, key: str) -> tuple[str, str]:
    for cog in bot.cogs.values():
        if type(cog).__name__.lower() == key:
            icon  = getattr(type(cog), "COG_ICON",  "⚙️")
            label = getattr(type(cog), "COG_LABEL", key.capitalize())
            return icon, label
    return "⚙️", key.capitalize()

def _get_cog_type(bot: commands.Bot, key: str) -> str:
    """Ritorna il COG_TYPE della classe cog (fallback: 'public')."""
    for cog in bot.cogs.values():
        if type(cog).__name__.lower() == key:
            return getattr(type(cog), "COG_TYPE", "public")
    return "public"

def _cmd_perm(cmd) -> str:
    """
    Legge il flag di visibilità per-comando.

    Priorità:
    1. `_cmd_perm` sulla callback della funzione (set da @perm(...))
    2. `COG_TYPE` del cog a cui appartiene il comando
    3. 'public' come default assoluto

    In questo modo @perm("admin") su un singolo comando batte
    il COG_TYPE del cog, permettendo cog 'public' con comandi
    admin al loro interno.
    """
    cb = getattr(cmd, "callback", None)
    if cb and hasattr(cb, "_cmd_perm"):
        return cb._cmd_perm
    # fallback: usa il COG_TYPE (letto direttamente dal binding, non dal bot)
    binding = getattr(cmd, "binding", None)
    if binding:
        return getattr(type(binding), "COG_TYPE", "public")
    return "public"

def _cmd_full_name(cmd) -> str:
    """Ritorna il nome completo con spazi, identico a come Discord lo mostra."""
    return getattr(cmd, "qualified_name", cmd.name)

def _is_hidden(cmd) -> bool:
    return _cmd_full_name(cmd) in _HIDDEN_CMDS

# ── Raccolta comandi ────────────────────────────────────────────────────────────────────────────────────
def _visible_for(cmd_perm_level: str, is_dev: bool, is_admin: bool) -> bool:
    if cmd_perm_level in ("dev", "owner"):
        return is_dev
    if cmd_perm_level == "admin":
        return is_admin or is_dev
    return True  # "public"

def _iter_leaf_commands(bot: commands.Bot):
    """Genera tutti i comandi foglia (non ContextMenu) dall'albero."""
    def walk(cmd):
        if isinstance(cmd, app_commands.ContextMenu):
            return
        if isinstance(cmd, app_commands.Command):
            yield cmd
            return
        if isinstance(cmd, app_commands.Group):
            for sub in cmd.commands:
                yield from walk(sub)

    for cmd in bot.tree.get_commands():
        yield from walk(cmd)

def _collect_groups(
    bot: commands.Bot,
    include_dev: bool,
    is_dev: bool,
    is_admin: bool,
) -> dict[str, list]:
    groups: dict[str, list] = {}
    for cmd in _iter_leaf_commands(bot):
        if _is_hidden(cmd):
            continue
        key = _cog_key(cmd)
        if key is None:
            continue
        level = _cmd_perm(cmd)
        cmd_is_dev = level in ("dev", "owner")
        if cmd_is_dev != include_dev:
            continue
        if not _visible_for(level, is_dev, is_admin):
            continue
        groups.setdefault(key, []).append(cmd)
    return groups

def _all_commands_flat(bot: commands.Bot, is_dev: bool, is_admin: bool) -> list:
    result = []
    for cmd in _iter_leaf_commands(bot):
        if _is_hidden(cmd):
            continue
        key = _cog_key(cmd)
        if key is None:
            continue
        level = _cmd_perm(cmd)
        if not _visible_for(level, is_dev, is_admin):
            continue
        result.append(cmd)
    return result

# ── Embed singolo comando ─────────────────────────────────────────────────────────────────────────
def _build_command_embed(cmd, bot: commands.Bot) -> discord.Embed:
    full_name  = _cmd_full_name(cmd)
    cog_key    = _cog_key(cmd)
    icon, category = _get_cog_meta(bot, cog_key) if cog_key else ("⚙️", "Altro")
    clean_desc = _clean_desc(cmd.description or "Nessuna descrizione disponibile.")
    level      = _cmd_perm(cmd)
    perm_badge, perm_color = _PERM_BADGES.get(level, _PERM_BADGES["public"])

    embed = discord.Embed(
        title=f"`/{full_name}`",
        description=_trunc(f"> {clean_desc}", DESC_MAX),
        color=perm_color,
    )
    embed.add_field(name="📂 Categoria",  value=f"{icon} {category}", inline=True)
    embed.add_field(name="🔐 Permessi",   value=perm_badge,           inline=True)
    embed.add_field(name=_BLANK, value=_BLANK, inline=False)

    params = [
        p for p in cmd.parameters
        if p.name not in ("interaction",)
    ] if hasattr(cmd, "parameters") else []

    if params:
        param_lines = []
        for p in params:
            opt_tag = " *(opzionale)*" if not p.required else ""
            desc_p  = p.description or "—"
            param_lines.append(f"`{p.name}`{opt_tag} — {desc_p}")
        embed.add_field(
            name="📝 Parametri",
            value=_trunc("\n".join(param_lines)),
            inline=False,
        )

    usage_parts = [f"/{full_name}"]
    for p in params:
        usage_parts.append(f"<{p.name}>" if p.required else f"[{p.name}]")
    embed.add_field(
        name="⌨️ Utilizzo",
        value=_trunc(f"`{' '.join(usage_parts)}`"),
        inline=False,
    )
    embed.set_footer(text=" [opzionale]")
    return embed

# ── Pagine per categoria ──────────────────────────────────────────────────────────────────────────────────
def _build_pages_for_category(
    key: str, cmds: list, include_dev: bool, bot: commands.Bot
) -> list[discord.Embed]:
    icon, label = _get_cog_meta(bot, key)
    color = 0x2f3136 if include_dev else 0x5865F2
    sorted_cmds = sorted(cmds, key=lambda c: c.name)
    pages = []

    for chunk_start in range(0, len(sorted_cmds), PAGE_SIZE):
        chunk = sorted_cmds[chunk_start : chunk_start + PAGE_SIZE]
        embed = discord.Embed(title=f"{icon} {label}", color=color)
        for cmd in chunk:
            desc = _clean_desc(cmd.description or "Nessuna descrizione.")
            embed.add_field(
                name=_trunc(f"`/{_cmd_full_name(cmd)}`", 256),
                value=_trunc(desc),
                inline=False,
            )
        pages.append(embed)

    return pages

def _build_all_pages(
    bot: commands.Bot,
    include_dev: bool,
    is_dev: bool,
    is_admin: bool,
) -> dict[str, list[discord.Embed]]:
    groups = _collect_groups(bot, include_dev, is_dev, is_admin)
    ordered_keys = sorted(
        groups.keys(),
        key=lambda k: (_PRIORITY.index(k) if k in _PRIORITY else len(_PRIORITY), k),
    )
    result = {}
    for key in ordered_keys:
        pages = _build_pages_for_category(key, groups[key], include_dev, bot)
        if pages:
            result[key] = pages
    return result

# ── Home embed ─────────────────────────────────────────────────────────────────────────────────
def _home_embed(all_pages: dict, include_dev: bool, bot: commands.Bot) -> discord.Embed:
    color = 0x2f3136 if include_dev else 0x5865F2
    embed = discord.Embed(
        title="📚 Comandi disponibili" if not include_dev else "🔧 Comandi Dev",
        description="Usa il menu per navigare fra le categorie, oppure cerca un comando specifico con `/help `.",
        color=color,
    )
    items = list(all_pages.items())
    for i, (key, pages) in enumerate(items):
        icon, label = _get_cog_meta(bot, key)
        count = sum(len(p.fields) for p in pages)
        embed.add_field(name=f"{icon} {label}", value=f"`{count}` comandi", inline=True)
        is_last = i == len(items) - 1
        remainder = (i + 1) % 3
        if is_last and remainder != 0:
            for _ in range(3 - remainder):
                embed.add_field(name=_BLANK, value=_BLANK, inline=True)
    return embed

# ── Views ────────────────────────────────────────────────────────────────────────────────────────
class _CategoryPagesView(discord.ui.View):
    def __init__(self, pages, author_id, category_label, all_pages, include_dev, bot):
        super().__init__(timeout=120)
        self.pages          = pages
        self.author_id      = author_id
        self.category_label = category_label
        self.all_pages      = all_pages
        self.include_dev    = include_dev
        self.bot            = bot
        self.current        = 0
        self._stamp_footers()
        self._update_buttons()

    def _stamp_footers(self):
        total = len(self.pages)
        for i, p in enumerate(self.pages):
            p.set_footer(text=f"{self.category_label} · Pagina {i+1}/{total} · ◄ ► per navigare")

    def _update_buttons(self):
        self.prev_btn.disabled = self.current == 0
        self.next_btn.disabled = self.current == len(self.pages) - 1

    async def _go(self, inter, page):
        if inter.user.id != self.author_id:
            return await inter.response.send_message("Non è il tuo help.", ephemeral=True)
        self.current = page
        self._update_buttons()
        await inter.response.edit_message(embed=self.pages[self.current], view=self)

    @discord.ui.button(emoji="◀️", style=discord.ButtonStyle.primary)
    async def prev_btn(self, inter, _): await self._go(inter, self.current - 1)

    @discord.ui.button(emoji="▶️", style=discord.ButtonStyle.primary)
    async def next_btn(self, inter, _): await self._go(inter, self.current + 1)

    @discord.ui.button(label="🏠 Home", style=discord.ButtonStyle.secondary)
    async def home_btn(self, inter, _):
        if inter.user.id != self.author_id:
            return await inter.response.send_message("Non è il tuo help.", ephemeral=True)
        home = _home_embed(self.all_pages, self.include_dev, self.bot)
        view = _CategorySelectView(self.all_pages, self.author_id, self.include_dev, self.bot)
        await inter.response.edit_message(embed=home, view=view)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True

class _CategorySelectView(discord.ui.View):
    def __init__(self, all_pages, author_id, include_dev, bot):
        super().__init__(timeout=120)
        self.all_pages   = all_pages
        self.author_id   = author_id
        self.include_dev = include_dev
        self.bot         = bot
        self._build_select()

    def _build_select(self):
        options = []
        for key, pages in self.all_pages.items():
            icon, label = _get_cog_meta(self.bot, key)
            count = sum(len(p.fields) for p in pages)
            options.append(
                discord.SelectOption(
                    label=label,
                    value=key,
                    emoji=icon,
                    description=f"{count} comandi",
                )
            )
        if not options:
            return
        select = discord.ui.Select(
            placeholder="💬 Scegli una categoria...",
            options=options[:25],
        )
        select.callback = self._on_select
        self.add_item(select)

    async def _on_select(self, inter: discord.Interaction):
        if inter.user.id != self.author_id:
            return await inter.response.send_message("Non è il tuo help.", ephemeral=True)
        values = (inter.data or {}).get("values", [])
        if not values:
            return await inter.response.send_message("Selezione non valida.", ephemeral=True)
        key    = values[0]
        pages  = self.all_pages.get(key, [])
        if not pages:
            return await inter.response.send_message("Categoria vuota.", ephemeral=True)
        _, label = _get_cog_meta(self.bot, key)
        view = _CategoryPagesView(pages, self.author_id, label, self.all_pages, self.include_dev, self.bot)
        await inter.response.edit_message(embed=pages[0], view=view)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True

# ── Cog ────────────────────────────────────────────────────────────────────────────────────────
class Help(commands.Cog):
    COG_ICON  = "📚"
    COG_LABEL = "Aiuto"
    COG_TYPE  = "public"

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── Autocomplete ───────────────────────────────────────────────────────────────────────
    async def _autocomplete_comando(
        self,
        inter: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        dev   = _is_dev(inter.user.id)
        admin = _is_admin(inter)
        all_cmds = _all_commands_flat(self.bot, dev, admin)
        current_lower = current.lower().lstrip("/")
        choices = []
        for cmd in sorted(all_cmds, key=lambda c: _cmd_full_name(c)):
            name = _cmd_full_name(cmd)
            if current_lower in name.lower():
                choices.append(app_commands.Choice(name=f"/{name}", value=name))
            if len(choices) >= 25:
                break
        return choices

    @app_commands.command(name="help", description="Mostra i comandi disponibili")
    @app_commands.describe(comando="Nome del comando specifico (opzionale)")
    @app_commands.autocomplete(comando=_autocomplete_comando)
    async def help_cmd(self, inter: discord.Interaction, comando: Optional[str] = None):
        dev   = _is_dev(inter.user.id)
        admin = _is_admin(inter)

        if comando:
            all_cmds = _all_commands_flat(self.bot, dev, admin)
            match = next(
                (c for c in all_cmds if _cmd_full_name(c).lower() == comando.lower().lstrip("/")),
                None,
            )
            if not match:
                return await inter.response.send_message(
                    embed=discord.Embed(
                        description=f"❌ Comando `{comando}` non trovato.",
                        color=0xED4245,
                    ),
                    ephemeral=True,
                )
            return await inter.response.send_message(
                embed=_build_command_embed(match, self.bot), ephemeral=True
            )

        all_pages = _build_all_pages(self.bot, include_dev=False, is_dev=dev, is_admin=admin)
        home      = _home_embed(all_pages, include_dev=False, bot=self.bot)
        view      = _CategorySelectView(all_pages, inter.user.id, include_dev=False, bot=self.bot)
        await inter.response.send_message(embed=home, view=view, ephemeral=True)

    @app_commands.command(name="help-dev", description="🔧 Comandi tecnici del bot")
    @perm("dev")
    @dev_check
    async def help_dev_cmd(self, inter: discord.Interaction):
        all_pages = _build_all_pages(self.bot, include_dev=True, is_dev=True, is_admin=True)
        home      = _home_embed(all_pages, include_dev=True, bot=self.bot)
        view      = _CategorySelectView(all_pages, inter.user.id, include_dev=True, bot=self.bot)
        await inter.response.send_message(embed=home, view=view, ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(Help(bot))
