from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from monitoring.notifier import NtfyConfig, NtfyNotifier


DEFAULT_STATE_PATH = Path("monitoring/.alert-monitor-state.json")


@dataclass(frozen=True)
class AlertRule:
    name: str
    severity: str
    patterns: tuple[str, ...]

    def matches(self, line: str) -> bool:
        haystack = line.lower()
        return all(pattern.lower() in haystack for pattern in self.patterns)


@dataclass(frozen=True)
class Alert:
    rule_name: str
    severity: str
    line: str


@dataclass(frozen=True)
class AlertProfile:
    label: str
    emoji: str
    tags: str
    summary: str
    checks: tuple[str, ...]


@dataclass(frozen=True)
class Notification:
    title: str
    message: str
    priority: str
    tags: str


@dataclass
class MonitorState:
    offset: int = 0
    last_sent_by_rule: dict[str, float] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> "MonitorState":
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            offset=int(data.get("offset", 0)),
            last_sent_by_rule={
                str(key): float(value)
                for key, value in dict(data.get("last_sent_by_rule", {})).items()
            },
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "offset": self.offset,
                    "last_sent_by_rule": self.last_sent_by_rule,
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )


DEFAULT_RULES = (
    AlertRule("youtube_cookie", "urgent", ("sign in to confirm you are not a bot",)),
    AlertRule("youtube_cookie_hint", "urgent", ("--cookies",)),
    AlertRule("youtube_bot_check", "urgent", ("confirm you are not a bot",)),
    AlertRule("ffmpeg_error", "high", ("FFmpeg", "error")),
    AlertRule("critical", "urgent", ("CRITICAL",)),
    AlertRule("traceback", "high", ("Traceback",)),
    AlertRule("exception", "high", ("Exception",)),
    AlertRule("error", "high", ("ERROR",)),
    AlertRule("warning", "default", ("WARNING",)),
)


ALERT_PROFILES = {
    "youtube_cookie": AlertProfile(
        label="YouTube cookie",
        emoji="🍪",
        tags="cookie,warning",
        summary="YouTube sta chiedendo cookie o verifica anti-bot al resolver.",
        checks=(
            "Controlla COOKIE_FILE=/home/sessionn/cookies.txt nel .env del bot.",
            "Aggiorna i cookie YouTube se sono vecchi o scaduti.",
            "Aggiorna yt-dlp nel venv della VM.",
        ),
    ),
    "youtube_cookie_hint": AlertProfile(
        label="YouTube cookie",
        emoji="🍪",
        tags="cookie,warning",
        summary="yt-dlp ha prodotto un messaggio legato ai cookie YouTube.",
        checks=(
            "Verifica che COOKIE_FILE punti a un file leggibile dal processo del bot.",
            "Se il file esiste, prova a rigenerarlo dal browser.",
            "Rilancia un benchmark con tools/benchmark_ytdlp.py.",
        ),
    ),
    "youtube_bot_check": AlertProfile(
        label="YouTube anti-bot",
        emoji="🛡️",
        tags="shield,warning",
        summary="YouTube ha attivato un controllo anti-bot sulla VM.",
        checks=(
            "Verifica cookie e proxy/WARP se configurati.",
            "Aggiorna yt-dlp.",
            "Se succede spesso, prova a ruotare rete o ridurre richieste ripetute.",
        ),
    ),
    "ffmpeg_error": AlertProfile(
        label="FFmpeg audio",
        emoji="🎧",
        tags="headphones,warning",
        summary="Il player audio ha visto un errore FFmpeg o stream non riproducibile.",
        checks=(
            "Controlla se lo stream URL e' scaduto.",
            "Verifica ffmpeg -version sulla VM.",
            "Riprova /play e guarda se il resolver rigenera lo stream.",
        ),
    ),
    "critical": AlertProfile(
        label="Critico",
        emoji="🚨",
        tags="rotating_light",
        summary="Evento critico: il bot potrebbe essere instabile o bloccato.",
        checks=(
            "Controlla subito il processo del bot.",
            "Guarda le righe prima e dopo nel log.",
            "Se il bot non risponde, valuta restart controllato.",
        ),
    ),
    "traceback": AlertProfile(
        label="Traceback",
        emoji="💥",
        tags="boom,warning",
        summary="Python ha stampato uno stack trace.",
        checks=(
            "Leggi le righe successive nel log per il file e la funzione.",
            "Cerca l'ultima riga dello stack trace: di solito contiene la causa.",
            "Se e' ripetuto, apri issue o patch sul punto indicato.",
        ),
    ),
    "exception": AlertProfile(
        label="Eccezione",
        emoji="💥",
        tags="boom,warning",
        summary="Una parte del bot ha segnalato una eccezione.",
        checks=(
            "Cerca nel log il comando o evento che l'ha causata.",
            "Controlla se riguarda Discord, resolver, dashboard o cache.",
            "Se si ripete, conserva le righe vicine per debug.",
        ),
    ),
    "error": AlertProfile(
        label="Errore",
        emoji="❌",
        tags="x,warning",
        summary="Errore generico rilevato nei log.",
        checks=(
            "Leggi la riga completa e le righe immediatamente precedenti.",
            "Se riguarda musica, prova benchmark_resolve o benchmark_ytdlp.",
            "Se riguarda Discord, verifica permessi e stato del bot.",
        ),
    ),
    "warning": AlertProfile(
        label="Warning",
        emoji="⚠️",
        tags="warning",
        summary="Warning rilevato: non sempre e' grave, ma va tenuto d'occhio.",
        checks=(
            "Se e' isolato, probabilmente basta monitorarlo.",
            "Se si ripete spesso, alza priorita' e controlla il modulo indicato.",
            "Guarda se precede un ERROR o un problema utente reale.",
        ),
    ),
}

