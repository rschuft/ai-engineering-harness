"""Host-loopback Gitea under the managed data root (plan leaf F-06.1; decisions 0007 and 0009).

Gitea's official Windows release binary, pinned by sha256 in composition/lock/components.lock.json,
is an asset (assets/release-binaries/gitea/<version>/ with its aieh-asset/1 record) and runs from
there: Gitea needs no install step. Its configuration and state live in the resolver's `gitea`
category (custom/conf/app.ini, data/, repositories/, run/), its logs in logs/gitea/ and its
temporary files in tmp/gitea/. Every path comes from integrations/paths; none is in the checkout.

Gitea listens on 127.0.0.1 only, runs as the current Windows user without elevation, and is the
child of a supervising "managed environment" process. The supervisor puts itself into a new
Windows Job Object with JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE before it starts Gitea, and it holds the
job's only handle: whenever the supervisor ends, cleanly or killed, the kernel closes that handle
and ends every process in the job, Gitea and its git children included. `down` asks Gitea to stop
through Gitea's own `manager shutdown`, then waits for both processes on their handles.

The binary is hashed against the pin through a handle that denies writing, renaming and deleting
it, and every Gitea process is started while that handle is held. Nothing unverified is executed.

Identities (Owner decision of 2026-11-07, decision 0007 confirmation 1): `identities` creates the
site administrator and the separate non-administrator Owner account with Gitea's own CLI
(`admin user create --random-password --must-change-password`); each temporary password goes from the
CLI's captured output into one credential-provider entry. `finalize-credentials` (Owner directive of
2026-11-07: the Owner never signs in to Gitea) then replaces each with a harness-held final password:
generated with `secrets`, stored in its provider entry first, set through Gitea's own forced change
(sign-in with the temporary password, then the change form, over loopback HTTP request bodies), after
which every access token of the account is revoked with the new credentials, the result is verified,
the temporary entry is deleted, and no password may appear in the managed root, the checkout or the
output. No password is ever printed, logged, put on a command line or in an environment.

Credentials are reached through CredentialProvider (get, set, delete, exists); its Windows
implementation is Credential Manager (CredWriteW, CredReadW, CredDeleteW).

  python -I -B integrations/gitea/gitea_host.py install [--from-file EXE] [--port N]
  python -I -B integrations/gitea/gitea_host.py up | down | status | verify
  python -I -B integrations/gitea/gitea_host.py identities | finalize-credentials

Exit 0 done, 1 failed, 2 refused (a stable code). Windows only.
"""
from __future__ import annotations

import argparse
import base64
import contextlib
import datetime
import hashlib
import http.client
import importlib.util
import json
import os
import re
import secrets
import socket
import struct
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable, Iterable

HERE = Path(os.path.realpath(__file__)).parent
REPO = HERE.parents[1]
LOCK = 'composition/lock/components.lock.json'
VERSION = '28.3.0'
ASSET_NAME = f'gitea-{VERSION}-windows-amd64.exe'
ASSET_KIND = 'release-binaries'
HOST_RECORD, HOST_FORMAT = 'aieh-gitea-host.json', 'aieh-gitea-host/1'
RUN_FORMAT = 'aieh-gitea-run/1'
LOOPBACK = '127.0.0.1'
DEFAULT_PORT = 13300
SITE_ADMIN, OWNER = 'aieh-site-admin', 'aieh-owner'
EMAIL_DOMAIN = 'localhost.invalid'
CRED_TARGETS = {SITE_ADMIN: 'AIEH Gitea site-admin (temporary)', OWNER: 'AIEH Gitea owner (temporary)'}
# The harness-held final credentials (Owner directive of 2026-11-07): read only by finalize-credentials and
# the fixture administration; never by agents, bots or tests.
FINAL_TARGETS = {SITE_ADMIN: 'AIEH Gitea site-admin', OWNER: 'AIEH Gitea owner'}
FINAL_PASSWORD_BYTES = 32  # secrets.token_urlsafe(32): 43 characters, 256 bits
# The role bots of S-01.2.2 (gitea_roles.py): restricted, non-administrator Gitea Bot accounts.
BOT_ACCOUNTS = {'planner': 'aieh-bot-planner', 'builder': 'aieh-bot-builder', 'reviewer': 'aieh-bot-reviewer',
                'verifier': 'aieh-bot-verifier'}
SECRET_NAMES = ('SECRET_KEY', 'INTERNAL_TOKEN', 'JWT_SECRET')
RANDOM_PASSWORD_LENGTH = 24
READY_CEILING_S, STOP_CEILING_S = 120.0, 60.0
GENERATED_PASSWORD = re.compile(rb"generated random password is '([^'\r\n]+)'")


def _load_paths():
    if (module := sys.modules.get('aieh_paths')) is None:
        spec = importlib.util.spec_from_file_location('aieh_paths', REPO / 'integrations' / 'paths' / 'aieh_paths.py')
        module = sys.modules['aieh_paths'] = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


paths = _load_paths()


class GiteaError(Exception):
    """A refusal (exit 2) or a failure (exit 1) with a stable code."""

    def __init__(self, code: str, detail: str, *, refusal: bool = True):
        self.code, self.detail, self.refusal = code, detail, refusal
        super().__init__(f'{code}: {detail}')


def now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


# ---------------------------------------------------------------- pin and layout


def pin(repo: Path = REPO) -> dict:
    """The lock's release_assets entry for the Windows binary: sha256, url and checksum sources."""
    lock = json.loads((repo / LOCK).read_text(encoding='utf-8'))
    rows = [a for a in lock.get('release_assets', []) if a.get('component') == 'gitea' and a.get('name') == ASSET_NAME]
    if len(rows) != 1 or not re.fullmatch('[0-9a-f]{64}', str(rows[0].get('sha256'))) or not rows[0].get('url'):
        raise GiteaError('PIN_MISSING', f'{LOCK} has no single release_assets entry for {ASSET_NAME} with sha256 and url')
    return rows[0]


class Layout(dict):
    """Every location Gitea uses, from one resolution. Attribute access for brevity."""
    __getattr__ = dict.__getitem__


def layout(res) -> Layout:
    """Pure: computes the locations from the resolver's categories and creates nothing."""
    assets = Path(str(res.paths['assets'])) / ASSET_KIND / 'gitea' / VERSION
    home = Path(str(res.paths['gitea']))
    lay = Layout(
        root=Path(str(res.root)), repo=Path(str(res.repo_root)),
        asset_dir=assets, binary=assets / ASSET_NAME,
        home=home, custom=home / 'custom', config=home / 'custom' / 'conf' / 'app.ini',
        data=home / 'data', db=home / 'data' / 'gitea.db', repositories=home / 'repositories',
        run=home / 'run', run_record=home / 'run' / 'supervisor.json', host_record=home / HOST_RECORD,
        logs=Path(str(res.paths['logs'])) / 'gitea', tmp=Path(str(res.paths['tmp'])) / 'gitea')
    for name, path in lay.items():
        if name != 'repo' and (path.is_relative_to(lay.repo) or lay.repo.is_relative_to(path)):
            raise GiteaError('PATH_INSIDE_CHECKOUT', f'{name} {path} is inside or contains the checkout')
    return lay


def ensure_dirs(res, lay: Layout) -> list[str]:
    """Create the category directories through the resolver (it never creates above the root) and
    return every directory that did not exist before, parents first."""
    targets = [(c, parts) for c, parts in (('assets', (ASSET_KIND, 'gitea', VERSION)), ('gitea', ('custom', 'conf')),
               ('gitea', ('data',)), ('gitea', ('repositories',)), ('gitea', ('run',)), ('logs', ('gitea',)),
               ('tmp', ('gitea',)))]
    candidates = []
    for category, parts in targets:
        leaf = Path(str(res.paths[category])).joinpath(*parts)
        candidates += [p for p in [leaf, *leaf.parents][::-1] if p.is_relative_to(lay.root) and p != lay.root]
    before = {p for p in candidates if p.is_dir()}
    for category, parts in targets:
        paths.ensure(category, res, *parts)
    return list(dict.fromkeys(str(p) for p in candidates if p not in before))


# ---------------------------------------------------------------- the verified binary


def sha256_stream(handle) -> str:
    digest = hashlib.sha256()
    for block in iter(lambda: handle.read(1 << 20), b''):
        digest.update(block)
    return digest.hexdigest()


@contextlib.contextmanager
def _locked_read(path: Path):
    """A read handle that, on Windows, shares read only: no writer, rename or delete while it is held."""
    if os.name != 'nt':
        with open(path, 'rb') as handle:
            yield handle
        return
    import ctypes
    import msvcrt
    from ctypes import wintypes
    k32 = ctypes.WinDLL('kernel32', use_last_error=True)
    k32.CreateFileW.restype = wintypes.HANDLE
    k32.CreateFileW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                                wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
    generic_read, file_share_read, open_existing = 0x80000000, 0x1, 3
    handle = k32.CreateFileW(str(path), generic_read, file_share_read, None, open_existing, 0, None)
    if handle in (None, wintypes.HANDLE(-1).value):
        raise GiteaError('BINARY_UNREADABLE', f'{path}: CreateFileW failed ({ctypes.get_last_error()})')
    with os.fdopen(msvcrt.open_osfhandle(handle, os.O_RDONLY), 'rb') as stream:
        yield stream


