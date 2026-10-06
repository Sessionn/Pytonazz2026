import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from monitoring.cookie_browser import Alerter, Outcome, netscape
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


if __name__ == "__main__":
    unittest.main()
