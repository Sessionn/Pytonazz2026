from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

ASSETS_DIR = REPO_ROOT / "assets"
ASSETS_CONFIG_DIR = ASSETS_DIR / "config"
ASSETS_DATA_DIR = ASSETS_DIR / "data"

DATA_DIR = REPO_ROOT / "data"
WELCOME_IMAGES_DIR = DATA_DIR / "welcome_images"
TMP_DIR = DATA_DIR / "tmp"

BOT_CONFIG_PATH = ASSETS_CONFIG_DIR / "bot_config.json"
CUSTOM_STATUSES_PATH = ASSETS_CONFIG_DIR / "custom_statuses.json"
BIRTHDAYS_PATH = ASSETS_DATA_DIR / "birthdays.json"
WELCOME_CONFIG_PATH = DATA_DIR / "welcome_config.json"


def ensure_runtime_dirs() -> None:
    ASSETS_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    ASSETS_DATA_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    WELCOME_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    TMP_DIR.mkdir(parents=True, exist_ok=True)
