# core/banner.py — Banner ASCII all'avvio.
# Per disabilitarlo: SHOW_BANNER=false nel .env
import os

# Colori ANSI
_CYAN    = "\033[36m"
_YELLOW  = "\033[33m"
_WHITE   = "\033[97m"
_BOLD    = "\033[1m"
_RESET   = "\033[0m"

# Font figlet "slant" — lettere esatte, spaziatura uniforme
_ART = [
    r"    ____                __                                           ",
    r"   / __ \   __  __    / /_    ____     ____    ____ _   ____   ____  ",
    r"  / /_/ /  / / / /   / __/   / __ \   / __ \  / __ `/  /_  /  /_  /  ",
    r" / ____/  / /_/ /   / /_    / /_/ /  / / / / / /_/ /    / /_   / /_  ",
    r"/_/       \__, /    \__/    \____/  /_/ /_/  \__,_/    /_ _/  /_ _/  ",
    r"         /____/                                                      ",
]

_TAGLINE = "Discord Music Bot  \u25b8  v2026"
_W       = 71
_HLINE   = "\u2500" * _W


def _box(content: str, color: str = "") -> str:
    padded = content.ljust(_W)
    return _CYAN + "\u2502" + _RESET + color + padded + _RESET + _CYAN + "\u2502" + _RESET


def print_banner() -> None:
    """Stampa il banner a console. Disabilitabile con SHOW_BANNER=false nel .env."""
    if os.getenv("SHOW_BANNER", "true").lower() == "false":
        return

    top    = _CYAN + "\u250c" + _HLINE + "\u2510" + _RESET
    bottom = _CYAN + "\u2514" + _HLINE + "\u2518" + _RESET
    sep    = _CYAN + "\u251c" + _HLINE + "\u2524" + _RESET
    empty  = _box(" ")

    print()
    print(top)
    print(empty)
    for line in _ART:
        print(_box("  " + line, _WHITE + _BOLD))
    print(empty)
    print(sep)
    tag_pad = " " * ((_W - len(_TAGLINE)) // 2)
    print(_box(tag_pad + _TAGLINE, _YELLOW + _BOLD))
    print(bottom)
    print()
