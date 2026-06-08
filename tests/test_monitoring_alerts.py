import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from monitoring.log_monitor import AlertRule, LogMonitor, MonitorState, format_notification, load_alert_profiles
from monitoring.notifier import NtfyConfig, build_ntfy_request


class MonitoringAlertsTests(unittest.TestCase):
    def test_ntfy_config_builds_topic_url_from_base_and_topic(self):
        config = NtfyConfig.from_mapping(
            {
                "PYTONAZZ_ALERT_BASE_URL": "https://alerts.example.com",
                "PYTONAZZ_ALERT_TOPIC": "bot-errors",
            }
        )

        self.assertEqual(config.url, "https://alerts.example.com/bot-errors")

    def test_ntfy_request_uses_secure_headers_and_utf8_body(self):
        request = build_ntfy_request(
            NtfyConfig(url="https://alerts.example.com/bot-errors", token="secret"),
            title="Pytonazz alert",
            message="Errore resolver YouTube",
            priority="high",
            tags="warning",
        )

        self.assertEqual(request.full_url, "https://alerts.example.com/bot-errors")
        self.assertEqual(request.headers["Authorization"], "Bearer secret")
        self.assertEqual(request.headers["Title"], "Pytonazz alert")
        self.assertEqual(request.headers["Priority"], "high")
        self.assertEqual(request.data, "Errore resolver YouTube".encode("utf-8"))

    def test_ntfy_request_keeps_headers_http_safe_when_title_has_emoji(self):
        request = build_ntfy_request(
            NtfyConfig(url="https://alerts.example.com/bot-errors"),
            title="🍪 Pytonazz: YouTube cookie",
            message="🍪 Corpo UTF-8 consentito",
            priority="urgent",
            tags="cookie,warning",
        )

        request.headers["Title"].encode("latin-1")
        self.assertEqual(request.headers["Title"], "Pytonazz: YouTube cookie")
        self.assertEqual(request.data, "🍪 Corpo UTF-8 consentito".encode("utf-8"))

    def test_log_monitor_detects_youtube_cookie_problem(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "bot.log"
            log_path.write_text(
                "[RESOLVE] ERROR: Sign in to confirm you are not a bot. Use --cookies-from-browser or --cookies\n",
                encoding="utf-8",
            )

            monitor = LogMonitor(
                log_path=log_path,
                state=MonitorState(),
                rules=[
                    AlertRule(
                        name="youtube_cookie",
                        severity="high",
                        patterns=("sign in to confirm you are not a bot", "--cookies"),
                    )
                ],
                cooldown_seconds=0,
            )

            alerts = monitor.scan_once(now=1000.0)

            self.assertEqual(len(alerts), 1)
            self.assertEqual(alerts[0].rule_name, "youtube_cookie")
            self.assertEqual(alerts[0].severity, "high")
            self.assertIn("Sign in to confirm", alerts[0].line)

    def test_log_monitor_tracks_offset_and_does_not_resend_same_line(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "bot.log"
            log_path.write_text("WARNING primo problema\n", encoding="utf-8")

            monitor = LogMonitor(log_path=log_path, state=MonitorState(), cooldown_seconds=0)

            self.assertEqual(len(monitor.scan_once(now=1000.0)), 1)
            self.assertEqual(monitor.scan_once(now=1001.0), [])

            with log_path.open("a", encoding="utf-8") as handle:
                handle.write("ERROR secondo problema\n")

            alerts = monitor.scan_once(now=1002.0)

            self.assertEqual(len(alerts), 1)
            self.assertIn("secondo problema", alerts[0].line)

    def test_log_monitor_applies_cooldown_per_rule(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "bot.log"
            log_path.write_text("WARNING primo\nWARNING secondo\n", encoding="utf-8")

            monitor = LogMonitor(log_path=log_path, state=MonitorState(), cooldown_seconds=300)

            alerts = monitor.scan_once(now=1000.0)

            self.assertEqual(len(alerts), 1)
            self.assertIn("primo", alerts[0].line)

    def test_youtube_cookie_alert_uses_specific_rule_before_generic_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "bot.log"
            log_path.write_text(
                "ERROR: Sign in to confirm you are not a bot. Use --cookies\n",
                encoding="utf-8",
            )

            monitor = LogMonitor(log_path=log_path, state=MonitorState(), cooldown_seconds=0)
            alerts = monitor.scan_once(now=1000.0)

            self.assertEqual(len(alerts), 1)
            self.assertEqual(alerts[0].rule_name, "youtube_cookie")

    def test_notification_format_is_clear_and_actionable(self):
        alert = AlertRule(
            name="youtube_cookie",
            severity="urgent",
            patterns=("confirm you are not a bot",),
        )
        matched = LogMonitor(
            log_path=Path("bot.log"),
            state=MonitorState(),
            rules=[alert],
            cooldown_seconds=0,
        )._alert_for_line("ERROR: Sign in to confirm you are not a bot. Use --cookies", 1000.0)

        notification = format_notification(matched, Path("/home/sessionn/Pytonazz2026/monitoring/logs/bot.log"))

        self.assertEqual(notification.priority, "urgent")
        self.assertIn("🍪", notification.title)
        self.assertIn("YouTube cookie", notification.title)
        self.assertIn("Cosa significa", notification.message)
        self.assertIn("Controlli rapidi", notification.message)
        self.assertIn("COOKIE_FILE", notification.message)
        self.assertIn("yt-dlp", notification.message)
        self.assertIn("cookie,warning", notification.tags)

    def test_notification_profiles_can_be_overridden_from_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            profile_path = Path(tmpdir) / "profiles.json"
            profile_path.write_text(
                """
{
  "youtube_cookie": {
    "label": "YouTube bloccato",
    "emoji": "🍪",
    "tags": "cookie,rotating_light",
    "summary": "Messaggio personalizzato.",
    "checks": ["Controllo uno.", "Controllo due."]
  }
}
""",
                encoding="utf-8",
            )
            profiles = load_alert_profiles(profile_path)
            matched = LogMonitor(
                log_path=Path("bot.log"),
                state=MonitorState(),
                rules=[AlertRule("youtube_cookie", "urgent", ("cookies",))],
                cooldown_seconds=0,
            )._alert_for_line("ERROR --cookies", 1000.0)

            notification = format_notification(matched, Path("bot.log"), profiles=profiles)

            self.assertIn("YouTube bloccato", notification.title)
            self.assertEqual(notification.tags, "cookie,rotating_light")
            self.assertIn("Messaggio personalizzato", notification.message)
            self.assertIn("Controllo uno", notification.message)


if __name__ == "__main__":
    unittest.main()
