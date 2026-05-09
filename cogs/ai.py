import logging
import re
import time
from collections import deque
from html import unescape

import aiohttp
import discord
from discord.ext import commands

from config import Config
from core.ai_client import chat, load_prompt, invalidate_prompt_cache as _invalidate_lru
from core.ai_runtime import _state
from core.log_colors import tag, b, user

log = logging.getLogger("pitonazz.ai")

_SYSTEM_PROMPT_PATH = "assets/prompts/ai_prompt.txt"
_FALLBACK_PROMPT    = "Sei Pitonazz. Rispondi in modo diretto, colloquiale e utile."
# Limite Discord per un singolo messaggio (margine di sicurezza -10 char)
_DISCORD_MAX = 1990
_SAFE_MENTIONS = discord.AllowedMentions.none()
_LOG_PREVIEW_MAX = 90
_CTX_FIELD_MAX = 80
_CTX_REPLY_MAX = 200
_CTX_ATTACHMENT_NAME_MAX = 40
_CTX_ATTACHMENTS_MAX = 3
_INPUT_SOFT_MAX_CHARS = 6000
_MEMORY_ITEM_MAX_CHARS = 1000
_BASE_HISTORY_CHAR_BUDGET = 4200
_MAX_HISTORY_CHAR_BUDGET = 7000
_MAX_TOKENS_MENTION = 700
_MAX_TOKENS_DM = 700
_MAX_TOKENS_CAP = 1200
_TOKEN_CHAR_RATIO = 4
_MAX_EXTRA_TOKENS = 320
_HISTORY_BUDGET_SCALING_FACTOR = 2
_BG_CACHE_TTL_SECONDS = 600
_BG_MAX_MENTIONED_USERS = 3
_BG_MAX_ITEMS_PER_USER = 5
_BG_MAX_ITEM_TEXT = 160
_BG_MAX_SUMMARY = 520
_BG_CHANNEL_RECENT_MAX = 120
_EXT_CTX_MAX_CHARS = 1800
_IMG_ATTACHMENTS_MAX = 2
_IMG_MAX_BYTES = 8 * 1024 * 1024
_WEB_SEARCH_TIMEOUT_SECONDS = 4
_WEB_RESULTS_MAX = 3
_WEB_SECTION_MAX = 700
_WEB_META_ROWS = 1
_WIKIPEDIA_SEARCH_API_URL = "https://it.wikipedia.org/w/api.php"
_SEARCH_MARKERS = ("cerca web:", "search:", "web:")
# Trigger espliciti per attivare la ricerca web in prompt (evita attivazioni accidentali).
_SEARCH_TRIGGER_RE = re.compile(r"(?is)(?:^|\s)(?:cerca\s+web\s*:|search\s*:|web\s*:|#web\b)")
_QUESTION_PREFIXES = (
    "chi", "cosa", "quando", "dove", "come", "perché", "perche", "quanto", "quale", "quali",
)
_UNCERTAIN_REPLY_RE = re.compile(
    r"(?is)\b(?:non so|non conosco|non ricordo|non posso verificare|non ho dati|"
    r"non sono sicur[oa]|boh|i don't know|not sure|can't verify|cannot verify)\b"
)
_AUTO_WEB_MIN_QUERY_CHARS = 12
_AUTO_WEB_MAX_QUERY_CHARS = 180
_WEB_RETRY_PREVIEW_MAX = 220
_WEB_METRICS_LOG_EVERY = 10
_WORD_RE = re.compile(r"\w{4,}", flags=re.UNICODE)
_MENTION_STOPWORDS = {
    "anche", "ancora", "allora", "avere", "avete", "come", "cosa", "cosi", "così",
    "della", "delle", "dello", "degli", "dentro", "dopo", "dove", "fare", "fatto",
    "fatti", "forse", "gli", "hai", "hanno", "ieri", "oggi", "loro", "nella", "nelle",
    "nello", "noi", "non", "per", "pero", "però", "quale", "quali", "quello", "questa",
    "questo", "sempre", "sono", "sotto", "solo", "sopra", "stato", "stata", "tanto",
    "tutti", "tutte", "tuoi", "tuo", "una", "uno", "voi", "with", "that", "this", "from",
}

_cached_prompt: str | None = None


