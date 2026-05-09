import shlex

DEFAULT_CROSSFADE_SECONDS = 4.0
MIN_CROSSFADE_SECONDS = 2.0
MAX_CROSSFADE_SECONDS = 8.0


def clamp_crossfade_seconds(value: float) -> float:
    seconds = float(value)
    if seconds < MIN_CROSSFADE_SECONDS:
        return MIN_CROSSFADE_SECONDS
    if seconds > MAX_CROSSFADE_SECONDS:
        return MAX_CROSSFADE_SECONDS
    return seconds


def build_crossfade_options(
    *,
    next_stream_url: str,
    seconds: float,
    audio_filter: str | None,
) -> str:
    d = clamp_crossfade_seconds(seconds)

    if audio_filter:
        chain_a = f"{audio_filter},aresample=48000"
        chain_b = f"{audio_filter},aresample=48000"
    else:
        chain_a = "aresample=48000"
        chain_b = "aresample=48000"

    graph = (
        f"[0:a]{chain_a}[a0];"
        f"[1:a]{chain_b}[a1];"
        f"[a0][a1]acrossfade=d={d:.2f}:c1=tri:c2=tri[aout]"
    )

    quoted_url = shlex.quote(next_stream_url)
    quoted_graph = shlex.quote(graph)
    return f"-vn -i {quoted_url} -filter_complex {quoted_graph} -map [aout] -bufsize 64k"