@contextlib.contextmanager
def verified_binary(lay: Layout, expected: str):
    """Yield the binary's path only after its sha256 equals the pin; the file stays locked against
    change until the block ends, so the process started inside the block runs the verified bytes."""
    if not lay.binary.is_file():
        raise GiteaError('BINARY_MISSING', f'{lay.binary} does not exist; run install')
    record = paths.read_asset_record(lay.asset_dir)
    if record['integrity'].get('sha256', {}).get(ASSET_NAME) != expected:
        raise GiteaError('BINARY_MISMATCH', 'the asset record does not carry the pinned sha256')
    with _locked_read(lay.binary) as stream:
        if (digest := sha256_stream(stream)) != expected:
            raise GiteaError('BINARY_MISMATCH', f'{lay.binary} has sha256 {digest}, the pin is {expected}')
        yield lay.binary


def acquire(res, lay: Layout, pinned: dict, *, from_file: Path | None = None,
            opener: Callable = urllib.request.urlopen) -> dict:
    """Download (or copy from a local file) into tmp/gitea/, verify against the pin, then move into
    the asset directory and write the aieh-asset/1 record. Reuses a present, recorded asset."""
    if os.path.lexists(lay.asset_dir / paths.ASSET_RECORD_NAME):
        with verified_binary(lay, pinned['sha256']):
            pass
        return {'asset': str(lay.binary), 'acquired': False}
    if os.path.lexists(lay.binary):
        raise GiteaError('ASSET_UNRECORDED', f'{lay.binary} exists without its record; move it aside and rerun')
    partial = lay.tmp / f'{ASSET_NAME}.{secrets.token_hex(4)}.partial'
    digest = hashlib.sha256()
    with open(partial, 'xb') as out:
        if from_file is not None:
            source = open(from_file, 'rb')
        else:
            source = opener(urllib.request.Request(pinned['url'], headers={'User-Agent': 'aieh-gitea-host'}),
                            timeout=60)
        with source:
            for block in iter(lambda: source.read(1 << 20), b''):
                digest.update(block)
                out.write(block)
    if digest.hexdigest() != pinned['sha256']:
        raise GiteaError('DOWNLOAD_MISMATCH', f'{partial} has sha256 {digest.hexdigest()}, the pin is '
                                              f'{pinned["sha256"]}; it was not moved into the assets', refusal=False)
    os.replace(partial, lay.binary)
    paths.write_asset_record(lay.asset_dir, paths.asset_record(
        ASSET_KIND, 'gitea', VERSION, source=pinned['url'], sha256={ASSET_NAME: pinned['sha256']},
        pin=f'{LOCK} release_assets {ASSET_NAME} sha256:{pinned["sha256"]}', consumers=['gitea'],
        reacquire=f'task gitea:install (downloads {pinned["url"]} and verifies it against the pin)'))
    with verified_binary(lay, pinned['sha256']):
        pass
    return {'asset': str(lay.binary), 'acquired': True, 'from': 'file' if from_file else pinned['url']}


# ---------------------------------------------------------------- configuration


def child_env(lay: Layout, environ=None) -> dict:
    """The inherited environment without GITEA_* settings, plus Gitea's work and custom paths and a
    temporary directory below tmp/gitea. HOME, USERPROFILE, APPDATA and LOCALAPPDATA stay untouched."""
    env = {k: v for k, v in (os.environ if environ is None else environ).items() if not k.upper().startswith('GITEA')}
    env.update(GITEA_WORK_DIR=str(lay.home), GITEA_CUSTOM=str(lay.custom), TMP=str(lay.tmp), TEMP=str(lay.tmp))
    return env


def gitea_argv(binary: Path, lay: Layout, *args: str) -> list[str]:
    return [str(binary), '--work-path', str(lay.home), '--custom-path', str(lay.custom),
            '--config', str(lay.config), *args]


def render_app_ini(lay: Layout, port: int, secret_values: dict) -> str:
    """app.ini: loopback HTTP only, no SSH, sign-in required, no registration, offline, no external
    services, SQLite in data/, logs in logs/gitea/, Actions and LFS off, installation locked. Gravatar
    and federated avatars are not set here: Gitea 28 moved them to its database settings and ignores
    the [picture] keys (it logs a deprecation error); OFFLINE_MODE disables both by default."""
    if set(secret_values) != set(SECRET_NAMES) or not all(isinstance(v, str) and v for v in secret_values.values()):
        raise GiteaError('SECRETS_INCOMPLETE', f'need exactly {SECRET_NAMES}')
    p = {k: str(v).replace('\\', '/') for k, v in lay.items()}
    sections = [
        ('', [('APP_NAME', 'AIEH Gitea'), ('RUN_MODE', 'prod'), ('WORK_PATH', p['home'])]),
        ('server', [('PROTOCOL', 'http'), ('HTTP_ADDR', LOOPBACK), ('HTTP_PORT', str(port)),
                    ('DOMAIN', LOOPBACK), ('ROOT_URL', f'http://{LOOPBACK}:{port}/'),
                    ('LOCAL_ROOT_URL', f'http://{LOOPBACK}:{port}/'), ('APP_DATA_PATH', p['data']),
                    ('DISABLE_SSH', 'true'), ('START_SSH_SERVER', 'false'), ('OFFLINE_MODE', 'true'),
                    ('LFS_START_SERVER', 'false'), ('ENABLE_PPROF', 'false')]),
        ('database', [('DB_TYPE', 'sqlite3'), ('PATH', p['db'])]),
        ('repository', [('ROOT', p['repositories'])]),
        ('security', [('INSTALL_LOCK', 'true'), ('SECRET_KEY', secret_values['SECRET_KEY']),
                      ('INTERNAL_TOKEN', secret_values['INTERNAL_TOKEN'])]),
        ('oauth2', [('ENABLED', 'false'), ('JWT_SECRET', secret_values['JWT_SECRET'])]),
        ('service', [('DISABLE_REGISTRATION', 'true'), ('SHOW_REGISTRATION_BUTTON', 'false'),
                     ('ALLOW_ONLY_EXTERNAL_REGISTRATION', 'false'), ('REQUIRE_SIGNIN_VIEW', 'true'),
                     ('ENABLE_NOTIFY_MAIL', 'false'), ('REGISTER_EMAIL_CONFIRM', 'false'),
                     ('ENABLE_CAPTCHA', 'false')]),
        ('openid', [('ENABLE_OPENID_SIGNIN', 'false'), ('ENABLE_OPENID_SIGNUP', 'false')]),
        ('mailer', [('ENABLED', 'false')]),
        ('cron.update_checker', [('ENABLED', 'false')]),
        ('federation', [('ENABLED', 'false')]),
        ('actions', [('ENABLED', 'false')]),
        ('lfs', [('PATH', p['data'] + '/lfs')]),
        ('log', [('MODE', 'file'), ('LEVEL', 'Info'), ('ROOT_PATH', p['logs'])]),
    ]
    lines = ['; Generated by integrations/gitea/gitea_host.py install (plan leaf F-06.1). Holds secrets:',
             '; class E, never copied into the checkout. Regenerate only with a new data directory.']
    for name, pairs in sections:
        lines += ([f'', f'[{name}]'] if name else ['']) + [f'{k} = {v}' for k, v in pairs]
    return '\n'.join(lines) + '\n'


def read_ini(path: Path) -> dict:
    """A minimal reader of the app.ini this tool writes: {section: {key: value}}, '' for the top."""
    result, section = {'': {}}, ''
    for raw in path.read_text(encoding='utf-8').splitlines():
        line = raw.strip()
        if not line or line[0] in ';#':
            continue
        if line.startswith('[') and line.endswith(']'):
            section = line[1:-1].strip()
            result.setdefault(section, {})
        elif '=' in line:
            key, value = line.split('=', 1)
            result[section][key.strip()] = value.strip()
    return result


def run_quiet(argv: list[str], env: dict, cwd: Path, run: Callable = subprocess.run, timeout: float = 120.0):
    """Run a Gitea CLI command with its output captured in memory only; the caller decides what to show."""
    return run(argv, env=env, cwd=str(cwd), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
               stderr=subprocess.PIPE, timeout=timeout,
               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))


def generate_secrets(binary: Path, lay: Layout, run: Callable = subprocess.run) -> dict:
    """Each secret from Gitea's own `generate secret NAME`, held in memory and returned."""
    values = {}
    for name in SECRET_NAMES:
        result = run_quiet([str(binary), 'generate', 'secret', name], child_env(lay), lay.home, run)
        value = result.stdout.decode('ascii', 'replace').strip()
        if result.returncode != 0 or not value or any(c.isspace() for c in value):
            raise GiteaError('SECRET_GENERATION_FAILED', f'gitea generate secret {name} exited {result.returncode}',
                             refusal=False)
        values[name] = value
    return values


