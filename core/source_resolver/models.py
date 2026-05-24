from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TrackInfo:
    title: str
    webpage_url: str
    duration: int
    thumbnail: str
    requester: str
    requester_id: int
    source: str
    stream_url: str = field(default="", repr=False)
    artist: str = field(default="", repr=False)
    origin_query: str = field(default="", repr=False)
    spotify_url: str = field(default="", repr=False)
    popularity: int = field(default=0, repr=False)


def clone_track(track: TrackInfo) -> TrackInfo:
    return TrackInfo(
        title=track.title,
        webpage_url=track.webpage_url,
        duration=track.duration,
        thumbnail=track.thumbnail,
        requester=track.requester,
        requester_id=track.requester_id,
        source=track.source,
        stream_url=track.stream_url,
        artist=track.artist,
        origin_query=track.origin_query,
        spotify_url=track.spotify_url,
        popularity=track.popularity,
    )
