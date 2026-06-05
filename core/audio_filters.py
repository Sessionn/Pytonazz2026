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
    "reverb": ("aecho=0.8:0.88:60|120:0.22|0.12", "Reverb"),
    "echo": ("aecho=0.8:0.82:140|230:0.32|0.18", "Echo"),
    "wide": (None, "Wide Stereo"),
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
    "reverb": {
        "low_gain": 0.0,
        "mid_gain": 0.0,
        "high_gain": 0.0,
        "presence_gain": 0.5,
        "highpass_hz": 0.0,
        "lowpass_hz": 18000.0,
        "pan_rate_hz": 0.0,
        "pan_depth": 0.0,
        "playback_rate": 1.0,
        "reverb_mix": 0.22,
        "reverb_decay": 0.42,
    },
    "echo": {
        "low_gain": 0.0,
        "mid_gain": 0.0,
        "high_gain": 0.0,
        "presence_gain": 0.0,
        "highpass_hz": 0.0,
        "lowpass_hz": 17000.0,
        "pan_rate_hz": 0.0,
        "pan_depth": 0.0,
        "playback_rate": 1.0,
        "reverb_mix": 0.34,
        "reverb_decay": 0.58,
    },
    "wide": {
        "low_gain": 0.0,
        "mid_gain": 0.0,
        "high_gain": 0.0,
        "presence_gain": 0.0,
        "highpass_hz": 0.0,
        "lowpass_hz": 20000.0,
        "pan_rate_hz": 0.0,
        "pan_depth": 0.0,
        "playback_rate": 1.0,
        "stereo_width": 1.28,
    },
}

BASE_FILTER_NAMES = ("off", "nightcore", "vaporwave", "night")
FX_FILTER_NAMES = ("bassboost", "trebleboost", "vocalboost", "radio", "reverb", "echo", "wide", "8d")

FILTER_COMPATIBILITY: dict[str, set[str]] = {
    "off": set(FX_FILTER_NAMES),
    "nightcore": set(FX_FILTER_NAMES),
    "vaporwave": set(FX_FILTER_NAMES),
    "night": set(FX_FILTER_NAMES),
}

EQ_DEFAULT = {"sub": 0.0, "low": 0.0, "mid": 0.0, "high": 0.0, "air": 0.0}
TONE_FILTER_DEFAULT = {
    "highpass_hz": 0.0,
    "lowpass_hz": 20000.0,
    "presence_gain": 0.0,
    "stereo_width": 1.0,
}


def is_base_filter(name: str) -> bool:
    return (name or "off").strip().lower() in BASE_FILTER_NAMES


def is_fx_filter(name: str) -> bool:
    return (name or "").strip().lower() in FX_FILTER_NAMES


def is_filter_combo_compatible(base_filter_name: str, fx_name: str) -> bool:
    base = (base_filter_name or "off").strip().lower()
    fx = (fx_name or "").strip().lower()
    if not is_fx_filter(fx):
        return False
    if not is_base_filter(base):
        base = "off"
    return fx in FILTER_COMPATIBILITY.get(base, set())


def list_base_filters() -> list[dict[str, str]]:
    return [{"name": name, "label": FILTER_PRESETS.get(name, (None, name))[1]} for name in BASE_FILTER_NAMES]


def list_fx_filters(base_filter_name: str = "off") -> list[dict[str, object]]:
    return [
        {
            "name": name,
            "label": FILTER_PRESETS.get(name, (None, name))[1],
            "compatible": is_filter_combo_compatible(base_filter_name, name),
        }
        for name in FX_FILTER_NAMES
    ]
def get_filter_preset(name: str) -> tuple[str | None, str]:
    return FILTER_PRESETS.get(name, FILTER_PRESETS["off"])


def is_live_filter_preset(name: str) -> bool:
    return name in LIVE_FILTER_PRESETS


def get_live_filter_preset(name: str) -> dict[str, float]:
    return dict(LIVE_FILTER_PRESETS.get(name, LIVE_FILTER_PRESETS["off"]))


def combine_live_filter_preset(base_filter_name: str, fx_names: list[str] | tuple[str, ...] | set[str]) -> dict[str, float]:
    combined = get_live_filter_preset(base_filter_name)
    fx_list = sorted({(name or "").strip().lower() for name in (fx_names or []) if is_fx_filter(name)})
    for fx_name in fx_list:
        if not is_filter_combo_compatible(base_filter_name, fx_name):
            continue
        fx_preset = get_live_filter_preset(fx_name)
        combined["low_gain"] = max(-12.0, min(12.0, float(combined.get("low_gain", 0.0)) + float(fx_preset.get("low_gain", 0.0))))
        combined["mid_gain"] = max(-12.0, min(12.0, float(combined.get("mid_gain", 0.0)) + float(fx_preset.get("mid_gain", 0.0))))
        combined["high_gain"] = max(-12.0, min(12.0, float(combined.get("high_gain", 0.0)) + float(fx_preset.get("high_gain", 0.0))))
        combined["presence_gain"] = max(-12.0, min(12.0, float(combined.get("presence_gain", 0.0)) + float(fx_preset.get("presence_gain", 0.0))))
        combined["highpass_hz"] = max(float(combined.get("highpass_hz", 0.0)), float(fx_preset.get("highpass_hz", 0.0)))
        lowpass = float(combined.get("lowpass_hz", 20000.0))
        fx_lowpass = float(fx_preset.get("lowpass_hz", 20000.0))
        combined["lowpass_hz"] = min(lowpass, fx_lowpass)
        combined["pan_rate_hz"] = float(combined.get("pan_rate_hz", 0.0)) or float(fx_preset.get("pan_rate_hz", 0.0))
        combined["pan_depth"] = max(float(combined.get("pan_depth", 0.0)), float(fx_preset.get("pan_depth", 0.0)))
        combined["playback_rate"] = float(combined.get("playback_rate", 1.0)) * float(fx_preset.get("playback_rate", 1.0))
        combined["reverb_mix"] = max(float(combined.get("reverb_mix", 0.0)), float(fx_preset.get("reverb_mix", 0.0)))
        combined["reverb_decay"] = max(float(combined.get("reverb_decay", 0.0)), float(fx_preset.get("reverb_decay", 0.0)))
        combined["stereo_width"] = max(float(combined.get("stereo_width", 1.0)), float(fx_preset.get("stereo_width", 1.0)))
    combined["playback_rate"] = max(0.5, min(1.5, float(combined.get("playback_rate", 1.0))))
    combined["reverb_mix"] = max(0.0, min(0.55, float(combined.get("reverb_mix", 0.0))))
    combined["reverb_decay"] = max(0.0, min(0.75, float(combined.get("reverb_decay", 0.0))))
    combined["stereo_width"] = max(0.65, min(1.45, float(combined.get("stereo_width", 1.0))))
    return combined


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
    try:
        presence = float(values.get("presence_gain", 0.0))
    except (TypeError, ValueError):
        presence = 0.0
    try:
        width = float(values.get("stereo_width", 1.0))
    except (TypeError, ValueError):
        width = 1.0
    data["presence_gain"] = max(-8.0, min(8.0, presence))
    data["stereo_width"] = max(0.65, min(1.45, width))
    return data


def compose_audio_filter(base_filter: str | None, eq: dict | None) -> str | None:
    parts: list[str] = []
    if base_filter:
        parts.append(base_filter)
    return ",".join(parts) if parts else None
