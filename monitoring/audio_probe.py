"""Bounded startup/watchdog worker. Never prints cookies or signed stream URLs."""
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


def probe(cookie_file: str, test_url: str) -> CookieProbeResult:
    from config import Config
    import yt_dlp

    checks = []

    def finish(ok, rule_name, detail):
        return CookieProbeResult(ok, rule_name, detail, list(checks))

    if cookie_file:
        if not Path(cookie_file).is_file():
            return finish(False, "youtube_cookie", "File cookie configurato non trovato.")
        try:
            jar = MozillaCookieJar(cookie_file)
            with contextlib.redirect_stderr(io.StringIO()):
                jar.load(ignore_discard=True, ignore_expires=True)
            cookies = [c for c in jar if c.domain.lstrip(".") == "youtube.com" or c.domain.endswith(".youtube.com")]
            if not cookies or all(c.is_expired() for c in cookies):
                return finish(False, "youtube_cookie", "Cookie YouTube assenti o tutti scaduti: esportare un nuovo file Netscape.")
        except Exception:
            return finish(False, "youtube_cookie", "File cookie illeggibile o formato Netscape non valido.")

    checks.append({"name": "Cookie", "status": "ok" if cookie_file else "off",
                   "detail": f"Netscape · {sum(not c.is_expired() for c in cookies)} non scaduti · {sum(c.is_expired() for c in cookies)} scaduti" if cookie_file else "non configurati"})
    messages = []

    class Logger:
        def debug(self, message):
            pass

        def warning(self, message):
            messages.append(message)

        error = warning

    # yt-dlp may save its cookie jar on close. Probe a private copy so the
    # watchdog cannot overwrite cookies used/refreshed by the live resolver.
    with tempfile.TemporaryDirectory(prefix="pytonazz-audio-") as temp:
        copied = None
        if cookie_file:
            copied = str(Path(temp) / "cookies.txt")
            shutil.copyfile(cookie_file, copied)
            os.chmod(copied, 0o600)
        opts = {**Config.YDL_OPTIONS, "cookiefile": copied, "logger": Logger(),
                "extract_flat": False, "noplaylist": True, "ignoreerrors": False,
                "socket_timeout": 6, "retries": 0, "extractor_retries": 0}
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(test_url, download=False)
            if not isinstance(info, dict) or not info.get("url"):
                return finish(False, "error", "Estrazione senza URL audio: test non riuscito.")
            checks.append({"name": "YouTube", "status": "ok", "detail": "stream estratto"})
            command = [Config.FFMPEG_PATH or "ffmpeg", "-v", "error",
                       *shlex.split(Config.FFMPEG_OPTIONS["before_options"]),
                       "-i", info["url"], "-t", "1", "-vn", "-ac", "1", "-ar", "8000", "-f", "s16le", "pipe:1"]
            result = subprocess.run(command, capture_output=True, timeout=15)
            if result.returncode or not result.stdout:
                failure = classify_cookie_probe_output(returncode=1, output=result.stderr.decode(errors="replace") or "Nessun campione audio decodificato.")
                return finish(False, failure.rule_name, failure.detail)
            checks.append({"name": "FFmpeg", "status": "ok", "detail": "audio PCM decodificato"})
            if any("cookies" in m.lower() and any(w in m.lower() for w in ("expired", "rotated", "invalid")) for m in messages):
                return finish(False, "youtube_cookie", "Audio disponibile ma yt-dlp segnala cookie scaduti/ruotati: rinnovarli.")
            return finish(True, "cookie_ok", "Audio OK · campione decodificato")
        except subprocess.TimeoutExpired:
            return finish(False, "error", "FFmpeg: test audio scaduto dopo 15 secondi.")
        except Exception as exc:
            failure = classify_cookie_probe_output(returncode=1, output=str(exc))
            return finish(False, failure.rule_name, failure.detail)


if __name__ == "__main__":
    payload = json.load(sys.stdin)
    # Keep the worker protocol clean even if a third-party component prints.
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        result = probe(payload["cookie_file"], payload["test_url"])
    print(json.dumps(asdict(result)))
