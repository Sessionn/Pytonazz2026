import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from monitoring.audio_probe import probe
from monitoring.cookie_watchdog import CookieWatchConfig, _run_ytdlp_cookie_probe_sync, classify_cookie_probe_output
from config import Config


class AudioProbeTests(unittest.TestCase):
    def test_probe_uses_private_cookie_copy(self):
        with tempfile.TemporaryDirectory() as temp:
            original = Path(temp) / 'cookies.txt'
            content = '# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t2147483647\tSID\tprivate-test-value\n'
            original.write_text(content)
            copied = []
            def make_ydl(opts):
                copied.append(Path(opts['cookiefile']))
                self.assertNotEqual(copied[-1], original)
                copied[-1].write_text('simulated cookie rotation')
                ydl = MagicMock()
                ydl.__enter__.return_value.extract_info.return_value = {'url': 'https://example.test/audio'}
                return ydl
            with patch('yt_dlp.YoutubeDL', side_effect=make_ydl), patch('monitoring.audio_probe.subprocess.run', return_value=SimpleNamespace(returncode=0, stdout=b'PCM', stderr=b'')):
                self.assertTrue(probe(str(original), 'unused').ok)
            self.assertEqual(original.read_text(), content)
            self.assertFalse(copied[0].exists())

    def test_missing_and_invalid_cookie_files(self):
        self.assertEqual(probe('/nonexistent/cookies.txt', 'unused').rule_name, 'youtube_cookie')
        with tempfile.TemporaryDirectory() as temp:
            file = Path(temp) / 'cookies.txt'
            file.write_text('not netscape: private-value')
            result = probe(str(file), 'unused')
            self.assertFalse(result.ok)
            self.assertNotIn('private-value', result.detail)

    def test_audio_must_be_decoded_not_just_extracted(self):
        ydl = MagicMock()
        ydl.__enter__.return_value.extract_info.return_value = {'url': 'https://example.test/audio?secret=123'}
        with patch('yt_dlp.YoutubeDL', return_value=ydl), patch('monitoring.audio_probe.subprocess.run') as run:
            run.return_value = SimpleNamespace(returncode=1, stdout=b'', stderr=b'HTTP 403 https://example.test/?secret=123')
            result = probe('', 'https://example.test/video')
            self.assertEqual(result.rule_name, 'youtube_stream')
            self.assertNotIn('secret', result.detail)
            run.return_value = SimpleNamespace(returncode=0, stdout=b'\0'*16000, stderr=b'')
            self.assertTrue(probe('', 'https://example.test/video').ok)
            run.return_value = SimpleNamespace(returncode=0, stdout=b'', stderr=b'')
            self.assertFalse(probe('', 'https://example.test/video').ok)

    def test_outer_deadline_and_failure_are_nonfatal(self):
        config = CookieWatchConfig.from_mapping({})
        with patch('monitoring.cookie_watchdog.subprocess.run', side_effect=subprocess.TimeoutExpired('probe', 45)):
            self.assertFalse(_run_ytdlp_cookie_probe_sync(config).ok)

    def test_signed_urls_are_redacted(self):
        result = classify_cookie_probe_output(returncode=1, output='failure https://example.test/?secret=123')
        self.assertNotIn('secret', result.detail)

    def test_hls_is_preferred_over_rejected_progressive_format(self):
        import yt_dlp
        formats = [
            {'format_id': '18', 'url': 'https://example.test/direct', 'protocol': 'https', 'height': 360, 'vcodec': 'h264', 'acodec': 'aac', 'ext': 'mp4'},
            {'format_id': '93', 'url': 'https://example.test/hls.m3u8', 'protocol': 'm3u8_native', 'height': 360, 'vcodec': 'h264', 'acodec': 'aac', 'ext': 'mp4'},
        ]
        with yt_dlp.YoutubeDL({'quiet': True, 'format': Config.YDL_OPTIONS['format']}) as ydl:
            selected = list(ydl.build_format_selector(Config.YDL_OPTIONS['format'])({'formats': formats, 'has_merged_format': True}))
        self.assertEqual(selected[0]['format_id'], '93')


if __name__ == '__main__':
    unittest.main()