def configure(res, lay: Layout, pinned: dict, port: int, run: Callable = subprocess.run) -> dict:
    """Write app.ini and the host record once (exclusive create); an existing configuration is kept."""
    if os.path.lexists(lay.config) or os.path.lexists(lay.host_record):
        record = read_host_record(lay)
        return {'config': str(lay.config), 'written': False, 'port': record['port']}
    if not 1024 <= port <= 49151:
        raise GiteaError('PORT_INVALID', f'{port} is outside 1024-49151 (registered, non-ephemeral ports)')
    with verified_binary(lay, pinned['sha256']) as binary:
        values = generate_secrets(binary, lay, run)
    text = render_app_ini(lay, port, values)
    with open(lay.config, 'x', encoding='utf-8', newline='\n') as handle:
        handle.write(text)
    record = {'format': HOST_FORMAT, 'version': VERSION, 'asset': ASSET_NAME, 'sha256': pinned['sha256'],
              'port': port, 'bind': LOOPBACK, 'created_at': now(),
              'secrets': {n: 'generated by gitea generate secret; in app.ini only' for n in SECRET_NAMES}}
    with open(lay.host_record, 'x', encoding='utf-8') as handle:
        json.dump(record, handle, indent=2)
        handle.write('\n')
    return {'config': str(lay.config), 'written': True, 'port': port}


def read_host_record(lay: Layout) -> dict:
    try:
        record = json.loads(lay.host_record.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise GiteaError('NOT_INSTALLED', f'{lay.host_record}: {type(exc).__name__}; run install') from None
    if record.get('format') != HOST_FORMAT or record.get('bind') != LOOPBACK or not isinstance(record.get('port'), int):
        raise GiteaError('HOST_RECORD_INVALID', f'{lay.host_record} is not a valid {HOST_FORMAT} record')
    ini = read_ini(lay.config)
    if ini.get('server', {}).get('HTTP_ADDR') != LOOPBACK or ini['server'].get('HTTP_PORT') != str(record['port']):
        raise GiteaError('CONFIG_NOT_LOOPBACK', f'{lay.config} does not bind {LOOPBACK}:{record["port"]}')
    return record


# ---------------------------------------------------------------- Windows: processes, jobs, sockets, tokens


def _k32():
    import ctypes
    from ctypes import wintypes
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    k.OpenProcess.restype = wintypes.HANDLE
    k.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    k.CloseHandle.argtypes = (wintypes.HANDLE,)
    k.GetProcessTimes.argtypes = (wintypes.HANDLE,) + (ctypes.POINTER(wintypes.FILETIME),) * 4
    k.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    k.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    k.WaitForSingleObject.restype = wintypes.DWORD
    k.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
    k.QueryFullProcessImageNameW.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                             ctypes.POINTER(wintypes.DWORD))
    k.CreateJobObjectW.restype = wintypes.HANDLE
    k.CreateJobObjectW.argtypes = (wintypes.LPVOID, wintypes.LPCWSTR)
    k.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD)
    k.QueryInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD,
                                            ctypes.POINTER(wintypes.DWORD))
    k.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    k.IsProcessInJob.argtypes = (wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL))
    k.GetCurrentProcess.restype = wintypes.HANDLE
    return k


class Proc:
    """One process id, opened for query, wait and terminate; identified by its creation time."""
    SYNCHRONIZE, TERMINATE, QUERY_LIMITED = 0x00100000, 0x0001, 0x1000
    STILL_ACTIVE = 259

    def __init__(self, pid: int):
        import ctypes
        self._ct, self._k, self.pid = ctypes, _k32(), int(pid)
        self.handle = self._k.OpenProcess(self.SYNCHRONIZE | self.TERMINATE | self.QUERY_LIMITED, False, self.pid)
        if not self.handle:
            raise OSError(ctypes.get_last_error(), f'OpenProcess({pid}) failed')

    @classmethod
    def maybe(cls, pid, created) -> 'Proc | None':
        """The live process with this id and creation time, else None (exited or id reused)."""
        try:
            proc = cls(pid)
        except (OSError, TypeError, ValueError):
            return None
        if proc.alive() and proc.created() == created:
            return proc
        proc.close()
        return None

    def created(self) -> int:
        from ctypes import wintypes
        times = [wintypes.FILETIME() for _ in range(4)]
        if not self._k.GetProcessTimes(self.handle, *[self._ct.byref(t) for t in times]):
            raise OSError(self._ct.get_last_error(), 'GetProcessTimes failed')
        return (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime

    def image(self) -> str:
        from ctypes import wintypes
        size = wintypes.DWORD(32768)
        buf = self._ct.create_unicode_buffer(size.value)
        if not self._k.QueryFullProcessImageNameW(self.handle, 0, buf, self._ct.byref(size)):
            raise OSError(self._ct.get_last_error(), 'QueryFullProcessImageNameW failed')
        return buf.value

    def alive(self) -> bool:
        from ctypes import wintypes
        code = wintypes.DWORD()
        self._k.GetExitCodeProcess(self.handle, self._ct.byref(code))
        return code.value == self.STILL_ACTIVE

    def wait(self, seconds: float) -> bool:
        """Wait on the process handle itself (its own completion signal); True once it has exited."""
        return self._k.WaitForSingleObject(self.handle, int(seconds * 1000)) == 0

    def in_any_job(self) -> bool:
        from ctypes import wintypes
        result = wintypes.BOOL()
        if not self._k.IsProcessInJob(self.handle, None, self._ct.byref(result)):
            raise OSError(self._ct.get_last_error(), 'IsProcessInJob failed')
        return bool(result.value)

    def terminate(self) -> None:
        if not self._k.TerminateProcess(self.handle, 1):
            raise OSError(self._ct.get_last_error(), 'TerminateProcess failed')

    def close(self) -> None:
        if self.handle:
            self._k.CloseHandle(self.handle)
            self.handle = None


JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
JOB_OBJECT_LIMIT_BREAKAWAY_OK = 0x0800
JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK = 0x1000
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9


def _job_structs():
    import ctypes
    from ctypes import wintypes

    class Basic(ctypes.Structure):
        _fields_ = [('PerProcessUserTimeLimit', ctypes.c_int64), ('PerJobUserTimeLimit', ctypes.c_int64),
                    ('LimitFlags', wintypes.DWORD), ('MinimumWorkingSetSize', ctypes.c_size_t),
                    ('MaximumWorkingSetSize', ctypes.c_size_t), ('ActiveProcessLimit', wintypes.DWORD),
                    ('Affinity', ctypes.c_size_t), ('PriorityClass', wintypes.DWORD),
                    ('SchedulingClass', wintypes.DWORD)]

    class IoCounters(ctypes.Structure):
        _fields_ = [(n, ctypes.c_uint64) for n in ('ReadOps', 'WriteOps', 'OtherOps', 'ReadBytes', 'WriteBytes',
                                                   'OtherBytes')]

    class Extended(ctypes.Structure):
        _fields_ = [('BasicLimitInformation', Basic), ('IoInfo', IoCounters),
                    ('ProcessMemoryLimit', ctypes.c_size_t), ('JobMemoryLimit', ctypes.c_size_t),
                    ('PeakProcessMemoryUsed', ctypes.c_size_t), ('PeakJobMemoryUsed', ctypes.c_size_t)]
    return Extended


class KillOnCloseJob:
    """A Job Object whose last handle closing ends every process in it. Its handle is not inheritable
    and is held by its creator only, so the job lives exactly as long as that process."""

    def __init__(self):
        import ctypes
        self._ct, self._k = ctypes, _k32()
        self.handle = self._k.CreateJobObjectW(None, None)
        if not self.handle:
            raise OSError(ctypes.get_last_error(), 'CreateJobObjectW failed')
        info = _job_structs()()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self._k.SetInformationJobObject(self.handle, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
                                               ctypes.byref(info), ctypes.sizeof(info)):
            raise OSError(ctypes.get_last_error(), 'SetInformationJobObject failed')

    def limit_flags(self) -> int:
        info = _job_structs()()
        if not self._k.QueryInformationJobObject(self.handle, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
                                                 self._ct.byref(info), self._ct.sizeof(info), None):
            raise OSError(self._ct.get_last_error(), 'QueryInformationJobObject failed')
        return int(info.BasicLimitInformation.LimitFlags)

    def assign_current(self) -> None:
        if not self._k.AssignProcessToJobObject(self.handle, self._k.GetCurrentProcess()):
            raise OSError(self._ct.get_last_error(), 'AssignProcessToJobObject(current) failed')

    def contains(self, process_handle) -> bool:
        from ctypes import wintypes
        result = wintypes.BOOL()
        if not self._k.IsProcessInJob(process_handle, self.handle, self._ct.byref(result)):
            raise OSError(self._ct.get_last_error(), 'IsProcessInJob failed')
        return bool(result.value)


def _ip4(value: int) -> str:
    return socket.inet_ntoa(struct.pack('<I', value))


def _port(value: int) -> int:
    return socket.ntohs(value & 0xFFFF)


def sockets(pid: int | None = None) -> list[dict]:
    """TCP listeners and UDP endpoints, IPv4 and IPv6, from GetExtendedTcpTable/GetExtendedUdpTable;
    filtered to one owning process when pid is given."""
    import ctypes
    from ctypes import wintypes
    ip = ctypes.WinDLL('iphlpapi')
    rows = []
    tables = (('tcp', socket.AF_INET, 3, 24), ('tcp', socket.AF_INET6, 3, 56),   # TCP_TABLE_OWNER_PID_LISTENER
              ('udp', socket.AF_INET, 1, 12), ('udp', socket.AF_INET6, 1, 28))   # UDP_TABLE_OWNER_PID
    for proto, family, table_class, row_size in tables:
        func = ip.GetExtendedTcpTable if proto == 'tcp' else ip.GetExtendedUdpTable
        size = wintypes.DWORD(0)
        func(None, ctypes.byref(size), False, family, table_class, 0)
        for _ in range(4):
            buf = ctypes.create_string_buffer(size.value + 4096)
            size = wintypes.DWORD(len(buf))
            code = func(buf, ctypes.byref(size), False, family, table_class, 0)
            if code == 0:
                break
            if code != 122:  # ERROR_INSUFFICIENT_BUFFER: the table grew; retry
                raise OSError(code, f'GetExtended{proto.title()}Table failed')
        data = buf.raw
        count = struct.unpack_from('<I', data, 0)[0]
        for i in range(count):
            off = 4 + i * row_size
            if family == socket.AF_INET:
                if proto == 'tcp':
                    _state, laddr, lport, _r, _rp, owner = struct.unpack_from('<6I', data, off)
                else:
                    laddr, lport, owner = struct.unpack_from('<3I', data, off)
                address = _ip4(laddr)
            else:
                address = socket.inet_ntop(socket.AF_INET6, data[off:off + 16])
                if proto == 'tcp':
                    _scope, lport = struct.unpack_from('<2I', data, off + 16)
                    owner = struct.unpack_from('<I', data, off + 52)[0]
                else:
                    _scope, lport, owner = struct.unpack_from('<3I', data, off + 16)
            if pid is None or owner == pid:
                rows.append({'proto': proto, 'family': 'ipv4' if family == socket.AF_INET else 'ipv6',
                             'address': address, 'port': _port(lport), 'pid': owner})
    return rows


def token_report(pid: int) -> dict:
    """The process token's elevation (TokenElevation, TokenElevationType) and integrity level RID."""
    import ctypes
    from ctypes import wintypes
    k, adv = _k32(), ctypes.WinDLL('advapi32', use_last_error=True)
    adv.OpenProcessToken.argtypes = (wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE))
    adv.GetTokenInformation.argtypes = (wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD,
                                        ctypes.POINTER(wintypes.DWORD))
    adv.GetSidSubAuthorityCount.restype = ctypes.POINTER(ctypes.c_ubyte)
    adv.GetSidSubAuthorityCount.argtypes = (wintypes.LPVOID,)
    adv.GetSidSubAuthority.restype = ctypes.POINTER(wintypes.DWORD)
    adv.GetSidSubAuthority.argtypes = (wintypes.LPVOID, wintypes.DWORD)
    process = k.OpenProcess(Proc.QUERY_LIMITED, False, pid)
    if not process:
        raise OSError(ctypes.get_last_error(), f'OpenProcess({pid}) failed')
    token = wintypes.HANDLE()
    try:
        if not adv.OpenProcessToken(process, 0x0008, ctypes.byref(token)):  # TOKEN_QUERY
            raise OSError(ctypes.get_last_error(), 'OpenProcessToken failed')

        def info(cls: int, size: int):
            buf, needed = ctypes.create_string_buffer(size), wintypes.DWORD()
            if not adv.GetTokenInformation(token, cls, buf, size, ctypes.byref(needed)):
                raise OSError(ctypes.get_last_error(), f'GetTokenInformation({cls}) failed')
            return buf
        elevated = struct.unpack('<I', info(20, 4).raw[:4])[0]          # TokenElevation
        elevation_type = struct.unpack('<I', info(18, 4).raw[:4])[0]    # TokenElevationType
        label = info(25, 256)                                           # TokenIntegrityLevel
        sid = ctypes.cast(label, ctypes.POINTER(ctypes.c_void_p))[0]
        rid = adv.GetSidSubAuthority(sid, adv.GetSidSubAuthorityCount(sid)[0] - 1)[0]
    finally:
        if token:
            k.CloseHandle(token)
        k.CloseHandle(process)
    return {'elevated': bool(elevated), 'elevation_type': {1: 'default', 2: 'full', 3: 'limited'}.get(elevation_type,
            str(elevation_type)), 'integrity_rid': hex(rid)}


