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

EQ_DEFAULT = {"low": 0.0, "mid": 0.0, "high": 0.0}
EQ_BANDS = {
    "low": "equalizer=f=120:t=q:w=0.8:g={gain}",
    "mid": "equalizer=f=1000:t=q:w=1.0:g={gain}",
    "high": "equalizer=f=8000:t=q:w=0.7:g={gain}",
}


def get_filter_preset(name: str) -> tuple[str | None, str]:
    return FILTER_PRESETS.get(name, FILTER_PRESETS["off"])


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


def compose_audio_filter(base_filter: str | None, eq: dict | None) -> str | None:
    parts: list[str] = []
    if base_filter:
        parts.append(base_filter)
    eq_norm = normalize_eq(eq)
    for band, template in EQ_BANDS.items():
        gain = eq_norm[band]
        if abs(gain) < 0.01:
            continue
        parts.append(template.format(gain=f"{gain:.2f}"))
    return ",".join(parts) if parts else None

