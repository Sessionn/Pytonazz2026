from __future__ import annotations

import os
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Mapping


DEFAULT_TIMEOUT_SECONDS = 10


@dataclass(frozen=True)
class NtfyConfig:
    url: str
    token: str | None = None
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS

    @classmethod
    def from_env(cls) -> "NtfyConfig":
        return cls.from_mapping(os.environ)

    @classmethod
    def from_mapping(cls, values: Mapping[str, str]) -> "NtfyConfig":
        direct_url = values.get("PYTONAZZ_ALERT_URL", "").strip()
        base_url = values.get("PYTONAZZ_ALERT_BASE_URL", "").strip()
        topic = values.get("PYTONAZZ_ALERT_TOPIC", "").strip()
        token = values.get("PYTONAZZ_ALERT_TOKEN", "").strip() or None
        timeout_raw = values.get("PYTONAZZ_ALERT_TIMEOUT_SECONDS", "").strip()

        if direct_url:
            url = direct_url
        elif base_url and topic:
            url = f"{base_url.rstrip('/')}/{urllib.parse.quote(topic, safe='')}"
        else:
            raise ValueError(
                "Set PYTONAZZ_ALERT_URL oppure PYTONAZZ_ALERT_BASE_URL + PYTONAZZ_ALERT_TOPIC."
            )

        if not url.startswith("https://"):
            raise ValueError("PYTONAZZ alert URL deve usare https://.")

        timeout_seconds = DEFAULT_TIMEOUT_SECONDS
        if timeout_raw:
            timeout_seconds = max(1, int(timeout_raw))

        return cls(url=url, token=token, timeout_seconds=timeout_seconds)


def build_ntfy_request(
    config: NtfyConfig,
    *,
    title: str,
    message: str,
    priority: str = "default",
    tags: str = "warning",
) -> urllib.request.Request:
    headers = {
        "Title": _http_header_value(title, fallback="Pytonazz alert"),
        "Priority": _http_header_value(priority, fallback="default"),
        "Tags": _http_header_value(tags, fallback="warning"),
    }
    if config.token:
        headers["Authorization"] = f"Bearer {config.token}"

    return urllib.request.Request(
        config.url,
        data=message.encode("utf-8"),
        headers=headers,
        method="POST",
    )


def _http_header_value(value: str, *, fallback: str) -> str:
    cleaned = "".join(ch for ch in str(value) if _is_latin1_header_char(ch)).strip()
    return cleaned or fallback


def _is_latin1_header_char(ch: str) -> bool:
    if ch in "\r\n":
        return False
    try:
        ch.encode("latin-1")
        return True
    except UnicodeEncodeError:
        return False


class NtfyNotifier:
    def __init__(self, config: NtfyConfig):
        self.config = config

    def send(
        self,
        *,
        title: str,
        message: str,
        priority: str = "default",
        tags: str = "warning",
    ) -> None:
        request = build_ntfy_request(
            self.config,
            title=title,
            message=message,
            priority=priority,
            tags=tags,
        )
        context = ssl.create_default_context()
        try:
            with urllib.request.urlopen(
                request,
                timeout=self.config.timeout_seconds,
                context=context,
            ) as response:
                response.read()
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"ntfy HTTP {exc.code}: {exc.reason}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"ntfy connection error: {exc.reason}") from exc
