from __future__ import annotations
import discord
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.player import MusicPlayer


def _fmt_dur(seconds: int) -> str:
    if seconds <= 0:
        return "LIVE"
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def now_playing_embed(player: "MusicPlayer") -> discord.Embed:
    t = player.current
    if not t:
        return discord.Embed(description="Niente in riproduzione.", color=0x5865F2)

    status = "⏸️ In pausa" if player.is_paused else "▶️ In riproduzione"

    embed = discord.Embed(title=t.title, url=t.webpage_url, color=0x5865F2)
    embed.set_author(name=f"🎵 {status}")
    if t.thumbnail:
        embed.set_thumbnail(url=t.thumbnail)

    requester_val = f"<@{t.requester_id}>" if t.requester_id else t.requester
    artist_val    = f"`{t.artist}`" if t.artist else "`Sconosciuto`"
    dur_val       = f"`{_fmt_dur(t.duration)}`"

    embed.add_field(name="⏱️ Durata",       value=dur_val,       inline=True)
    embed.add_field(name="🎤 Artista",      value=artist_val,    inline=True)
    embed.add_field(name="👤 Richiesto da", value=requester_val, inline=False)
    return embed


def queue_notification_embed(
    track,
    position: int,
    requester: discord.Member,
    collection_name: str = "",
    collection_total: int = 0,
) -> discord.Embed:
    """
    Embed di risposta al /play.
    position=0  →  brano avviato subito (coda era vuota)
    position>=1 →  brano aggiunto in coda alla posizione indicata
    """
    dur        = _fmt_dur(track.duration) if track.duration else "?"
    if collection_name:
        context_label = collection_name.strip()
    else:
        context_label = (getattr(track, "artist", "") or "").strip()
    url        = getattr(track, "webpage_url", "") or ""
    track_name = track.title  # rinominato per evitare shadow del builtin title()

    track_line = f"[{track_name}]({url})" if url else f"**{track_name}**"
    if context_label:
        track_line += f" | {context_label}"
    if collection_name and collection_total > 0:
        track_line += f" • {collection_total} tracce"
    track_line += f"  `[{dur}]`"

    if position == 0:
        embed_title = "✅ ▶️ In riproduzione adesso"
    else:
        embed_title = f"✅ ▶️ Aggiunto in coda #{position}"

    embed = discord.Embed(
        title=embed_title,
        description=track_line,
        color=0x5865F2,
    )
    author_name = collection_name or requester.display_name
    embed.set_author(name=author_name, icon_url=requester.display_avatar.url)
    if collection_name:
        embed.set_footer(text=f"Richiesto da {requester.display_name}")
    return embed


def _queue_line(idx: int, t) -> str:
    req   = f"<@{t.requester_id}>" if t.requester_id else t.requester
    short_title = t.title[:60] + ("…" if len(t.title) > 60 else "")
    url   = t.webpage_url or ""
    dur   = _fmt_dur(t.duration)
    if url:
        return f"`{idx}.` [{short_title}]({url}) — `{dur}` • {req}"
    return f"`{idx}.` {short_title} — `{dur}` • {req}"


def queue_embed(player: "MusicPlayer", page: int = 0) -> discord.Embed:
    items    = player.queue.items
    per_page = 10
    start    = page * per_page
    page_items  = items[start : start + per_page]
    total_pages = max(1, (len(items) + per_page - 1) // per_page)

    embed = discord.Embed(title="📋 Coda musicale", color=0x5865F2)

    if player.current:
        t   = player.current
        req = f"<@{t.requester_id}>" if t.requester_id else t.requester
        short_title = t.title[:60] + ("…" if len(t.title) > 60 else "")
        url = t.webpage_url or ""
        val = f"[{short_title}]({url}) — `{_fmt_dur(t.duration)}` • {req}" if url \
              else f"{short_title} — `{_fmt_dur(t.duration)}` • {req}"
        embed.add_field(
            name="▶️ Ora in riproduzione",
            value=val[:1024],
            inline=False,
        )

    if page_items:
        lines = [_queue_line(start + i + 1, t) for i, t in enumerate(page_items)]
        embed.description = "\n".join(lines)[:4096]
    else:
        embed.description = "La coda è vuota."

    embed.set_footer(text=f"Pagina {page + 1}/{total_pages} • {len(items)} in coda")
    return embed


def error_embed(desc: str) -> discord.Embed:
    return discord.Embed(title="❌ Errore", description=desc, color=0xFF0000)


def success_embed(desc: str) -> discord.Embed:
    return discord.Embed(description=f"✅ {desc}", color=0x57F287)
