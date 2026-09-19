"""Failures reach the audio callback and stale callbacks never advance a new track."""
import asyncio
import shutil
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import discord
from core.music.ffmpeg_source import CheckedFFmpegPCMAudio
from core.music.player import MusicPlayer
from config import Config


def check_source():
    source = object.__new__(CheckedFFmpegPCMAudio)
    source.cleanup = Mock()  # This unit fixture owns no real subprocess.
    source._process = Mock()
    with patch.object(discord.FFmpegPCMAudio, 'read', return_value=b''):
        source._process.wait.return_value = 1
        try:
            source.read()
        except RuntimeError as error:
            assert 'return code of 1' in str(error)
        else:
            raise AssertionError('FFmpeg error treated as successful EOF')
        source._process.wait.return_value = 0
        assert source.read() == b''
    with patch.object(discord.FFmpegPCMAudio, 'read', return_value=b'pcm'):
        assert source.read() == b'pcm'
    source._process = None


async def check_retry():
    player = MusicPlayer(SimpleNamespace(id=1, voice_client=None), None)
    track = SimpleNamespace(title='Test', webpage_url='https://example.test/song', stream_url='expired')
    player.current = track
    player.play_next = AsyncMock()
    with patch('core.music.player.SourceResolver.invalidate_stream_cache') as invalidate, patch('core.music.player.cache_db.invalidate_webpage_url'):
        await player._retry_current_after_ffmpeg_error(track, 0)
        invalidate.assert_called_once_with(track.webpage_url)
        assert track.stream_url == '' and player._filter_replay
        player.play_next.assert_awaited_once_with(_depth=1)
        await player._retry_current_after_ffmpeg_error(track, 1)
        assert player.current is None
        player.play_next.reset_mock()
        player.current = SimpleNamespace(title='New track')
        await player._retry_current_after_ffmpeg_error(track, 0)
        player.play_next.assert_not_awaited()


def check_real_http_403():
    executable = shutil.which('ffmpeg')
    if not executable:
        print('SKIP: real HTTP 403 probe requires FFmpeg on PATH')
        return
    class Forbidden(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(403)
            self.end_headers()
        def log_message(self, *args):
            pass
    server = HTTPServer(('127.0.0.1', 0), Forbidden)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    source = None
    try:
        started = time.monotonic()
        source = CheckedFFmpegPCMAudio(
            f'http://127.0.0.1:{server.server_port}/forbidden', executable=executable,
            before_options=Config.FFMPEG_OPTIONS['before_options'] + ' -http_proxy ""',
            options='-vn',
        )
        try:
            source.read()
        except Exception:
            assert time.monotonic() - started < 5, '403 retried instead of returning to resolver'
        else:
            raise AssertionError('Real FFmpeg 403 was not reported as an error')
    finally:
        if source:
            source.cleanup()
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


check_source()
asyncio.run(check_retry())
check_real_http_403()
print('OK: nonzero exit, normal EOF, one refresh, failed repeat and stale callback')
