"""Measure real PCM transformations against Discord's 20 ms frame budget."""
from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from importlib.metadata import version
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from core.music.live_fx import LivePCMTransform


class ToneSource:
    def __init__(self):
        samples = np.arange(960) / 48000
        channels = np.column_stack((
            np.sin(2 * np.pi * 440 * samples),
            np.sin(2 * np.pi * 660 * samples),
        ))
        self.frame = (channels * 6000).astype("<i2").tobytes()

    def read(self) -> bytes:
        return self.frame

    def cleanup(self) -> None:
        pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frames", type=int, default=2000)
    parser.add_argument("--output", type=Path, help="Optional JSON report path")
    args = parser.parse_args()
    if args.frames < 1:
        parser.error("--frames must be positive")

    report = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "numpy": version("numpy"),
        "scipy": version("scipy"),
        "frames_per_case": args.frames,
        "budget_ms": 20,
        "cases": [],
    }
    for name in ("clean", "eq", "heavy"):
        transform = LivePCMTransform(ToneSource(), volume=1.0)
        try:
            if name != "clean":
                transform.set_eq(low=4, mid=-2, high=3)
                transform.set_tone_filters(80, 16000)
            if name == "heavy":
                transform.set_filter_preset({
                    "low_gain": 5, "mid_gain": -1, "high_gain": 2,
                    "presence_gain": 2, "highpass_hz": 60,
                    "lowpass_hz": 12000, "pan_rate_hz": .3,
                    "pan_depth": .6, "reverb_mix": .3,
                    "reverb_decay": .5, "playback_rate": 1.12,
                }, immediate=True)
            for _ in range(50):
                transform.read()
            durations = []
            nonzero = False
            for _ in range(args.frames):
                started = time.perf_counter()
                frame = transform.read()
                durations.append((time.perf_counter() - started) * 1000)
                if len(frame) != 3840:
                    raise RuntimeError(f"{name}: expected 3840 PCM bytes, got {len(frame)}")
                nonzero = nonzero or bool(np.any(np.frombuffer(frame, dtype="<i2")))
            if not nonzero:
                raise RuntimeError(f"{name}: silent output")
            report["cases"].append({
                "name": name,
                "median_ms": round(float(np.median(durations)), 3),
                "p95_ms": round(float(np.percentile(durations, 95)), 3),
                "p99_ms": round(float(np.percentile(durations, 99)), 3),
                "max_ms": round(max(durations), 3),
                "frames_over_budget": sum(value > 20 for value in durations),
            })
        finally:
            transform.cleanup()

    encoded = json.dumps(report, indent=2)
    print(encoded)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n", encoding="utf-8")
    return int(any(case["p99_ms"] >= 20 for case in report["cases"]))


if __name__ == "__main__":
    raise SystemExit(main())
