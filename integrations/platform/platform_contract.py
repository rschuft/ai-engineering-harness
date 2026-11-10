"""The host-service lifecycle contract (plan leaf F-06.2; the accepted cross-platform lifecycle design,
draft decision 0011): platform-neutral Python, standard library only.

A host service of the harness (today Gitea, integrations/gitea/gitea_host.py) is driven through one set of
verbs. Each verb's result and record shape and each refusal code is defined here, once, for every
platform:

- service: install, up, down, restart, status, inspect, verify;
- credentials: provision, rotate, retire;
- transitions: upgrade, recover, uninstall.

A platform adapter supplies only what differs per operating system: supervised start and stop and the
managed environment's liveness, process identity, listeners, user identity, the verified-bytes guarantee
and the credential provider. Windows is platform_windows.py (a Job Object with kill-on-close; the TCP
table and the process token; Credential Manager). Linux and macOS follow in F-06.4 and F-06.5: until
then select_adapter refuses them with PLATFORM_UNSUPPORTED. Nothing here names PowerShell, a Windows
path form, a Job Object, Credential Manager, /proc or launchctl.

Records:
- aieh-platform/1: system, machine, asset_key, supervision, credentials (platform_record);
- aieh-asset/1: the managed root's asset record (integrations/paths, decision 0009), re-exported;
- aieh-service-run/1: the managed environment's run record; it generalises aieh-gitea-run/1, which
  readers still accept (RUN_FORMATS);
- aieh-readiness/1: a service's readiness, with platform-neutral check names, each record carrying its
  platform (readiness_record);
- aieh-service-transition/1: the write-ahead record of a transition (TransitionLog).

Credential invariants I1-I8 bind every act: a secret is (1) never printed, logged, on a command line or
in an environment variable; (2) one named entry per credential; (3) stored before the upstream change;
(4) every act can be rerun and resumes; (5) the harness fails closed; (6) the backend is chosen by the
harness; (7) a no-exposure scan follows every act (ExposureGuard); (8) reports carry fingerprints only.
"""
from __future__ import annotations

import datetime
import hashlib
import importlib.util
import json
import os
import platform as _platform
import re
import secrets
import sys
from pathlib import Path
from typing import Callable, Iterable

HERE = Path(os.path.realpath(__file__)).parent

VERBS = ('install', 'up', 'down', 'restart', 'status', 'inspect', 'verify',
         'provision', 'rotate', 'retire',
         'upgrade', 'recover', 'uninstall')
SERVICE_VERBS, CREDENTIAL_VERBS, TRANSITION_VERBS = VERBS[:7], VERBS[7:10], VERBS[10:]

PLATFORM_FORMAT = 'aieh-platform/1'
ASSET_FORMAT = 'aieh-asset/1'
SERVICE_RUN_FORMAT = 'aieh-service-run/1'
LEGACY_RUN_FORMATS = ('aieh-gitea-run/1',)
RUN_FORMATS = (SERVICE_RUN_FORMAT, *LEGACY_RUN_FORMATS)
READINESS_FORMAT = 'aieh-readiness/1'
TRANSITION_FORMAT = 'aieh-service-transition/1'