def port_in_use(port: int) -> bool:
    if any(row['port'] == port and row['proto'] == 'tcp' for row in sockets()):
        return True
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.setsockopt(socket.SOL_SOCKET, getattr(socket, 'SO_EXCLUSIVEADDRUSE', socket.SO_REUSEADDR), 1)
        probe.bind((LOOPBACK, port))
        return False
    except OSError:
        return True
    finally:
        probe.close()


# ---------------------------------------------------------------- the managed environment


def _write_json(path: Path, data: dict) -> None:
    partial = path.with_name(path.name + '.partial')
    partial.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
    os.replace(partial, path)


def read_run_record(lay: Layout) -> dict | None:
    try:
        record = json.loads(lay.run_record.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        raise GiteaError('RUN_RECORD_INVALID', f'{lay.run_record} is unreadable') from None
    return record if record.get('format') == RUN_FORMAT else None


def live(record: dict | None, role: str) -> 'Proc | None':
    if not record or not isinstance(record.get(role), dict):
        return None
    return Proc.maybe(record[role].get('pid'), record[role].get('created'))


def supervise(res, lay: Layout, pinned: dict) -> int:
    """The managed environment: join a new kill-on-close job, start Gitea in it, record both
    processes, and wait for Gitea. When this process ends, however it ends, the job ends Gitea."""
    host = read_host_record(lay)
    job = KillOnCloseJob()
    job.assign_current()  # every process this one starts from now on is born inside the job
    flags = job.limit_flags()
    if not flags & JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE or flags & (JOB_OBJECT_LIMIT_BREAKAWAY_OK |
                                                                 JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK):
        raise GiteaError('JOB_UNSAFE', f'job limit flags {flags:#x}', refusal=False)
    me = Proc(os.getpid())
    record = {'format': RUN_FORMAT, 'state': 'starting', 'port': host['port'], 'started_at': now(),
              'supervisor': {'pid': me.pid, 'created': me.created(), 'image': me.image()},
              'job': {'limit_flags': hex(flags), 'kill_on_job_close': True, 'breakaway_allowed': False}}
    _write_json(lay.run_record, record)
    with open(lay.logs / 'console.log', 'ab') as console:
        console.write(f'--- {now()} supervisor {me.pid} starting gitea web\n'.encode())
        console.flush()
        with verified_binary(lay, pinned['sha256']) as binary:
            child = subprocess.Popen(gitea_argv(binary, lay, 'web'), env=child_env(lay), cwd=str(lay.home),
                                     stdin=subprocess.DEVNULL, stdout=console, stderr=console, close_fds=True,
                                     creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        gitea = Proc(child.pid)
        record.update(state='running', gitea={'pid': gitea.pid, 'created': gitea.created(), 'image': gitea.image(),
                                              'in_supervisor_job': job.contains(gitea.handle)})
        _write_json(lay.run_record, record)
        code = child.wait()
        console.write(f'--- {now()} gitea exited {code}; supervisor {me.pid} exiting\n'.encode())
    record.update(state='stopped', stopped_at=now(), gitea_exit=code)
    _write_json(lay.run_record, record)
    return 0


def http_get(port: int, path: str, *, method: str = 'GET', body: bytes | None = None, headers=None,
             timeout: float = 5.0) -> tuple[int, dict, bytes]:
    connection = http.client.HTTPConnection(LOOPBACK, port, timeout=timeout)
    try:
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        return response.status, {k.lower(): v for k, v in response.getheaders()}, response.read()
    finally:
        connection.close()


def healthy(port: int) -> bool:
    try:
        return http_get(port, '/api/healthz', timeout=2.0)[0] == 200
    except OSError:
        return False


def up(res, lay: Layout, pinned: dict) -> dict:
    host = read_host_record(lay)
    record = read_run_record(lay)
    if live(record, 'supervisor') or live(record, 'gitea'):
        raise GiteaError('ALREADY_RUNNING', f'the managed environment runs (supervisor {record["supervisor"]["pid"]})')
    if port_in_use(host['port']):
        raise GiteaError('PORT_IN_USE', f'{LOOPBACK}:{host["port"]} or the port on another address is in use')
    with verified_binary(lay, pinned['sha256']):
        pass  # refuse before starting anything; the supervisor verifies again before it starts Gitea
    argv = [sys.executable, '-I', '-B', str(Path(os.path.realpath(__file__))), 'supervise']
    base = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    with open(lay.logs / 'supervisor.log', 'ab') as log:
        try:
            supervisor = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=log, stderr=log, close_fds=True,
                                          cwd=str(lay.home), creationflags=base | subprocess.CREATE_BREAKAWAY_FROM_JOB)
        except OSError:  # the caller's job forbids breakaway: the supervisor then also ends with the caller
            supervisor = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=log, stderr=log, close_fds=True,
                                          cwd=str(lay.home), creationflags=base)
    deadline = time.monotonic() + READY_CEILING_S
    while not healthy(host['port']):
        if supervisor.poll() is not None:
            raise GiteaError('START_FAILED', f'the supervisor exited {supervisor.returncode}; see '
                                             f'{lay.logs / "supervisor.log"} and {lay.logs / "console.log"}',
                             refusal=False)
        if time.monotonic() > deadline:
            raise GiteaError('START_TIMEOUT', f'Gitea did not answer /api/healthz within {READY_CEILING_S:.0f}s; '
                                              'run down', refusal=False)
        time.sleep(0.25)  # readiness poll interval; the bound is the ceiling above
    return status(res, lay, pinned)


