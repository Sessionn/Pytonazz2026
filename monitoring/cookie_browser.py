"""Maintain YouTube cookies from the dedicated, manually authenticated browser.

Run as a user service; WebDriver and noVNC must remain on localhost.
Never logs cookie values or handles Google passwords.
"""
from __future__ import annotations

import json
import os
import shutil
import time
import urllib.request
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlsplit

ENDPOINT = "http://127.0.0.1:14444"
STATE = Path.home() / ".local/share/pytonazz-cookie-browser"


def request(method, path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(ENDPOINT + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=40) as response:
        return json.load(response)["value"]


def session():
    saved = STATE / "session"
    if saved.exists():
        sid = saved.read_text().strip()
        try:
            request("GET", f"/session/{sid}/url")
            return sid
        except Exception:
            pass
    value = request("POST", "/session", {"capabilities": {"alwaysMatch": {
        "browserName": "chrome", "goog:chromeOptions": {
            "args": ["--user-data-dir=/home/seluser/pytonazz-profile", "--no-first-run", "--window-size=1280,900"],
            "excludeSwitches": ["enable-automation"],
        }}}})
    sid = value["sessionId"]
    saved.write_text(sid)
    os.chmod(saved, 0o600)
    request("POST", f"/session/{sid}/url", {"url": "https://www.youtube.com/"})
    return sid


def netscape(cookies):
    lines = ["# Netscape HTTP Cookie File"]
    accepted = []
    for cookie in cookies:
        domain = cookie.get("domain", "")
        if domain.lstrip(".") != "youtube.com" and not domain.endswith(".youtube.com"):
            continue
        values = [domain, "TRUE" if domain.startswith(".") else "FALSE", cookie.get("path", "/"),
                  "TRUE" if cookie.get("secure") else "FALSE", str(int(cookie.get("expiry", 0))),
                  cookie["name"], cookie["value"]]
        if any(any(char in value for char in "\t\r\n") for value in values):
            raise ValueError("Invalid cookie fields")
        if cookie.get("httpOnly"):
            values[0] = "#HttpOnly_" + values[0]
        lines.append("\t".join(values))
        accepted.append(cookie["name"])
    if not ({"SID", "SAPISID"} <= set(accepted)):
        return None
    return "\n".join(lines) + "\n"


def refresh_once():
    from config import Config
    from monitoring.cookie_watchdog import CookieWatchConfig, _run_ytdlp_cookie_probe_sync

    sid = session()
    url = request("GET", f"/session/{sid}/url")
    if (urlsplit(url).hostname or "").removeprefix("www.") != "youtube.com":
        return "LOGIN RICHIESTO · completa l'accesso nel browser", False
    cookies = request("GET", f"/session/{sid}/cookie")
    if not netscape(cookies):
        return "LOGIN RICHIESTO · apri YouTube e accedi", False
    request("POST", f"/session/{sid}/refresh", {})
    content = netscape(request("GET", f"/session/{sid}/cookie"))
    if not content:
        return "LOGIN RICHIESTO · sessione non autenticata", False
    candidate = STATE / "candidate.cookies.txt"
    candidate.write_text(content, encoding="utf-8")
    os.chmod(candidate, 0o600)
    try:
        config = replace(CookieWatchConfig.from_env(), cookie_file=str(candidate))
        result = _run_ytdlp_cookie_probe_sync(config)
        if not result.ok:
            return f"COOKIE NON INSTALLATI · {result.rule_name} · file precedente conservato", True
        if not Config.EFFECTIVE_COOKIE_FILE:
            return "COOKIE NON INSTALLATI · COOKIE_FILE disabilitato", True
        destination = Path(Config.EFFECTIVE_COOKIE_FILE)
        if destination.exists():
            backup = destination.with_name(destination.name + ".last-good")
            shutil.copyfile(destination, backup)
            os.chmod(backup, 0o600)
        temporary = destination.with_name(destination.name + ".browser-incoming")
        try:
            shutil.copyfile(candidate, temporary)
            os.chmod(temporary, 0o600)
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
        return "COOKIE AGGIORNATI · test audio OK", True
    finally:
        candidate.unlink(missing_ok=True)


def main():
    import fcntl
    os.umask(0o077)
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (STATE / "lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        previous = None
        while True:
            try:
                message, authenticated = refresh_once()
            except Exception as exc:
                # Exception text from WebDriver may include session data.
                message, authenticated = f"BROWSER NON DISPONIBILE · {type(exc).__name__}", False
            if message != previous or authenticated:
                print(message, flush=True)
                previous = message
            time.sleep(900 if authenticated else 30)


if __name__ == "__main__":
    main()