# The refusal codes this contract adds, each with its remedy. A component's existing codes are kept as
# they are; a LifecycleError of one of these codes carries its remedy in its message.
REMEDIES = {
    'PLATFORM_UNSUPPORTED': 'run it on a platform that has an adapter: Windows only today (Linux and macOS '
                            'follow in plan leaves F-06.4 and F-06.5)',
    'PLATFORM_MISMATCH': 'this installation was made for another platform; install anew on this platform '
                         'under its own managed data root (nothing is converted in place)',
    'SUPERVISION_UNAVAILABLE': "the platform's supervision mechanism could not be set up; run from an "
                               'ordinary signed-in user session of this platform, where it is available',
    'NO_CREDENTIAL_PROVIDER': 'no qualified credential provider exists on this platform and the harness never '
                              "falls back to a file or plaintext: provide the platform's credential store "
                              '(an Owner act)',
    'CREDENTIAL_PROVIDER_LOCKED': "the platform's credential store is not available to this session; sign in "
                                  'to (or unlock) the user session that owns the entries, then rerun',
    'VERSION_MISMATCH': 'the requested, desired and running versions do not agree with the pins: pin the '
                        'version in composition/lock/components.lock.json first, or run recover to '
                        'reconcile the running version with the desired one',
    'DOWNGRADE_REFUSED': 'a downgrade is never automatic: it is a restore from a transition backup by an '
                         'Owner decision',
    'TRANSITION_PENDING': 'run recover: it reconciles the actual state with the pending transition record '
                          'before anything else happens',
    'UNINSTALL_RUNNING': 'run down first; uninstall never stops a running service',
    'EXPOSURE_FOUND': 'the output was withheld: treat every credential the act held as exposed and rotate it',
}


class LifecycleError(Exception):
    """A refusal (exit 2) or a failure (exit 1) with a stable code. A code of REMEDIES carries its
    remedy; the message of every other code is unchanged: 'CODE: detail'."""

    def __init__(self, code: str, detail: str, *, refusal: bool = True, remedy: str | None = None):
        self.code, self.detail, self.refusal = code, detail, refusal
        self.remedy = remedy if remedy is not None else REMEDIES.get(code)
        super().__init__(f'{code}: {detail}' + (f' (remedy: {self.remedy})' if self.remedy else ''))


def now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


# ---------------------------------------------------------------- the platform record

SYSTEMS = {'Windows': 'windows', 'Linux': 'linux', 'Darwin': 'darwin'}
MACHINES = {'amd64': 'amd64', 'x86_64': 'amd64', 'x64': 'amd64', 'arm64': 'arm64', 'aarch64': 'arm64'}


def asset_key(system: str, machine: str) -> str:
    """The platform part of a release asset's name: windows-amd64, linux-arm64, darwin-arm64, ..."""
    os_key, cpu = SYSTEMS.get(system), MACHINES.get(str(machine).lower())
    if os_key is None or cpu is None:
        raise LifecycleError('PLATFORM_UNSUPPORTED', f'no asset key for system {system!r}, machine {machine!r}')
    return f'{os_key}-{cpu}'


def platform_record(adapter) -> dict:
    """aieh-platform/1: what the adapter is, how it supervises and where it keeps credentials."""
    return {'format': PLATFORM_FORMAT, 'system': adapter.system, 'machine': adapter.machine,
            'asset_key': adapter.asset_key, 'supervision': dict(adapter.supervision),
            'credentials': dict(adapter.credentials)}


def check_asset_key(recorded, adapter) -> None:
    """PLATFORM_MISMATCH when a record names another platform's asset key; an absent key (a record
    written before F-06.2) is accepted."""
    if recorded is not None and recorded != adapter.asset_key:
        raise LifecycleError('PLATFORM_MISMATCH', f'the record names {recorded!r}; this host is '
                                                  f'{adapter.asset_key!r}')


# ---------------------------------------------------------------- credentials


class CredentialProvider:
    """Where the harness keeps service credentials, by entry name: get, set, delete, exists. A secret is a
    str held in memory; an implementation never prints or logs it. The adapter supplies the platform's
    implementation (Windows: Credential Manager); the harness, never the environment, chooses it (I6)."""

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


def fingerprint(secret: str) -> str:
    """What reports carry instead of a secret (I8): a 16-hex-digit prefix of its sha256."""
    return 'sha256:' + hashlib.sha256(secret.encode('utf-8')).hexdigest()[:16]


# A Gitea access token's shape: exactly 40 lowercase hex digits, not part of a longer hex run (a sha256
# of 64 digits is not one).
TOKEN_SHAPE = re.compile(r'(?<![0-9a-fA-F])[0-9a-f]{40}(?![0-9a-fA-F])')


