from __future__ import annotations

from config import Config
from core.audio_backends.current import CurrentAudioBackend
from core.audio_backends.lavalink import LavalinkAudioBackend


def create_audio_backend(name: str | None = None):
    backend = (name or Config.AUDIO_BACKEND or "current").strip().lower()
    if backend in {"current", "ffmpeg", "yt-dlp", "ytdlp"}:
        return CurrentAudioBackend()
    if backend in {"lavalink", "wavelink"}:
        return LavalinkAudioBackend()
    raise ValueError(f"Unknown audio backend: {backend}")
