from __future__ import annotations

FILTER_PRESETS: dict[str, tuple[str | None, str]] = {
    "off": (None, "Nessun filtro"),
    "nightcore": ("aresample=48000,asetrate=48000*1.25", "Nightcore"),
    "vaporwave": ("aresample=48000,asetrate=48000*0.8", "Vaporwave"),
    "8d": ("apulsator=hz=0.08", "8D Audio"),
    "bassboost": ("bass=g=8:f=110:w=0.8", "Bass Boost"),
    "trebleboost": ("treble=g=6:f=4500:w=0.8", "Treble Boost"),
    "vocalboost": ("equalizer=f=2500:t=q:w=1.2:g=5", "Vocal Boost"),
    "radio": ("highpass=f=300,lowpass=f=3200", "Radio / Phone"),
    "night": (
        "acompressor=threshold=0.22:ratio=2.5:attack=5:release=120,alimiter=limit=0.93",
        "Night Mode",
    ),
}

LIVE_FILTER_PRESETS: dict[str, dict[str, float]] = {
    "off": {
        "low_gain": 0.0,
        "mid_gain": 0.0,
        "high_gain": 0.0,
        "presence_gain": 0.0,
        "highpass_hz": 0.0,
        "lowpass_hz": 20000.0,
        "pan_rate_hz": 0.0,
        "pan_depth": 0.0,
        "playback_rate": 1.0,
    },
    "nightcore": {
        "low_gain": -1.0,
        "mid_gain": 1.5,
        "high_gain": 5.5,
        "presence_gain": 1.5,
        "highpass_hz": 30.0,
        "lowpass_hz": 18500.0,
        "pan_rate_hz": 0.0,
        "pan_depth": 0.0,
        "playback_rate": 1.25,
    },
    "vaporwave": {
        "low_gain": 4.0,
        "mid_gain": -1.0,
        "high_gain": -4.5,
        "presence_gain": -1.0,
        "highpass_hz": 0.0,
        "lowpass_hz": 8500.0,
        "pan_rate_hz": 0.0,
        "pan_depth": 0.0,
        "playback_rate": 0.8,
    },
    "8d": {
        "low_gain": 0.0,
        "mid_gain": 0.5,
        "high_gain": 1.5,
        "presence_gain": 0.0,
        "highpass_hz": 0.0,
        "lowpass_hz": 20000.0,
        "pan_rate_hz": 0.08,
        "pan_depth": 0.92,
        "playback_rate": 1.0,
    },
    "bassboost": {
        "low_gain": 8.0,
        "mid_gain": -1.0,
        "high_gain": 1.0,
        "presence_gain": 0.0,
        "highpass_hz": 0.0,
        "lowpass_hz": 20000.0,
        "pan_rate_hz": 0.0,
        "pan_depth": 0.0,
        "playback_rate": 1.0,
    },
    "trebleboost": {
        "low_gain": 0.0,
        "mid_gain": 0.0,
        "high_gain": 6.0,
        "presence_gain": 0.0,
        "highpass_hz": 0.0,
        "lowpass_hz": 20000.0,
        "pan_rate_hz": 0.0,
        "pan_depth": 0.0,
        "playback_rate": 1.0,
    },
    "vocalboost": {
        "low_gain": -1.0,
        "mid_gain": 1.5,
        "high_gain": 1.0,
        "presence_gain": 5.0,
        "highpass_hz": 0.0,
        "lowpass_hz": 20000.0,
        "pan_rate_hz": 0.0,
        "pan_depth": 0.0,
        "playback_rate": 1.0,
    },
    "radio": {
        "low_gain": -5.0,
        "mid_gain": 2.0,
        "high_gain": -2.5,
        "presence_gain": 2.0,
        "highpass_hz": 300.0,
        "lowpass_hz": 3200.0,
        "pan_rate_hz": 0.0,
        "pan_depth": 0.0,
        "playback_rate": 1.0,
    },
    "night": {
        "low_gain": -0.5,
        "mid_gain": 0.5,
        "high_gain": -2.5,
        "presence_gain": -1.0,
        "highpass_hz": 0.0,
        "lowpass_hz": 11000.0,
        "pan_rate_hz": 0.0,
        "pan_depth": 0.0,
        "playback_rate": 1.0,
    },
}

EQ_DEFAULT = {"low": 0.0, "mid": 0.0, "high": 0.0}
TONE_FILTER_DEFAULT = {"highpass_hz": 0.0, "lowpass_hz": 20000.0}
def get_filter_preset(name: str) -> tuple[str | None, str]:
    return FILTER_PRESETS.get(name, FILTER_PRESETS["off"])


def is_live_filter_preset(name: str) -> bool:
    return name in LIVE_FILTER_PRESETS


def get_live_filter_preset(name: str) -> dict[str, float]:
    return dict(LIVE_FILTER_PRESETS.get(name, LIVE_FILTER_PRESETS["off"]))


def normalize_eq(values: dict | None) -> dict[str, float]:
    data = dict(EQ_DEFAULT)
    if not values:
        return data
    for key in data:
        try:
            gain = float(values.get(key, 0.0))
        except (TypeError, ValueError):
            gain = 0.0
        data[key] = max(-12.0, min(12.0, gain))
    return data


def normalize_tone_filters(values: dict | None) -> dict[str, float]:
    data = dict(TONE_FILTER_DEFAULT)
    if not values:
        return data

    try:
        highpass = float(values.get("highpass_hz", 0.0))
    except (TypeError, ValueError):
        highpass = 0.0
    try:
        lowpass = float(values.get("lowpass_hz", 0.0))
    except (TypeError, ValueError):
        lowpass = 0.0

    data["highpass_hz"] = max(0.0, min(4000.0, highpass))

    if lowpass <= 0.0:
        data["lowpass_hz"] = 20000.0
    else:
        data["lowpass_hz"] = max(200.0, min(20000.0, lowpass))

    if 0.0 < data["highpass_hz"] < 20.0:
        data["highpass_hz"] = 20.0
    return data


def compose_audio_filter(base_filter: str | None, eq: dict | None) -> str | None:
    parts: list[str] = []
    if base_filter:
        parts.append(base_filter)
    return ",".join(parts) if parts else None