class ExposureGuard:
    """I7: the no-exposure scan that follows every act. The act's secrets are held here in memory only
    (hold, or a WatchedProvider); after the act, scan_text searches what the act is about to show (its
    report and its messages) for each secret, as UTF-8 and as UTF-16LE, and for anything shaped like an
    access token; scan_files searches listed files. Results are names and counts, never content (I8);
    clear() forgets every secret."""

    def __init__(self):
        self._needles: list[bytes] = []
        self.scanned: list[str] = []
        self.found: list[str] = []
        self.unreadable: list[str] = []

    def hold(self, secret) -> None:
        if isinstance(secret, str):
            secret = secret.encode('utf-8')
        if secret and secret not in self._needles:
            self._needles.append(bytes(secret))

    @property
    def held(self) -> int:
        return len(self._needles)

    def _forms(self) -> list[bytes]:
        return [form for n in self._needles for form in (n, n.decode('utf-8', 'replace').encode('utf-16-le'))]

    def scan_text(self, name: str, text, *, token_shape: bool = True) -> bool:
        """True when text holds no secret and nothing token-shaped; the name is recorded either way."""
        data = text.encode('utf-8') if isinstance(text, str) else bytes(text)
        hit = any(form in data for form in self._forms())
        if token_shape and TOKEN_SHAPE.search(data.decode('utf-8', 'replace')):
            hit = True
        self.scanned.append(name)
        if hit:
            self.found.append(name)
        return not hit

    def scan_files(self, files: Iterable[Path]) -> None:
        """Each listed file, for the held secrets only (a checkout legitimately holds 40-hex commit names)."""
        forms = self._forms()
        for path in files:
            try:
                data = Path(path).read_bytes()
            except FileNotFoundError:
                continue
            except OSError as exc:
                self.unreadable.append(f'{path} (file not read: {type(exc).__name__})')
                continue
            self.scanned.append(str(path))
            if forms and any(form in data for form in forms):
                self.found.append(str(path))

    def report(self) -> dict:
        return {'invariant': 'I7', 'secrets_held': self.held, 'scanned': len(self.scanned),
                'found_in': list(self.found), 'unreadable': list(self.unreadable),
                'clean': not self.found and not self.unreadable}

    def clear(self) -> None:
        self._needles.clear()


class WatchedProvider(CredentialProvider):
    """A provider whose every secret read or written is held by an ExposureGuard, so the scan that follows
    the act knows what to look for without the act having to name it."""

    def __init__(self, provider: CredentialProvider, guard: ExposureGuard):
        self.provider, self.guard = provider, guard

    def get(self, name):
        entry = self.provider.get(name)
        if entry is not None:
            self.guard.hold(entry[1])
        return entry

    def set(self, name, user, secret, comment=''):
        self.guard.hold(secret)
        self.provider.set(name, user, secret, comment)

    def delete(self, name):
        return self.provider.delete(name)

    def exists(self, name):
        return self.provider.exists(name)


# ---------------------------------------------------------------- the adapter interface


class PlatformAdapter:
    """What one operating system supplies to the contract. Attributes: system, machine, asset_key,
    supervision (mechanism and how 'the managed environment shuts down' maps onto it), credentials (the
    provider and its mechanism), verified_bytes (the verified-bytes guarantee level)."""
    system = machine = asset_key = verified_bytes = ''
    supervision: dict = {}
    credentials: dict = {}

    def record(self) -> dict:
        return platform_record(self)

    # supervised start and stop, and the managed environment's liveness
    def launch_supervisor(self, argv: list[str], log, cwd: Path):
        """Start the managed environment's supervisor detached from the caller; returns a Popen."""
        raise NotImplementedError

    def enter_supervision(self):
        """In the supervisor: make every process it starts from now on end with it. Returns an object
        with report() (the record's 'job' entry) and contains(process_handle)."""
        raise NotImplementedError

    # process identity
    def process(self, pid: int):
        raise NotImplementedError

    def process_maybe(self, pid, created):
        """The live process with this id and identity (creation time), else None."""
        raise NotImplementedError

    # listeners and user identity
    def listeners(self, pid: int | None = None) -> list[dict]:
        raise NotImplementedError

    def port_in_use(self, port: int, address: str) -> bool:
        raise NotImplementedError

    def user_identity(self, pid: int) -> dict:
        raise NotImplementedError

    # the verified-bytes guarantee
    def locked_read(self, path: Path):
        """A context manager yielding a binary read stream of path."""
        raise NotImplementedError

    # credentials
    def credential_provider(self) -> CredentialProvider:
        raise LifecycleError('NO_CREDENTIAL_PROVIDER', f'{self.system} has no credential provider')