def down(res, lay: Layout, pinned: dict, run: Callable = subprocess.run) -> dict:
    record = read_run_record(lay)
    supervisor, gitea = live(record, 'supervisor'), live(record, 'gitea')
    if supervisor is None and gitea is None:
        return {'stopped': False, 'detail': 'not running', 'port_open': port_in_use(read_host_record(lay)['port'])}
    method = 'gitea manager shutdown'
    if gitea is not None:
        with verified_binary(lay, pinned['sha256']) as binary:
            result = run_quiet(gitea_argv(binary, lay, 'manager', 'shutdown'), child_env(lay), lay.home, run)
        if result.returncode != 0:
            method = f'manager shutdown exited {result.returncode}; supervisor terminated'
            (supervisor or gitea).terminate()
        if not gitea.wait(STOP_CEILING_S):
            method = 'gitea did not stop within the ceiling; supervisor terminated (the job ends gitea)'
            (supervisor or gitea).terminate()
            gitea.wait(STOP_CEILING_S)
    if supervisor is not None and not supervisor.wait(STOP_CEILING_S):
        supervisor.terminate()
        supervisor.wait(STOP_CEILING_S)
        method += '; supervisor terminated after gitea stopped'
    port = read_host_record(lay)['port']
    return {'stopped': True, 'method': method, 'gitea_alive': bool(gitea and gitea.alive()),
            'supervisor_alive': bool(supervisor and supervisor.alive()), 'port_open': port_in_use(port)}


def status(res, lay: Layout, pinned: dict) -> dict:
    host = read_host_record(lay)
    record = read_run_record(lay)
    supervisor, gitea = live(record, 'supervisor'), live(record, 'gitea')
    report = {'url': f'http://{LOOPBACK}:{host["port"]}/', 'running': bool(supervisor and gitea),
              'supervisor': None, 'gitea': None, 'record_state': (record or {}).get('state'),
              'healthz': healthy(host['port'])}
    report['stale_record'] = report['record_state'] in ('starting', 'running') and not report['running']
    if supervisor:
        report['supervisor'] = {'pid': supervisor.pid, 'in_a_job': supervisor.in_any_job()}
    if gitea:
        report['gitea'] = {'pid': gitea.pid, 'image': gitea.image(), 'in_a_job': gitea.in_any_job(),
                           'in_supervisor_job_at_start': record['gitea'].get('in_supervisor_job'),
                           'listeners': sockets(gitea.pid), 'token': token_report(gitea.pid)}
    if record and supervisor:
        report['job'] = record.get('job')
    return report


# ---------------------------------------------------------------- Windows Credential Manager


class CredentialStore:
    """Generic credentials through CredWriteW / CredReadW / CredDeleteW (advapi32). Values are bytes in
    memory; nothing here prints or logs them."""
    GENERIC, PERSIST_LOCAL_MACHINE, ERROR_NOT_FOUND = 1, 2, 1168

    def __init__(self):
        import ctypes
        from ctypes import wintypes

        class Credential(ctypes.Structure):
            _fields_ = [('Flags', wintypes.DWORD), ('Type', wintypes.DWORD), ('TargetName', wintypes.LPWSTR),
                        ('Comment', wintypes.LPWSTR), ('LastWritten', wintypes.FILETIME),
                        ('CredentialBlobSize', wintypes.DWORD), ('CredentialBlob', ctypes.POINTER(ctypes.c_ubyte)),
                        ('Persist', wintypes.DWORD), ('AttributeCount', wintypes.DWORD),
                        ('Attributes', wintypes.LPVOID), ('TargetAlias', wintypes.LPWSTR),
                        ('UserName', wintypes.LPWSTR)]
        self._ct, self._Credential = ctypes, Credential
        adv = ctypes.WinDLL('advapi32', use_last_error=True)
        adv.CredWriteW.argtypes = (ctypes.POINTER(Credential), wintypes.DWORD)
        adv.CredReadW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  ctypes.POINTER(ctypes.POINTER(Credential)))
        adv.CredDeleteW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD)
        adv.CredFree.argtypes = (wintypes.LPVOID,)
        self._adv = adv

    def write(self, target: str, user: str, secret: bytes, comment: str) -> None:
        ct = self._ct
        blob = (ct.c_ubyte * len(secret)).from_buffer_copy(secret)
        cred = self._Credential(Type=self.GENERIC, TargetName=target, Comment=comment,
                                CredentialBlobSize=len(secret), CredentialBlob=ct.cast(blob, ct.POINTER(ct.c_ubyte)),
                                Persist=self.PERSIST_LOCAL_MACHINE, UserName=user)
        ok = self._adv.CredWriteW(ct.byref(cred), 0)
        ct.memset(blob, 0, len(secret))
        if not ok:
            raise GiteaError('CREDENTIAL_WRITE_FAILED', f'CredWriteW({target!r}) failed ({ct.get_last_error()})',
                             refusal=False)

    def read(self, target: str) -> tuple[str, bytes] | None:
        ct = self._ct
        pointer = ct.POINTER(self._Credential)()
        if not self._adv.CredReadW(target, self.GENERIC, 0, ct.byref(pointer)):
            if (code := ct.get_last_error()) == self.ERROR_NOT_FOUND:
                return None
            raise GiteaError('CREDENTIAL_READ_FAILED', f'CredReadW({target!r}) failed ({code})', refusal=False)
        try:
            cred = pointer.contents
            return cred.UserName or '', ct.string_at(cred.CredentialBlob, cred.CredentialBlobSize)
        finally:
            self._adv.CredFree(pointer)

    def delete(self, target: str) -> bool:
        if self._adv.CredDeleteW(target, self.GENERIC, 0):
            return True
        if (code := self._ct.get_last_error()) == self.ERROR_NOT_FOUND:
            return False
        raise GiteaError('CREDENTIAL_DELETE_FAILED', f'CredDeleteW({target!r}) failed ({code})', refusal=False)


class CredentialProvider:
    """Where the harness keeps service credentials, by entry name: get, set, delete, exists. A secret is a
    str held in memory; an implementation never prints or logs it. WindowsCredentialProvider is the only
    implementation today; a cross-platform one replaces it through credential_provider() without its
    callers changing."""

    def get(self, name: str) -> tuple[str, str] | None:
        """(user name, secret), or None when the entry does not exist."""
        raise NotImplementedError

    def set(self, name: str, user: str, secret: str, comment: str = '') -> None:
        """Create or replace the entry."""
        raise NotImplementedError

    def delete(self, name: str) -> bool:
        """True when an entry was deleted, False when there was none."""
        raise NotImplementedError

    def exists(self, name: str) -> bool:
        return self.get(name) is not None


class WindowsCredentialProvider(CredentialProvider):
    """Windows Credential Manager generic credentials (CredentialStore); the secret is stored as UTF-16LE, as
    the Credential Manager UI shows it."""

    def __init__(self, store=None):
        self.store = store or CredentialStore()

    def get(self, name):
        entry = self.store.read(name)
        return None if entry is None else (entry[0], entry[1].decode('utf-16-le'))

    def set(self, name, user, secret, comment=''):
        self.store.write(name, user, secret.encode('utf-16-le'), comment)

    def delete(self, name):
        return self.store.delete(name)


def credential_provider() -> CredentialProvider:
    """The platform's credential provider."""
    if os.name == 'nt':
        return WindowsCredentialProvider()
    raise GiteaError('NO_CREDENTIAL_PROVIDER', 'only the Windows Credential Manager provider is implemented; the '
                     'cross-platform provider is pending')


# ---------------------------------------------------------------- identities


def gitea_users(binary: Path, lay: Layout, run: Callable = subprocess.run) -> dict:
    """{name: {'admin': bool}} from `gitea admin user list` (its columns are named in its header), plus
    {'type': 'User' | 'Bot'} where the header has Gitea 28's Type column."""
    result = run_quiet(gitea_argv(binary, lay, 'admin', 'user', 'list'), child_env(lay), lay.home, run)
    if result.returncode != 0:
        raise GiteaError('USER_LIST_FAILED', f'gitea admin user list exited {result.returncode}', refusal=False)
    lines = [ln for ln in result.stdout.decode('utf-8', 'replace').splitlines() if ln.strip()]
    if not lines:
        return {}
    header = lines[0].split()
    if 'Username' not in header or 'IsAdmin' not in header:
        raise GiteaError('USER_LIST_UNPARSED', f'unexpected header {header}', refusal=False)
    users = {}
    for line in lines[1:]:
        cells = line.split()
        row = dict(zip(header, cells))
        users[row['Username']] = {'admin': row.get('IsAdmin') == 'true',
                                  **({'type': row['Type']} if 'Type' in row else {})}
    return users


