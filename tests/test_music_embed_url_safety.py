"""
tests/test_music_embed_url_safety.py

Run from project root:
    python tests/test_music_embed_url_safety.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.source_resolver.models import TrackInfo
from ui.music.embeds import now_playing_embed, queue_embed, queue_notification_embed


class DummyAvatar:
    url = "https://cdn.example.test/avatar.png"


class DummyRequester:
    display_name = "Tester"
    display_avatar = DummyAvatar()


class DummyQueue:
    def __init__(self, items):
        self.items = items


class DummyPlayer:
    def __init__(self, current, items=None):
        self.current = current
        self.queue = DummyQueue(items or [])
        self.is_paused = False


def fallback_track() -> TrackInfo:
    return TrackInfo(
        title="do you mind?",
        webpage_url="ytsearch1:do you mind?",
        duration=0,
        thumbnail="",
        requester="tester",
        requester_id=1,
        source="youtube",
    )


def test_now_playing_ignores_non_http_track_url() -> None:
    embed = now_playing_embed(DummyPlayer(fallback_track()))

    assert embed.url is None, embed.url


def test_queue_notification_ignores_non_http_track_url() -> None:
    embed = queue_notification_embed(fallback_track(), 1, DummyRequester())

    assert "ytsearch1:" not in embed.description, embed.description
    assert "**do you mind?**" in embed.description, embed.description


def test_queue_embed_ignores_non_http_track_url() -> None:
    track = fallback_track()
    embed = queue_embed(DummyPlayer(track, [track]))

    assert "ytsearch1:" not in (embed.description or ""), embed.description
    assert all("ytsearch1:" not in field.value for field in embed.fields), embed.fields


test_now_playing_ignores_non_http_track_url()
test_queue_notification_ignores_non_http_track_url()
test_queue_embed_ignores_non_http_track_url()
print("OK: music embeds ignore non-http track URLs")
