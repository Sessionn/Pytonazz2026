import asyncio
import logging
import re
import time
from typing import AsyncIterable, Optional

import discord
from discord import app_commands
from discord.ext import commands

from config import Config
import core.cache_db as cache_db
from core.player import MusicPlayer
from core.source_resolver import (
    SourceResolver,
    _is_yt_channel_url,
    extract_spotify_album_id,
    extract_spotify_playlist_id,
    extract_spotify_track_id,
    is_spotify_artist_url,
)
from embeds.music_embeds import queue_embed, error_embed, success_embed, queue_notification_embed
from views.queue_view import QueueView
from core.log_colors import tag, b, ms, guild, user, ch

log = logging.getLogger("pitonazz.music")
_EMBED_RULER = "`" + "─" * 54 + "`"
_QUEUE_PROGRESS_STEP = 10
_PLAY_DEBOUNCE_WINDOW_SECONDS = 1.8
_PLAY_DEBOUNCE_CLEANUP_MULTIPLIER = 4
_PLAY_DEBOUNCE_GC_EVERY = 8
_BATCH_WARMUP_LIMIT = 8
_AUTOPLAY_REFILL_LIMIT = 8

# list= prefix comuni nelle raccolte YouTube:
# PL playlist, OLAK album/topic, RDCLAK radio/mix, UU upload canale, LL liked, FL favorites, WL watch later.
_RE_YT_PLAYLIST    = re.compile(
    r"(?:youtube\.com/playlist|[?&]list=(?:PL|OLAK|RDCLAK|UU|LL|FL|WL))",
    re.IGNORECASE,
)
_RE_SC_COLLECTION  = re.compile(r"soundcloud\.com/[^/?#]+/(?:sets|albums)/[^/?#]+", re.IGNORECASE)
_RE_URL_LIKE       = re.compile(
    r"^(?:https?://)?(?:(?:www\.)?(?:open\.)?spotify\.com|(?:www\.)?youtube\.com|youtu\.be|(?:www\.)?soundcloud\.com|on\.soundcloud\.com)(?:/|$)",
    re.IGNORECASE,
)


def _normalize_url_like(query: str) -> str:
    q = (query or "").strip()
    if not q:
        return ""
    if q.startswith(("http://", "https://")):
        return q
    if _RE_URL_LIKE.match(q):
        return f"https://{q}"
    return q


def _is_spotify_uri(query: str) -> bool:
    return (query or "").strip().lower().startswith("spotify:")


def _spotify_kind(query: str) -> Optional[str]:
    q = (query or "").strip()
    if not q:
        return None
    if extract_spotify_track_id(q):
        return "track"
    if extract_spotify_playlist_id(q):
        return "playlist"
    if extract_spotify_album_id(q):
        return "album"
    if is_spotify_artist_url(q):
        return "artist"
    return None


def _is_text_search(query: str) -> bool:
    q = (query or "").strip().lower()
    return not (_RE_URL_LIKE.match(q) or _is_spotify_uri(q))


def _is_multi_url(query: str) -> bool:
    normalized = _normalize_url_like(query)
    spotify_kind = _spotify_kind(normalized)
    if spotify_kind in {"playlist", "album"}:
        return True
    if not normalized.startswith(("http://", "https://")):
        return False
    return bool(
        _RE_YT_PLAYLIST.search(normalized)
        or _RE_SC_COLLECTION.search(normalized)
    )


def _progress_bar(current: int, total: int, width: int = 18) -> str:
    if total > 0:
        filled = min(width, int(width * current / total))
        pct    = int(100 * current / total)
        bar    = "█" * filled + "░" * (width - filled)
        return f"`{bar}` {current}/{total} ({pct}%)"
    else:
        dots = "." * ((current % 3) + 1)
        return f"`caricamento{dots}` {current} tracce"


def _batch_loading_embed(
    nome: str,
    requester: discord.Member,
    current: int = 0,
    total: int = 0,
) -> discord.Embed:
    return discord.Embed(
        description=(
            f"⏳ Caricamento tracce di **{nome}** in corso...\n"
            f"{_progress_bar(current, total)}\n"
            f"👥 da {requester.mention}"
        ),
        color=0x5865F2,
    )


def _batch_done_embed(nome: str, total: int, requester: discord.Member) -> discord.Embed:
    return discord.Embed(
        description=(
            f"✅ **{total}** tracce di **{nome}** caricate in coda.\n"
            f"👥 da {requester.mention}"
        ),
        color=0x57F287,
    )


def _batch_cancelled_embed(nome: str, loaded: int, requester: discord.Member) -> discord.Embed:
    return discord.Embed(
        description=(
            f"❌ Caricamento **{nome}** annullato.\n"
            f"📋 **{loaded}** tracce già in coda.\n"
            f"👥 da {requester.mention}"
        ),
        color=0xFF6B6B,
    )


def _autoplay_status_embed(enabled: bool) -> discord.Embed:
    state = "🟢 ON" if enabled else "🔴 OFF"
    return success_embed(f"Autoplay: **{state}**")


class _AutoplaySelect(discord.ui.Select):
    def __init__(self, player: MusicPlayer, owner_id: int):
        self.player = player
        self.owner_id = owner_id
        enabled = bool(getattr(player, "autoplay_enabled", False))
        options = [
            discord.SelectOption(label="🟢 ON", value="on", default=enabled),
            discord.SelectOption(label="🔴 OFF", value="off", default=not enabled),
        ]
        super().__init__(
            placeholder="Seleziona autoplay",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, inter: discord.Interaction):
        if inter.user.id != self.owner_id:
            return await inter.response.send_message(
                "Solo chi ha aperto questo menu può modificarlo.",
                ephemeral=True,
            )
        self.player.autoplay_enabled = self.values[0] == "on"
        await inter.response.edit_message(
            embed=_autoplay_status_embed(self.player.autoplay_enabled),
            view=_AutoplayView(self.player, self.owner_id),
        )
        await self.player._update_msg_inplace()


