"""Allarmi ntfy sui cookie YouTube e test audio isolato.

Il rinnovo e il controllo periodico dei cookie li fa il servizio esterno
monitoring/cookie_browser.py (fuori dal processo del bot, mai durante la
riproduzione). Qui restano:
- classify_cookie_probe_output: classifica l'output di yt-dlp;
- notify_ytdlp_cookie_error: allarme immediato quando un /play reale fallisce
  per i cookie (chiamato dal logger yt-dlp del resolver);
- run_audio_probe_isolated: test audio in un processo separato, usato dal
  servizio dei cookie prima di installarli.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Protocol

from monitoring.log_monitor import Alert, format_notification, load_alert_profiles
from monitoring.notifier import NtfyConfig, NtfyNotifier


DEFAULT_TEST_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
DEFAULT_COOLDOWN_SECONDS = 21600
DEFAULT_INLINE_COOLDOWN_SECONDS = 300
_last_inline_cookie_alert_at = 0.0


class AlertNotifier(Protocol):
    def send(self, *, title: str, message: str, priority: str = "default", tags: str = "warning") -> None:
        ...


@dataclass(frozen=True)
class CookieWatchConfig:
    enabled: bool
    cookie_file: str
    alert_url: str
    cooldown_seconds: int
    test_url: str
    profiles_path: Path | None = None

    @classmethod
    def from_env(cls) -> "CookieWatchConfig":
        _load_monitoring_env()
        return cls.from_mapping(os.environ)

    @classmethod
    def from_mapping(cls, values: Mapping[str, str]) -> "CookieWatchConfig":
        cookie_file = (values.get("COOKIE_FILE") or values.get("PYTONAZZ_COOKIE_FILE") or "").strip()
        enabled_raw = values.get("PYTONAZZ_COOKIE_WATCH_ENABLED", "").strip().lower()
        alert_url = _alert_url_from_mapping(values)
        enabled = (
            enabled_raw not in ("false", "0", "no", "off")
            if enabled_raw
            else bool(cookie_file and alert_url)
        )
        return cls(
            enabled=enabled,
            cookie_file=cookie_file,
            alert_url=alert_url,
            cooldown_seconds=_int_env(values, "PYTONAZZ_COOKIE_WATCH_COOLDOWN_SECONDS", DEFAULT_COOLDOWN_SECONDS),
            test_url=(values.get("PYTONAZZ_COOKIE_WATCH_TEST_URL") or DEFAULT_TEST_URL).strip(),
            profiles_path=Path(values["PYTONAZZ_ALERT_PROFILES"]) if values.get("PYTONAZZ_ALERT_PROFILES") else None,
        )


@dataclass(frozen=True)
class CookieProbeResult:
    ok: bool
    rule_name: str
    detail: str


def _alert_url_from_mapping(values: Mapping[str, str]) -> str:
    direct_url = values.get("PYTONAZZ_ALERT_URL", "").strip()
    if direct_url:
        return direct_url
    base_url = values.get("PYTONAZZ_ALERT_BASE_URL", "").strip()
    topic = values.get("PYTONAZZ_ALERT_TOPIC", "").strip()
    if base_url and topic:
        return f"{base_url.rstrip('/')}/{topic}"
    return ""


def _load_monitoring_env() -> None:
    env_path = Path("monitoring/.env")
    if not env_path.exists():
        return
    try:
        from dotenv import load_dotenv
    except Exception:
        return
    load_dotenv(env_path, override=False)


def _int_env(values: Mapping[str, str], key: str, default: int) -> int:
    raw = values.get(key, "").strip()
    if not raw:
        return default
    return max(0, int(raw))


def classify_cookie_probe_output(*, returncode: int, output: str) -> CookieProbeResult:
    # Signed stream URLs carry session-bound tokens: never forward them.
    text = re.sub(r"https?://\S+", "[URL oscurato]", output.strip())
    lowered = text.lower()
    if returncode == 0:
        return CookieProbeResult(ok=True, rule_name="cookie_ok", detail=text or "probe ok")
    if "sign in to confirm" in lowered or "confirm you are not a bot" in lowered:
        return CookieProbeResult(
            ok=False,
            rule_name="youtube_cookie",
            detail=f"YouTube richiede cookie validi o verifica anti-bot. Output: {text}",
        )
    if "403" in lowered or "forbidden" in lowered:
        return CookieProbeResult(
            ok=False,
            rule_name="youtube_stream",
            detail="Stream audio rifiutato (HTTP 403): verificare client e formato; da solo non prova cookie scaduti.",
        )
    if "--cookies" in lowered or "cookies-from-browser" in lowered:
        return CookieProbeResult(
            ok=False,
            rule_name="youtube_cookie_hint",
            detail=f"yt-dlp segnala un problema cookie. Output: {text}",
        )
    return CookieProbeResult(
        ok=False,
        rule_name="error",
        detail=f"Cookie probe fallito con codice {returncode}. Output: {text}",
    )


def notify_ytdlp_cookie_error(
    message: str,
    *,
    config: CookieWatchConfig | None = None,
    notifier: AlertNotifier | None = None,
    now: float | None = None,
) -> bool:
    global _last_inline_cookie_alert_at
    result = classify_cookie_probe_output(returncode=1, output=message)
    if result.ok or result.rule_name not in ("youtube_cookie", "youtube_cookie_hint"):
        return False

    config = CookieWatchConfig.from_env() if config is None else config
    if not config.enabled:
        return False
    now = time.time() if now is None else now
    cooldown = min(config.cooldown_seconds, DEFAULT_INLINE_COOLDOWN_SECONDS)
    if now - _last_inline_cookie_alert_at < cooldown:
        return False

    notifier = NtfyNotifier(NtfyConfig.from_env()) if notifier is None else notifier
    notification = _build_cookie_failure_notification(config, result)
    notifier.send(
        title=notification.title,
        message=notification.message,
        priority=notification.priority,
        tags=notification.tags,
    )
    _last_inline_cookie_alert_at = now
    return True


def run_audio_probe_isolated(cookie_file: str, test_url: str, *, timeout: int = 45) -> CookieProbeResult:
    """Real playback test (extraction + 1s FFmpeg decode) in a bounded worker process."""
    root = Path(__file__).resolve().parents[1]
    try:
        result = subprocess.run(
            [sys.executable, "-m", "monitoring.audio_probe"],
            input=json.dumps({"cookie_file": cookie_file, "test_url": test_url}),
            capture_output=True, text=True, timeout=timeout, cwd=root,
        )
        if result.returncode:
            return CookieProbeResult(False, "error", "Processo del test audio terminato in errore.")
        return CookieProbeResult(**json.loads(result.stdout))
    except subprocess.TimeoutExpired:
        return CookieProbeResult(False, "error", f"Test audio scaduto dopo {timeout} secondi.")
    except Exception:
        return CookieProbeResult(False, "error", "Impossibile eseguire il test audio isolato.")


def _build_cookie_failure_notification(config: CookieWatchConfig, result: CookieProbeResult):
    profiles = load_alert_profiles(config.profiles_path)
    line = (
        f"Cookie health check fallito. COOKIE_FILE={config.cookie_file} "
        f"TEST_URL={config.test_url} DETTAGLIO={result.detail}"
    )
    return format_notification(
        Alert(rule_name=result.rule_name, severity="urgent", line=line),
        Path(config.cookie_file or "COOKIE_FILE"),
        profiles=profiles,
    )
