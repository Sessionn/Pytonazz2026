"""Maintain YouTube cookies from the dedicated, manually authenticated browser.

Run as a user service; noVNC must remain on localhost.
Firefox keeps YouTube open and rotates the session cookies, which invalidates
any older copy within an hour or two. So every few minutes it reads the
profile's YouTube cookies (a cheap SQLite snapshot) and, only when they have
changed, runs a real playback test and installs them if audio decodes. While
the bot is playing the test is skipped and the fresh cookies are installed
directly: the browser holds the live session, the installed copy is the stale
one. A failed test is retried hourly; everything runs at the lowest CPU
priority, so playback cannot stutter.
Persistent problems (login lost, browser down, test failing) go to ntfy.
Never logs cookie values or handles Google passwords.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

STATE = Path.home() / ".local/share/pytonazz-cookie-browser"
CONTAINER = "pytonazz-cookie-browser"
PROFILE = "/home/seluser/pytonazz-profile"
SYNC_SECONDS = int(os.getenv("PYTONAZZ_COOKIE_SYNC_SECONDS", "600"))
FAILED_RETRY_SECONDS = 3600
STARTING_RETRY_SECONDS = 30
LOGIN_RETRY_SECONDS = 300
ALERT_AFTER_SECONDS = 3600
ALERT_COOLDOWN_SECONDS = 21600


class BrowserStarting(Exception):
    """Firefox was not running and has just been launched."""


def browser_cookies():
    """Read only YouTube rows from the native Firefox profile, including HttpOnly."""
    running = subprocess.run(["docker", "exec", CONTAINER, "pgrep", "-f",
                              f"^firefox --no-remote --profile {PROFILE}"],
                             capture_output=True, timeout=10)
    if running.returncode:
        subprocess.run(["docker", "exec", "-d", "-u", "seluser", "-e", "DISPLAY=:99", CONTAINER,
                        "firefox", "--no-remote", "--profile", PROFILE,
                        "https://www.youtube.com/"], check=True, capture_output=True, timeout=15)
        raise BrowserStarting()
    code = f"""
