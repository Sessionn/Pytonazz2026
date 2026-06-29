"""
tests/test_audio_backends_static.py

Esegui dalla root del progetto con:
    python tests/test_audio_backends_static.py
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

expected_files = [
    ROOT / "core" / "audio_backends" / "__init__.py",
    ROOT / "core" / "audio_backends" / "base.py",
    ROOT / "core" / "audio_backends" / "current.py",
    ROOT / "core" / "audio_backends" / "lavalink.py",
    ROOT / "core" / "audio_backends" / "factory.py",
    ROOT / "tools" / "benchmark_audio_backends.py",
    ROOT / "infra" / "lavalink" / "docker-compose.yml",
    ROOT / "infra" / "lavalink" / "application.yml",
]

for path in expected_files:
    assert path.exists(), f"FAIL: missing {path.relative_to(ROOT)}"

config_py = (ROOT / "config.py").read_text(encoding="utf-8")
assert "AUDIO_BACKEND" in config_py, "FAIL: manca Config.AUDIO_BACKEND"
assert "LAVALINK_URI" in config_py, "FAIL: manca Config.LAVALINK_URI"
assert "LAVALINK_PASSWORD" in config_py, "FAIL: manca Config.LAVALINK_PASSWORD"

factory_py = (ROOT / "core" / "audio_backends" / "factory.py").read_text(encoding="utf-8")
assert "def create_audio_backend" in factory_py, "FAIL: manca factory backend"
assert "current" in factory_py and "lavalink" in factory_py, "FAIL: factory non espone entrambi i backend"

benchmark_py = (ROOT / "tools" / "benchmark_audio_backends.py").read_text(encoding="utf-8")
assert "Config.CACHE_ENABLED = False" in benchmark_py, "FAIL: benchmark deve disabilitare cache DB"
assert "_clear_runtime_caches" in benchmark_py, "FAIL: benchmark deve svuotare cache in memoria tra casi"
assert "--backend" in benchmark_py, "FAIL: benchmark deve accettare --backend"
assert "--jsonl" in benchmark_py, "FAIL: benchmark deve poter produrre JSONL confrontabile"

requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
assert "wavelink" in requirements.lower(), "FAIL: requirements deve includere wavelink per link-up"

print("OK: audio backend adapter and benchmark surfaces exist")