def _metric_inc(key: str) -> int:
    _state.web_retry_metrics[key] += 1
    return _state.web_retry_metrics[key]


def _maybe_log_web_retry_metrics() -> None:
    attempts = _state.web_retry_metrics.get("attempts", 0)
    if attempts <= 0 or attempts % _WEB_METRICS_LOG_EVERY != 0:
        return
    success = _state.web_retry_metrics.get("success", 0)
    explicit_ctx = _state.web_retry_metrics.get("explicit_ctx", 0)
    auto_ctx = _state.web_retry_metrics.get("auto_ctx", 0)
    no_ctx = _state.web_retry_metrics.get("no_ctx", 0)
    rate = (success / attempts) * 100 if attempts else 0.0
    log.info(tag("AI", f"METRICS web_retry attempts={attempts} success={success} rate={rate:.0f}% explicit_ctx={explicit_ctx} auto_ctx={auto_ctx} no_ctx={no_ctx}"))


def _system_prompt() -> str:
    global _cached_prompt
    if _cached_prompt is None:
        p = load_prompt(_SYSTEM_PROMPT_PATH)
        _cached_prompt = p if p else _FALLBACK_PROMPT
    return _cached_prompt


def invalidate_prompt_cache() -> None:
    """Invalida sia la cache locale sia la cache LRU di ai_client.load_prompt."""
    global _cached_prompt
    _cached_prompt = None
    _invalidate_lru()  # resetta la cache LRU — fondamentale per rileggere il file dal disco


def _get_memory(channel_id: int) -> deque:
    if channel_id not in _state.conversation_memory:
        _state.conversation_memory[channel_id] = deque(maxlen=20)
    return _state.conversation_memory[channel_id]


def _clip_for_model(text: str, limit: int) -> str:
    raw = (text or "").strip()
    if len(raw) <= limit:
        return raw
    return raw[: limit - 1] + "…"


def _entry_len(msg: dict) -> int:
    # Coerente con il clipping memoria: eventuali item già presenti da versioni precedenti
    # (prima del limite per-item) vengono comunque stimati al massimo consentito.
    return min(len(msg.get("content", "")), _MEMORY_ITEM_MAX_CHARS)


def _build_messages(channel_id: int, user_message: str, user_content_len: int) -> list[dict]:
    budget = _history_char_budget(user_content_len)
    messages = [{"role": "system", "content": _system_prompt()}]

    # Seleziona solo la coda più recente della memoria entro budget caratteri.
    mem = _get_memory(channel_id)
    selected: list[dict] = []
    total = 0
    for item in reversed(mem):
        size = _entry_len(item)
        if total + size > budget:
            break
        selected.append(item)
        total += size
    messages.extend(reversed(selected))
    messages.append({"role": "user", "content": user_message})
    return messages


def _history_char_budget(user_content_len: int) -> int:
    # Budget dinamico: più contesto quando l'utente scrive input lunghi,
    # mantenendo comunque un cap per contenere costi/token.
    extra = min(
        _MAX_HISTORY_CHAR_BUDGET - _BASE_HISTORY_CHAR_BUDGET,
        user_content_len // _HISTORY_BUDGET_SCALING_FACTOR,
    )
    return _BASE_HISTORY_CHAR_BUDGET + extra


def _short(text: str, limit: int) -> str:
    compact = " ".join((text or "").split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1] + "…"


def _resolved_reply_message(message: discord.Message) -> discord.Message | None:
    ref = message.reference
    if not ref:
        return None
    resolved = ref.resolved
    return resolved if isinstance(resolved, discord.Message) else None


def _trigger_label(is_dm: bool, is_mention: bool, is_reply_to_bot: bool) -> str:
    if is_dm:
        return "dm"
    if is_mention and is_reply_to_bot:
        return "mention+reply"
    if is_mention:
        return "mention"
    return "reply"


def _guild_channel_names(message: discord.Message) -> tuple[str, str]:
    guild_name = _short(getattr(message.guild, "name", "unknown"), _CTX_FIELD_MAX)
    channel_name = _short(getattr(message.channel, "name", "unknown"), _CTX_FIELD_MAX)
    return guild_name, channel_name