def create_identities(res, lay: Layout, pinned: dict, provider: CredentialProvider | None = None,
                      run: Callable = subprocess.run) -> dict:
    """The site administrator and the separate non-administrator Owner account, each with a random
    temporary password that Gitea generates and that goes from the CLI's captured output straight into one
    provider entry; finalize-credentials then replaces it."""
    provider = provider or credential_provider()
    host = read_host_record(lay)
    if not healthy(host['port']):
        raise GiteaError('NOT_RUNNING', 'run up first: the accounts are created against the migrated database')
    for target in (*CRED_TARGETS.values(), *FINAL_TARGETS.values()):
        if provider.exists(target):
            raise GiteaError('CREDENTIAL_EXISTS', f'the credential entry {target!r} already exists')
    with verified_binary(lay, pinned['sha256']) as binary:
        existing = gitea_users(binary, lay, run)
        if clash := sorted(set(CRED_TARGETS) & set(existing)):
            raise GiteaError('ACCOUNT_EXISTS', f'Gitea already has {clash}')
        created = []
        for user, admin in ((SITE_ADMIN, True), (OWNER, False)):
            argv = gitea_argv(binary, lay, 'admin', 'user', 'create', '--username', user,
                              '--email', f'{user}@{EMAIL_DOMAIN}', '--random-password',
                              '--random-password-length', str(RANDOM_PASSWORD_LENGTH),
                              '--must-change-password=true', *(['--admin'] if admin else []))
            result = run_quiet(argv, child_env(lay), lay.home, run)
            found = GENERATED_PASSWORD.findall(result.stdout)
            if result.returncode != 0 or len(found) != 1:
                raise GiteaError('ACCOUNT_CREATE_FAILED', f'gitea admin user create {user} exited {result.returncode} '
                                                          f'({len(found)} generated passwords seen; output withheld)',
                                 refusal=False)
            secret = found[0].decode('utf-8')
            del found, result
            provider.set(CRED_TARGETS[user], user, secret,
                         f'Temporary password of {user} on the AIEH Gitea at http://{LOOPBACK}:{host["port"]}/; '
                         'replaced and deleted by task gitea:finalize-credentials.')
            del secret
            created.append(user)
        after = gitea_users(binary, lay, run)
    return {'created': created, 'admin': {u: after.get(u, {}).get('admin') for u in created},
            'credential_targets': [CRED_TARGETS[u] for u in created],
            'password_handling': 'gitea --random-password output captured in memory; credential provider; never shown'}


def contains_secret(root: Path, needles: list[bytes], skip: Iterable[Path] = ()) -> dict:
    """Search every file below root for any needle (as given, or as UTF-16LE). Returns 'found' (files holding
    one) and 'unreadable' (what the search could not cover: a directory the walk could not list, the root
    included, and a non-empty file that could not be read). A scan with anything unreadable is incomplete
    and never a clean result. An unreadable EMPTY file holds nothing and is not reported (e.g. LevelDB's
    LOCK, held open by the running Gitea). Names only, never content."""
    forms = [form for n in needles for form in (n, n.decode('utf-8').encode('utf-16-le'))]
    longest, skipped = max(map(len, forms)), {Path(s) for s in skip}
    found, unreadable = [], []

    def directory_error(exc: OSError) -> None:
        unreadable.append(f'{exc.filename} (directory not listed: {type(exc).__name__})')

    for directory, _dirs, files in os.walk(root, onerror=directory_error):
        for name in files:
            path = Path(directory) / name
            if path in skipped:
                continue
            try:
                with open(path, 'rb') as handle:
                    tail = b''
                    for block in iter(lambda: handle.read(1 << 20), b''):
                        window = tail + block
                        if any(form in window for form in forms):
                            found.append(str(path))
                            break
                        tail = window[-longest:]
            except OSError as exc:
                try:
                    empty = os.stat(path).st_size == 0
                except OSError:
                    empty = False
                if not empty:
                    unreadable.append(f'{path} (file not read: {type(exc).__name__})')
    return {'found': found, 'unreadable': unreadable}


def checkout_files(repo: Path) -> list[Path]:
    """Tracked and untracked, not ignored files of the checkout (git's own listing)."""
    result = subprocess.run(['git', '-C', str(repo), 'ls-files', '-z', '--cached', '--others', '--exclude-standard'],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=True)
    return [repo / name for name in result.stdout.decode('utf-8').split('\0') if name]


def files_containing(files: Iterable[Path], needles: list[bytes]) -> dict:
    """Search each listed file for any needle (as given, or as UTF-16LE). Returns 'found' (files holding one),
    'unreadable' (files that could not be read: any OSError but FileNotFoundError) and 'absent' (listed but
    not in the working tree, e.g. a tracked file deleted from it: it holds no content, so it is reported
    and is not a failure). A scan with anything unreadable is incomplete and never a clean result. Names
    only, never content."""
    forms = [form for n in needles for form in (n, n.decode('utf-8').encode('utf-16-le'))]
    found, unreadable, absent = [], [], []
    for path in files:
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            absent.append(str(path))
            continue
        except OSError as exc:
            unreadable.append(f'{path} (file not read: {type(exc).__name__})')
            continue
        if any(form in data for form in forms):
            found.append(str(path))
    return {'found': found, 'unreadable': unreadable, 'absent': absent}


# ---------------------------------------------------------------- credential finalization


def basic_header(user: str, password: str) -> dict:
    return {'Authorization': 'Basic ' + base64.b64encode(f'{user}:{password}'.encode('utf-8')).decode('ascii')}


def basic_call(port: int, user: str, password: str, method: str, path: str, http: Callable = None):
    """(status, parsed JSON or None) of an API call with HTTP basic authentication."""
    status, _headers, body = (http or http_get)(port, '/api/v1' + path, method=method,
                                                headers={**basic_header(user, password), 'Accept': 'application/json'})
    try:
        return status, json.loads(body) if body else None
    except ValueError:
        return status, None


MUST_CHANGE = 'change your password'


def password_state(port: int, user: str, password: str, http: Callable = None) -> str:
    """'valid' (200), 'must-change' (correct, but Gitea refuses the account until it changes it), or
    'rejected' (anything else)."""
    status, body = basic_call(port, user, password, 'GET', '/user', http)
    if status == 200 and isinstance(body, dict) and body.get('login') == user:
        return 'valid'
    if status == 403 and isinstance(body, dict) and MUST_CHANGE in str(body.get('message', '')):
        return 'must-change'
    return 'rejected'


class WebSession:
    """A cookie-keeping HTTP client for Gitea's own web forms on loopback. Form values travel in request
    bodies only; nothing here prints or logs them."""

    def __init__(self, port: int, connection: Callable = None):
        self.port, self.cookies = port, {}
        self.connection = connection or (lambda: http.client.HTTPConnection(LOOPBACK, port, timeout=30))

    def request(self, method: str, path: str, fields: dict | None = None) -> tuple[int, str, bytes]:
        """(status, Location header, body) of a GET or a form POST, keeping the session's cookies."""
        headers, body = {}, None
        if fields is not None:
            body = urllib.parse.urlencode(fields).encode('utf-8')
            headers['Content-Type'] = 'application/x-www-form-urlencoded'
        if self.cookies:
            headers['Cookie'] = '; '.join(f'{k}={v}' for k, v in self.cookies.items())
        connection = self.connection()
        try:
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            for raw in response.msg.get_all('Set-Cookie') or []:
                name, _, rest = raw.partition('=')
                self.cookies[name.strip()] = rest.split(';', 1)[0]
            data = response.read()
            return response.status, response.getheader('Location') or '', data
        finally:
            connection.close()

    def post(self, path: str, fields: dict) -> tuple[int, str]:
        status, location, _body = self.request('POST', path, fields)
        return status, location

    def get(self, path: str) -> tuple[int, str, bytes]:
        return self.request('GET', path)


CHANGE_FORM = '/user/settings/change_password'


def _path(location: str) -> str:
    return urllib.parse.urlsplit(location).path or '/'


def change_password_by_web(port: int, user: str, current: str, new: str, connection: Callable = None) -> dict:
    """Gitea's own forced password change. Gitea 28.3.0 answers a correct sign-in of an account that must
    change its password with a redirect to where it was going (usually /), not to the change form; the
    next page request is what Gitea redirects to the form. So: sign in, follow that redirect with the
    session, require Gitea itself to send the session to the change form, then submit the new password.
    A wrong password answers 200 with the sign-in form. Statuses and paths only in errors."""
    web = WebSession(port, connection)
    status, location = web.post('/user/login', {'user_name': user, 'password': current})
    if status not in (302, 303) or _path(location).startswith('/user/login'):
        raise GiteaError('SIGN_IN_FAILED', f'{user}: sign-in answered {status} (Location path {_path(location)!r})',
                         refusal=False)
    trail = [f'sign-in {status} {_path(location)}']
    path = _path(location)
    for _hop in range(3):
        if path == CHANGE_FORM:
            break
        status, location, _body = web.get(path)
        trail.append(f'GET {path} {status} {_path(location) if location else ""}'.rstrip())
        if status not in (302, 303):
            break
        path = _path(location)
    if path != CHANGE_FORM:
        raise GiteaError('CHANGE_NOT_DEMANDED', f'{user}: Gitea did not send the session to the change form '
                                                f'({"; ".join(trail)})', refusal=False)
    status, _location, body = web.get(CHANGE_FORM)
    trail.append(f'GET {CHANGE_FORM} {status}')
    if status != 200 or b'name="retype"' not in body:
        raise GiteaError('CHANGE_FORM_MISSING', f'{user}: {"; ".join(trail)}', refusal=False)
    status, location = web.post(CHANGE_FORM, {'password': new, 'retype': new})
    trail.append(f'change {status} {_path(location) if location else ""}'.rstrip())
    if status not in (302, 303) or _path(location) in (CHANGE_FORM, '/user/login'):
        raise GiteaError('PASSWORD_CHANGE_FAILED', f'{user}: {"; ".join(trail)}', refusal=False)
    return {'trail': trail}


