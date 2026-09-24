import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from monitoring.cookie_browser import netscape


class ExportTests(unittest.TestCase):
    def test_only_youtube_and_authenticated_session(self):
        base = {'domain': '.youtube.com', 'path': '/', 'secure': True, 'httpOnly': True, 'value': 'test'}
        self.assertIsNone(netscape([{**base, 'name': 'SID'}]))
        text = netscape([{**base, 'name': name} for name in ['SID', 'SAPISID']] +
                        [{**base, 'domain': '.google.com', 'name': 'PRIVATE'}])
        self.assertIn('#HttpOnly_.youtube.com', text)
        self.assertNotIn('PRIVATE', text)
        self.assertIsNone(netscape([{**base, 'domain': 'evilyoutube.com', 'name': n} for n in ['SID', 'SAPISID']]))

    def test_no_cookie_file_injection(self):
        with self.assertRaises(ValueError):
            netscape([{'domain': '.youtube.com', 'name': 'SID', 'value': 'a\nb'}])


if __name__ == '__main__':
    unittest.main()