def _load(name: str, path: Path):
    if (module := sys.modules.get(name)) is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = sys.modules[name] = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except BaseException:
            del sys.modules[name]
            raise
    return module


ADAPTERS = {'Windows': ('aieh_platform_windows', 'platform_windows.py', 'WindowsAdapter')}


def select_adapter(system: str | None = None, machine: str | None = None) -> PlatformAdapter:
    """This host's adapter, chosen by the harness from the running system (never from configuration or
    the environment); PLATFORM_UNSUPPORTED where none exists yet."""
    system = system or _platform.system()
    machine = machine or _platform.machine()
    if system not in ADAPTERS:
        raise LifecycleError('PLATFORM_UNSUPPORTED', f'no lifecycle adapter for {system!r}: host services run '
                                                     'on Windows only until the Linux and macOS adapters exist')
    module_name, file_name, class_name = ADAPTERS[system]
    module = _load(module_name, HERE / file_name)
    return getattr(module, class_name)(machine)


# ---------------------------------------------------------------- run and readiness records


def read_run_record(path: Path) -> dict | None:
    """The managed environment's run record, aieh-service-run/1 or the legacy aieh-gitea-run/1; None when
    absent or of another format. RUN_RECORD_INVALID when it cannot be read."""
    try:
        record = json.loads(Path(path).read_text(encoding='utf-8'))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        raise LifecycleError('RUN_RECORD_INVALID', f'{path} is unreadable') from None
    return record if isinstance(record, dict) and record.get('format') in RUN_FORMATS else None


# Words that name a platform mechanism: a readiness check name holding one is not platform-neutral.
PLATFORM_WORDS = ('windows', 'win32', 'linux', 'darwin', 'macos', 'job', 'token', 'proc', 'pid', 'systemd',
                  'launchd', 'launchctl', 'credential_manager', 'keychain', 'registry', 'powershell', 'lsof')
CHECK_NAME = re.compile(r'[a-z][a-z0-9_]*')


def readiness_record(service: str, adapter, checks: dict, *, checked_at: str | None = None) -> dict:
    """aieh-readiness/1: the service's checks under platform-neutral names, with the platform they ran on."""
    for name, value in checks.items():
        if not CHECK_NAME.fullmatch(name) or any(word in name for word in PLATFORM_WORDS):
            raise LifecycleError('CHECK_NAME_NOT_NEUTRAL', f'{name!r} names a platform mechanism', refusal=False)
        if not isinstance(value, bool):
            raise LifecycleError('CHECK_NOT_BOOLEAN', f'{name!r} is {type(value).__name__}', refusal=False)
    return {'format': READINESS_FORMAT, 'service': service, 'platform': platform_record(adapter),
            'checked_at': checked_at or now(), 'checks': dict(checks), 'passed': all(checks.values())}


# ---------------------------------------------------------------- versions


VERSION_SHAPE = re.compile(r'\d+(\.\d+){1,3}')


def parse_version(text: str) -> tuple[int, ...]:
    if not isinstance(text, str) or not VERSION_SHAPE.fullmatch(text):
        raise LifecycleError('VERSION_MISMATCH', f'{text!r} is not a release version (digits and dots)')
    return tuple(int(part) for part in text.split('.'))


