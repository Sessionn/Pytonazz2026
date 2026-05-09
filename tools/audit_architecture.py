#!/usr/bin/env python3
"""
tools/audit_architecture.py
===========================
Audit leggero per manutenzione "signal-driven":

1) segnala dipendenze cog->cog (accoppiamento indesiderato);
2) segnala duplicazioni concrete di logica (funzioni/metodi con stesso AST body).

Uso:
  python tools/audit_architecture.py
  python tools/audit_architecture.py --strict
  python tools/audit_architecture.py --min-lines 10
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).parent.parent
COGS_DIR = ROOT / "cogs"
CORE_DIR = ROOT / "core"


@dataclass
class CogCoupling:
    src: Path
    line: int
    target: str


@dataclass
class FuncSample:
    path: Path
    qualname: str
    line: int
    lines: int


def iter_python_files(folder: Path) -> list[Path]:
    return sorted(
        p for p in folder.rglob("*.py")
        if "__pycache__" not in p.parts and p.name != "__init__.py"
    )


def _sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _node_lines(node: ast.AST) -> int:
    start = getattr(node, "lineno", 0) or 0
    end = getattr(node, "end_lineno", start) or start
    return max(0, end - start + 1)


def _function_fingerprint(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    payload = ast.dump(
        ast.Module(body=node.body, type_ignores=[]),
        annotate_fields=False,
        include_attributes=False,
    )
    return _sha1(payload)


def find_cog_coupling() -> list[CogCoupling]:
    findings: list[CogCoupling] = []
    for path in iter_python_files(COGS_DIR):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module.startswith("cogs."):
                    findings.append(
                        CogCoupling(
                            src=path,
                            line=node.lineno,
                            target=node.module,
                        )
                    )
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("cogs."):
                        findings.append(
                            CogCoupling(
                                src=path,
                                line=node.lineno,
                                target=alias.name,
                            )
                        )
    return findings


def find_duplicate_logic(min_lines: int) -> dict[str, list[FuncSample]]:
    buckets: dict[str, list[FuncSample]] = {}

    targets = iter_python_files(COGS_DIR) + iter_python_files(CORE_DIR)
    for path in targets:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))

        class_stack: list[str] = []

        def visit(node: ast.AST) -> None:
            if isinstance(node, ast.ClassDef):
                class_stack.append(node.name)
                for child in node.body:
                    visit(child)
                class_stack.pop()
                return

            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                body_lines = _node_lines(node)
                if body_lines >= min_lines and node.body:
                    qual = ".".join([*class_stack, node.name]) if class_stack else node.name
                    fp = _function_fingerprint(node)
                    buckets.setdefault(fp, []).append(
                        FuncSample(
                            path=path,
                            qualname=qual,
                            line=node.lineno,
                            lines=body_lines,
                        )
                    )
                for child in node.body:
                    visit(child)

        for top in tree.body:
            visit(top)

    return {
        fp: samples
        for fp, samples in buckets.items()
        if len(samples) > 1
    }


def _rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audit rapido accoppiamento cog->cog e duplicazioni logiche"
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit code 1 se trova segnali oltre soglia",
    )
    parser.add_argument(
        "--min-lines",
        type=int,
        default=8,
        help="Linee minime della funzione/metodo per audit duplicazioni (default: 8)",
    )
    args = parser.parse_args()

    couplings = find_cog_coupling()
    dupes = find_duplicate_logic(min_lines=max(1, args.min_lines))

    print("\n============================================================")
    print("  🧭  Pitonazz — Architecture Audit (signal-driven)")
    print("============================================================")
    print(f"  Cog coupling findings : {len(couplings)}")
    print(f"  Duplicate groups      : {len(dupes)}")

    if couplings:
        print("\n[1] Dipendenze cog->cog (da valutare estrazione in core/)")
        for item in couplings:
            print(f"  - {_rel(item.src)}:{item.line} -> {item.target}")
    else:
        print("\n[1] Dipendenze cog->cog: nessuna.")

    if dupes:
        print("\n[2] Duplicazioni logica (stesso AST body)")
        for i, samples in enumerate(dupes.values(), start=1):
            longest = max(s.lines for s in samples)
            print(f"  Gruppo {i} (max {longest} linee):")
            for s in samples:
                print(f"    - {_rel(s.path)}:{s.line}  {s.qualname}  [{s.lines} righe]")
    else:
        print("\n[2] Duplicazioni logica: nessun gruppo oltre soglia.")

    total_findings = len(couplings) + len(dupes)
    print("\n------------------------------------------------------------")
    print(f"  Segnali totali: {total_findings}")
    print("------------------------------------------------------------\n")

    if args.strict and total_findings > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