class _AutoplayView(discord.ui.View):
    def __init__(self, player: MusicPlayer, owner_id: int):
        super().__init__(timeout=180)
        self.add_item(_AutoplaySelect(player, owner_id))


class _CancelBatchView(discord.ui.View):
    """View con pulsante ❌ che cancella il caricamento batch in corso."""

    def __init__(self, cancel_event: asyncio.Event, requester_id: int):
        super().__init__(timeout=600)
        self._cancel_event    = cancel_event
        self._requester_id    = requester_id
        self._already_clicked = False

    @discord.ui.button(label="Annulla caricamento", style=discord.ButtonStyle.danger, emoji="❌")
    async def cancel_btn(self, inter: discord.Interaction, button: discord.ui.Button):
        if inter.user.id != self._requester_id:
            return await inter.response.send_message(
                "Solo chi ha avviato il caricamento può annullarlo.", ephemeral=True
            )
        if self._already_clicked:
            return await inter.response.send_message("Già annullato.", ephemeral=True)
        self._already_clicked = True
        self._cancel_event.set()
        button.disabled = True
        button.label    = "Annullato"
        await inter.response.edit_message(view=self)

    def stop_view(self):
        """Disabilita il pulsante quando il caricamento finisce normalmente."""
        for child in self.children:
            child.disabled = True  # type: ignore
        self.stop()


class _PlaySelect(discord.ui.Select):
    def __init__(self, player, results, channel, requester, vc_ch, original_query: str = ""):
        self.player    = player
        self.results   = results
        self.channel   = channel
        self.requester = requester
        self.vc_ch     = vc_ch
        self.original_query = original_query
        options = []
        for i, r in enumerate(results[:7]):
            dur    = f"{r.duration//60}:{r.duration%60:02d}" if r.duration else "?:??"
            label  = f"{r.title[:80]} [{dur}]"[:100]
            artist = getattr(r, "artist", "") or ""
            desc   = artist[:100] if artist else None
            options.append(discord.SelectOption(label=label, value=str(i), description=desc))
        super().__init__(placeholder="Scegli la versione giusta...", options=options)

    async def callback(self, inter: discord.Interaction):
        current_vc_ch = (
            inter.user.voice.channel
            if inter.user.voice and inter.user.voice.channel
            else self.vc_ch
        )
        try:
            idx = int(self.values[0])
            chosen = self.results[idx]
        except (ValueError, IndexError):
            return await inter.response.send_message(
                embed=error_embed("Selezione non valida."),
                ephemeral=True,
            )
        vc = inter.guild.voice_client
        if not vc:
            vc = await current_vc_ch.connect()
        elif vc.channel != current_vc_ch:
            await vc.move_to(current_vc_ch)
        was_empty = not self.player.queue and not self.player.current
        position = 0 if was_empty else (len(self.player.queue) + 1)
        if self.original_query:
            try:
                cache_db.put(self.original_query, chosen)
            except Exception:
                log.debug(tag("CACHE", "skip manual selection cache"), exc_info=True)
        if not self.player.queue.put(chosen):
            return await inter.response.send_message(
                embed=error_embed(f"Coda piena (max {Config.MAX_QUEUE} tracce)."),
                ephemeral=True,
            )
        await inter.response.defer()
        await inter.delete_original_response()
        await self.channel.send(embed=queue_notification_embed(chosen, position, self.requester))
        await _maybe_start(self.player, vc, was_empty)


class _PlaySelectView(discord.ui.View):
    def __init__(self, player, results, channel, requester, vc_ch, original_query: str = ""):
        super().__init__(timeout=60)
        self.add_item(_PlaySelect(player, results, channel, requester, vc_ch, original_query))


class _VersionSelect(discord.ui.Select):
    def __init__(self, player, results: list):
        self.player  = player
        self.results = results
        options = []
        for i, r in enumerate(results[:5]):
            dur   = f"{r.duration//60}:{r.duration%60:02d}" if r.duration else "?:??"
            label = f"{r.title[:85]} [{dur}]"[:100]
            options.append(discord.SelectOption(label=label, value=str(i)))
        super().__init__(placeholder="Scegli una versione...", options=options)

    async def callback(self, inter: discord.Interaction):
        try:
            idx = int(self.values[0])
            chosen = self.results[idx]
        except (ValueError, IndexError):
            return await inter.response.send_message(
                embed=error_embed("Selezione non valida."),
                ephemeral=True,
            )
        self.player.switch_version(chosen)
        await inter.response.edit_message(
            content=f"▶️ Passato a: **{chosen.title}**",
            embed=None, view=None,
        )


class _VersionView(discord.ui.View):
    def __init__(self, player, results: list):
        super().__init__(timeout=60)
        self.add_item(_VersionSelect(player, results))


async def _maybe_start(player: MusicPlayer, vc: discord.VoiceClient, was_empty: bool):
    if not (vc.is_playing() or vc.is_paused()) and player.queue:
        await player.play_next()


async def _fetch_playlist_meta(query: str) -> tuple[str, int]:
    """
    Recupera (nome, total_tracks) prima di avviare il generator.
    Restituisce ("Playlist", 0) come fallback sicuro.
    """
    nome  = "Playlist"
    total = 0
    loop  = asyncio.get_running_loop()

    try:
        if pid_str := extract_spotify_playlist_id(query):
            sp  = SourceResolver._sp_client()
            if sp:
                pl = await loop.run_in_executor(
                    None,
                    lambda _id=pid_str: sp.playlist(_id, fields="name,tracks.total"),
                )
                nome  = pl.get("name") or "Playlist"
                total = pl.get("tracks", {}).get("total", 0)

        elif aid_str := extract_spotify_album_id(query):
            sp  = SourceResolver._sp_client()
            if sp:
                al = await loop.run_in_executor(
                    None,
                    lambda _id=aid_str: sp.album(_id),
                )
                nome  = al.get("name") or "Album"
                total = al.get("total_tracks", 0)

        elif _RE_YT_PLAYLIST.search(query) or _RE_SC_COLLECTION.search(query):
            import yt_dlp
            ydl_opts = {
                **Config.YDL_OPTIONS,
                "extract_flat": True,
                "skip_download": True,
                "quiet": True,
            }
            q = query
            info = await loop.run_in_executor(
                None,
                lambda _q=q: yt_dlp.YoutubeDL(ydl_opts).extract_info(_q, download=False),
            )
            if info:
                entries = info.get("entries") or []
                valid_entries_count = sum(1 for e in entries if e)
                if valid_entries_count > 0:
                    nome  = info.get("title") or info.get("uploader") or "Playlist"
                    total = valid_entries_count
                else:
                    # yt-dlp espone il totale con chiavi diverse in base all'estrattore.
                    fallback_keys = ("playlist_count", "n_entries", "entry_count")
                    raw_total = next((value for key in fallback_keys if (value := info.get(key)) is not None), None)
                    try:
                        fallback_total = int(raw_total) if raw_total is not None else 0
                    except (TypeError, ValueError):
                        fallback_total = 0
                    if fallback_total > 0:
                        nome  = info.get("title") or info.get("uploader") or "Playlist"
                        total = fallback_total

    except Exception as exc:
        log.warning(tag("WARN", f"_fetch_playlist_meta: {exc}"))

    return nome, total