def _where_label(message: discord.Message, is_dm: bool) -> str:
    if is_dm:
        return "dm"
    guild_name, channel_name = _guild_channel_names(message)
    return f"#{channel_name}@{guild_name}"


def _build_ai_user_input(
    message: discord.Message,
    content: str,
    trigger: str,
    reply_target: discord.Message | None,
) -> str:
    author = message.author
    display = _short(author.display_name, _CTX_FIELD_MAX)
    username = _short(str(author), _CTX_FIELD_MAX)

    ctx = [
        "[CONTESTO]",
        f"trigger={trigger}",
        f"user_display_name={display}",
        f"user_username={username}",
        f"user_id={author.id}",
    ]

    if isinstance(message.channel, discord.DMChannel):
        ctx.append("chat_scope=dm")
    else:
        guild_name, channel_name = _guild_channel_names(message)
        ctx.append("chat_scope=guild")
        ctx.append(f"guild={guild_name}")
        ctx.append(f"channel=#{channel_name}")

    if reply_target:
        reply_author = _short(str(reply_target.author), _CTX_FIELD_MAX)
        reply_text = _short(reply_target.content or "<messaggio vuoto>", _CTX_REPLY_MAX)
        ctx.append(f"reply_to_author={reply_author}")
        ctx.append(f"reply_to_text={reply_text}")

    if message.attachments:
        # Solo i primi N allegati per non gonfiare inutilmente il prompt.
        names = [_short(a.filename, _CTX_ATTACHMENT_NAME_MAX) for a in message.attachments[:_CTX_ATTACHMENTS_MAX]]
        ctx.append(f"attachments={', '.join(names)}")

    ctx.append("[MESSAGGIO_UTENTE]")
    ctx.append(content)
    return "\n".join(ctx)


def _is_image_attachment(attachment: discord.Attachment) -> bool:
    content_type = (attachment.content_type or "").lower()
    if content_type.startswith("image/"):
        return True
    filename = (attachment.filename or "").lower()
    return filename.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"))


def _extract_image_hints(filename: str) -> str:
    base = (filename or "").rsplit(".", 1)[0].replace("_", " ").replace("-", " ")
    words = [
        w for w in re.findall(r"\w{3,}", base, flags=re.UNICODE)
        if not w.isdigit() and any(ch.isalpha() for ch in w)
    ]
    if not words:
        return "n/a"
    return ", ".join(words[:4])


def _build_attachments_context(message: discord.Message) -> str:
    if not message.attachments:
        return ""

    rows: list[str] = []
    for attachment in message.attachments[:_IMG_ATTACHMENTS_MAX]:
        if not _is_image_attachment(attachment):
            continue
        size_flag = "ok" if attachment.size <= _IMG_MAX_BYTES else "too_large"
        dims = f"{attachment.width or '?'}x{attachment.height or '?'}"
        hint = _extract_image_hints(attachment.filename)
        rows.append(
            f"- image={_short(attachment.filename, 45)} size={attachment.size}B dims={dims} status={size_flag} hint={hint}"
        )

    if not rows:
        return ""
    return "[ALLEGATI_IMMAGINE]\n" + "\n".join(rows)


def _message_author_meta(message: discord.Message) -> tuple[str, str]:
    return _short(message.author.display_name, _CTX_FIELD_MAX), _short(str(message.author), _CTX_FIELD_MAX)


def _record_message_for_context(message: discord.Message) -> None:
    if isinstance(message.channel, discord.DMChannel):
        return
    text = _short((message.content or "").strip(), _BG_MAX_ITEM_TEXT)
    if not text:
        return
    channel_id = message.channel.id
    display, username = _message_author_meta(message)
    entry = {
        "ts": time.time(),
        "author_id": message.author.id,
        "author_display": display,
        "author_username": username,
        "content": text,
        "mentions": [m.id for m in message.mentions if not m.bot],
    }
    if channel_id not in _state.channel_recent_messages:
        _state.channel_recent_messages[channel_id] = deque(maxlen=_BG_CHANNEL_RECENT_MAX)
    _state.channel_recent_messages[channel_id].append(entry)
    _state.mention_background_cache.pop((channel_id, message.author.id), None)


