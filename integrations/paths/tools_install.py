"""task tools:install: the hash-locked Python tools venv (plan leaf F-07.1, decision 0009).

A consumer of the managed data root, like any component: the verified wheels are an asset,
assets/python-wheels/python-tools/<version>/ with its aieh-asset/1 record, and the venv built
from them is an install, persistent/installs/python-tools/<version>/. pip's cache is
ephemeral/cache/pip. <version> is the interpreter tag and the lock digest, so versions sit side
by side. Wheels only, with required hashes, from composition/lock/python/tools-requirements.txt.

It reads no config.yml: it installs the YAML loader that config.yml needs, so it follows
AIEH_DATA_ROOT or the OS default only. Network: PyPI, once per lock. It deletes nothing.

  python -I -B integrations/paths/tools_install.py
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
TOOLS_LOCK = 'composition/lock/python/tools-requirements.txt'
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
    if (result := run(command, env=env)).returncode != 0:
        raise subprocess.CalledProcessError(result.returncode, command)


def tools_install(res, run: Callable = subprocess.run, python: str = sys.executable) -> dict:
    """Download the locked wheels into their asset directory once (recording their digests), verify
    them against that record on every run, and install them into the venv from that directory only."""
    lock = Path(str(res.repo_root)) / TOOLS_LOCK
    digest = hashlib.sha256(lock.read_bytes().replace(b'\r\n', b'\n')).hexdigest()  # checkout-EOL neutral
    version = f'cp{sys.version_info[0]}{sys.version_info[1]}-{digest[:12]}'
    paths.init(res)
    wheels = paths.ensure('assets', res, 'python-wheels', 'python-tools', version)
    env = dict(os.environ, PIP_CACHE_DIR=str(paths.ensure('cache', res, 'pip')), PIP_DISABLE_PIP_VERSION_CHECK='1')
    hashed = ['--require-hashes', '--only-binary=:all:', '-r', str(lock)]
    if not os.path.lexists(wheels / paths.ASSET_RECORD_NAME):
        _call(run, [python, '-m', 'pip', 'download', '--dest', str(wheels), *hashed], env)
        files = {f.name: sha256_file(f) for f in sorted(wheels.iterdir()) if f.suffix == '.whl'}
        paths.write_asset_record(wheels, paths.asset_record(
            'python-wheels', 'python-tools', version, source=PYPI, pin=f'{TOOLS_LOCK} sha256:{digest}',
            sha256=files, consumers=['installs/python-tools'],
            reacquire=f'task tools:install (pip download --require-hashes --only-binary=:all: -r {TOOLS_LOCK})'))
    for name, expected in paths.read_asset_record(wheels)['integrity'].get('sha256', {}).items():
        if not os.path.isfile(wheels / name) or sha256_file(wheels / name) != expected:
            raise paths.PathsError('ASSET_RECORD_INVALID', f'{wheels / name} is missing or differs from its record')
    venv = paths.ensure('installs', res, 'python-tools') / version
    if not os.path.isfile(venv / 'pyvenv.cfg'):
        _call(run, [python, '-m', 'venv', str(venv)], env)
    venv_python = venv / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    _call(run, [str(venv_python), '-m', 'pip', 'install', '--no-index', '--find-links', str(wheels), *hashed], env)
    return {'python': str(venv_python), 'venv': str(venv), 'assets': str(wheels)}


def main(argv=None) -> int:
    if argv:
        sys.stderr.write('usage: tools_install.py (no arguments)\n')
        return 2
    try:
        result = tools_install(paths.resolve(config={}))
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
