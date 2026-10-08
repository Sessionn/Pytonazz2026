import tempfile
import unittest
from unittest import mock
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from monitoring import cookie_browser
from monitoring.cookie_browser import Alerter, Outcome, netscape, next_delay, refresh_once
from monitoring.cookie_watchdog import classify_cookie_probe_output

OK = Outcome("COOKIE AGGIORNATI · test audio OK", "ok")
LOGIN = Outcome("LOGIN RICHIESTO", "login")
PROBE = Outcome("COOKIE NON INSTALLATI · youtube_stream", "probe")
STARTING = Outcome("BROWSER AVVIATO", "starting")


def cookie(name, domain=".youtube.com", http_only=False):
    return {"domain": domain, "path": "/", "secure": True, "expiry": 2000000000,
            "name": name, "value": "v", "httpOnly": http_only}


class NetscapeTests(unittest.TestCase):
    def test_requires_login_cookies(self):
        self.assertIsNone(netscape([cookie("PREF")]))

    def test_keeps_only_youtube_and_marks_http_only(self):
        content = netscape([cookie("SID"), cookie("SAPISID", http_only=True), cookie("NID", ".google.com")])
        self.assertIn("#HttpOnly_.youtube.com", content)
        self.assertNotIn("google.com", content)

    def test_rejects_injected_fields(self):
        with self.assertRaises(ValueError):
            netscape([cookie("SID"), {**cookie("SAPISID"), "value": "a\tb"}])


class ScheduleTests(unittest.TestCase):
    def test_healthy_syncs_again_within_minutes(self):
        self.assertEqual(next_delay(OK), cookie_browser.SYNC_SECONDS)
        self.assertLessEqual(cookie_browser.SYNC_SECONDS, 900)

    def test_failures_retry_hourly_and_login_sooner(self):
        self.assertEqual(next_delay(PROBE), 3600)
        self.assertEqual(next_delay(LOGIN), 300)
        self.assertEqual(next_delay(STARTING), 30)

    def test_firefox_millisecond_expiry_becomes_seconds(self):
        content = netscape([{**cookie("SID"), "expiry": 1823000000000}, cookie("SAPISID")])
        self.assertIn("\t1823000000\tSID\t", content)


class RefreshTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.dir = Path(folder.name)
        self.dest = self.dir / "cookies.txt"
        self.browser = [cookie("SID"), cookie("SAPISID")]
        self.probe_ok = True
        self.probes = 0

        def probe(path, url):
            self.probes += 1
            return mock.Mock(ok=self.probe_ok, rule_name="youtube_bot_check", detail="bot")

        for target, value in [
            ("monitoring.cookie_browser.STATE", self.dir),
            ("monitoring.cookie_browser.browser_cookies", lambda: self.browser),
            ("monitoring.cookie_watchdog.run_audio_probe_isolated", probe),
            ("config.Config.EFFECTIVE_COOKIE_FILE", str(self.dest)),
        ]:
            patcher = mock.patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_installs_verified_then_skips_unchanged(self):
        first = refresh_once(None)
        self.assertTrue(first.installed)
        self.assertEqual(self.dest.read_text(encoding="utf-8"), netscape(self.browser))
        again = refresh_once(first.digest)
        self.assertFalse(again.installed)
        self.assertEqual(self.probes, 1)

    def test_rotated_cookies_are_installed_again(self):
        first = refresh_once(None)
        self.browser = [cookie("SID"), {**cookie("SAPISID"), "value": "rotated"}]
        second = refresh_once(first.digest)
        self.assertTrue(second.installed)
        self.assertNotEqual(second.digest, first.digest)
        self.assertIn("rotated", self.dest.read_text(encoding="utf-8"))

    def test_file_crippled_by_yt_dlp_is_restored_without_probe(self):
        first = refresh_once(None)
        self.dest.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
        restored = refresh_once(first.digest)
        self.assertTrue(restored.installed)
        self.assertEqual(self.dest.read_text(encoding="utf-8"), netscape(self.browser))
        self.assertEqual(self.probes, 1)

    def test_playing_installs_without_probe(self):
        outcome = refresh_once(None, verify=False)
        self.assertTrue(outcome.installed and outcome.healthy)
        self.assertEqual(self.probes, 0)

    def test_failed_probe_keeps_old_file(self):
        self.dest.write_text("old", encoding="utf-8")
        self.probe_ok = False
        outcome = refresh_once(None)
        self.assertEqual(outcome.kind, "probe")
        self.assertIsNone(outcome.digest)
        self.assertEqual(self.dest.read_text(encoding="utf-8"), "old")


class AlerterTests(unittest.TestCase):
    def setUp(self):
        self.sent = []
        self.alerter = Alerter(lambda **kw: self.sent.append(kw), alert_after=3600, cooldown=21600)

    def test_login_alerts_immediately_once_per_cooldown(self):
        self.alerter.observe(LOGIN, 0)
        self.alerter.observe(LOGIN, 30)
        self.assertEqual(len(self.sent), 1)
        self.assertIn("login", self.sent[0]["title"])
        self.alerter.observe(LOGIN, 21600)
        self.assertEqual(len(self.sent), 2)

    def test_probe_failure_alerts_only_when_persistent(self):
        self.alerter.observe(PROBE, 0)
        self.alerter.observe(PROBE, 1800)
        self.assertEqual(self.sent, [])
        self.alerter.observe(PROBE, 3600)
        self.assertEqual(len(self.sent), 1)

    def test_transient_failure_is_silent_and_resets(self):
        self.alerter.observe(PROBE, 0)
        self.alerter.observe(OK, 900)
        self.alerter.observe(PROBE, 3000)
        self.alerter.observe(PROBE, 4000)
        self.assertEqual(self.sent, [])

    def test_recovery_is_announced_after_an_alert(self):
        self.alerter.observe(LOGIN, 0)
        self.alerter.observe(STARTING, 10)
        self.alerter.observe(OK, 60)
        self.assertEqual(len(self.sent), 2)
        self.assertIn("OK", self.sent[1]["title"])

    def test_notification_errors_do_not_escape(self):
        def boom(**_):
            raise RuntimeError("ntfy down")
        Alerter(boom).observe(LOGIN, 0)


class ClassifierTests(unittest.TestCase):
    def test_403_is_stream_rule_and_urls_are_redacted(self):
        result = classify_cookie_probe_output(
            returncode=1, output="https://rr1.googlevideo.com/videoplayback?sig=x: Server returned 403 Forbidden")
        self.assertEqual(result.rule_name, "youtube_stream")
        self.assertNotIn("googlevideo", result.detail)


@unittest.skipUnless(hasattr(cookie_browser.os, "getuid"), "POSIX only")
class BotIsPlayingTests(unittest.TestCase):
    def proc(self, *processes):
        root = Path(tempfile.mkdtemp())
        for pid, comm, state in processes:
            (root / str(pid)).mkdir()
            (root / str(pid) / "stat").write_text(f"{pid} ({comm}) {state} 1 1 1")
        (root / "self").mkdir()
        return root

    def test_running_ffmpeg_means_playing(self):
        self.assertTrue(cookie_browser.bot_is_playing(self.proc((10, "python3", "S"), (11, "ffmpeg", "S"))))

    def test_zombie_ffmpeg_is_ignored(self):
        self.assertFalse(cookie_browser.bot_is_playing(self.proc((11, "ffmpeg", "Z"), (12, "ffmpeg2", "R"))))


if __name__ == "__main__":
    unittest.main()