def _pick_keywords(texts: list[str], limit: int = 4) -> list[str]:
    scores: dict[str, int] = {}
    for text in texts:
        for word in _WORD_RE.findall(text.lower()):
            if word in _MENTION_STOPWORDS:
                continue
            if not any(ch.isalpha() for ch in word):
                continue
            scores[word] = scores.get(word, 0) + 1
    return [k for k, _ in sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]]


def _style_label(texts: list[str]) -> str:
    if not texts:
        return "sconosciuto"
    questions = sum(t.count("?") for t in texts)
    exclaims = sum(t.count("!") for t in texts)
    if exclaims > questions and exclaims >= 2:
        return "energico"
    if questions > exclaims and questions >= 2:
        return "interrogativo"
    return "neutro"


def _build_mentioned_user_background(channel_id: int, target: discord.abc.User, requester_id: int) -> str:
    cache_key = (channel_id, target.id)
    now = time.time()
    cached = _state.mention_background_cache.get(cache_key)
    if cached and now - cached[0] < _BG_CACHE_TTL_SECONDS:
        return cached[1]

    history = _state.channel_recent_messages.get(channel_id)
    if not history:
        summary = f"- @{_short(target.display_name, _CTX_FIELD_MAX)}: nessun background disponibile."
        _state.mention_background_cache[cache_key] = (now, summary)
        return summary

    own = [m for m in reversed(history) if m["author_id"] == target.id][: _BG_MAX_ITEMS_PER_USER]
    if not own:
        summary = f"- @{_short(target.display_name, _CTX_FIELD_MAX)}: nessun background disponibile."
        _state.mention_background_cache[cache_key] = (now, summary)
        return summary

    texts = [m["content"] for m in own]
    topics = _pick_keywords(texts)
    style = _style_label(texts)
    mentions_requester = sum(1 for m in own if requester_id in m.get("mentions", []))
    last_line = _short(texts[0], 90)
    line = (
        f"- @{_short(target.display_name, _CTX_FIELD_MAX)} (user={_short(str(target), _CTX_FIELD_MAX)}): "
        f"tone={style}; topics={', '.join(topics) if topics else 'n/a'}; "
        f"mentions_current_user={mentions_requester}; last='{last_line}'"
    )
    line = _clip_for_model(line, _BG_MAX_SUMMARY)
    _state.mention_background_cache[cache_key] = (now, line)
    return line


def _build_mentions_context(message: discord.Message) -> str:
    if isinstance(message.channel, discord.DMChannel):
        return ""
    mentioned = [m for m in message.mentions if not m.bot and m.id != message.author.id]
    if not mentioned:
        return ""
    uniq: dict[int, discord.abc.User] = {m.id: m for m in mentioned}
    users = list(uniq.values())[:_BG_MAX_MENTIONED_USERS]
    lines = [_build_mentioned_user_background(message.channel.id, target, message.author.id) for target in users]
    if not lines:
        return ""
    return "[UTENTI_MENZIONATI]\n" + "\n".join(lines)


def _extract_web_query(content: str) -> str:
    cleaned = content.strip()
    if cleaned.startswith("#web"):
        return cleaned[4:].strip(" :;-")
    for marker in _SEARCH_MARKERS:
        pos = cleaned.lower().find(marker)
        if pos != -1:
            return cleaned[pos + len(marker):].strip()
    return ""


def _should_use_web_search(content: str) -> bool:
    return bool(_SEARCH_TRIGGER_RE.search(content or ""))


def _looks_like_question(content: str) -> bool:
    cleaned = (content or "").strip().lower()
    if not cleaned or cleaned.startswith("/"):
        return False
    if "?" in cleaned:
        return True
    return any(cleaned.startswith(prefix + " ") for prefix in _QUESTION_PREFIXES)


def _auto_web_query(content: str) -> str:
    cleaned = " ".join((content or "").split()).strip(" :;-")
    if len(cleaned) < _AUTO_WEB_MIN_QUERY_CHARS:
        return ""
    return _short(cleaned, _AUTO_WEB_MAX_QUERY_CHARS)


def _should_retry_with_web(content: str, reply: str) -> bool:
    if not _looks_like_question(content):
        return False
    return bool(_UNCERTAIN_REPLY_RE.search(reply or ""))