DEFAULT_PROFILE = AlertProfile(
    label="Anomalia",
    emoji="🔔",
    tags="bell",
    summary="Evento anomalo rilevato nel log.",
    checks=(
        "Controlla la riga log.",
        "Guarda le righe immediatamente precedenti e successive.",
        "Se si ripete, riduci il cooldown e raccogli piu' esempi.",
    ),
)


def load_alert_profiles(path: Path | None) -> dict[str, AlertProfile]:
    profiles = dict(ALERT_PROFILES)
    if path is None or not path.exists():
        return profiles

    raw = json.loads(path.read_text(encoding="utf-8"))
    for name, value in raw.items():
        checks = tuple(str(item) for item in value.get("checks", ()))
        if not checks:
            checks = profiles.get(name, DEFAULT_PROFILE).checks
        current = profiles.get(name, DEFAULT_PROFILE)
        profiles[str(name)] = AlertProfile(
            label=str(value.get("label", current.label)),
            emoji=str(value.get("emoji", current.emoji)),
            tags=str(value.get("tags", current.tags)),
            summary=str(value.get("summary", current.summary)),
            checks=checks,
        )
    return profiles


class LogMonitor:
    def __init__(
        self,
        *,
        log_path: Path,
        state: MonitorState,
        rules: Iterable[AlertRule] = DEFAULT_RULES,
        cooldown_seconds: int = 300,
    ):
        self.log_path = log_path
        self.state = state
        self.rules = tuple(rules)
        self.cooldown_seconds = cooldown_seconds

    def scan_once(self, *, now: float | None = None) -> list[Alert]:
        now = time.time() if now is None else now
        if not self.log_path.exists():
            return []

        file_size = self.log_path.stat().st_size
        if file_size < self.state.offset:
            self.state.offset = 0

        alerts: list[Alert] = []
        with self.log_path.open("r", encoding="utf-8", errors="replace") as handle:
            handle.seek(self.state.offset)
            for raw_line in handle:
                line = raw_line.strip()
                alert = self._alert_for_line(line, now)
                if alert is not None:
                    alerts.append(alert)
            self.state.offset = handle.tell()
        return alerts

    def _alert_for_line(self, line: str, now: float) -> Alert | None:
        if not line:
            return None
        for rule in self.rules:
            if not rule.matches(line):
                continue
            last_sent = self.state.last_sent_by_rule.get(rule.name, 0.0)
            if now - last_sent < self.cooldown_seconds:
                return None
            self.state.last_sent_by_rule[rule.name] = now
            return Alert(rule_name=rule.name, severity=rule.severity, line=line)
        return None


