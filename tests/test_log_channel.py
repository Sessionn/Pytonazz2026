"""
/set_log_channel: gli ERROR dei logger pitonazz.* arrivano nel canale,
raggruppati, senza colori ANSI e senza ripetere lo stesso errore.

Esegui dalla root del progetto con:
    python tests/test_log_channel.py
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.log_channel as log_channel
from core.bot_config import cfg

CHANNEL_ID = 42


class FakeChannel:
    def __init__(self):
        self.messages: list[str] = []

    async def send(self, content, allowed_mentions=None):
        self.messages.append(content)


class FakeBot:
    def __init__(self, channel):
        self.channel = channel

    def get_channel(self, channel_id):
        return self.channel if channel_id == CHANNEL_ID else None


async def main() -> None:
    log_channel.BATCH_SECONDS = 0.05
    channel = FakeChannel()
    saved = cfg._data.get("log_channel_id")
    cfg._data["log_channel_id"] = CHANNEL_ID
    handler = log_channel.install_log_channel(FakeBot(channel))
    logger = logging.getLogger("pitonazz.test")
    try:
        logger.error("\x1b[31mERR\x1b[0m FFmpeg error: code 1 at 12:00")
        logger.error("\x1b[31mERR\x1b[0m FFmpeg error: code 1 at 12:05")  # stesso errore, numeri diversi
        threading.Thread(target=logger.error, args=("errore da un thread",)).start()
        logger.warning("solo un warning")
        await asyncio.sleep(0.3)

        assert len(channel.messages) == 1, channel.messages
        body = channel.messages[0]
        assert "FFmpeg error" in body and "\x1b[" not in body
        assert body.count("FFmpeg error") == 1, body
        assert "errore da un thread" in body
        assert "solo un warning" not in body

        cfg._data["log_channel_id"] = None
        logger.error("canale non impostato")
        await asyncio.sleep(0.2)
        assert len(channel.messages) == 1
    finally:
        cfg._data["log_channel_id"] = saved
        logging.getLogger("pitonazz").removeHandler(handler)
        handler._task.cancel()


asyncio.run(main())
print("OK: errori inoltrati al canale log, raggruppati e senza duplicati")
