#!/usr/bin/env python3
"""Check the host prerequisites for one tool tier (stdlib only, read-only).

    python -I -B tools/check_prereqs.py [--tier basic|components|inventory]

basic       Python >= 3.12 (CPython), git, and the seed revision in this clone's
            history (needed by `verify_seed.py --baseline seed`). Task is an
            optional convenience and is only reported.
components  The resolver's own prerequisite check (composition/resolve.py):
            CPython 3.12 with pip >= 23.1, Node.js >= 24 with npm >= 11.
            Registry network access is required but not probed here. The
            resolver runs under the Python tools interpreter, whose Dulwich
            reads the source tags; this check never imports Dulwich.
inventory   The optional SBOM/licence scan (composition/inventory/scan.py)
            downloads its pinned Syft and Grant archives itself; only Windows
            x86_64 archives are pinned, so this tier checks the host platform.

Exit status: 0 every check of the tier passed, 1 a check failed.
"""
from pathlib import Path
import argparse
import importlib.util
import os
import platform
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
PINNED_TASK_VERSION = '3.54.0'  # recorded with its checksums in docs/development.md


def load(name, path):
    sys.dont_write_bytecode = True  # leave no __pycache__ in the checkout
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def report(ok, name, detail):
    print(f'[{"PASS" if ok else "FAIL"}] {name}: {detail}')
    return ok


def output(cmd):
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return proc.stdout.strip() if proc.returncode == 0 else None


def basic():
    ok = True
    impl, version = platform.python_implementation(), platform.python_version()
    ok &= report(impl == 'CPython' and sys.version_info[:2] >= (3, 12), 'python',
                 f'{impl} {version} at {sys.executable} (CPython >= 3.12 required)')
    git = shutil.which('git')
    git_version = output([git, '--version']) if git else None
    ok &= report(bool(git_version), 'git', git_version or 'not found on PATH')
    if git_version:
        seed = load('verify_seed', ROOT / 'tools' / 'verify_seed.py').SEED_REVISION
        present = output([git, '-C', str(ROOT), 'cat-file', '-t', seed]) == 'commit'
        ok &= report(present, 'seed revision', f'{seed} '
                     + ('present' if present else 'missing: use a full (non-shallow) git clone'))
    task_version = os.environ.get('AIEH_TASK_VERSION')
    if not task_version:
        task = shutil.which('task')
        task_version = output([task, '--version']) if task else None
    print(f'[INFO] task: {task_version or "not found"} (optional; pinned {PINNED_TASK_VERSION})')
    return ok


def components():
    resolve = load('resolve', ROOT / 'composition' / 'resolve.py')
    ok, info, _npm = resolve.prerequisites(resolve.Checks())
    print(f'[INFO] host: {info}')
    print('[INFO] network: HTTPS to the registries in composition/lock/README.md is required, not probed')
    return ok


def inventory():
    host = f'{sys.platform}/{platform.machine()}'
    return report(sys.platform == 'win32' and platform.machine().lower() in ('amd64', 'x86_64'),
                  'inventory host', f'{host} (pinned Syft/Grant archives exist for Windows x86_64 only)')


def main(argv=None):
    parser = argparse.ArgumentParser(description='Check host prerequisites for one tool tier.')
    parser.add_argument('--tier', choices=('basic', 'components', 'inventory'), default='basic')
    args = parser.parse_args(argv)
    ok = {'basic': basic, 'components': components, 'inventory': inventory}[args.tier]()
    print(f'{args.tier} prerequisites: {"PASS" if ok else "FAIL"}')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
