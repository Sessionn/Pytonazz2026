"""Attende che un link audio YouTube appena generato smetta di rispondere 403.

Misurato sulla VM (2026-10-06): circa un link googlevideo su tre, usato
subito dopo l'estrazione, risponde 403 per 1.5-2 s e poi funziona. FFmpeg
ritenta dopo 0, 1 e 3 secondi, quindi l'avvio del brano restava muto per
~4.2 s. Qui si ritenta ogni 0.25 s con una richiesta minima (1 byte) e FFmpeg
parte appena il link risponde. Qualsiasi altro esito (errore di rete, 404,
timeout) lascia decidere a FFmpeg come prima: questo controllo non blocca mai
un brano, al massimo lo anticipa. Si controllano solo i link nati da pochi
secondi (eta' ricavata da "expire", sempre emissione + 6 h): quelli dal DB,
dal prefetch o riusati nel seek partono subito senza alcuna richiesta.
"""
from __future__ import annotations

import asyncio
import logging
import time
import urllib.parse
from collections import OrderedDict

import aiohttp

from config import Config
from core.log_colors import ms, tag

log = logging.getLogger("pitonazz.stream_ready")

READY_TIMEOUT_SECONDS = 3.0
FRESH_SECONDS = 15
_LINK_LIFETIME_SECONDS = 6 * 60 * 60
RETRY_INTERVAL_SECONDS = 0.25
_REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=2.0)
_READY_CACHE_MAX = 64
_ready_urls: "OrderedDict[str, None]" = OrderedDict()


def _needs_check(url: str, now: float | None = None) -> bool:
    try:
        parts = urllib.parse.urlsplit(url)
        host = parts.hostname or ""
        expire = urllib.parse.parse_qs(parts.query).get("expire", [""])[0]
    except ValueError:
        return False
    if not host.endswith(".googlevideo.com"):
        return False
    if not expire.isdigit():
        return True  # eta' sconosciuta: meglio controllare
    now = time.time() if now is None else now
    age = _LINK_LIFETIME_SECONDS - (int(expire) - now)
    return age < FRESH_SECONDS


def _remember(url: str) -> None:
    _ready_urls[url] = None
    _ready_urls.move_to_end(url)
    while len(_ready_urls) > _READY_CACHE_MAX:
        _ready_urls.popitem(last=False)


async def wait_until_ready(url: str, *, timeout: float = READY_TIMEOUT_SECONDS) -> bool:
    """True se il link risponde (o non serve controllarlo), False se resta 403."""
    if not url or not _needs_check(url) or url in _ready_urls:
        return True
    proxy = (Config._ffmpeg_proxy or "").strip() or None  # stesso IP di FFmpeg: i link sono legati all'IP
    started = time.perf_counter()
    deadline = started + timeout
    attempts = 0
    try:
        async with aiohttp.ClientSession(timeout=_REQUEST_TIMEOUT) as session:
            while True:
                attempts += 1
                async with session.get(url, headers={"Range": "bytes=0-0"}, proxy=proxy) as response:
                    status = response.status
                if status != 403:
                    if status in (200, 206):
                        _remember(url)
                    if attempts > 1:
                        elapsed = (time.perf_counter() - started) * 1000
                        log.info(tag("STREAM", f"link pronto dopo {attempts - 1}x 403  {ms(elapsed)}"))
                    return True
                if time.perf_counter() + RETRY_INTERVAL_SECONDS > deadline:
                    log.warning(tag("STREAM", f"link ancora 403 dopo {ms(timeout * 1000)}: decide FFmpeg"))
                    return False
                await asyncio.sleep(RETRY_INTERVAL_SECONDS)
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
        log.debug(tag("STREAM", f"controllo link saltato: {type(exc).__name__}"))
        return True
