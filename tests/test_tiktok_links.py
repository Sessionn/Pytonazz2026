"""
tests/test_tiktok_links.py

Esegui dalla root del progetto con:
    python tests/test_tiktok_links.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.music.input import is_text_search, normalize_url_like
from core.source_resolver import SourceResolver, tiktok

VIDEO_PC = "https://www.tiktok.com/@sharaxyna/video/7669122121381055764?is_from_webapp=1&sender_device=pc"
SOUND_PC = "https://www.tiktok.com/music/original-sound-☆rara🏎️-7669122156421532437?is_from_webapp=1&sender_device=pc"

# Riconoscimento dei link (con e senza parametri, mobile, brevi, embed).
assert tiktok.parse_tiktok_url(VIDEO_PC) == tiktok.TikTokRef("video", "7669122121381055764", "sharaxyna")
assert tiktok.parse_tiktok_url(VIDEO_PC.split("?")[0]).id == "7669122121381055764"
assert tiktok.parse_tiktok_url(SOUND_PC) == tiktok.TikTokRef("music", "7669122156421532437")
assert tiktok.parse_tiktok_url("https://www.tiktok.com/music/Lovely-Day-6774722733428410374").id == "6774722733428410374"
assert tiktok.parse_tiktok_url("https://m.tiktok.com/v/7669122121381055764.html").kind == "video"
assert tiktok.parse_tiktok_url("https://www.tiktok.com/embed/v2/7669122121381055764").kind == "video"
assert tiktok.parse_tiktok_url("https://www.tiktok.com/@user/photo/7669122121381055764").kind == "video"
assert tiktok.parse_tiktok_url("https://vm.tiktok.com/ZNdAbC123/") == tiktok.TikTokRef("short", "ZNdAbC123")
assert tiktok.parse_tiktok_url("https://www.tiktok.com/t/ZTabc123/").kind == "short"
assert tiktok.parse_tiktok_url("https://www.youtube.com/watch?v=abc") is None
assert tiktok.parse_tiktok_url("tiktok version blinding lights") is None

# Un link incollato senza https:// e' un link, non una ricerca testuale.
assert normalize_url_like("www.tiktok.com/@a/video/7669122121381055764") == "https://www.tiktok.com/@a/video/7669122121381055764"
assert not is_text_search(normalize_url_like("vm.tiktok.com/ZNdAbC123/"))
assert is_text_search("blinding lights tiktok version")

# Canzone pubblicata contro suono originale.
song = tiktok.TikTokSound("1", "Lovely Day", "Bill Withers", False, "https://cdn.test/a.mp3")
assert tiktok.is_named_song(song)
for title, original in (("original sound - rara", False), ("suono originale - x", False), ("Lovely Day", True)):
    assert not tiktok.is_named_song(tiktok.TikTokSound("1", title, "x", original, "u")), title

# Titolo del video senza hashtag.
video = tiktok.TikTokVideo("7", "sharaxyna", "rara", "Peak Iceman #kimiraikkonen #f1  #fyp", 18, "https://cdn.test/v.mp4",
                           sound=tiktok.TikTokSound("9", "original sound - rara", "rara", True, "https://cdn.test/s.mp3"))
assert tiktok.video_title(video) == "Peak Iceman", tiktok.video_title(video)


async def resolve_with(fake_video=None, fake_sound=None, fake_full=None):
    originals = (tiktok.fetch_video, tiktok.fetch_sound, SourceResolver.resolve_choices)
    tiktok.fetch_video = fake_video or originals[0]
    tiktok.fetch_sound = fake_sound or originals[1]
    if fake_full is not None:
        async def _full(cls, query, requester, requester_id, n=7):
            fake_full.append(query)
            from core.source_resolver.models import TrackInfo
            return [TrackInfo("Lovely Day", "https://www.youtube.com/watch?v=full", 254, "", requester, requester_id,
                              "youtube", stream_url="https://stream.test/full", artist="Bill Withers")]
        SourceResolver.resolve_choices = classmethod(_full)
    SourceResolver._stream_url_cache.clear()
    try:
        return await SourceResolver._resolve_tiktok(
            VIDEO_PC if fake_video else SOUND_PC, "tester", 1
        )
    finally:
        tiktok.fetch_video, tiktok.fetch_sound, SourceResolver.resolve_choices = originals
        SourceResolver._stream_url_cache.clear()


# Video: si riproduce l'audio del video.
tracks = asyncio.run(resolve_with(fake_video=lambda vid: video))
assert len(tracks) == 1 and tracks[0].source == "tiktok", tracks
assert tracks[0].stream_url == "https://cdn.test/v.mp4", tracks[0]
assert tracks[0].webpage_url == "https://www.tiktok.com/@sharaxyna/video/7", tracks[0]
assert tracks[0].title == "Peak Iceman" and tracks[0].duration == 18

# Suono originale: si riproduce il suono.
tracks = asyncio.run(resolve_with(fake_sound=lambda sid: video.sound))
assert tracks[0].stream_url == "https://cdn.test/s.mp3", tracks[0]
assert tracks[0].webpage_url == "https://www.tiktok.com/music/x-7669122156421532437", tracks[0]

# Suono che e' una canzone pubblicata: versione completa cercata per titolo + artista.
asked = []
tracks = asyncio.run(resolve_with(fake_sound=lambda sid: song, fake_full=asked))
assert asked == ["Lovely Day Bill Withers"], asked
assert tracks[0].webpage_url == "https://www.youtube.com/watch?v=full", tracks[0]

# Link scaduto in coda: il rinnovo passa dalla pagina di embed, non da yt-dlp.
original_fresh = tiktok.fresh_stream_url
try:
    tiktok.fresh_stream_url = lambda url: "https://cdn.test/nuovo.mp4"
    SourceResolver._stream_url_cache.clear()
    assert SourceResolver._fetch_stream_url("https://www.tiktok.com/@a/video/7") == "https://cdn.test/nuovo.mp4"
finally:
    tiktok.fresh_stream_url = original_fresh
    SourceResolver._stream_url_cache.clear()

print("OK: link TikTok (video, suoni, link brevi) senza account")
