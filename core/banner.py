# core/banner.py — Banner ASCII all'avvio.
# Per disabilitarlo: SHOW_BANNER=false nel .env
import os


# Colori ANSI
_CYAN   = "\033[36m"
_YELLOW = "\033[33m"
_WHITE  = "\033[97m"
_BOLD   = "\033[1m"
_RESET  = "\033[0m"


# Font figlet
_ART = [
    r":'########::'##:::'##:'########::'#######::'##::: ##::::'###::::'########:'########:",
    r": ##.... ##:. ##:'##::... ##..::'##.... ##: ###:: ##:::'## ##:::..... ##::..... ##::",
    r": ##:::: ##::. ####:::::: ##:::: ##:::: ##: ####: ##::'##:. ##:::::: ##::::::: ##:::",
    r": ########::::. ##::::::: ##:::: ##:::: ##: ## ## ##:'##:::. ##:::: ##::::::: ##::::",
    r": ##.....:::::: ##::::::: ##:::: ##:::: ##: ##. ####: #########::: ##::::::: ##:::::",
    r": ##::::::::::: ##::::::: ##:::: ##:::: ##: ##:. ###: ##.... ##:: ##::::::: ##::::::",
    r": ##::::::::::: ##::::::: ##::::. #######:: ##::. ##: ##:::: ##: ########: ########:",
    r":..::::::::::::..::::::::..::::::.......:::..::::..::..:::::..::........::........::",
]

_TAGLINE = "Discord Music Bot ▸ v2026"
_W = max(max(len(line) for line in _ART), len(_TAGLINE)) + 6
_HLINE = "─" * _W


def _box(content: str, color: str = "") -> str:
    padded = content.ljust(_W)
    return _CYAN + "│" + _RESET + color + padded + _RESET + _CYAN + "│" + _RESET


def print_banner() -> None:
    """Stampa il banner a console. Disabilitabile con SHOW_BANNER=false nel .env."""
    if os.getenv("SHOW_BANNER", "true").lower() == "false":
        return

    top = _CYAN + "┌" + _HLINE + "┐" + _RESET
    bottom = _CYAN + "└" + _HLINE + "┘" + _RESET
    sep = _CYAN + "├" + _HLINE + "┤" + _RESET
    empty = _box("")

    print()
    print(top)
    print(empty)

    for line in _ART:
        print(_box(line.center(_W), _WHITE + _BOLD))

    print(empty)
    print(sep)
    print(_box(_TAGLINE.center(_W), _YELLOW + _BOLD))
    print(bottom)
    print()