def revoke_all_tokens(port: int, user: str, password: str, http: Callable = None) -> dict:
    """Delete every access token of the account with its own credentials, then list again: a finalized
    human account holds no token, and this is enforced, not only reported. It fails closed:
    TOKEN_REVOCATION_UNVERIFIED when the listing after the deletions is not 200 with a JSON list (the
    postcondition is unknown; distinct from TOKEN_LIST_FAILED, which happens before anything was deleted),
    and TOKENS_REMAIN when any token is still listed, including one whose deletion answered 204. On success
    'remaining' is always []. Token names only; never a value or its last characters."""
    status, tokens = basic_call(port, user, password, 'GET', f'/users/{user}/tokens', http)
    if status != 200 or not isinstance(tokens, list):
        raise GiteaError('TOKEN_LIST_FAILED', f'{user}: listing its tokens answered {status}', refusal=False)
    deleted = []
    for token in tokens:
        code, _body = basic_call(port, user, password, 'DELETE', f'/users/{user}/tokens/{token["id"]}', http)
        if code != 204:
            raise GiteaError('TOKEN_DELETE_FAILED', f'{user}: deleting token {token.get("name")!r} answered {code}',
                             refusal=False)
        deleted.append(token.get('name'))
    status, after = basic_call(port, user, password, 'GET', f'/users/{user}/tokens', http)
    if status != 200 or not isinstance(after, list):
        raise GiteaError('TOKEN_REVOCATION_UNVERIFIED', f'{user}: deleted {deleted!r}, but listing its tokens '
                                                        f'afterwards answered {status} without a token list',
                         refusal=False)
    remaining = [t.get('name') if isinstance(t, dict) else None for t in after]
    if remaining:
        raise GiteaError('TOKENS_REMAIN', f'{user}: still listed after revocation: {remaining!r} '
                                          f'(deleted with 204: {deleted!r})', refusal=False)
    return {'found': [t.get('name') for t in tokens], 'deleted': deleted, 'remaining': remaining}


def finalize_account(port: int, user: str, provider: CredentialProvider, http: Callable = None,
                     connection: Callable = None, secrets_seen: list | None = None) -> dict:
    """One account: a new random password, stored in its provider entry BEFORE Gitea is changed (so a crash
    never loses it), set through Gitea's forced change, then every token of the account revoked with the new
    credentials, then verified, then the temporary entry deleted. Reruns resume from any intermediate state.
    The token revocation fails closed on both paths (TOKENS_REMAIN, TOKEN_REVOCATION_UNVERIFIED) and no
    report is returned. A raise after the password change and before the temporary entry is deleted leaves
    both entries in place and the final password set in Gitea: a rerun finds the final entry, sees the
    change already applied and revokes again, so it resumes there."""
    final_name, temp_name = FINAL_TARGETS[user], CRED_TARGETS[user]
    final_entry, temp_entry = provider.get(final_name), provider.get(temp_name)
    report = {'user': user, 'entry': final_name}
    if temp_entry is None:
        if final_entry is None:
            raise GiteaError('ENTRIES_MISSING', f'neither {temp_name!r} nor {final_name!r} exists; run identities')
        final = final_entry[1]
        if password_state(port, user, final, http) != 'valid':
            raise GiteaError('FINAL_PASSWORD_REJECTED', f'{user}: the stored final password does not authenticate',
                             refusal=False)
        report.update(state='already final', tokens=revoke_all_tokens(port, user, final, http))
    else:
        temp = temp_entry[1]
        if final_entry is None:
            final = secrets.token_urlsafe(FINAL_PASSWORD_BYTES)
            provider.set(final_name, user, final, f'Password of {user} on the AIEH Gitea (harness-held; set by task '
                                                  'gitea:finalize-credentials). Not for agents, bots or tests.')
            report['stored_before_change'] = True
        else:
            final = final_entry[1]
            report['stored_before_change'] = 'by an earlier run'
        if secrets_seen is not None:
            secrets_seen += [temp, final]
        if password_state(port, user, final, http) == 'valid':
            report['change'] = 'already applied by an earlier run'
        else:
            if password_state(port, user, temp, http) == 'rejected':
                raise GiteaError('TEMPORARY_PASSWORD_REJECTED', f'{user}: the temporary password does not authenticate',
                                 refusal=False)
            report['change'] = change_password_by_web(port, user, temp, final, connection)
        # First call with the new credentials: every token of the account goes (S-01.2.2's dangling one included).
        report['tokens'] = revoke_all_tokens(port, user, final, http)
        report['temporary_password'] = password_state(port, user, temp, http)
        if report['temporary_password'] != 'rejected':
            raise GiteaError('TEMPORARY_PASSWORD_ACTIVE', f'{user}: the temporary password still authenticates',
                             refusal=False)
        report['temporary_entry_deleted'] = provider.delete(temp_name)
    status, body = basic_call(port, user, final, 'GET', '/user', http)
    report['final_password'] = 'valid' if status == 200 and body.get('login') == user else f'HTTP {status}'
    report['is_admin'] = bool(body.get('is_admin')) if status == 200 else None
    if report['final_password'] != 'valid':
        raise GiteaError('FINAL_PASSWORD_REJECTED', f'{user}: the final password answered {status}', refusal=False)
    if report['is_admin'] is not (user == SITE_ADMIN):
        raise GiteaError('ACCOUNT_ROLE_MISMATCH', f'{user}: is_admin is {report["is_admin"]}', refusal=False)
    if secrets_seen is not None and temp_entry is None:
        secrets_seen.append(final)
    del final
    return report


def finalize_credentials(res, lay: Layout, pinned: dict, provider: CredentialProvider | None = None,
                         http: Callable = None, connection: Callable = None, repo: Path | None = None) -> dict:
    """Owner directive of 2026-11-07: the harness finishes the two human accounts' credential lifecycle itself.
    The site administrator first, then the Owner account; then no temporary or final password may appear in
    the managed root (its logs included), the checkout or this report: PASSWORD_FOUND on a hit, and
    SECRET_SCAN_INCOMPLETE when a file or directory could not be searched (names only)."""
    provider = provider or credential_provider()
    port = read_host_record(lay)['port']
    if not healthy(port):
        raise GiteaError('NOT_RUNNING', 'run up: the credentials are finalized against the running Gitea')
    seen: list[str] = []
    try:
        report = {'accounts': [finalize_account(port, user, provider, http, connection, seen)
                               for user in (SITE_ADMIN, OWNER)]}
        report['entries'] = {name: provider.exists(name) for name in (*FINAL_TARGETS.values(), *CRED_TARGETS.values())}
        needles = [s.encode('utf-8') for s in seen]
        root_scan = contains_secret(lay.root, needles)
        checkout_scan = files_containing(checkout_files(repo or lay.repo), needles)
        report['found_in_managed_root'] = root_scan['found']
        report['found_in_checkout'] = checkout_scan['found']
        report['scan_incomplete'] = {'managed_root': root_scan['unreadable'], 'checkout': checkout_scan['unreadable']}
        report['absent_from_checkout'] = checkout_scan['absent']
        text = json.dumps(report)
        report['found_in_report'] = any(s in text for s in seen)
    finally:
        seen.clear()
    if report['found_in_managed_root'] or report['found_in_checkout'] or report['found_in_report']:
        found = ('found_in_managed_root', 'found_in_checkout', 'scan_incomplete')
        raise GiteaError('PASSWORD_FOUND', json.dumps({k: report[k] for k in found}), refusal=False)
    if any(report['scan_incomplete'].values()):
        # Not PASSWORD_FOUND: nothing was found; what could not be read was not searched.
        raise GiteaError('SECRET_SCAN_INCOMPLETE', json.dumps(report['scan_incomplete']), refusal=False)
    report['password_handling'] = ('generated with secrets, stored by the credential provider before use, sent only in '
                                   'loopback HTTP request bodies and basic-auth headers; never on a command line, in '
                                   'an environment, in a log or in output')
    return report


# ---------------------------------------------------------------- verification