class Music(commands.Cog):
    COG_ICON  = "🎵"
    COG_LABEL = "Musica"
    COG_TYPE  = "public"

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._players:        dict[int, MusicPlayer]  = {}
        self._empty_ch_tasks: dict[int, asyncio.Task] = {}
        self._batch_cancel:   dict[int, asyncio.Event] = {}
        self._play_debounce:  dict[tuple[int, str], float] = {}
        self._play_debounce_gc_counter: int = 0
        self._warmup_sem = asyncio.Semaphore(3)

    def _player(self, gid: int, ch_) -> MusicPlayer:
        if gid not in self._players:
            self._players[gid] = MusicPlayer(
                self.bot.get_guild(gid), ch_,
                on_cleanup=lambda guild_id: self._players.pop(guild_id, None),
                on_autoplay=self._autoplay_refill,
            )
        return self._players[gid]

    def _need_voice(self, inter: discord.Interaction) -> Optional[discord.VoiceChannel]:
        return inter.user.voice.channel if inter.user.voice else None

    def _get_cancel_event(self, guild_id: int) -> asyncio.Event:
        ev = asyncio.Event()
        self._batch_cancel[guild_id] = ev
        return ev

    def _trigger_cancel(self, guild_id: int):
        ev = self._batch_cancel.get(guild_id)
        if ev:
            ev.set()

    def _is_duplicate_play(self, guild_id: int, query: str) -> bool:
        now = time.monotonic()
        normalized = (query or "").strip().lower()
        if not normalized:
            return False
        key = (guild_id, normalized)
        last = self._play_debounce.get(key, 0.0)
        self._play_debounce[key] = now
        self._play_debounce_gc_counter += 1
        if self._play_debounce_gc_counter % _PLAY_DEBOUNCE_GC_EVERY == 0:
            cutoff = now - (_PLAY_DEBOUNCE_WINDOW_SECONDS * _PLAY_DEBOUNCE_CLEANUP_MULTIPLIER)
            stale = [k for k, ts in self._play_debounce.items() if ts < cutoff]
            for stale_key in stale:
                self._play_debounce.pop(stale_key, None)
        return (now - last) <= _PLAY_DEBOUNCE_WINDOW_SECONDS

    async def _warmup_track_stream_url(self, track) -> None:
        if not track or track.stream_url or not track.webpage_url:
            return
        async with self._warmup_sem:
            t0 = time.perf_counter()
            url = await SourceResolver.resolve_fresh_url(track)
            elapsed = (time.perf_counter() - t0) * 1000
            if url and not track.stream_url:
                track.stream_url = url
                log.debug(tag("WARMUP", f"{b(track.title)}  {ms(elapsed)}"))

    async def _autoplay_refill(self, player: MusicPlayer, seed_track) -> int:
        if not seed_track:
            return 0

        raw_artist = (getattr(seed_track, "artist", "") or "").strip()
        # Euristica semplice: se il resolver salva più artisti separati da virgola,
        # autoplay usa il primo come seed principale.
        seed_artist = raw_artist.split(",")[0].strip() if raw_artist else ""
        requester = getattr(seed_track, "requester", "Autoplay")
        requester_id = int(getattr(seed_track, "requester_id", 0) or 0)
        existing_urls = {
            (getattr(t, "webpage_url", "") or "").strip()
            for t in ([player.current] + player.queue.items + list(player.queue.history))
            if t
        }

        added = 0
        try:
            if seed_artist:
                gen = SourceResolver.resolve_artist_stream(
                    seed_artist, requester, requester_id, limit=_AUTOPLAY_REFILL_LIMIT
                )
                async for track in gen:
                    url = (getattr(track, "webpage_url", "") or "").strip()
                    if not url or url in existing_urls:
                        continue
                    if not player.queue.put(track):
                        break
                    existing_urls.add(url)
                    added += 1
                    if added >= _AUTOPLAY_REFILL_LIMIT:
                        break
            else:
                query = f"{seed_track.title} audio"
                tracks = await SourceResolver.resolve(query, requester, requester_id)
                for track in tracks:
                    url = (getattr(track, "webpage_url", "") or "").strip()
                    if not url or url in existing_urls:
                        continue
                    if not player.queue.put(track):
                        break
                    existing_urls.add(url)
                    added += 1
                    if added >= _AUTOPLAY_REFILL_LIMIT:
                        break
        except Exception as exc:
            log.warning(tag("WARN", f"autoplay refill errore: {exc}"))
            return 0

        if added > 0:
            who = seed_artist or seed_track.title
            log.info(tag("QUEUE", f"Autoplay refill  +{added}  seed={b(who)}"))
        return added

    async def _ensure_voice_client(
        self,
        inter: discord.Interaction,
        target_channel: discord.VoiceChannel,
        *,
        allow_move: bool = False,
    ) -> discord.VoiceClient:
        vc = inter.guild.voice_client
        if not vc:
            return await target_channel.connect()
        if allow_move and vc.channel != target_channel:
            await vc.move_to(target_channel)
        return vc

    async def _start_batch_stream(
        self,
        inter: discord.Interaction,
        vc: discord.VoiceClient,
        gen: AsyncIterable,
        *,
        nome: str,
        total: int,
        do_spotify_shuffle: bool = False,
    ):
        cancel_event = self._get_cancel_event(inter.guild_id)
        cancel_view = _CancelBatchView(cancel_event, inter.user.id)

        await inter.edit_original_response(
            embed=_batch_loading_embed(nome, inter.user, current=0, total=total),
            view=cancel_view,
        )
        await self._load_batch(
            inter, vc, gen,
            nome=nome, total=total,
            cancel_event=cancel_event,
            do_spotify_shuffle=do_spotify_shuffle,
            keep_loading_embed=True,
            cancel_view=cancel_view,
        )

    async def _load_batch(
        self,
        inter: discord.Interaction,
        vc: discord.VoiceClient,
        gen,
        nome: str,
        total: int,
        cancel_event: asyncio.Event,
        do_spotify_shuffle: bool = False,
        keep_loading_embed: bool = False,
        cancel_view: Optional["_CancelBatchView"] = None,
    ):
        player = self._player(inter.guild_id, inter.channel)

        try:
            first = await gen.__anext__()
        except StopAsyncIteration:
            return await inter.edit_original_response(
                embed=error_embed(f"Nessuna traccia trovata per: **{nome}**"), view=None
            )
        except Exception as e:
            log.exception("_load_batch: errore prima traccia")
            return await inter.edit_original_response(embed=error_embed("Errore: " + str(e)), view=None)

        was_empty = not player.queue and not player.current
        position = 0 if was_empty else (len(player.queue) + 1)
        if not player.queue.put(first):
            return await inter.edit_original_response(
                embed=error_embed(f"Coda piena (max {Config.MAX_QUEUE} tracce)."),
                view=None,
            )
        log.info(tag("QUEUE", f"[001] {b(first.title)}  —  {first.source}  (prima traccia)"))
        if not was_empty:
            asyncio.create_task(self._warmup_track_stream_url(first))

        if cancel_view is None:
            cancel_view = _CancelBatchView(cancel_event, inter.user.id)

        if keep_loading_embed:
            # La risposta originale è già la barra progresso mostrata dal
            # chiamante: aggiorniamo view con il cancel_view appena creato.
            await inter.edit_original_response(
                embed=_batch_loading_embed(nome, inter.user, current=1, total=total),
                view=cancel_view,
            )
            load_msg = await inter.original_response()
            await inter.channel.send(embed=queue_notification_embed(
                first,
                position,
                inter.user,
                collection_name=nome,
                collection_total=total,
            ))
        else:
            await inter.edit_original_response(
                embed=queue_notification_embed(
                    first,
                    position,
                    inter.user,
                    collection_name=nome,
                    collection_total=total,
                )
            )
            load_msg = await inter.channel.send(
                embed=_batch_loading_embed(nome, inter.user, current=1, total=total),
                view=cancel_view,
            )

        await _maybe_start(player, vc, was_empty)

        asyncio.create_task(self._fill_queue(
            gen, player, inter.channel,
            nome=nome, requester=inter.user,
            load_msg=load_msg, first_already_added=True,
            do_spotify_shuffle=do_spotify_shuffle, total=total,
            edit_load_msg=not keep_loading_embed,
            inter=inter if keep_loading_embed else None,
            cancel_event=cancel_event,
            cancel_view=cancel_view,
        ))

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        g = member.guild
        if member.id == self.bot.user.id:
            if before.channel and not after.channel:
                p = self._players.pop(g.id, None)
                if p:
                    p.stop()
                self._trigger_cancel(g.id)
            elif before.channel and after.channel and before.channel != after.channel:
                p = self._players.get(g.id)
                if p:
                    if not [m for m in after.channel.members if not m.bot]:
                        self._schedule_empty_disconnect(g)
                    else:
                        self._cancel_empty_task(g.id)
            return
        vc = g.voice_client
        if not vc or not vc.channel:
            return
        if before.channel != vc.channel and after.channel != vc.channel:
            return
        if not [m for m in vc.channel.members if not m.bot]:
            self._schedule_empty_disconnect(g)
        else:
            self._cancel_empty_task(g.id)

    def _schedule_empty_disconnect(self, g):
        self._cancel_empty_task(g.id)
        self._empty_ch_tasks[g.id] = asyncio.create_task(self._empty_channel_disconnect(g))

    def _cancel_empty_task(self, guild_id: int):
        task = self._empty_ch_tasks.pop(guild_id, None)
        if task and not task.done():
            task.cancel()

    async def _empty_channel_disconnect(self, g):
        await asyncio.sleep(Config.EMPTY_CH_TIMEOUT)
        vc = g.voice_client
        if not vc:
            self._empty_ch_tasks.pop(g.id, None)
            return
        if [m for m in vc.channel.members if not m.bot]:
            self._empty_ch_tasks.pop(g.id, None)
            return
        if vc.is_paused():
            self._empty_ch_tasks.pop(g.id, None)
            return
        p = self._players.pop(g.id, None)
        if p:
            p.stop()
        self._trigger_cancel(g.id)
        if vc.is_connected():
            await vc.disconnect()
        self._empty_ch_tasks.pop(g.id, None)

    @app_commands.command(name="join", description="Fai entrare il bot nel tuo canale vocale (o quello di un utente)")
    @app_commands.describe(utente="Utente di cui entrare nel canale (default: il tuo)")
    async def join(self, inter: discord.Interaction, utente: Optional[discord.Member] = None):
        target = utente or inter.user
        if not target.voice or not target.voice.channel:
            msg = f"{target.mention} non è in nessun canale vocale." if utente else "Devi essere in un canale vocale!"
            return await inter.response.send_message(embed=error_embed(msg), ephemeral=True)
        vc_ch = target.voice.channel
        vc = inter.guild.voice_client
        if vc:
            if vc.channel == vc_ch:
                return await inter.response.send_message(embed=error_embed(f"Sono già in **{vc_ch.name}**!"), ephemeral=True)
            await vc.move_to(vc_ch)
        else:
            await vc_ch.connect()
        await inter.response.send_message(embed=success_embed(f"Entrato in **{vc_ch.name}**."), ephemeral=True)
        log.info(tag("JOIN", f"{guild(inter.guild.name)}  →  {ch(vc_ch.name)}  (da {user(str(inter.user))})"))

    @app_commands.command(name="play", description="Riproduci da YouTube, Spotify, SoundCloud o testo (risultato diretto)")
    @app_commands.describe(query="Link o titolo della canzone / playlist / album")
    async def play(self, inter: discord.Interaction, query: str):
        t_cmd = time.perf_counter()
        query = _normalize_url_like(query)
        if not query:
            return await inter.response.send_message(
                embed=error_embed("Inserisci un link o una query valida."),
                ephemeral=True,
            )
        if self._is_duplicate_play(inter.guild_id, query):
            return await inter.response.send_message(
                embed=error_embed(
                    f"Richiesta duplicata rilevata: attendi ~{_PLAY_DEBOUNCE_WINDOW_SECONDS:.1f}s prima di rilanciare **/play**."
                ),
                ephemeral=True,
            )

        try:
            await inter.response.defer()
        except discord.NotFound:
            log.warning(tag("CMD", f"/play interaction scaduta prima del defer  {b(query)}"))
            return

        vc = inter.guild.voice_client
        if vc and vc.channel:
            vc_ch = vc.channel
        else:
            vc_ch = self._need_voice(inter)
            if not vc_ch:
                return await inter.edit_original_response(
                    embed=error_embed("Devi essere in un canale vocale per usare questo comando!"),
                )

        if is_spotify_artist_url(query):
            return await inter.edit_original_response(
                embed=error_embed(
                    "I link artista di Spotify non sono supportati qui.\n"
                    "Usa il comando `/artistshuffle` per riprodurre la radio di un artista! 🎨"
                ),
            )

        is_spotify_query = bool(_spotify_kind(query))
        if is_spotify_query and not Config.SPOTIFY_CLIENT_ID:
            return await inter.edit_original_response(
                embed=error_embed("Per Spotify configura SPOTIFY_CLIENT_ID nel .env"),
            )

        if _is_yt_channel_url(query):
            return await inter.edit_original_response(
                embed=error_embed("I link di canali YouTube non sono supportati."),
            )

        is_multi = _is_multi_url(query)

        if is_multi:
            vc, meta = await asyncio.gather(
                self._ensure_voice_client(inter, vc_ch),
                _fetch_playlist_meta(query),
            )
            nome, total = meta
            log.info(tag("CMD", f"/play playlist  {b(nome)}  total={total}  ({b(query)})"))

            gen    = SourceResolver.resolve_stream(query, inter.user.display_name, inter.user.id)
            await self._start_batch_stream(
                inter, vc, gen,
                nome=nome, total=total,
            )
            return

        vc = await self._ensure_voice_client(inter, vc_ch)

        player = self._player(inter.guild_id, inter.channel)

        if _is_text_search(query):
            t0 = time.perf_counter()
            try:
                results = await SourceResolver.resolve_choices(
                    query, inter.user.display_name, inter.user.id, n=1
                )
            except Exception as e:
                log.exception("resolve_choices error")
                return await inter.edit_original_response(embed=error_embed(str(e)))
            log.info(tag("CMD", f"/play direct  {b(query)}  {ms((time.perf_counter()-t0)*1000)}"))
            if not results:
                return await inter.edit_original_response(
                    embed=error_embed(f"Nessuna traccia trovata per: **{query}**")
                )
            track     = results[0]
            was_empty = not player.queue and not player.current
            position  = 0 if was_empty else (len(player.queue) + 1)
            if not player.queue.put(track):
                return await inter.edit_original_response(
                    embed=error_embed(f"Coda piena (max {Config.MAX_QUEUE} tracce).")
                )
            await inter.edit_original_response(
                embed=queue_notification_embed(track, position, inter.user)
            )
            await _maybe_start(player, vc, was_empty)
            log.info(tag("PERF", f"/play direct total={ms((time.perf_counter()-t_cmd)*1000)}"))

        else:
            t0 = time.perf_counter()
            try:
                tracks = await SourceResolver.resolve(
                    query, inter.user.display_name, inter.user.id
                )
            except Exception as e:
                log.exception("Resolve error")
                return await inter.edit_original_response(embed=error_embed("Errore: " + str(e)))
            log.info(tag("CMD", f"/play resolve  {b(query)}  {ms((time.perf_counter()-t0)*1000)}"))
            if not tracks:
                return await inter.edit_original_response(
                    embed=error_embed(f"Nessuna traccia trovata per: **{query}**")
                )
            was_empty = not player.queue and not player.current
            position  = 0 if was_empty else (len(player.queue) + 1)
            added     = player.queue.put_many(tracks)
            if added == 1:
                await inter.edit_original_response(
                    embed=queue_notification_embed(tracks[0], position, inter.user)
                )
            else:
                await inter.edit_original_response(
                    embed=discord.Embed(
                        description=f"📂 **{added}** tracce aggiunte in coda da {inter.user.mention}",
                        color=0x5865F2,
                    )
                )
            await _maybe_start(player, vc, was_empty)
            log.info(tag("PERF", f"/play resolve total={ms((time.perf_counter()-t_cmd)*1000)}"))

    @app_commands.command(name="search", description="Cerca una canzone e scegli la versione giusta tra i risultati")
    @app_commands.describe(query="Titolo o artista da cercare")
    async def search(self, inter: discord.Interaction, query: str):
        vc_ch = self._need_voice(inter)
        if not vc_ch:
            return await inter.response.send_message(
                embed=error_embed("Devi essere in un canale vocale!"), ephemeral=True
            )
        await inter.response.defer(ephemeral=True)
        t0 = time.perf_counter()
        try:
            results = await SourceResolver.resolve_choices(
                query, inter.user.display_name, inter.user.id, n=7
            )
        except Exception as e:
            log.exception("resolve_choices error")
            return await inter.followup.send(embed=error_embed(str(e)), ephemeral=True)
        log.info(tag("CMD", f"/search  {b(query)}  {ms((time.perf_counter()-t0)*1000)}"))
        if not results:
            return await inter.followup.send(
                embed=error_embed(f"Nessun risultato per: **{query}**"), ephemeral=True
            )
        player = self._player(inter.guild_id, inter.channel)
        embed  = discord.Embed(
            title="🔍 Scegli una versione",
            description=f"Risultati per: **{query}**\n{_EMBED_RULER}",
            color=0x5865F2,
        )
        view = _PlaySelectView(player, results, inter.channel, inter.user, vc_ch, query)
        await inter.followup.send(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="versions", description="Scegli una versione alternativa della traccia corrente")
    async def versions(self, inter: discord.Interaction):
        p = self._players.get(inter.guild_id)
        if not p or not p.current:
            return await inter.response.send_message(
                embed=error_embed("Nessuna traccia in riproduzione."), ephemeral=True
            )
        await inter.response.defer(ephemeral=True)
        track  = p.current
        search_query = (getattr(track, "origin_query", "") or "").strip()
        if not search_query:
            artist = (track.artist or "").split(",")[0].strip()
            search_query = f"{track.title} {artist}".strip()
        try:
            results = await SourceResolver.resolve_choices(
                search_query,
                track.requester, track.requester_id, n=5,
            )
        except Exception as e:
            log.exception("versions resolve_choices error")
            return await inter.followup.send(embed=error_embed(str(e)), ephemeral=True)
        if not results:
            return await inter.followup.send(
                embed=error_embed("Nessuna alternativa trovata."), ephemeral=True
            )
        embed = discord.Embed(
            title="🔀 Versioni alternative",
            description=f"In riproduzione: **{track.title}**\nScegli una versione diversa:",
            color=0x5865F2,
        )
        await inter.followup.send(embed=embed, view=_VersionView(p, results), ephemeral=True)

    async def _fill_queue(
        self,
        gen,
        player,
        channel,
        nome: str = "",
        requester: discord.Member = None,
        load_msg: discord.Message = None,
        first_already_added: bool = False,
        do_spotify_shuffle: bool = False,
        total: int = 0,
        edit_load_msg: bool = True,
        inter: discord.Interaction = None,
        cancel_event: asyncio.Event = None,
        cancel_view: "_CancelBatchView" = None,
    ):
        """Carica tracce in coda aggiornando la progress bar. Rispetta cancel_event."""
        player._loading_count += 1
        count        = 0
        added_so_far = 1 if first_already_added else 0
        UPDATE_EVERY = 3
        cancelled    = False
        t_batch      = time.perf_counter()

        try:
            async for track in gen:
                if cancel_event and cancel_event.is_set():
                    cancelled = True
                    log.info(tag("QUEUE", f"fill_queue annullato  [{nome}]  dopo {added_so_far} tracce"))
                    break

                if not player.queue.put(track):
                    log.warning(tag("WARN", f"Coda piena (MAX_QUEUE={Config.MAX_QUEUE}), tracce scartate"))
                    break
                count        += 1
                added_so_far += 1
                log.debug(tag("QUEUE", f"[{count+1:03d}] {b(track.title)}  —  {track.source}"))
                if added_so_far <= _BATCH_WARMUP_LIMIT:
                    asyncio.create_task(self._warmup_track_stream_url(track))
                if added_so_far % _QUEUE_PROGRESS_STEP == 0:
                    pct = f"{(100 * added_so_far / total):.0f}%" if total > 0 else "in corso"
                    log.info(tag("QUEUE", f"Progress  [{nome}]  {b(str(added_so_far))} tracce  ({pct})"))

                if requester and count % UPDATE_EVERY == 0:
                    loading_embed = _batch_loading_embed(
                        nome, requester, current=added_so_far, total=total
                    )
                    try:
                        if edit_load_msg and load_msg:
                            await load_msg.edit(embed=loading_embed)
                        elif inter:
                            await inter.edit_original_response(embed=loading_embed, view=cancel_view)
                    except Exception:
                        pass

        except Exception as e:
            log.error(tag("ERR", f"fill_queue: {e}"))
        finally:
            player._loading_count -= 1
            if player._loading_count == 0 and not player.current and not player.queue:
                player._arm_idle()

        if do_spotify_shuffle and not cancelled and len(player.queue) > 1:
            player.queue.spotify_shuffle()

        total_loaded = count + 1 if first_already_added else count
        elapsed = ms((time.perf_counter() - t_batch) * 1000)
        state = "annullato" if cancelled else "completato"
        log.info(tag("QUEUE", f"Batch {state}  [{nome}]  {b(str(total_loaded))} tracce  {elapsed}"))

        if cancel_view:
            cancel_view.stop_view()

        if cancelled:
            final_embed = _batch_cancelled_embed(nome or "Playlist", total_loaded, requester) if requester \
                else discord.Embed(description=f"❌ Caricamento annullato. **{total_loaded}** tracce in coda.", color=0xFF6B6B)
        else:
            final_embed = _batch_done_embed(nome or "Playlist", total_loaded, requester) if requester \
                else discord.Embed(description=f"✅ Aggiunte **{total_loaded}** tracce in coda.", color=0x57F287)

        try:
            if edit_load_msg and load_msg:
                await load_msg.edit(embed=final_embed, view=None)
            elif inter:
                await inter.edit_original_response(embed=final_embed, view=None)
            else:
                await channel.send(embed=final_embed)
        except Exception:
            await channel.send(embed=final_embed)

    @app_commands.command(
        name="artistshuffle",
        description="Emula la radio artista di Spotify: top tracks + raccomandazioni, mischiati in modo intelligente"
    )
    @app_commands.describe(nome="Nome dell'artista", quantita="Quante tracce (1-50, default 20)")
    async def artistshuffle(
        self, inter: discord.Interaction,
        nome: str,
        quantita: app_commands.Range[int, 1, 50] = 20
    ):
        await inter.response.defer()

        vc_ch = self._need_voice(inter)
        if not vc_ch:
            return await inter.edit_original_response(
                embed=error_embed("Devi essere in un canale vocale!")
            )

        vc = await self._ensure_voice_client(inter, vc_ch, allow_move=True)

        gen = SourceResolver.resolve_artist_stream(
            nome, inter.user.display_name, inter.user.id, limit=quantita
        )

        await self._start_batch_stream(
            inter, vc, gen,
            nome=nome, total=quantita,
            do_spotify_shuffle=True,
        )

    @app_commands.command(name="skip", description="Salta la traccia corrente")
    async def skip(self, inter: discord.Interaction):
        p = self._players.get(inter.guild_id)
        if not p or not p.current:
            return await inter.response.send_message(
                embed=error_embed("Niente in riproduzione!"), ephemeral=True
            )
        skipped_title = p.current.title
        p.skip()
        await inter.response.send_message(
            embed=discord.Embed(
                description=f"⏭️ **{skipped_title}** saltata da {inter.user.mention}",
                color=0x5865F2,
            )
        )

    @app_commands.command(name="seek", description="Vai avanti/indietro di N secondi (es. +10 o -15)")
    @app_commands.describe(secondi="Secondi relativi (negativo = indietro, positivo = avanti)")
    async def seek(self, inter: discord.Interaction, secondi: app_commands.Range[int, -600, 600]):
        p = self._players.get(inter.guild_id)
        if not p or not p.current:
            return await inter.response.send_message(
                embed=error_embed("Niente in riproduzione!"), ephemeral=True
            )
        if secondi == 0:
            return await inter.response.send_message(
                embed=error_embed("Specifica un valore diverso da 0."), ephemeral=True
            )
        await inter.response.defer(ephemeral=True)
        ok = await p.seek_relative(float(secondi))
        if not ok:
            return await inter.edit_original_response(
                embed=error_embed("Seek non è disponibile in questo momento.")
            )
        sign = "+" if secondi > 0 else ""
        await inter.edit_original_response(
            embed=success_embed(f"Seek applicato: **{sign}{secondi}s** (ora a ~`{int(p.position)}s`).")
        )

    @app_commands.command(name="skipto", description="Salta direttamente a una traccia specifica in coda")
    @app_commands.describe(posizione="Posizione in coda (1 = prossima traccia)")
    async def skipto(self, inter: discord.Interaction, posizione: app_commands.Range[int, 1, 500]):
        p = self._players.get(inter.guild_id)
        if not p or not p.current:
            return await inter.response.send_message(
                embed=error_embed("Niente in riproduzione!"), ephemeral=True
            )
        if posizione > len(p.queue):
            return await inter.response.send_message(
                embed=error_embed(f"La coda ha solo **{len(p.queue)}** tracce."), ephemeral=True
            )
        removed = p.queue.skipto(posizione - 1)
        p.skip()
        await inter.response.send_message(
            embed=discord.Embed(
                description=f"⏭️ Saltate **{removed}** tracce da {inter.user.mention}",
                color=0x5865F2,
            )
        )

    @app_commands.command(name="pause", description="Pausa")
    async def pause(self, inter: discord.Interaction):
        p = self._players.get(inter.guild_id)
        if not p or not p.current:
            return await inter.response.send_message(
                embed=error_embed("Niente in riproduzione!"), ephemeral=True
            )
        p.pause()
        await inter.response.send_message(embed=success_embed("In pausa."), ephemeral=True)

    @app_commands.command(name="resume", description="Riprendi")
    async def resume(self, inter: discord.Interaction):
        p = self._players.get(inter.guild_id)
        if not p:
            return await inter.response.send_message(
                embed=error_embed("Niente da riprendere!"), ephemeral=True
            )
        p.resume()
        await inter.response.send_message(embed=success_embed("Riproduzione ripresa."), ephemeral=True)

    @app_commands.command(name="autoplay", description="Attiva/disattiva autoplay quando la coda finisce")
    async def autoplay(self, inter: discord.Interaction):
        p = self._players.get(inter.guild_id)
        if not p:
            return await inter.response.send_message(
                embed=error_embed("Nessun player attivo."), ephemeral=True
            )
        await inter.response.send_message(
            embed=_autoplay_status_embed(p.autoplay_enabled),
            view=_AutoplayView(p, inter.user.id),
            ephemeral=True,
        )

    @app_commands.command(name="stop", description="Ferma, svuota la coda e disconnetti")
    async def stop(self, inter: discord.Interaction):
        p  = self._players.get(inter.guild_id)
        vc = inter.guild.voice_client
        if not p and not vc:
            return await inter.response.send_message(
                embed=error_embed("Niente da fermare!"), ephemeral=True
            )
        self._trigger_cancel(inter.guild_id)
        if p:
            await p._delete_player_msg()
            p.stop()
            self._players.pop(inter.guild_id, None)
        self._cancel_empty_task(inter.guild_id)
        if vc:
            await vc.disconnect()
        await inter.response.send_message(
            embed=discord.Embed(
                description=f"⏹️ Riproduzione interrotta da {inter.user.mention}",
                color=0xFF0000,
            )
        )
        log.info(tag("DISC", f"{guild(inter.guild.name)}  stop da {user(str(inter.user))}"))

    @app_commands.command(name="clearqueue", description="Svuota la coda (traccia corrente continua)")
    async def clearqueue(self, inter: discord.Interaction):
        p = self._players.get(inter.guild_id)
        if not p or not len(p.queue):
            return await inter.response.send_message(
                embed=error_embed("La coda è già vuota."), ephemeral=True
            )
        count = len(p.queue)
        p.queue.clear()
        await inter.response.send_message(
            embed=success_embed(f"Coda svuotata: **{count}** tracce rimosse."), ephemeral=True
        )

    @app_commands.command(name="queue", description="Visualizza la coda con navigazione")
    async def queue_cmd(self, inter: discord.Interaction):
        p = self._players.get(inter.guild_id)
        if not p or (not p.current and not p.queue):
            return await inter.response.send_message(
                embed=error_embed("La coda è vuota."), ephemeral=True
            )
        view = QueueView(p, page=0)
        await inter.response.send_message(embed=queue_embed(p, 0), view=view)
        view._message = await inter.original_response()

    @app_commands.command(name="nowplaying", description="Mostra la traccia corrente con i controlli")
    async def nowplaying(self, inter: discord.Interaction):
        p = self._players.get(inter.guild_id)
        if not p or not p.current:
            return await inter.response.send_message(
                embed=error_embed("Niente in riproduzione!"), ephemeral=True
            )
        await inter.response.defer()
        await inter.delete_original_response()
        await p.send_player_message(inter.channel)

    @app_commands.command(name="loop", description="Modalità loop")
    @app_commands.choices(modalita=[
        app_commands.Choice(name="Off",     value="off"),
        app_commands.Choice(name="Traccia", value="track"),
        app_commands.Choice(name="Coda",    value="queue"),
    ])
    async def loop(self, inter: discord.Interaction, modalita: str):
        p = self._players.get(inter.guild_id)
        if not p:
            return await inter.response.send_message(
                embed=error_embed("Nessun player."), ephemeral=True
            )
        p.queue.loop_mode = modalita
        labels = {"off": "Off", "track": "Traccia", "queue": "Coda"}
        await inter.response.send_message(
            embed=success_embed(f"Loop: **{labels[modalita]}**"), ephemeral=True
        )
        await p._update_msg_inplace()

    @app_commands.command(name="shuffle", description="Attiva/disattiva la modalità shuffle")
    async def shuffle(self, inter: discord.Interaction):
        p = self._players.get(inter.guild_id)
        if not p:
            return await inter.response.send_message(
                embed=error_embed("Nessun player attivo."), ephemeral=True
            )
        p.queue.shuffle_mode = not p.queue.shuffle_mode
        if p.queue.shuffle_mode and len(p.queue) > 1:
            p.queue.shuffle()
        stato = "🔀 Shuffle **ON**" if p.queue.shuffle_mode else "➡️ Shuffle **OFF**"
        await inter.response.send_message(embed=success_embed(stato), ephemeral=True)
        await p._update_msg_inplace()

    @app_commands.command(name="smartshuffle", description="Mischia la coda alternando gli artisti (stile Spotify)")
    async def smartshuffle(self, inter: discord.Interaction):
        p = self._players.get(inter.guild_id)
        if not p or not len(p.queue):
            return await inter.response.send_message(
                embed=error_embed("La coda è vuota."), ephemeral=True
            )
        p.queue.spotify_shuffle()
        await inter.response.send_message(
            embed=success_embed("🎲 Coda riordinata stile Spotify! Gli artisti ora si alternano."),
            ephemeral=True
        )

    @app_commands.command(name="remove", description="Rimuovi una traccia dalla coda")
    @app_commands.describe(posizione="Posizione (1-based)")
    async def remove(self, inter: discord.Interaction, posizione: int):
        p = self._players.get(inter.guild_id)
        if not p:
            return await inter.response.send_message(
                embed=error_embed("Nessun player."), ephemeral=True
            )
        removed = p.queue.remove(posizione - 1)
        if removed:
            await inter.response.send_message(
                embed=success_embed(f"Rimosso: **{removed.title}**"), ephemeral=True
            )
        else:
            await inter.response.send_message(
                embed=error_embed("Posizione non valida!"), ephemeral=True
            )

    @app_commands.command(name="move", description="Sposta una traccia in coda da una posizione a un'altra")
    @app_commands.describe(da="Posizione attuale della traccia (1-based)", a="Nuova posizione (1-based)")
    async def move(self, inter: discord.Interaction, da: int, a: int):
        p = self._players.get(inter.guild_id)
        if not p or not len(p.queue):
            return await inter.response.send_message(
                embed=error_embed("La coda è vuota."), ephemeral=True
            )
        n = len(p.queue)
        if not (1 <= da <= n and 1 <= a <= n):
            return await inter.response.send_message(
                embed=error_embed(f"Posizioni non valide. La coda ha **{n}** tracce."), ephemeral=True
            )
        if da == a:
            return await inter.response.send_message(
                embed=error_embed("La traccia è già in quella posizione."), ephemeral=True
            )
        track = p.queue.move(da - 1, a - 1)
        if track:
            await inter.response.send_message(
                embed=success_embed(f"↕️ **{track.title}** spostata da pos. **{da}** → **{a}**"),
                ephemeral=True
            )
        else:
            await inter.response.send_message(
                embed=error_embed("Impossibile spostare la traccia."), ephemeral=True
            )

    @app_commands.command(name="history", description="Ultime 10 tracce riprodotte")
    async def history(self, inter: discord.Interaction):
        p = self._players.get(inter.guild_id)
        if not p or not p.queue.history:
            return await inter.response.send_message(
                embed=error_embed("Nessuna cronologia."), ephemeral=True
            )
        hist  = list(reversed(list(p.queue.history)[-10:]))
        lines = [
            f"`{i+1}.` [{t.title}]({t.webpage_url})" if t.webpage_url else f"`{i+1}.` {t.title}"
            for i, t in enumerate(hist)
        ]
        await inter.response.send_message(
            embed=discord.Embed(
                title="Cronologia (ultime 10)", description="\n".join(lines), color=0x5865F2
            )
        )

    @app_commands.command(name="disconnect", description="Disconnetti il bot dal canale vocale")
    async def disconnect(self, inter: discord.Interaction):
        vc = inter.guild.voice_client
        if not vc:
            return await inter.response.send_message(
                embed=error_embed("Non sono in nessun canale vocale."), ephemeral=True
            )
        self._trigger_cancel(inter.guild_id)
        p = self._players.pop(inter.guild_id, None)
        if p:
            p.stop()
        self._cancel_empty_task(inter.guild_id)
        await vc.disconnect()
        await inter.response.send_message(embed=success_embed("Disconnesso."), ephemeral=True)
        log.info(tag("DISC", f"{guild(inter.guild.name)}  disconnect da {user(str(inter.user))}"))


async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))
