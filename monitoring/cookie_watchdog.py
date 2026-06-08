from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable, Mapping, Protocol

from monitoring.log_monitor import Alert, format_notification, load_alert_profiles
from monitoring.notifier import NtfyConfig, NtfyNotifier


DEFAULT_TEST_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
DEFAULT_INTERVAL_SECONDS = 3600
DEFAULT_STARTUP_DELAY_SECONDS = 30
DEFAULT_COOLDOWN_SECONDS = 21600


class AlertNotifier(Protocol):
    def send(self, *, title: str, message: str, priority: str = "default", tags: str = "warning") -> None:
        ...


@dataclass(frozen=True)
class CookieWatchConfig:
    enabled: bool
    cookie_file: str
    alert_url: str
    interval_seconds: int
    startup_delay_seconds: int
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
            interval_seconds=_int_env(values, "PYTONAZZ_COOKIE_WATCH_INTERVAL_SECONDS", DEFAULT_INTERVAL_SECONDS),
            startup_delay_seconds=_int_env(
                values,
                "PYTONAZZ_COOKIE_WATCH_STARTUP_DELAY_SECONDS",
                DEFAULT_STARTUP_DELAY_SECONDS,
            ),
            cooldown_seconds=_int_env(values, "PYTONAZZ_COOKIE_WATCH_COOLDOWN_SECONDS", DEFAULT_COOLDOWN_SECONDS),
            test_url=(values.get("PYTONAZZ_COOKIE_WATCH_TEST_URL") or DEFAULT_TEST_URL).strip(),
            profiles_path=Path(values["PYTONAZZ_ALERT_PROFILES"]) if values.get("PYTONAZZ_ALERT_PROFILES") else None,
        )


@dataclass(frozen=True)
class CookieProbeResult:
    ok: bool
    rule_name: str
    detail: str


@dataclass
class CookieWatchState:
    last_failure_alert_at: float = 0.0


ProbeFunc = Callable[[CookieWatchConfig], Awaitable[CookieProbeResult]]


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
    text = output.strip()
    lowered = text.lower()
    if returncode == 0:
        return CookieProbeResult(ok=True, rule_name="cookie_ok", detail=text or "probe ok")
    if "sign in to confirm" in lowered or "confirm you are not a bot" in lowered:
        return CookieProbeResult(
            ok=False,
            rule_name="youtube_cookie",
            detail=f"YouTube richiede cookie validi o verifica anti-bot. Output: {text}",
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


async def run_ytdlp_cookie_probe(config: CookieWatchConfig) -> CookieProbeResult:
    if not config.cookie_file:
        return CookieProbeResult(False, "youtube_cookie", "COOKIE_FILE non configurato.")
    if not Path(config.cookie_file).exists():
        return CookieProbeResult(False, "youtube_cookie", f"COOKIE_FILE non trovato: {config.cookie_file}")

    return await asyncio.to_thread(_run_ytdlp_cookie_probe_sync, config)


def _run_ytdlp_cookie_probe_sync(config: CookieWatchConfig) -> CookieProbeResult:
    try:
        import yt_dlp
    except Exception as exc:
        return CookieProbeResult(False, "error", f"yt-dlp non importabile: {exc}")

    messages: list[str] = []

    class ProbeLogger:
        def debug(self, msg: str) -> None:
            if msg and not msg.startswith("[debug]"):
                messages.append(msg)

        def info(self, msg: str) -> None:
            if msg:
                messages.append(msg)

        def warning(self, msg: str) -> None:
            if msg:
                messages.append(msg)

        def error(self, msg: str) -> None:
            if msg:
                messages.append(msg)

    opts = {
        "cookiefile": config.cookie_file,
        "extract_flat": True,
        "format": "bestaudio/best",
        "ignoreerrors": False,
        "logger": ProbeLogger(),
        "noplaylist": True,
        "quiet": True,
        "skip_download": True,
        "socket_timeout": 10,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(config.test_url, download=False)
        title = info.get("title", "video raggiungibile") if isinstance(info, dict) else "video raggiungibile"
        return CookieProbeResult(True, "cookie_ok", f"yt-dlp cookie probe OK: {title}")
    except Exception as exc:
        messages.append(str(exc))
        return classify_cookie_probe_output(returncode=1, output="\n".join(messages))


async def run_cookie_check_once(
    *,
    config: CookieWatchConfig,
    state: CookieWatchState,
    notifier: AlertNotifier,
    probe: ProbeFunc = run_ytdlp_cookie_probe,
    now: float | None = None,
) -> bool:
    if not config.enabled:
        return False
    now = time.time() if now is None else now
    result = await probe(config)
    if result.ok:
        return False
    if now - state.last_failure_alert_at < config.cooldown_seconds:
        return False

    notification = _build_cookie_failure_notification(config, result)
    await asyncio.to_thread(
        notifier.send,
        title=notification.title,
        message=notification.message,
        priority=notification.priority,
        tags=notification.tags,
    )
    state.last_failure_alert_at = now
    return True


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


async def cookie_watch_loop(
    *,
    config: CookieWatchConfig,
    notifier: AlertNotifier,
    state: CookieWatchState | None = None,
    probe: ProbeFunc = run_ytdlp_cookie_probe,
    logger=None,
) -> None:
    state = CookieWatchState() if state is None else state
    if not config.enabled:
        if logger:
            logger.info("cookie watchdog disabilitato")
        return
    if config.startup_delay_seconds:
        await asyncio.sleep(config.startup_delay_seconds)
    while True:
        try:
            await run_cookie_check_once(config=config, state=state, notifier=notifier, probe=probe)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if logger:
                logger.warning("cookie watchdog check fallito: %s", exc)
        await asyncio.sleep(max(1, config.interval_seconds))


def start_cookie_watchdog(bot, *, logger=None):
    config = CookieWatchConfig.from_env()
    if not config.enabled:
        if logger:
            logger.info("cookie watchdog non avviato: COOKIE_FILE o ntfy non configurati")
        return None
    task = getattr(bot, "_cookie_watchdog_task", None)
    if task and not task.done():
        return task
    notifier = NtfyNotifier(NtfyConfig.from_env())
    task = asyncio.create_task(cookie_watch_loop(config=config, notifier=notifier, logger=logger))
    bot._cookie_watchdog_task = task
    if logger:
        logger.info(
            "cookie watchdog avviato: ogni %ss, test_url=%s",
            config.interval_seconds,
            config.test_url,
        )
    return task