def verify(res, lay: Layout, pinned: dict) -> dict:
    """The F-06.1 proof set, mechanically: pin, listeners, elevation, job, paths, sign-up and anonymous
    API refusals, and no Gitea secret in the checkout. Returns checks; exits 1 when any fails."""
    checks = {}
    with verified_binary(lay, pinned['sha256']) as binary:
        checks['binary_sha256_equals_pin'] = True
    st = status(res, lay, pinned)
    port = read_host_record(lay)['port']
    g = st['gitea'] or {}
    checks['running_under_supervisor'] = st['running']
    checks['gitea_image_is_the_asset'] = bool(g) and os.path.normcase(g['image']) == os.path.normcase(str(binary))
    listeners = g.get('listeners', [])
    others = [r for r in listeners if r['port'] != port]
    checks['listeners_only_loopback'] = bool(listeners) and all(
        r['proto'] == 'tcp' and r['address'] == LOOPBACK for r in listeners)
    checks['http_listener_on_configured_port'] = any(r['port'] == port for r in listeners)
    egress = {r['port']: egress_proxy(r['port']) for r in others}
    checks['other_listeners_are_the_egress_proxy'] = all(egress.values())
    checks['no_other_listener_on_port'] = all(r['pid'] == g.get('pid') for r in sockets() if r['port'] == port)
    checks['token_not_elevated'] = bool(g) and not g['token']['elevated']
    checks['gitea_in_supervisor_kill_on_close_job'] = bool(g.get('in_supervisor_job_at_start')) and bool(
        (st.get('job') or {}).get('kill_on_job_close'))
    ini = read_ini(lay.config)
    used = {'work': ini['']['WORK_PATH'], 'data': ini['server']['APP_DATA_PATH'], 'db': ini['database']['PATH'],
            'repositories': ini['repository']['ROOT'], 'logs': ini['log']['ROOT_PATH'], 'lfs': ini['lfs']['PATH'],
            'config': str(lay.config), 'binary': str(lay.binary), 'tmp': str(lay.tmp)}
    categories = [Path(str(res.paths[c])) for c in ('gitea', 'logs', 'assets', 'tmp')]
    checks['paths_from_resolver'] = all(any(Path(v).is_relative_to(c) for c in categories) for v in used.values())
    checks['paths_outside_checkout'] = not any(Path(v).is_relative_to(lay.repo) for v in used.values())
    checks['config_settings'] = all([
        ini['server'].get('HTTP_ADDR') == LOOPBACK, ini['server'].get('DISABLE_SSH') == 'true',
        ini['server'].get('START_SSH_SERVER') == 'false', ini['server'].get('OFFLINE_MODE') == 'true',
        ini['service'].get('DISABLE_REGISTRATION') == 'true', ini['service'].get('REQUIRE_SIGNIN_VIEW') == 'true',
        ini['security'].get('INSTALL_LOCK') == 'true', ini['database'].get('DB_TYPE') == 'sqlite3',
        ini['mailer'].get('ENABLED') == 'false', 'picture' not in ini,
        ini['cron.update_checker'].get('ENABLED') == 'false', ini['federation'].get('ENABLED') == 'false',
        ini['actions'].get('ENABLED') == 'false', ini['server'].get('LFS_START_SERVER') == 'false'])
    probes = anonymous_probes(port)
    checks['sign_up_refused'] = (probes['sign_up_post'] == 403 and probes['sign_up_page_says_disabled']
                                 and probes['login_post_control_reached_handler'])
    with verified_binary(lay, pinned['sha256']) as binary:
        users = gitea_users(binary, lay)
    checks['no_account_created_by_probe'] = PROBE_USER not in users
    checks['accounts_are_the_expected_ones'] = set(users) <= set(CRED_TARGETS) | set(BOT_ACCOUNTS.values())
    checks['bots_are_non_admin_bot_accounts'] = all(
        not users[u]['admin'] and users[u].get('type') == 'Bot' for u in BOT_ACCOUNTS.values() if u in users)
    checks['anonymous_api_refused'] = all(probes[k] in (401, 403) for k in probes if k.startswith('api '))
    checks['anonymous_web_redirected_to_login'] = probes['explore_users'] in (302, 303)
    secret_values = [ini['security']['SECRET_KEY'].encode(), ini['security']['INTERNAL_TOKEN'].encode(),
                     ini['oauth2']['JWT_SECRET'].encode()]
    checkout_scan = files_containing(checkout_files(lay.repo), secret_values)
    del secret_values
    # An incomplete scan is a failure, never a clean result; the unreadable paths are in 'checkout_scan'.
    checks['no_gitea_secret_in_checkout'] = not checkout_scan['found'] and not checkout_scan['unreadable']
    return {'checks': checks, 'checkout_scan': checkout_scan, 'probes': probes, 'accounts': users, 'paths': used,
            'pid': g.get('pid'),
            'listeners': listeners, 'egress_proxy_ports': sorted(egress),
            'token': g.get('token'), 'job': st.get('job'), 'passed': all(checks.values())}


def egress_proxy(port: int) -> bool:
    """Gitea 28's built-in egress-policy proxy ([security] EGRESS_MODE): it binds 127.0.0.1:0 and answers
    an unauthenticated request with 407 and the realm 'gitea egress proxy'."""
    try:
        code, headers, _body = http_get(port, '/')
    except OSError:
        return False
    return code == 407 and headers.get('proxy-authenticate', '') == 'Basic realm="gitea egress proxy"'


PROBE_USER = 'aieh-probe'


def anonymous_probes(port: int) -> dict:
    """Unauthenticated HTTP: the sign-up page; a sign-up POST, with a login POST for an unknown user as
    the control that same-origin form POSTs reach their handlers (Gitea 28 checks the request origin, not
    a form token); the API's user and repository routes; the explore page. Status codes only."""
    probes, form_type = {}, {'Content-Type': 'application/x-www-form-urlencoded'}
    code, _headers, body = http_get(port, '/user/sign_up')
    probes['sign_up_page'] = code
    probes['sign_up_page_says_disabled'] = b'Registration is disabled' in body
    throwaway = secrets.token_urlsafe(18)
    control = urllib.parse.urlencode({'user_name': f'{PROBE_USER}-unknown', 'password': throwaway}).encode()
    code, _headers, body = http_get(port, '/user/login', method='POST', body=control, headers=form_type)
    probes['login_post_control'] = code
    probes['login_post_control_reached_handler'] = code == 200 and b'Username or password is incorrect' in body
    form = urllib.parse.urlencode({'user_name': PROBE_USER, 'email': f'{PROBE_USER}@{EMAIL_DOMAIN}',
                                   'password': throwaway, 'retype': throwaway}).encode()
    del throwaway
    probes['sign_up_post'] = http_get(port, '/user/sign_up', method='POST', body=form, headers=form_type)[0]
    for route in ('/api/v1/users/search', f'/api/v1/users/{OWNER}', f'/api/v1/users/{SITE_ADMIN}', '/api/v1/user',
                  '/api/v1/admin/users', '/api/v1/repos/search', '/api/v1/orgs'):
        probes[f'api {route}'] = http_get(port, route)[0]
    probes['explore_users'] = http_get(port, '/explore/users')[0]
    return probes


# ---------------------------------------------------------------- command line


def install(res, lay: Layout, pinned: dict, port: int, from_file: Path | None) -> dict:
    created = paths.init(res)['created']
    created += ensure_dirs(res, lay)
    asset = acquire(res, lay, pinned, from_file=from_file)
    config = configure(res, lay, pinned, port)
    return {'root': str(lay.root), 'created': created, 'asset': asset, 'config': config,
            'layout': {k: str(v) for k, v in lay.items() if k != 'repo'}}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog='gitea_host.py', description='Host-loopback Gitea under the managed data '
                                     'root (F-06.1). Exit 0 done, 1 failed, 2 refused.')
    sub = parser.add_subparsers(dest='command', required=True)
    inst = sub.add_parser('install', help='init the root, acquire and verify the pinned binary, write app.ini')
    inst.add_argument('--from-file', type=Path, help='a local copy of the release asset (verified against the pin)')
    inst.add_argument('--port', type=int, default=DEFAULT_PORT)
    for name, text in (('up', 'start the managed environment and wait until Gitea answers'),
                       ('down', 'stop Gitea with its own manager shutdown, then the supervisor'),
                       ('status', 'report the processes, listeners, token and job; changes nothing'),
                       ('verify', 'run the F-06.1 proof set against the running instance'),
                       ('identities', 'create the site administrator and the Owner account (temporary passwords '
                                      'into the credential provider)'),
                       ('finalize-credentials', 'replace both temporary passwords with harness-held final ones '
                                                "through Gitea's forced change, revoke the accounts' tokens, verify, "
                                                'delete the temporary entries'),
                       ('supervise', 'internal: the managed environment process started by up')):
        sub.add_parser(name, help=text)
    args = parser.parse_args(argv)
    out = sys.stdout
    if hasattr(out, 'reconfigure'):
        out.reconfigure(encoding='utf-8')
    if os.name != 'nt':
        sys.stderr.write('gitea-host: REFUSED: host-loopback Gitea is implemented for Windows only\n')
        return 2
    try:
        res = paths.resolve()
        lay, pinned = layout(res), pin()
        if args.command == 'supervise':
            return supervise(res, lay, pinned)
        if args.command == 'install':
            report = install(res, lay, pinned, args.port, args.from_file)
        else:
            report = {'up': up, 'down': down, 'status': status, 'verify': verify,
                      'identities': create_identities, 'finalize-credentials': finalize_credentials}[args.command](
                res, lay, pinned)
    except paths.PathsError as exc:
        sys.stderr.write(f'gitea-host: {exc}\n')
        return 2
    except GiteaError as exc:
        sys.stderr.write(f'gitea-host: {exc}\n')
        return 2 if exc.refusal else 1
    out.write(json.dumps(report, indent=2, default=str) + '\n')
    return 1 if args.command == 'verify' and not report['passed'] else 0


if __name__ == '__main__':
    sys.exit(main())
