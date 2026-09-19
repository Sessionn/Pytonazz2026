"""Turn FFmpeg process failures into player errors, including older discord.py."""
import subprocess

import discord


class CheckedFFmpegPCMAudio(discord.FFmpegPCMAudio):
    def read(self) -> bytes:
        data = super().read()
        if data:
            return data
        process = getattr(self, '_process', None)
        if process and hasattr(process, 'wait'):
            try:
                code = process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                code = process.poll()
            if code not in (None, 0):
                raise RuntimeError(f'FFmpeg exited with return code of {code}')
        return data
