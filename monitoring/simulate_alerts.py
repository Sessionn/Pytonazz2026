from __future__ import annotations

import argparse
from pathlib import Path


SAMPLE_LINES = (
    "2026-06-07 20:00:00  WARNING  pitonazz.player  URL scaduto -> skip stream",
    "2026-06-07 20:00:01  ERROR  pitonazz.resolver  ERROR: Sign in to confirm you are not a bot. Use --cookies",
    "2026-06-07 20:00:02  ERROR  pitonazz.player  FFmpeg error: connection refused",
    "2026-06-07 20:00:03  CRITICAL  pitonazz.runtime  heartbeat bloccato oltre soglia",
    "2026-06-07 20:00:04  ERROR  pitonazz.music  Traceback (most recent call last): Resolve error",
)


def append_samples(log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        for line in SAMPLE_LINES:
            handle.write(f"{line}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Scrive anomalie simulate in un file log.")
    parser.add_argument(
        "--log",
        default="monitoring/sample-bot.log",
        help="File log su cui appendere le anomalie simulate.",
    )
    args = parser.parse_args()

    log_path = Path(args.log)
    append_samples(log_path)
    print(f"Scritte {len(SAMPLE_LINES)} anomalie simulate in {log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
