"""Maintain YouTube cookies from the dedicated, manually authenticated browser.

Run as a user service; noVNC must remain on localhost.
Never logs cookie values or handles Google passwords.
"""
from __future__ import annotations

import json
import os
import shutil
import time
import subprocess
from dataclasses import replace
from pathlib import Path

STATE = Path.home() / ".local/share/pytonazz-cookie-browser"
CONTAINER = "pytonazz-cookie-browser"


def browser_cookies():
    """Read only YouTube rows from a native Firefox profile, including HttpOnly."""
    running = subprocess.run(["docker", "exec", CONTAINER, "pgrep", "-f",
                              "^firefox --no-remote --profile /home/seluser/pytonazz-profile"],
                             capture_output=True, timeout=10)
    if running.returncode:
        subprocess.run(["docker", "exec", "-d", "-u", "seluser", "-e", "DISPLAY=:99", CONTAINER,
                        "firefox", "--no-remote", "--profile", "/home/seluser/pytonazz-profile",
                        "https://www.youtube.com/"], check=True, capture_output=True, timeout=15)
        return []
    code = """
import json,sqlite3,shutil,tempfile
from pathlib import Path
p=Path('/home/seluser/pytonazz-profile/cookies.sqlite')
result=[]
if p.exists():
    # Firefox holds an exclusive lock. Read a private snapshot, including WAL,
    # without changing the live database or asking the user to close Firefox.
    with tempfile.TemporaryDirectory(prefix='pytonazz-cookie-') as folder:
        snapshot=Path(folder)/'cookies.sqlite'
        shutil.copyfile(p,snapshot)
        wal=p.with_name(p.name+'-wal')
        if wal.exists():
            shutil.copyfile(wal,snapshot.with_name(snapshot.name+'-wal'))
        with sqlite3.connect(snapshot.as_uri()+'?mode=ro',uri=True,timeout=5) as db:
            for host,path,secure,expiry,name,value,http_only in db.execute(
                "SELECT host,path,isSecure,expiry,name,value,isHttpOnly FROM moz_cookies WHERE host='youtube.com' OR host LIKE '%.youtube.com'"):
                result.append(dict(domain=host,path=path,secure=bool(secure),expiry=expiry,name=name,value=value,httpOnly=bool(http_only)))
print(json.dumps(result))
"""
    result = subprocess.run(["docker", "exec", "-u", "seluser", CONTAINER, "python3", "-c", code],
                            check=True, capture_output=True, text=True, timeout=15)
    return json.loads(result.stdout)


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

    content = netscape(browser_cookies())
    if not content:
        return "LOGIN RICHIESTO · apri YouTube e accedi", False
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
                # Exception text may include session data.
                message, authenticated = f"BROWSER NON DISPONIBILE · {type(exc).__name__}", False
            if message != previous or authenticated:
                print(message, flush=True)
                previous = message
            time.sleep(900 if authenticated else 30)


if __name__ == "__main__":
    main()
