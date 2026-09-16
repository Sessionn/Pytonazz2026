"""Run script-style tests in a temporary copy, without local runtime files.

Usage: python tools/run_repository_checks.py [--pattern test_dashboard_*.py]
Dependencies must be installed in the selected interpreter.
"""
import argparse
import ast
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pattern', default='test_*.py')
    parser.add_argument('--extra-site-packages', default='')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    files = subprocess.check_output(['git', 'ls-files', '-z'], cwd=root).decode().split('\0')
    output = root / 'data/tmp/repository-checks.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    results = []
    syntax_count = 0
    with tempfile.TemporaryDirectory(prefix='pytonazz-checks-') as folder:
        isolated = Path(folder)
        for name in files:
            source = root / name
            if not name or not source.is_file() or name.startswith('.env'):
                continue
            target = isolated / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            if source.suffix == '.py':
                ast.parse(source.read_text(encoding='utf-8-sig'), filename=name)
                syntax_count += 1
        env = dict(os.environ, PYTHON_DOTENV_DISABLED='1', PYTHONIOENCODING='utf-8')
        tests = sorted((isolated / 'tests').glob(args.pattern))
        if not tests:
            raise SystemExit('No tests matched')
        for test in tests:
            code = ('import sys,runpy; extra=sys.argv.pop(1); '
                    'sys.path.extend([extra] if extra else []); sys.argv=sys.argv[1:]; '
                    'runpy.run_path(sys.argv[0], run_name="__main__")')
            try:
                proc = subprocess.run(
                    [sys.executable, '-c', code, args.extra_site_packages, str(test)],
                    cwd=isolated, env=env, capture_output=True, text=True,
                    encoding='utf-8', errors='replace', timeout=45,
                )
                result = {'test': test.name, 'code': proc.returncode,
                          'output': (proc.stdout + proc.stderr)[-5000:]}
            except subprocess.TimeoutExpired:
                result = {'test': test.name, 'code': 'timeout', 'output': 'Exceeded 45 seconds'}
            results.append(result)
            print(f"{result['code']}: {test.name}", flush=True)
        passed = sum(result['code'] == 0 for result in results)
        output.write_text(json.dumps({'syntax_files': syntax_count, 'passed': passed,
                                     'total': len(results), 'tests': results}, indent=2), encoding='utf-8')
        print(f'Syntax OK: {syntax_count} files. PASS {passed}/{len(results)}. Results: {output}')
        return 0 if passed == len(results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
