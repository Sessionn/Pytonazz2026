#!/usr/bin/env python3
"""
tools/check_logs.py
===================
Audit e autofix automatico dei log in tutto il progetto Pitonazz.

Regole:
  1. Ogni file che usa `log.*()` DEVE importare `tag` da core.log_colors
  2. Ogni file che usa `log.*()` DEVE avere un logger  `log = logging.getLogger(...)`
  3. Ogni chiamata log.info/warning/error/debug DEVE passare tag() come primo argomento
     OPPURE usare un helper riconosciuto (b, hi, ms, title, guild, user, ch)
  4. Il formato `log.xxx("testo %s", var)` è VIETATO — usare f-string con tag()
  5. Il logger name DEVE seguire il pattern  "pitonazz.<modulo>"

Uso:
  python tools/check_logs.py            # solo audit (stampa violazioni)
  python tools/check_logs.py --fix      # audit + suggerisce fix (non modifica)
  python tools/check_logs.py --strict   # esce con codice 1 se ci sono violazioni
                                        # (utile come pre-commit hook)
"""

import argparse
import ast
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# ──────────────────────────────────────────────────────────────────────
ROOT    = Path(__file__).parent.parent
SCAN    = [ROOT / "cogs", ROOT / "core", ROOT / "main.py"]
EXCLUDE = {"log_colors.py", "check_logs.py"}  # skip helpers stessi

# Tag validi definiti in log_colors.py
VALID_TAGS = {
    "SYNC", "BOOT", "READY", "WATCH", "RELOAD", "PLAYER", "STREAM",
    "FILTER", "QUEUE", "RESOLVE", "SPOTIFY", "WARN", "ERR", "AI",
    "CMD", "JOIN", "TTS", "DEV", "STATUS", "VOICE", "DISC", "MOD",
    "BDAY", "WEL", "BACKUP", "RESTORE", "DEV_AUDIO", "FALLBACK",
    "GATEWAY", "PROXY",
}

# Helper di formattazione importabili da log_colors
FORMAT_HELPERS = {"tag", "b", "hi", "ms", "title", "guild", "user", "ch"}

# Livelli di log che devono usare tag()
LOG_LEVELS = {"debug", "info", "warning", "error", "critical"}

ANSI_R     = "\033[0m"
ANSI_RED   = "\033[91m"
ANSI_YEL   = "\033[93m"
ANSI_GRN   = "\033[92m"
ANSI_CYN   = "\033[96m"
ANSI_BOLD  = "\033[1m"
ANSI_GRY   = "\033[90m"


def red(s):  return f"{ANSI_RED}{s}{ANSI_R}"
def yel(s):  return f"{ANSI_YEL}{s}{ANSI_R}"
def grn(s):  return f"{ANSI_GRN}{s}{ANSI_R}"
def cyn(s):  return f"{ANSI_CYN}{s}{ANSI_R}"
def bold(s): return f"{ANSI_BOLD}{s}{ANSI_R}"
def gry(s):  return f"{ANSI_GRY}{s}{ANSI_R}"


# ──────────────────────────────────────────────────────────────────────
@dataclass
class Violation:
    file:    Path
    line:    int
    code:    str   # V1..V5
    message: str
    snippet: str
    fix_hint: str = ""


@dataclass
class FileResult:
    path:       Path
    violations: list[Violation] = field(default_factory=list)
    ok:         bool = True


# ──────────────────────────────────────────────────────────────────────
RE_LOG_CALL   = re.compile(r"\blog\.(debug|info|warning|error|critical)\s*\(")
RE_PERCENT_FMT= re.compile(r'log\.\w+\s*\(\s*["\'].*?%[sdrf]')
RE_LOGGER_DEF = re.compile(r'log\s*=\s*logging\.getLogger\s*\(\s*["\']([^\'"]+)["\']')
RE_LOGGER_NAME= re.compile(r'^pitonazz\.')
RE_TAG_CALL   = re.compile(r'tag\s*\(')
RE_IMPORT_TAG  = re.compile(r'from\s+core\.log_colors\s+import')


def collect_files() -> list[Path]:
    files = []
    for target in SCAN:
        if target.is_file():
            files.append(target)
        elif target.is_dir():
            files.extend(target.rglob("*.py"))
    return [
        f for f in files
        if f.name not in EXCLUDE and "__pycache__" not in f.parts
    ]


