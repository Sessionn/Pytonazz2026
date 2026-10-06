"""Bounded playback probe worker. Never prints cookies or signed stream URLs.

Uses the bot's own YDL_OPTIONS/FFMPEG_OPTIONS so the test fails exactly when
real playback would, then decodes one second of audio with FFmpeg.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict
from http.cookiejar import MozillaCookieJar
from pathlib import Path

from monitoring.cookie_watchdog import CookieProbeResult, classify_cookie_probe_output


def _youtube_cookies(cookie_file: str):
    jar = MozillaCookieJar(cookie_file)
    with contextlib.redirect_stderr(io.StringIO()):
        jar.load(ignore_discard=True, ignore_expires=True)
    return [c for c in jar if c.domain.lstrip(".") == "youtube.com" or c.domain.endswith(".youtube.com")]


def probe(cookie_file: str, test_url: str) -> CookieProbeResult:
    from config import Config
    import yt_dlp

    if cookie_file:
        if not Path(cookie_file).is_file():
            return CookieProbeResult(False, "youtube_cookie", "File cookie non trovato.")
        try:
            cookies = _youtube_cookies(cookie_file)
        except Exception:
            return CookieProbeResult(False, "youtube_cookie", "File cookie illeggibile o formato Netscape non valido.")
        if not cookies or all(c.is_expired() for c in cookies):
            return CookieProbeResult(False, "youtube_cookie", "Cookie YouTube assenti o tutti scaduti.")

    messages: list[str] = []

    class Logger:
        def debug(self, message):
            pass

        def warning(self, message):
            messages.append(message)

        error = warning

    # yt-dlp may save its cookie jar on close: probe a private copy so the
    # test cannot rewrite the file the live resolver is using.
    with tempfile.TemporaryDirectory(prefix="pytonazz-audio-") as temp:
        copied = None
        if cookie_file:
            copied = str(Path(temp) / "cookies.txt")
            shutil.copyfile(cookie_file, copied)
            os.chmod(copied, 0o600)
        opts = {**Config.YDL_OPTIONS, "cookiefile": copied, "logger": Logger(),
                "noplaylist": True, "ignoreerrors": False, "socket_timeout": 8}
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(test_url, download=False)
            if not isinstance(info, dict) or not info.get("url"):
                return CookieProbeResult(False, "error", "Estrazione senza URL audio.")
            command = [Config.FFMPEG_PATH or "ffmpeg", "-v", "error",
                       *shlex.split(Config.FFMPEG_OPTIONS["before_options"]),
                       "-i", info["url"], "-t", "1", "-vn", "-ac", "1", "-ar", "8000", "-f", "s16le", "pipe:1"]
            result = subprocess.run(command, capture_output=True, timeout=20)
            if result.returncode or not result.stdout:
                return classify_cookie_probe_output(
                    returncode=1, output=result.stderr.decode(errors="replace") or "Nessun campione audio decodificato.")
            if any("cookies" in m.lower() and any(w in m.lower() for w in ("expired", "rotated", "invalid")) for m in messages):
                return CookieProbeResult(False, "youtube_cookie", "Audio disponibile ma yt-dlp segnala cookie scaduti/ruotati.")
            return CookieProbeResult(True, "cookie_ok", "Audio OK · campione decodificato")
        except subprocess.TimeoutExpired:
            return CookieProbeResult(False, "error", "FFmpeg: test audio scaduto dopo 20 secondi.")
        except Exception as exc:
            return classify_cookie_probe_output(returncode=1, output="\n".join([*messages, str(exc)]))


if __name__ == "__main__":
    payload = json.load(sys.stdin)
    # Keep the worker protocol clean even if a third-party component prints.
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        outcome = probe(payload["cookie_file"], payload["test_url"])
    print(json.dumps(asdict(outcome)))