def _priority_for_severity(severity: str) -> str:
    if severity == "urgent":
        return "urgent"
    if severity == "high":
        return "high"
    return "default"


def format_notification(
    alert: Alert,
    log_path: Path,
    *,
    profiles: dict[str, AlertProfile] | None = None,
) -> Notification:
    active_profiles = ALERT_PROFILES if profiles is None else profiles
    profile = active_profiles.get(alert.rule_name, DEFAULT_PROFILE)
    priority = _priority_for_severity(alert.severity)
    checks = "\n".join(f"- {check}" for check in profile.checks)
    message = (
        f"Tipo: {profile.label}\n"
        f"Priorita': {alert.severity.upper()}\n"
        f"Log: {log_path}\n\n"
        f"Cosa significa\n"
        f"{profile.summary}\n\n"
        f"Controlli rapidi\n"
        f"{checks}\n\n"
        f"Riga log\n"
        f"{alert.line}"
    )
    return Notification(
        title=f"{profile.emoji} Pytonazz: {profile.label} {profile.emoji}",
        message=message,
        priority=priority,
        tags=profile.tags,
    )


def run_monitor(
    *,
    log_path: Path,
    state_path: Path,
    once: bool,
    interval_seconds: int,
    cooldown_seconds: int,
    dry_run: bool,
    profiles_path: Path | None,
) -> None:
    notifier = None if dry_run else NtfyNotifier(NtfyConfig.from_env())
    profiles = load_alert_profiles(profiles_path)
    state = MonitorState.load(state_path)
    monitor = LogMonitor(log_path=log_path, state=state, cooldown_seconds=cooldown_seconds)

    while True:
        alerts = monitor.scan_once()
        for alert in alerts:
            notification = format_notification(alert, log_path, profiles=profiles)
            if dry_run:
                _print_dry_run(notification)
            else:
                assert notifier is not None
                notifier.send(
                    title=notification.title,
                    message=notification.message,
                    priority=notification.priority,
                    tags=notification.tags,
                )
        state.save(state_path)
        if once:
            return
        time.sleep(interval_seconds)


def _print_dry_run(notification: Notification) -> None:
    text = f"[DRY-RUN] {notification.title}\n{notification.message}\n\n"
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is None:
        print(text)
        return
    buffer.write(text.encode("utf-8", errors="replace"))
    buffer.flush()


def main() -> int:
    parser = argparse.ArgumentParser(description="Monitor log Pytonazz e invia alert ntfy.")
    parser.add_argument(
        "--log",
        default=os.environ.get("PYTONAZZ_MONITOR_LOG", ""),
        help="Percorso del file log da monitorare.",
    )
    parser.add_argument(
        "--state",
        default=os.environ.get("PYTONAZZ_MONITOR_STATE", str(DEFAULT_STATE_PATH)),
        help="File stato offset/cooldown.",
    )
    parser.add_argument("--once", action="store_true", help="Scansiona una volta e termina.")
    parser.add_argument(
        "--interval",
        type=int,
        default=int(os.environ.get("PYTONAZZ_MONITOR_INTERVAL_SECONDS", "10")),
        help="Secondi tra una scansione e la successiva.",
    )
    parser.add_argument(
        "--cooldown",
        type=int,
        default=int(os.environ.get("PYTONAZZ_ALERT_COOLDOWN_SECONDS", "300")),
        help="Secondi minimi tra alert dello stesso tipo.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Stampa invece di inviare.")
    parser.add_argument(
        "--profiles",
        default=os.environ.get("PYTONAZZ_ALERT_PROFILES", ""),
        help="JSON opzionale per personalizzare testi, emoji e checklist.",
    )
    args = parser.parse_args()

    if not args.log:
        parser.error("imposta --log oppure PYTONAZZ_MONITOR_LOG")

    run_monitor(
        log_path=Path(args.log),
        state_path=Path(args.state),
        once=args.once,
        interval_seconds=max(1, args.interval),
        cooldown_seconds=max(0, args.cooldown),
        dry_run=args.dry_run,
        profiles_path=Path(args.profiles) if args.profiles else None,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
