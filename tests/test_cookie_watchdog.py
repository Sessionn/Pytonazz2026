import asyncio
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from monitoring.cookie_watchdog import (
    CookieProbeResult,
    CookieWatchConfig,
    CookieWatchState,
    classify_cookie_probe_output,
    notify_ytdlp_cookie_error,
    run_cookie_check_once,
)


class FakeNotifier:
    def __init__(self):
        self.sent = []

    def send(self, *, title, message, priority="default", tags="warning"):
        self.sent.append(
            {
                "title": title,
                "message": message,
                "priority": priority,
                "tags": tags,
            }
        )


class CookieWatchdogTests(unittest.TestCase):
    def test_config_uses_cookie_file_and_alert_env(self):
        config = CookieWatchConfig.from_mapping(
            {
                "COOKIE_FILE": "/home/sessionn/cookies.txt",
                "PYTONAZZ_ALERT_BASE_URL": "https://ntfy.sh",
                "PYTONAZZ_ALERT_TOPIC": "pytonazBot",
                "PYTONAZZ_COOKIE_WATCH_INTERVAL_SECONDS": "120",
            }
        )

        self.assertTrue(config.enabled)
        self.assertEqual(config.cookie_file, "/home/sessionn/cookies.txt")
        self.assertEqual(config.interval_seconds, 120)
        self.assertEqual(config.alert_url, "https://ntfy.sh/pytonazBot")

    def test_classifier_detects_expired_youtube_cookie_error(self):
        result = classify_cookie_probe_output(
            returncode=1,
            output="ERROR: Sign in to confirm you are not a bot. Use --cookies-from-browser or --cookies",
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.rule_name, "youtube_cookie")
        self.assertIn("cookie", result.detail.lower())

    def test_classifier_accepts_successful_probe(self):
        result = classify_cookie_probe_output(returncode=0, output="title: ok")

        self.assertTrue(result.ok)
        self.assertEqual(result.rule_name, "cookie_ok")

    def test_run_once_sends_actionable_alert_on_failure(self):
        async def probe(_config):
            return CookieProbeResult(
                ok=False,
                rule_name="youtube_cookie",
                detail="Sign in to confirm you are not a bot. Use --cookies",
            )

        notifier = FakeNotifier()
        state = CookieWatchState()
        config = CookieWatchConfig(
            enabled=True,
            cookie_file="/home/sessionn/cookies.txt",
            alert_url="https://ntfy.sh/pytonazBot",
            interval_seconds=60,
            startup_delay_seconds=0,
            cooldown_seconds=300,
            test_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        )

        sent = asyncio.run(
            run_cookie_check_once(
                config=config,
                state=state,
                notifier=notifier,
                probe=probe,
                now=1000.0,
            )
        )

        self.assertTrue(sent)
        self.assertEqual(len(notifier.sent), 1)
        self.assertIn("YouTube cookie", notifier.sent[0]["title"])
        self.assertIn("COOKIE_FILE", notifier.sent[0]["message"])
        self.assertEqual(notifier.sent[0]["priority"], "urgent")

    def test_run_once_respects_failure_cooldown(self):
        async def probe(_config):
            return CookieProbeResult(
                ok=False,
                rule_name="youtube_cookie",
                detail="Use --cookies",
            )

        notifier = FakeNotifier()
        state = CookieWatchState()
        config = CookieWatchConfig(
            enabled=True,
            cookie_file="/home/sessionn/cookies.txt",
            alert_url="https://ntfy.sh/pytonazBot",
            interval_seconds=60,
            startup_delay_seconds=0,
            cooldown_seconds=300,
            test_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        )

        first = asyncio.run(run_cookie_check_once(config=config, state=state, notifier=notifier, probe=probe, now=1000.0))
        second = asyncio.run(run_cookie_check_once(config=config, state=state, notifier=notifier, probe=probe, now=1100.0))

        self.assertTrue(first)
        self.assertFalse(second)
        self.assertEqual(len(notifier.sent), 1)

    def test_ytdlp_error_hook_sends_immediate_cookie_alert_with_cooldown(self):
        notifier = FakeNotifier()
        config = CookieWatchConfig(
            enabled=True,
            cookie_file="/home/sessionn/cookies.txt",
            alert_url="https://ntfy.sh/pytonazBot",
            interval_seconds=60,
            startup_delay_seconds=0,
            cooldown_seconds=300,
            test_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        )

        first = notify_ytdlp_cookie_error(
            "ERROR: [youtube] Sign in to confirm you are not a bot. Use --cookies",
            config=config,
            notifier=notifier,
            now=1000.0,
        )
        second = notify_ytdlp_cookie_error(
            "ERROR: [youtube] Sign in to confirm you are not a bot. Use --cookies",
            config=config,
            notifier=notifier,
            now=1100.0,
        )

        self.assertTrue(first)
        self.assertFalse(second)
        self.assertEqual(len(notifier.sent), 1)
        self.assertIn("YouTube cookie", notifier.sent[0]["title"])
        self.assertIn("Sign in to confirm", notifier.sent[0]["message"])


if __name__ == "__main__":
    unittest.main()
