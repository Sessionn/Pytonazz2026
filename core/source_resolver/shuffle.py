"""Shuffle: shared resolver policies and helpers."""
from __future__ import annotations
import random
from collections import defaultdict
from typing import Callable, TypeVar

_T = TypeVar("_T")


def _popularity_tier_shuffle(pairs: list[tuple]) -> list[tuple]:
    if not pairs:
        return []
    sorted_pairs = sorted(
        pairs,
        key=lambda p: p[0].get("popularity", 0) if isinstance(p[0], dict) else getattr(p[0], "popularity", 0),
        reverse=True,
    )
    n     = len(sorted_pairs)
    third = max(1, n // 3)
    top   = sorted_pairs[:third]
    mid   = sorted_pairs[third:third * 2]
    deep  = sorted_pairs[third * 2:]
    random.shuffle(top)
    random.shuffle(mid)
    random.shuffle(deep)
    result = []
    for i in range(max(len(top), len(mid), len(deep))):
        if i < len(top):  result.append(top[i])
        if i < len(mid):  result.append(mid[i])
        if i < len(deep): result.append(deep[i])
    return result


def _bucket_shuffle(items: list[_T], key_fn: Callable[[_T], str]) -> list[_T]:
    if not items:
        return []
    buckets: dict[str, list] = defaultdict(list)
    for item in items:
        buckets[key_fn(item).strip().lower()].append(item)
    for lst in buckets.values():
        random.shuffle(lst)
    sorted_keys = sorted(buckets, key=lambda k: len(buckets[k]), reverse=True)
    total  = len(items)
    result: list = [None] * total
    for key in sorted_keys:
        group   = buckets[key]
        n       = len(group)
        spacing = total / n
        for i, item in enumerate(group):
            ideal = int((i + 0.5) * spacing)
            for delta in range(total):
                pos = (ideal + delta) % total
                if result[pos] is None:
                    result[pos] = item
                    break
    return [x for x in result if x is not None]


def spotify_style_shuffle(tracks: list["TrackInfo"]) -> list["TrackInfo"]:
    return _bucket_shuffle(tracks, lambda t: getattr(t, "artist", "") or "unknown")


def _shuffle_pairs(pairs: list[tuple]) -> list[tuple]:
    return _bucket_shuffle(pairs, lambda p: p[1])
