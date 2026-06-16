"""
Verifica la normalizzazione dei path cookie da .env.

Esegui dalla root del progetto con:
    python tests/test_config_cookie_path.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from config import _resolve_optional_file_path


project_root = Path(config.__file__).resolve().parent

assert _resolve_optional_file_path("") == ""
assert _resolve_optional_file_path("cookies.txt") == str(project_root / "cookies.txt")
assert _resolve_optional_file_path("../cookies.txt") == str(project_root / "../cookies.txt")

home_path = _resolve_optional_file_path("~/cookies.txt")
assert home_path == str(Path.home() / "cookies.txt"), home_path

absolute = str(Path.home() / "absolute-cookies.txt")
assert _resolve_optional_file_path(absolute) == absolute

print("OK: cookie paths are resolved from project root or user home")