def audit_file(path: Path) -> FileResult:
    result = FileResult(path=path)
    try:
        source = path.read_text(encoding="utf-8")
    except Exception as e:
        result.violations.append(Violation(
            file=path, line=0, code="V0",
            message=f"Impossibile leggere il file: {e}",
            snippet="",
        ))
        result.ok = False
        return result

    lines = source.splitlines()

    # Controlla se il file usa log.*() — se no, skip
    has_log_calls = bool(RE_LOG_CALL.search(source))
    if not has_log_calls:
        return result  # file pulito

    # V1: importa tag da core.log_colors?
    has_import = bool(RE_IMPORT_TAG.search(source))
    if not has_import:
        result.ok = False
        result.violations.append(Violation(
            file=path, line=1, code="V1",
            message="Usa log.*() ma NON importa da core.log_colors",
            snippet="",
            fix_hint="Aggiungi: from core.log_colors import tag, b, user  (ecc.)",
        ))

    # V2: ha logger definito correttamente?
    logger_match = RE_LOGGER_DEF.search(source)
    if not logger_match:
        result.ok = False
        result.violations.append(Violation(
            file=path, line=1, code="V2",
            message="Manca  log = logging.getLogger(\"pitonazz.xxx\")",
            snippet="",
            fix_hint=f'Aggiungi: log = logging.getLogger("pitonazz.{path.stem}")',
        ))
    else:
        logger_name = logger_match.group(1)
        if not RE_LOGGER_NAME.match(logger_name):
            result.ok = False
            lno = next(
                (i+1 for i, l in enumerate(lines) if "logging.getLogger" in l), 0
            )
            result.violations.append(Violation(
                file=path, line=lno, code="V2b",
                message=f"Logger name '{logger_name}' non segue il pattern 'pitonazz.<modulo>'",
                snippet=lines[lno-1].strip() if lno else "",
                fix_hint=f'Usa: log = logging.getLogger("pitonazz.{path.stem}")',
            ))

    # V3 + V4: analisi riga per riga
    for i, line in enumerate(lines, start=1):
        stripped = line.strip()

        # V4: formato % (sempre sbagliato)
        if RE_PERCENT_FMT.search(line):
            result.ok = False
            result.violations.append(Violation(
                file=path, line=i, code="V4",
                message="Usa formato %s invece di f-string con tag()",
                snippet=stripped,
                fix_hint='Sostituisci con: log.xxx(tag("LABEL", f"msg {b(var)}"))',
            ))
            continue

        # V3: log.*() senza tag() come primo argomento
        if RE_LOG_CALL.search(line):
            if not RE_TAG_CALL.search(line):
                # Controlla se usa almeno un helper di format
                uses_helper = any(f"{h}(" in line for h in FORMAT_HELPERS - {"tag"})
                if not uses_helper:
                    result.ok = False
                    result.violations.append(Violation(
                        file=path, line=i, code="V3",
                        message="log.*() senza tag() — messaggio grezzo non formattato",
                        snippet=stripped,
                        fix_hint='Avvolgi con tag(): log.info(tag("LABEL", f"..."))',
                    ))

    return result


# ──────────────────────────────────────────────────────────────────────
def print_results(results: list[FileResult], show_fix: bool) -> int:
    total_v = 0
    ok_files = 0

    print()
    print(bold("=" * 60))
    print(bold("  🔍  Pitonazz — Log Audit"))
    print(bold("=" * 60))

    for r in results:
        rel = r.path.relative_to(ROOT)
        if r.ok:
            ok_files += 1
            print(f"  {grn('✅')} {gry(str(rel))}")
            continue

        print(f"  {red('❌')} {bold(str(rel))}  —  {red(str(len(r.violations)))} violazioni")
        for v in r.violations:
            total_v += 1
            code_str = yel(f"[{v.code}]")
            loc      = cyn(f"riga {v.line}")
            print(f"      {code_str} {loc}  {v.message}")
            if v.snippet:
                print(f"             {gry('>')} {v.snippet}")
            if show_fix and v.fix_hint:
                print(f"             {grn('→')} {v.fix_hint}")

    print()
    print(bold("-" * 60))
    files_checked = len(results)
    print(f"  File controllati : {bold(str(files_checked))}")
    print(f"  File OK          : {grn(str(ok_files))}")
    print(f"  File con problemi: {red(str(files_checked - ok_files))}")
    print(f"  Violazioni totali: {(red if total_v else grn)(str(total_v))}")
    print(bold("-" * 60))
    print()

    # Stampa legenda codici
    print(gry("Codici: V1=import mancante  V2=logger mancante/errato"))
    print(gry("        V3=niente tag()      V4=formato %s vietato"))
    print()

    return total_v


def main():
    parser = argparse.ArgumentParser(
        description="Audit log Pitonazz — verifica conformità a log_colors.py"
    )
    parser.add_argument("--fix",    action="store_true", help="Mostra hint di fix")
    parser.add_argument("--strict", action="store_true", help="Esci con codice 1 se ci sono violazioni")
    parser.add_argument("--only",   type=str, default="",  help="Controlla solo file con questo nome")
    args = parser.parse_args()

    files = collect_files()
    if args.only:
        files = [f for f in files if args.only in f.name]

    results = [audit_file(f) for f in sorted(files)]
    # Mostra prima i file con problemi
    results.sort(key=lambda r: (r.ok, str(r.path)))

    total_violations = print_results(results, show_fix=args.fix or args.strict)

    if args.strict and total_violations > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
