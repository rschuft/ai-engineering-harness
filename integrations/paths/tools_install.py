"""task tools:install: the hash-locked Python tools venv (plan leaf F-07.1, decision 0009), and
task dev:install: the same mechanism for the developer test tools (plan leaf F-09.2).

A consumer of the managed data root, like any component: the verified wheels are an asset,
assets/python-wheels/python-tools/<version>/ with its aieh-asset/1 record, and the venv built
from them is an install, persistent/installs/python-tools/<version>/. pip's cache is
ephemeral/cache/pip. <version> is the interpreter tag and the lock digest, so versions sit side
by side. Wheels only, with required hashes, from composition/lock/python/tools-requirements.txt:
the tools set is PyYAML, Dulwich, urllib3 and keyring with its closure (each platform's part by its
sys_platform marker). `--set python-dev-tools` installs the dev set (pytest, pytest-xdist, and the
tools set) the same way, from
composition/lock/python/dev-requirements.txt, as python-dev-tools beside it.

It reads no config.yml: it installs the YAML loader that config.yml needs, so it follows
AIEH_DATA_ROOT or the OS default only. Network: PyPI, once per lock. It deletes nothing.

  python -I -B integrations/paths/tools_install.py [--set python-tools|python-dev-tools] [--python]

--python creates and installs nothing: it prints the set's venv interpreter for the current lock,
or exits 1 when that venv is not installed (the test targets find the dev tools this way).
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Callable

HERE = Path(os.path.realpath(__file__)).parent
# Windows: a console process started with this flag gets a console that no window shows (0 elsewhere);
# every process this module starts carries it (tools/tests/test_launch_census.py checks it).
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
TOOLS_LOCK = 'composition/lock/python/tools-requirements.txt'
DEV_LOCK = 'composition/lock/python/dev-requirements.txt'
# Each installable set: its name (the asset name and the install's tool directory), its lock and
# the task that installs it.
SETS = {'python-tools': (TOOLS_LOCK, 'task tools:install'),
        'python-dev-tools': (DEV_LOCK, 'task dev:install')}
PYPI = 'https://pypi.org/simple/'


def _load_paths():
    if (module := sys.modules.get('aieh_paths')) is None:
        spec = importlib.util.spec_from_file_location('aieh_paths', HERE / 'aieh_paths.py')
        module = sys.modules['aieh_paths'] = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


paths = _load_paths()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def _call(run: Callable, command: list, env: dict) -> None:
    if (result := run(command, env=env, creationflags=NO_WINDOW)).returncode != 0:
        raise subprocess.CalledProcessError(result.returncode, command)


def _lock_version(res, lock_name: str) -> tuple[Path, str, str]:
    """The lock's path, its digest and the version it gives: the interpreter tag and the digest's start."""
    lock = Path(str(res.repo_root)) / lock_name
    digest = hashlib.sha256(lock.read_bytes().replace(b'\r\n', b'\n')).hexdigest()  # checkout-EOL neutral
    return lock, digest, f'cp{sys.version_info[0]}{sys.version_info[1]}-{digest[:12]}'


def _interpreter(venv: Path) -> Path:
    return venv / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def installed_python(res, name: str = 'python-tools') -> Path | None:
    """The venv interpreter of the set `name` for the current lock, or None when it is not installed.
    Creates nothing."""
    _, _, version = _lock_version(res, SETS[name][0])
    python = _interpreter(Path(str(res.paths['installs'])) / name / version)
    return python if os.path.isfile(python) else None


def tools_install(res, run: Callable = subprocess.run, python: str = sys.executable,
                  name: str = 'python-tools') -> dict:
    """Download the locked wheels of the set `name` into their asset directory once (recording their
    digests), verify them against that record on every run, and install them into the venv from that
    directory only."""
    lock_name, task = SETS[name]
    lock, digest, version = _lock_version(res, lock_name)
    paths.init(res)
    wheels = paths.ensure('assets', res, 'python-wheels', name, version)
    env = dict(os.environ, PIP_CACHE_DIR=str(paths.ensure('cache', res, 'pip')), PIP_DISABLE_PIP_VERSION_CHECK='1')
    hashed = ['--require-hashes', '--only-binary=:all:', '-r', str(lock)]
    if not os.path.lexists(wheels / paths.ASSET_RECORD_NAME):
        _call(run, [python, '-m', 'pip', 'download', '--dest', str(wheels), *hashed], env)
        files = {f.name: sha256_file(f) for f in sorted(wheels.iterdir()) if f.suffix == '.whl'}
        paths.write_asset_record(wheels, paths.asset_record(
            'python-wheels', name, version, source=PYPI, pin=f'{lock_name} sha256:{digest}',
            sha256=files, consumers=[f'installs/{name}'],
            reacquire=f'{task} (pip download --require-hashes --only-binary=:all: -r {lock_name})'))
    for wheel, expected in paths.read_asset_record(wheels)['integrity'].get('sha256', {}).items():
        if not os.path.isfile(wheels / wheel) or sha256_file(wheels / wheel) != expected:
            raise paths.PathsError('ASSET_RECORD_INVALID', f'{wheels / wheel} is missing or differs from its record')
    venv = paths.ensure('installs', res, name) / version
    if not os.path.isfile(venv / 'pyvenv.cfg'):
        _call(run, [python, '-m', 'venv', str(venv)], env)
    venv_python = _interpreter(venv)
    _call(run, [str(venv_python), '-m', 'pip', 'install', '--no-index', '--find-links', str(wheels), *hashed], env)
    return {'python': str(venv_python), 'venv': str(venv), 'assets': str(wheels)}


def main(argv=None) -> int:
    argv = list(argv or [])
    show = argv.count('--python') == 1
    if show:
        argv = [arg for arg in argv if arg != '--python']
    name = 'python-tools'
    if argv[:1] == ['--set'] and len(argv) == 2 and argv[1] in SETS:
        name = argv[1]
    elif argv:
        sys.stderr.write(f'usage: tools_install.py [--set {"|".join(SETS)}] [--python]\n')
        return 2
    if show:
        try:
            python = installed_python(paths.resolve(config={}), name)
        except paths.PathsError as exc:
            sys.stderr.write(f'tools-install: {exc}\n')
            return 2
        if python is None:
            sys.stderr.write(f'tools-install: {name} is not installed for the current lock; run {SETS[name][1]}\n')
            return 1
        sys.stdout.write(f'{python}\n')
        return 0
    try:
        result = tools_install(paths.resolve(config={}), name=name)
    except paths.PathsError as exc:
        sys.stderr.write(f'tools-install: {exc}\n')
        return 2
    except subprocess.CalledProcessError as exc:
        sys.stderr.write(f'tools-install: {" ".join(map(str, exc.cmd[:4]))} ... exited {exc.returncode}\n')
        return 1
    sys.stdout.write(json.dumps(result, indent=2) + '\n')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
