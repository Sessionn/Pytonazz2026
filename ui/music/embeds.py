from __future__ import annotations

from typing import TYPE_CHECKING

import discord

if TYPE_CHECKING:
    from core.music.player import MusicPlayer


_EMBED_RULER = "`" + ("-" * 54) + "`"


def _fmt_dur(seconds: int) -> str:
    if seconds <= 0:
        return "LIVE"
    minutes, secs = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def _safe_http_url(url: str) -> str:
    url = (url or "").strip()
    return url if url.startswith(("http://", "https://")) else ""


def _track_web_url(track) -> str:
    return _safe_http_url(getattr(track, "webpage_url", "") or "")


def now_playing_embed(player: "MusicPlayer") -> discord.Embed:
    track = player.current
    if not track:
        return discord.Embed(description="Niente in riproduzione.", color=0x5865F2)

    status = "In pausa" if player.is_paused else "In riproduzione"
    embed = discord.Embed(title=track.title, url=_track_web_url(track) or None, color=0x5865F2)
    embed.set_author(name=f"Musica | {status}")
    if track.thumbnail:
        embed.set_thumbnail(url=track.thumbnail)

    requester_val = f"<@{track.requester_id}>" if track.requester_id else track.requester
    artist_val = f"`{track.artist}`" if track.artist else "`Sconosciuto`"
    dur_val = f"`{_fmt_dur(track.duration)}`"

    embed.add_field(name="Durata", value=dur_val, inline=True)
    embed.add_field(name="Artista", value=artist_val, inline=True)
    embed.add_field(name="Richiesto da", value=requester_val, inline=False)
    return embed


def queue_notification_embed(
    track,
    position: int,
    requester: discord.Member,
    collection_name: str = "",
    collection_total: int = 0,
) -> discord.Embed:
    dur = _fmt_dur(track.duration) if track.duration else "?"
    context_label = collection_name.strip() if collection_name else (getattr(track, "artist", "") or "").strip()
    url = _track_web_url(track)
    track_line = f"[{track.title}]({url})" if url else f"**{track.title}**"

    if context_label:
        track_line += f" | {context_label}"
    if collection_name and collection_total > 0:
        track_line += f" | {collection_total} tracce"
    track_line += f" `[{dur}]`"

    title = "In riproduzione adesso" if position == 0 else f"Aggiunto in coda #{position}"
    embed = discord.Embed(title=title, description=track_line, color=0x5865F2)
    author_name = collection_name or requester.display_name
    embed.set_author(name=author_name, icon_url=requester.display_avatar.url)
    if collection_name:
        embed.set_footer(text=f"Richiesto da {requester.display_name}")
    return embed


def _queue_line(idx: int, track) -> str:
    requester = f"<@{track.requester_id}>" if track.requester_id else track.requester
    short_title = track.title[:60] + ("..." if len(track.title) > 60 else "")
    url = _track_web_url(track)
    dur = _fmt_dur(track.duration)
    if url:
        return f"`{idx}.` [{short_title}]({url}) - `{dur}` | {requester}"
    return f"`{idx}.` {short_title} - `{dur}` | {requester}"


def queue_embed(player: "MusicPlayer", page: int = 0) -> discord.Embed:
    items = player.queue.items
    per_page = 10
    start = page * per_page
    page_items = items[start : start + per_page]
    total_pages = max(1, (len(items) + per_page - 1) // per_page)

    embed = discord.Embed(title="Coda musicale", color=0x5865F2)

    if player.current:
        track = player.current
        requester = f"<@{track.requester_id}>" if track.requester_id else track.requester
        short_title = track.title[:60] + ("..." if len(track.title) > 60 else "")
        url = _track_web_url(track)
        value = (
            f"[{short_title}]({url}) - `{_fmt_dur(track.duration)}` | {requester}"
            if url
            else f"{short_title} - `{_fmt_dur(track.duration)}` | {requester}"
        )
        embed.add_field(name="Ora in riproduzione", value=value[:1024], inline=False)

    embed.description = (
        "\n".join(_queue_line(start + index + 1, track) for index, track in enumerate(page_items))[:4096]
        if page_items
        else "La coda e' vuota."
    )
    embed.set_footer(text=f"Pagina {page + 1}/{total_pages} | {len(items)} in coda")
    return embed


def error_embed(desc: str) -> discord.Embed:
    return discord.Embed(title="Errore", description=desc, color=0xFF0000)


def success_embed(desc: str) -> discord.Embed:
    return discord.Embed(description=f"OK {desc}", color=0x57F287)


def batch_added_embed(count: int, requester: discord.Member) -> discord.Embed:
    return discord.Embed(
        description=f"{count} tracce aggiunte in coda da {requester.mention}",
        color=0x5865F2,
    )


def skipped_track_embed(track_title: str, requester: discord.Member) -> discord.Embed:
    return discord.Embed(
        description=f"Traccia saltata: **{track_title}** da {requester.mention}",
        color=0x5865F2,
    )


def skipto_result_embed(removed: int, requester: discord.Member) -> discord.Embed:
    return discord.Embed(
        description=f"Saltate **{removed}** tracce da {requester.mention}",
        color=0x5865F2,
    )


def stopped_embed(requester: discord.Member) -> discord.Embed:
    return discord.Embed(
        description=f"Riproduzione interrotta da {requester.mention}",
        color=0xFF0000,
    )


def search_results_embed(query: str) -> discord.Embed:
    return discord.Embed(
        title="Scegli una versione",
        description=f"Risultati per: **{query}**\n{_EMBED_RULER}",
        color=0x5865F2,
    )


def versions_embed(track_title: str) -> discord.Embed:
    return discord.Embed(
        title="Versioni alternative",
        description=f"In riproduzione: **{track_title}**\nScegli una versione diversa:",
        color=0x5865F2,
    )


def history_embed(tracks: list) -> discord.Embed:
    lines = [
        f"`{i + 1}.` [{track.title}]({_track_web_url(track)})"
        if _track_web_url(track)
        else f"`{i + 1}.` {track.title}"
        for i, track in enumerate(tracks)
    ]
    return discord.Embed(
        title="Cronologia (ultime 10)",
        description="\n".join(lines),
        color=0x5865F2,
    )
