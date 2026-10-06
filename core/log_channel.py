"""Inoltra gli errori del bot nel canale scelto con /set_log_channel.

Ogni record ERROR dei logger "pitonazz.*" finisce in una coda; un task sul
loop del bot li raggruppa e li invia. Lo stesso errore (testo senza numeri)
non viene ripetuto prima di DEDUP_SECONDS, cosi' un problema che si ripete
a ogni /play non riempie il canale. I record possono arrivare da qualsiasi
thread (yt-dlp, callback FFmpeg): l'handler li passa al loop in modo sicuro.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time

import discord

from core.bot_config import cfg

BATCH_SECONDS = 5.0
DEDUP_SECONDS = 600.0
_MAX_MESSAGE = 1900
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_NUMBERS = re.compile(r"\d+")

log = logging.getLogger("pitonazz.log_channel")


def _plain(text: str) -> str:
    return _ANSI.sub("", text)


class LogChannelHandler(logging.Handler):
    def __init__(self, bot: discord.Client, loop: asyncio.AbstractEventLoop):
        super().__init__(level=logging.ERROR)
        self.bot = bot
        self.loop = loop
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self._last_sent: dict[str, float] = {}
        self._task: asyncio.Task | None = None
        self.setFormatter(logging.Formatter("%(name)s · %(message)s"))

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = self.loop.create_task(self._run(), name="log-channel")

    def emit(self, record: logging.LogRecord) -> None:
        # Gli errori dell'invio stesso non devono tornare nel canale.
        if record.name == log.name or cfg.log_channel_id is None:
            return
        try:
            text = _plain(self.format(record))
        except Exception:
            return
        try:
            self.loop.call_soon_threadsafe(self.queue.put_nowait, text)
        except RuntimeError:
            pass  # loop chiuso: il bot si sta spegnendo

    def _is_duplicate(self, text: str, now: float) -> bool:
        key = _NUMBERS.sub("#", text)[:300]
        last = self._last_sent.get(key)
        if last is not None and now - last < DEDUP_SECONDS:
            return True
        self._last_sent[key] = now
        if len(self._last_sent) > 500:
            cutoff = now - DEDUP_SECONDS
            self._last_sent = {k: t for k, t in self._last_sent.items() if t >= cutoff}
        return False

    async def _run(self) -> None:
        while True:
            lines = [await self.queue.get()]
            await asyncio.sleep(BATCH_SECONDS)
            while not self.queue.empty():
                lines.append(self.queue.get_nowait())
            now = time.monotonic()
            fresh = [line for line in lines if not self._is_duplicate(line, now)]
            if fresh:
                await self._send(fresh)

    async def _send(self, lines: list[str]) -> None:
        channel_id = cfg.log_channel_id
        channel = self.bot.get_channel(channel_id) if channel_id else None
        if channel is None:
            return
        body = "\n".join(line[:600] for line in lines)
        if len(body) > _MAX_MESSAGE:
            body = body[:_MAX_MESSAGE] + "\n…"
        try:
            await channel.send(f"⚠️ **Errori del bot**\n```\n{body}\n```",
                               allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException as exc:
            log.warning(f"invio al canale log fallito: {exc}")


def install_log_channel(bot: discord.Client) -> LogChannelHandler:
    """Aggancia l'handler al logger "pitonazz" (una sola volta) e avvia l'invio."""
    root = logging.getLogger("pitonazz")
    handler = next((h for h in root.handlers if isinstance(h, LogChannelHandler)), None)
    if handler is None:
        handler = LogChannelHandler(bot, asyncio.get_running_loop())
        root.addHandler(handler)
    handler.start()
    return handler