async def _web_search_context(content: str) -> str:
    query = _extract_web_query(content) if _should_use_web_search(content) else _auto_web_query(content)
    if not query:
        return ""

    params = {
        "action": "query",
        "list": "search",
        "utf8": "1",
        "format": "json",
        "srlimit": str(_WEB_RESULTS_MAX),
        "srsearch": query,
    }
    timeout = aiohttp.ClientTimeout(total=_WEB_SEARCH_TIMEOUT_SECONDS)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(_WIKIPEDIA_SEARCH_API_URL, params=params) as resp:
                if resp.status != 200:
                    return f"[RICERCA_WEB]\n- Errore ricerca (status={resp.status})."
                payload = await resp.json()
    except Exception as e:
        log.warning(tag("AI", f"Web search non disponibile: {_short(str(e), 90)}"))
        return "[RICERCA_WEB]\n- Ricerca non disponibile al momento."

    rows: list[str] = []
    results = ((payload.get("query") or {}).get("search") or [])
    rows.append("- Fonte: Wikipedia (search API)")
    for item in results:
        if len(rows) >= _WEB_RESULTS_MAX + _WEB_META_ROWS:
            break
        if not isinstance(item, dict):
            continue
        title = (item.get("title") or "").strip()
        snippet_html = (item.get("snippet") or "").strip()
        snippet = re.sub(r"<[^>]+>", "", unescape(snippet_html)).strip()
        page_id = item.get("pageid")
        if not title:
            continue
        page_url = f"https://it.wikipedia.org/?curid={page_id}" if page_id else "https://it.wikipedia.org"
        rows.append(f"- {title}: {_short(snippet or 'nessuna sintesi disponibile', 180)} ({page_url})")

    if not rows:
        rows.append("- Nessun risultato sintetico disponibile.")
    section = "[RICERCA_WEB]\n" + "\n".join(rows[: _WEB_RESULTS_MAX + _WEB_META_ROWS])
    return _clip_for_model(section, _WEB_SECTION_MAX)


def _merge_extra_context(parts: list[str]) -> str:
    joined = "\n".join([part for part in parts if part]).strip()
    return _clip_for_model(joined, _EXT_CTX_MAX_CHARS) if joined else ""


