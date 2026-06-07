from __future__ import annotations

import argparse
import json
import os
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
    AlertRule("critical", "urgent", ("CRITICAL",)),
    AlertRule("error", "high", ("ERROR",)),
    AlertRule("traceback", "high", ("Traceback",)),
    AlertRule("exception", "high", ("Exception",)),
    AlertRule("warning", "default", ("WARNING",)),
    AlertRule("youtube_cookie", "urgent", ("sign in to confirm you are not a bot",)),
    AlertRule("youtube_cookie_hint", "urgent", ("--cookies",)),
    AlertRule("youtube_bot_check", "urgent", ("confirm you are not a bot",)),
    AlertRule("ffmpeg_error", "high", ("FFmpeg", "error")),
)


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


def _format_alert(alert: Alert, log_path: Path) -> tuple[str, str]:
    title = f"Pytonazz: {alert.rule_name}"
    message = f"{alert.severity.upper()} in {log_path}\n\n{alert.line}"
    return title, message


def run_monitor(
    *,
    log_path: Path,
    state_path: Path,
    once: bool,
    interval_seconds: int,
    cooldown_seconds: int,
    dry_run: bool,
) -> None:
    notifier = None if dry_run else NtfyNotifier(NtfyConfig.from_env())
    state = MonitorState.load(state_path)
    monitor = LogMonitor(log_path=log_path, state=state, cooldown_seconds=cooldown_seconds)

    while True:
        alerts = monitor.scan_once()
        for alert in alerts:
            title, message = _format_alert(alert, log_path)
            if dry_run:
                print(f"[DRY-RUN] {title}\n{message}\n")
            else:
                assert notifier is not None
                notifier.send(
                    title=title,
                    message=message,
                    priority=_priority_for_severity(alert.severity),
                    tags="warning",
                )
        state.save(state_path)
        if once:
            return
        time.sleep(interval_seconds)


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
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