import json,sqlite3,shutil,tempfile
from pathlib import Path
p=Path('{PROFILE}/cookies.sqlite')
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
        expiry = int(cookie.get("expiry", 0))
        if expiry > 10**11:  # recent Firefox stores milliseconds; Netscape wants seconds
            expiry //= 1000
        values = [domain, "TRUE" if domain.startswith(".") else "FALSE", cookie.get("path", "/"),
                  "TRUE" if cookie.get("secure") else "FALSE", str(expiry),
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


@dataclass(frozen=True)
class Outcome:
    message: str
    kind: str  # "ok", "login", "probe", "browser", "starting"
    digest: str | None = None  # of the browser export that is now installed
    installed: bool = False

    @property
    def healthy(self) -> bool:
        return self.kind == "ok"


def refresh_once(installed_digest: str | None = None, verify: bool = True) -> Outcome:
    """Install the browser's cookies if they differ from the ones installed last.

    ``verify=False`` (bot playing) installs without the playback test.
    """
    from config import Config
    from monitoring.cookie_watchdog import CookieWatchConfig, run_audio_probe_isolated

    try:
        content = netscape(browser_cookies())
    except BrowserStarting:
        return Outcome("BROWSER AVVIATO · nuovo tentativo a breve", "starting")
    if not content:
        return Outcome("LOGIN RICHIESTO · apri il browser dedicato e accedi a YouTube", "login")
    if not Config.EFFECTIVE_COOKIE_FILE:
        return Outcome("COOKIE NON INSTALLATI · COOKIE_FILE disabilitato", "probe")
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    destination = Path(Config.EFFECTIVE_COOKIE_FILE)
    if digest == installed_digest:
        # The bot's yt-dlp saves its cookie jar back into the file, and after a
        # bot check it saves a crippled one: put the verified export back.
        if _read(destination) == content:
            return Outcome("COOKIE INVARIATI", "ok", digest)
        _install(content, destination, backup=False)
        return Outcome("COOKIE RIPRISTINATI · file riscritto da yt-dlp", "ok", digest, True)
    candidate = STATE / "candidate.cookies.txt"
    candidate.write_text(content, encoding="utf-8")
    os.chmod(candidate, 0o600)
    try:
        if verify:
            result = run_audio_probe_isolated(str(candidate), CookieWatchConfig.from_env().test_url)
            if not result.ok:
                return Outcome(f"COOKIE NON INSTALLATI · {result.rule_name} · {result.detail[:160]}", "probe")
        _install(content, destination, backup=verify)
        if verify:
            return Outcome("COOKIE AGGIORNATI · test audio OK", "ok", digest, True)
        return Outcome("COOKIE AGGIORNATI · bot in riproduzione, test rimandato", "ok", digest, True)
    finally:
        candidate.unlink(missing_ok=True)


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _install(content: str, destination: Path, *, backup: bool) -> None:
    if backup and destination.exists():
        last_good = destination.with_name(destination.name + ".last-good")
        shutil.copyfile(destination, last_good)
        os.chmod(last_good, 0o600)
    temporary = destination.with_name(destination.name + ".browser-incoming")
    try:
        temporary.write_text(content, encoding="utf-8")
        os.chmod(temporary, 0o600)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


class Alerter:
    """Alert once when a problem persists, again after the cooldown, and on recovery."""

    def __init__(self, send, *, alert_after=ALERT_AFTER_SECONDS, cooldown=ALERT_COOLDOWN_SECONDS):
        self.send = send
        self.alert_after = alert_after
        self.cooldown = cooldown
        self.failing_since = None
        self.last_alert_at = None

    def observe(self, outcome: Outcome, now: float) -> None:
        if outcome.healthy:
            if self.last_alert_at is not None:
                self._send("Cookie YouTube di nuovo OK", outcome.message, "default", "white_check_mark")
            self.failing_since = self.last_alert_at = None
            return
        if outcome.kind == "starting":
            return
        if self.failing_since is None:
            self.failing_since = now
        # A lost login cannot heal by itself: tell the owner straight away.
        due = outcome.kind == "login" or now - self.failing_since >= self.alert_after
        if due and (self.last_alert_at is None or now - self.last_alert_at >= self.cooldown):
            title = "Pytonazz: serve il login YouTube" if outcome.kind == "login" else "Pytonazz: rinnovo cookie bloccato"
            self._send(title, outcome.message, "high", "warning")
            self.last_alert_at = now

    def _send(self, title, message, priority, tags):
        try:
            self.send(title=title, message=message, priority=priority, tags=tags)
        except Exception as exc:
            print(f"NOTIFICA NON INVIATA · {type(exc).__name__}", flush=True)


def _ntfy_sender():
    from monitoring.cookie_watchdog import _load_monitoring_env
    from monitoring.notifier import NtfyConfig, NtfyNotifier
    _load_monitoring_env()
    try:
        return NtfyNotifier(NtfyConfig.from_env()).send
    except ValueError:
        print("NOTIFICHE DISATTIVATE · ntfy non configurato", flush=True)
        return lambda **_: None


def next_delay(outcome: Outcome) -> float:
    if outcome.healthy:
        return SYNC_SECONDS
    if outcome.kind == "starting":
        return STARTING_RETRY_SECONDS
    if outcome.kind == "login":
        # Only a cheap cookie read: pick up a fresh manual login quickly.
        return LOGIN_RETRY_SECONDS
    return FAILED_RETRY_SECONDS


def bot_is_playing(proc: Path = Path("/proc")) -> bool:
    """Discord playback runs one FFmpeg per active voice stream.

    Zombie FFmpeg processes (exited, not yet reaped by the bot) do not count:
    pgrep matched them and the playback test stayed postponed for hours."""
    uid = os.getuid()
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            if entry.stat().st_uid != uid:
                continue
            stat = (entry / "stat").read_text()
        except OSError:
            continue  # the process exited meanwhile
        # "pid (comm) state ...": comm may contain spaces and ')'.
        comm = stat[stat.find("(") + 1:stat.rfind(")")]
        state = stat[stat.rfind(")") + 2:][:1]
        if comm == "ffmpeg" and state not in ("Z", "X"):
            return True
    return False


def main():
    import fcntl
    import config  # noqa: F401  loads .env for ntfy settings
    os.nice(19)  # inherited by the probe, yt-dlp and FFmpeg children
    os.umask(0o077)
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (STATE / "lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        alerter = Alerter(_ntfy_sender())
        previous = None
        installed = None
        while True:
            try:
                outcome = refresh_once(installed, verify=not bot_is_playing())
            except Exception as exc:
                # Exception text may include session data.
                outcome = Outcome(f"BROWSER NON DISPONIBILE · {type(exc).__name__}", "browser")
            if outcome.digest:
                installed = outcome.digest
            if outcome.message != previous or outcome.installed:
                print(outcome.message, flush=True)
                previous = outcome.message
            alerter.observe(outcome, time.time())
            time.sleep(next_delay(outcome))


if __name__ == "__main__":
    main()