def _response_token_limit(trigger: str, content: str) -> int:
    base = _MAX_TOKENS_DM if trigger == "dm" else _MAX_TOKENS_MENTION
    # Euristica morbida: input più lungo => output più ampio, con cap per evitare sprechi.
    # _TOKEN_CHAR_RATIO assume ~4 caratteri medi per token.
    extra = min(_MAX_EXTRA_TOKENS, len(content) // _TOKEN_CHAR_RATIO)
    return min(_MAX_TOKENS_CAP, base + extra)


def _split_reply(text: str, limit: int = _DISCORD_MAX) -> list[str]:
    """Divide una risposta lunga in chunk da ≤ limit caratteri, rispettando le righe."""
    if len(text) <= limit:
        return [text]
    chunks = []
    while text:
        if len(text) <= limit:
            chunks.append(text)
            break
        # Cerca l'ultimo newline entro il limite
        cut = text.rfind("\n", 0, limit)
        if cut == -1:
            cut = limit
        chunks.append(text[:cut])
        text = text[cut:].lstrip("\n")
    return chunks


class AI(commands.Cog):
    COG_ICON  = "🤖"
    COG_LABEL = "Intelligenza Artificiale"
    COG_TYPE  = "public"

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_unload(self) -> None:
        # Il cog viene scaricato (hot-reload): resetta lo stato in-memory
        # per evitare che rate_limit_map e conversation_memory obsoleti
        # sopravvivano alla nuova istanza del cog.
        # Invalida anche _cached_prompt: se ai_prompt.txt è stato modificato,
        # il prossimo caricamento del cog riletterà il file dal disco.
        _state.reset()
        invalidate_prompt_cache()
        log.info(tag("AI", "Stato in-memory e cache prompt resettati (cog_unload)."))

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        if not self.bot.user:
            return

        is_dm      = isinstance(message.channel, discord.DMChannel)
        is_mention = self.bot.user in message.mentions
        reply_target = _resolved_reply_message(message)
        is_reply_to_bot = bool(reply_target and reply_target.author.id == self.bot.user.id)

        if not is_dm and not is_mention and not is_reply_to_bot:
            return
        trigger = _trigger_label(is_dm, is_mention, is_reply_to_bot)

        uid  = message.author.id
        now  = time.time()
        elapsed = now - _state.rate_limit_map.get(uid, 0)
        if elapsed < Config.AI_COOLDOWN_SECONDS:
            remaining = max(0.0, Config.AI_COOLDOWN_SECONDS - elapsed)
            log.info(tag("AI", f"Rate-limit  trigger={b(trigger)}  {user(str(message.author))}  (remaining {remaining:.1f}s)"))
            try:
                await message.reply("Rallenta.", mention_author=False, allowed_mentions=_SAFE_MENTIONS)
            except discord.HTTPException:
                pass
            return
        _state.rate_limit_map[uid] = now

        content = message.content
        if is_mention:
            content = (
                content
                .replace(f"<@{self.bot.user.id}>", "")
                .replace(f"<@!{self.bot.user.id}>", "")
                .strip()
            )
            if content.startswith("/"):
                log.info(tag("AI", f"Mention con slash ignorata  {user(str(message.author))}  msg={repr(content[:60])}"))
                return

        if not content:
            log.info(tag("AI", f"Input vuoto  trigger={b(trigger)}  {user(str(message.author))}"))
            try:
                await message.reply("Dimmi.", mention_author=False, allowed_mentions=_SAFE_MENTIONS)
            except discord.HTTPException:
                pass
            return

        where = _where_label(message, is_dm)
        log.info(tag("AI", f"IN  trigger={b(trigger)}  where={where}  {user(str(message.author))}  msg={repr(_short(content, _LOG_PREVIEW_MAX))}"))

        # channel_id per DM: usa author.id (ogni utente ha memoria separata)
        channel_id = message.channel.id if not is_dm else message.author.id
        content_for_model = _clip_for_model(content, _INPUT_SOFT_MAX_CHARS)
        ai_user_input = _build_ai_user_input(
            message,
            content_for_model,
            trigger,
            reply_target,
        )
        messages = _build_messages(channel_id, ai_user_input, len(content_for_model))
        max_tokens = _response_token_limit(trigger, content)
        log.info(tag("AI", f"CTX  history={len(messages) - 2}msg  prompt_chars={sum(len(m.get('content', '')) for m in messages)}  max_tokens={max_tokens}"))

        async with message.channel.typing():
            try:
                reply, model_used = await chat(messages, max_tokens=max_tokens)
            except Exception as e:
                log.error(tag("AI", f"Tutti i provider falliti  {user(str(message.author))}  → {e}"))
                try:
                    await message.reply(
                        "⚠️ Si è verificato un errore interno. Riprova tra poco.",
                        mention_author=False,
                        allowed_mentions=_SAFE_MENTIONS,
                    )
                except discord.HTTPException:
                    pass
                return

        # Guardia risposta vuota: alcuni provider possono restituire stringa vuota
        if not reply or not reply.strip():
            log.warning(tag("AI", f"Risposta vuota dal provider  model={b(model_used)}"))
            try:
                await message.reply(
                    "⚠️ Risposta vuota dal provider AI. Riprova tra poco.",
                    mention_author=False,
                    allowed_mentions=_SAFE_MENTIONS,
                )
            except discord.HTTPException:
                pass
            return

        log.info(tag("AI", f"OK  model={b(model_used)}  len={len(reply)}ch"))

        mem = _get_memory(channel_id)
        mem.append({"role": "user",      "content": _clip_for_model(ai_user_input, _MEMORY_ITEM_MAX_CHARS)})
        mem.append({"role": "assistant", "content": _clip_for_model(reply, _MEMORY_ITEM_MAX_CHARS)})

        # Invia in più messaggi se la risposta supera il limite Discord (2000 char)
        chunks = _split_reply(reply)
        for i, chunk in enumerate(chunks):
            try:
                if i == 0:
                    await message.reply(chunk, mention_author=False, allowed_mentions=_SAFE_MENTIONS)
                else:
                    await message.channel.send(chunk, allowed_mentions=_SAFE_MENTIONS)
            except discord.HTTPException as e:
                log.warning(tag("AI", f"Invio chunk {i} fallito: {e}"))
                break


async def setup(bot: commands.Bot):
    await bot.add_cog(AI(bot))