def plan_upgrade(*, desired: str, running: str | None, target: str, pinned: Iterable[str]) -> str:
    """'noop' when target is already the desired version, else 'upgrade'. Refuses a target without a pin
    and a running version that is not the desired one (VERSION_MISMATCH), and a lower target
    (DOWNGRADE_REFUSED). Desired, staged and running versions are kept distinct: only the transition
    changes the desired one."""
    pinned = set(pinned)
    if target not in pinned:
        raise LifecycleError('VERSION_MISMATCH', f'{target} has no pin (pinned: {sorted(pinned)})')
    if running is not None and running != desired:
        raise LifecycleError('VERSION_MISMATCH', f'the running version {running} is not the desired {desired}')
    if parse_version(target) < parse_version(desired):
        raise LifecycleError('DOWNGRADE_REFUSED', f'{target} is lower than the desired version {desired}')
    return 'noop' if target == desired else 'upgrade'


# ---------------------------------------------------------------- transitions


TRANSITION_STATES = ('pending', 'completed', 'rolled-back', 'failed')


class TransitionLog:
    """aieh-service-transition/1 records, one file per transition in one directory, written before any
    process is replaced (write-ahead) and updated after each step by an atomic replace. Nothing is ever
    deleted. At most one transition is pending; begin refuses another with TRANSITION_PENDING."""

    def __init__(self, directory: Path, service: str, platform_key: str):
        self.directory, self.service, self.platform_key = Path(directory), service, platform_key

    def records(self) -> list[dict]:
        if not self.directory.is_dir():
            return []
        out = []
        for path in sorted(self.directory.glob('*.json')):
            try:
                record = json.loads(path.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                raise LifecycleError('TRANSITION_RECORD_INVALID', f'{path} is unreadable', refusal=False) from None
            if not isinstance(record, dict) or record.get('format') != TRANSITION_FORMAT:
                raise LifecycleError('TRANSITION_RECORD_INVALID', f'{path} is not {TRANSITION_FORMAT}',
                                     refusal=False)
            out.append(record)
        return sorted(out, key=lambda r: (r.get('started_at', ''), r.get('id', '')))

    def pending(self) -> dict | None:
        pending = [r for r in self.records() if r.get('state') == 'pending']
        if len(pending) > 1:
            raise LifecycleError('TRANSITION_RECORD_INVALID', f'{len(pending)} transitions are pending',
                                 refusal=False)
        return pending[0] if pending else None

    def latest(self) -> dict | None:
        records = self.records()
        return records[-1] if records else None

    def refuse_if_pending(self) -> None:
        if (record := self.pending()) is not None:
            raise LifecycleError('TRANSITION_PENDING', f'{record["verb"]} {record["id"]} started at '
                                                       f'{record["started_at"]} is pending')

    def _path(self, record: dict) -> Path:
        return self.directory / f'{record["id"]}.json'

    def _write(self, record: dict, *, create: bool = False) -> None:
        path = self._path(record)
        if create:
            self.directory.mkdir(parents=True, exist_ok=True)
            with open(path, 'x', encoding='utf-8') as handle:
                handle.write(json.dumps(record, indent=2) + '\n')
            return
        partial = path.with_name(path.name + '.partial')
        partial.write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
        os.replace(partial, path)

    def begin(self, verb: str, versions: dict, **facts) -> dict:
        if verb not in VERBS:
            raise LifecycleError('VERB_UNKNOWN', f'{verb!r} is not a lifecycle verb', refusal=False)
        self.refuse_if_pending()
        stamp = now()
        record = {'format': TRANSITION_FORMAT, 'service': self.service, 'platform': {'asset_key': self.platform_key},
                  'id': f'{stamp.replace("-", "").replace(":", "")}-{verb}-{secrets.token_hex(4)}', 'verb': verb,
                  'state': 'pending', 'started_at': stamp,
                  'versions': {k: versions.get(k) for k in ('desired', 'staged', 'running', 'target')},
                  'facts': facts, 'steps': []}
        self._write(record, create=True)
        return record

    def step(self, record: dict, name: str, **facts) -> dict:
        record['steps'].append({'step': name, 'at': now(), **facts})
        self._write(record)
        return record

    def finish(self, record: dict, state: str, **facts) -> dict:
        if state not in TRANSITION_STATES[1:]:
            raise LifecycleError('TRANSITION_STATE_UNKNOWN', state, refusal=False)
        record.update(state=state, finished_at=now(), **facts)
        self._write(record)
        return record


def done_steps(record: dict) -> list[str]:
    return [s['step'] for s in record.get('steps', [])]


class ServiceOperations:
    """What a service supplies to the transition verbs. Each operation acts on the service as it is; the
    orchestration below decides the order and records each step."""

    def observe(self) -> dict:
        """{'running': bool, 'ready': bool, 'running_version': str | None, 'desired_version': str}"""
        raise NotImplementedError

    def stop(self) -> dict:
        raise NotImplementedError

    def start(self, version: str | None = None) -> dict:
        raise NotImplementedError

    def ready(self, version: str | None = None) -> bool:
        raise NotImplementedError

    def stage(self, version: str) -> dict:
        raise NotImplementedError

    def backup(self, transition_id: str) -> dict:
        raise NotImplementedError

    def restore(self, transition_id: str) -> dict:
        raise NotImplementedError

    def set_desired(self, version: str) -> dict:
        raise NotImplementedError

    def pinned_versions(self) -> list[str]:
        raise NotImplementedError

    def remove_ephemeral(self) -> dict:
        raise NotImplementedError

    def retained(self) -> dict:
        raise NotImplementedError


def restart(log: TransitionLog, ops: ServiceOperations) -> dict:
    """Stop (when running) and start again under a transition record; recover resumes an interrupted one."""
    state = ops.observe()
    record = log.begin('restart', {'desired': state['desired_version'], 'running': state['running_version']},
                       was_running=state['running'])
    if state['running']:
        log.step(record, 'stopped', result=ops.stop())
    return _finish_restart(log, ops, record)


def _finish_restart(log, ops, record) -> dict:
    """From any point after the record: stop what still runs of an unfinished stop, then start, then
    check readiness. A service found running and ready after its start step is reconciled as is."""
    state = ops.observe()
    if 'started' in done_steps(record) and state['running'] and ops.ready():
        return log.finish(record, 'completed')
    if state['running']:
        log.step(record, 'stopped', result=ops.stop())
    log.step(record, 'started', result=ops.start())
    if not ops.ready():
        log.finish(record, 'failed', reason='not ready after the start')
        raise LifecycleError('RESTART_NOT_READY', f'transition {record["id"]}: the service is not ready',
                             refusal=False)
    return log.finish(record, 'completed')


def upgrade(log: TransitionLog, ops: ServiceOperations, target: str) -> dict:
    """upgrade --to TARGET: stage the pinned asset, stop, back up the state, make TARGET desired, start it
    and check readiness. A failure before readiness is confirmed rolls back automatically (stop, restore
    the backup, the previous version desired again, start it); after that, going back is an Owner
    decision (DOWNGRADE_REFUSED for an automatic one)."""
    state = ops.observe()
    log.refuse_if_pending()
    kind = plan_upgrade(desired=state['desired_version'], running=state['running_version'], target=target,
                        pinned=ops.pinned_versions())
    if kind == 'noop':
        return {'upgrade': 'noop', 'version': target, 'running': state['running']}
    record = log.begin('upgrade', {'desired': state['desired_version'], 'running': state['running_version'],
                                   'target': target}, was_running=state['running'], previous=state['desired_version'])
    return _continue_upgrade(log, ops, record)


def _continue_upgrade(log, ops, record) -> dict:
    target, previous = record['versions']['target'], record['facts']['previous']
    steps = done_steps(record)
    try:
        if 'staged' not in steps:
            log.step(record, 'staged', result=ops.stage(target))
            record['versions']['staged'] = target
        if 'stopped' not in steps and ops.observe()['running']:
            log.step(record, 'stopped', result=ops.stop())
        if 'backed-up' not in steps:
            log.step(record, 'backed-up', result=ops.backup(record['id']))
        if 'desired-set' not in steps:
            log.step(record, 'desired-set', result=ops.set_desired(target))
            record['versions']['desired'] = target
        if 'started' not in steps:
            log.step(record, 'started', result=ops.start(target))
        if not ops.ready(target):
            raise LifecycleError('UPGRADE_NOT_READY', f'{target} did not become ready', refusal=False)
        log.step(record, 'verified')
    except Exception as exc:
        return _rollback(log, ops, record, previous, exc)
    record['versions']['running'] = target
    return log.finish(record, 'completed')


def _rollback(log, ops, record, previous, cause) -> dict:
    """Automatic rollback before verification: only to the transition backup."""
    reason = f'{getattr(cause, "code", type(cause).__name__)}: {getattr(cause, "detail", cause)}'
    log.step(record, 'rollback-started', reason=reason)
    if ops.observe()['running']:
        log.step(record, 'rollback-stopped', result=ops.stop())
    if 'backed-up' in done_steps(record):
        log.step(record, 'restored', result=ops.restore(record['id']))
    log.step(record, 'desired-reset', result=ops.set_desired(previous))
    record['versions']['desired'] = previous
    if record['facts'].get('was_running'):
        log.step(record, 'rollback-started-previous', result=ops.start(previous))
        if not ops.ready(previous):
            log.finish(record, 'failed', reason=reason, rollback='the previous version is not ready')
            raise LifecycleError('ROLLBACK_NOT_READY', f'transition {record["id"]}: the previous version '
                                                       f'{previous} is not ready after the rollback', refusal=False)
    return log.finish(record, 'rolled-back', reason=reason)


def uninstall(log: TransitionLog, ops: ServiceOperations) -> dict:
    """Refuses a running service; removes only ephemeral state; deletes nothing under persistent/ and no
    asset, and reports what it leaves."""
    state = ops.observe()
    if state['running']:
        raise LifecycleError('UNINSTALL_RUNNING', 'the managed environment runs')
    record = log.begin('uninstall', {'desired': state['desired_version'], 'running': None})
    return _continue_uninstall(log, ops, record)


def _continue_uninstall(log, ops, record) -> dict:
    if 'ephemeral-removed' not in done_steps(record):
        log.step(record, 'ephemeral-removed', result=ops.remove_ephemeral())
    return log.finish(record, 'completed', retained=ops.retained())


def recover(log: TransitionLog, ops: ServiceOperations) -> dict:
    """Reconcile the actual state first, then resume or roll back the pending transition from its record.
    With nothing pending it only reports the reconciled state."""
    state = ops.observe()
    record = log.pending()
    if record is None:
        return {'pending': None, 'observed': state}
    log.step(record, 'recover-observed', observed=state)
    verb = record['verb']
    if verb == 'restart':
        result = _finish_restart(log, ops, record)
    elif verb == 'upgrade':
        target = record['versions']['target']
        if 'verified' in done_steps(record) or (state['running'] and state['running_version'] == target
                                                and 'desired-set' in done_steps(record) and ops.ready(target)):
            record['versions']['running'] = target
            result = log.finish(record, 'completed', reconciled='the target version runs and is ready')
        else:
            result = _rollback(log, ops, record, record['facts']['previous'],
                               LifecycleError('INTERRUPTED', 'the upgrade was interrupted before verification'))
    elif verb == 'uninstall':
        if state['running']:
            raise LifecycleError('UNINSTALL_RUNNING', f'transition {record["id"]}: the managed environment runs')
        result = _continue_uninstall(log, ops, record)
    else:
        raise LifecycleError('TRANSITION_RECORD_INVALID', f'no recovery for {verb!r}', refusal=False)
    return {'pending': record['id'], 'verb': verb, 'observed': state, 'transition': result}
