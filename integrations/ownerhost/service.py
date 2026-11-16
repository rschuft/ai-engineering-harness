"""The Integration process's lifecycle (plan leaf U-01.3; Proposed decision 0025 point 1; decision 0011's service verbs
through the platform contract of integrations/platform).

Verbs: ``up``, ``down``, ``restart``, ``status``, ``inspect``, ``verify``. There is no ``install``, ``upgrade``,
``uninstall`` or credential verb: the process runs from the checkout under the tools interpreter, and it is custodian
of no credential. Linux and macOS are ``PLATFORM_UNSUPPORTED``, as the contract answers today.

- ``up`` refuses a running environment (``ALREADY_RUNNING``) and a held port (``PORT_IN_USE``: 127.0.0.1:13310 is
  the only port; never another), then starts the managed environment through the platform adapter: a supervisor,
  detached with no window, that joins a new kill-on-close Job Object and starts the server process (app.py serve)
  inside it, with a minimal environment (``ENVIRONMENT_NAMES``: no credential, no proxy, no harness setting) and the
  managed root's ``<state>/owner-host`` and ``<logs>/owner-host``. It returns once the server listens; readiness is
  the kernel's TCP table read by process, never a request (the package opens no client socket).
- ``down`` writes the stop request the server watches for, waits on the processes themselves (bounded by a
  ceiling), and terminates the supervisor only if they have not ended; the job then ends the server.
- ``restart`` is the contract's, under a write-ahead transition record (``<state>/owner-host/transitions``).
- ``status`` and ``inspect`` change nothing. ``verify`` writes nothing and exits 0 only when its
  ``aieh-readiness/1`` record passes: the supervisor and the server run, the server runs in the supervision, it
  listens on 127.0.0.1:13310 and nowhere else, and nothing else holds that port.

Records: ``<state>/owner-host/run.json`` (``aieh-service-run/1``: the supervisor, the server, the job, the harness
commit and the tools lock digest, the configuration), ``<state>/owner-host/server.json`` (the server's own record:
its process, address, port, console window and its live import census), the conversation store beside them; logs in
``<logs>/owner-host/`` (``supervisor.log``, ``console.log``, ``service.log``).

  <tools python> -I -B integrations/ownerhost/service.py up|down|restart|status|inspect|verify

Exit 0 done, 1 failed (or verify did not pass), 2 refused (a stable code).
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(os.path.realpath(__file__)).parent
REPO = HERE.parents[1]


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


contract = _load('aieh_platform_contract', REPO / 'integrations' / 'platform' / 'platform_contract.py')
no_window = _load('aieh_no_window', REPO / 'integrations' / 'platform' / 'no_window.py')
paths = _load('aieh_paths', REPO / 'integrations' / 'paths' / 'aieh_paths.py')
APP = HERE / 'app.py'
app = _load('aieh_ownerhost_app', APP)       # the one declaration of the address and port

SERVICE = 'owner-host'
COMPONENT = 'owner-host'                     # <state>/owner-host, <logs>/owner-host
LOOPBACK = app.LOOPBACK
PORT = app.PORT                              # 13310: the network matrix's nm-owner-ui-integration, the host census
TOOLS_LOCK = REPO / 'composition' / 'lock' / 'python' / 'tools-requirements.txt'
READY_CEILING_S, STOP_CEILING_S = 30.0, 15.0
POLL_S = 0.1                                 # readiness poll interval; each wait is bounded by its ceiling
# The server process's whole environment: what Windows and the interpreter need, and nothing else.
ENVIRONMENT_NAMES = ('SYSTEMROOT', 'SYSTEMDRIVE', 'WINDIR', 'TEMP', 'TMP', 'PROCESSOR_ARCHITECTURE',
                     'NUMBER_OF_PROCESSORS')
RUN_FORMAT = contract.SERVICE_RUN_FORMAT

LifecycleError = contract.LifecycleError
REMEDIES = {
    'ALREADY_RUNNING': 'it already runs: use status, or down first',
    'PORT_IN_USE': f'stop what holds {LOOPBACK}:{PORT}: the Integration process uses this port only',
    'START_FAILED': 'see <logs>/owner-host/supervisor.log, console.log and service.log',
    'START_TIMEOUT': 'run down, then see <logs>/owner-host/console.log and service.log',
}


def refused(code: str, detail: str, *, refusal: bool = True) -> LifecycleError:
    return LifecycleError(code, detail, refusal=refusal, remedy=REMEDIES[code])


def now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


@dataclasses.dataclass(frozen=True)
class Layout:
    """The managed root's places for this service (decision 0009): its state and logs directories."""
    state: Path
    logs: Path

    @property
    def run_record(self) -> Path:
        return self.state / 'run.json'

    @property
    def server_record(self) -> Path:
        return self.state / 'server.json'

    @property
    def stop_request(self) -> Path:
        return self.state / 'stop-request'

    @property
    def transitions(self) -> Path:
        return self.state / 'transitions'

    @property
    def store(self) -> Path:
        return self.state / 'conversation.sqlite'


def layout(res) -> Layout:
    """``<state>/owner-host`` and ``<logs>/owner-host`` of the resolution RES, created if needed."""
    return Layout(paths.ensure('state', res, COMPONENT), paths.ensure('logs', res, COMPONENT))


def child_environment(environ) -> dict:
    """The server process's environment: only ENVIRONMENT_NAMES of ENVIRON (names compared case-insensitively)."""
    wanted = {name.upper() for name in ENVIRONMENT_NAMES}
    return {name: value for name, value in environ.items() if name.upper() in wanted}


def server_argv(lay: Layout, python: str = sys.executable) -> list[str]:
    return [python, '-I', '-B', str(APP), 'serve', '--state-dir', str(lay.state), '--logs-dir', str(lay.logs)]


def _write_json(path: Path, data: dict) -> None:
    partial = path.with_name(path.name + '.partial')
    partial.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
    os.replace(partial, path)


def _read_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def harness() -> dict:
    """The checkout this runs from: its commit (None outside a git checkout) and the tools lock's digest."""
    commit = None
    try:
        from dulwich.repo import Repo
        with Repo(str(REPO)) as repo:
            commit = repo.head().decode('ascii')
    except Exception:            # not a git checkout (an archive copy), or no HEAD: recorded as unknown
        commit = None
    lock = hashlib.sha256(TOOLS_LOCK.read_bytes()).hexdigest() if TOOLS_LOCK.is_file() else None
    return {'commit': commit, 'tools_lock_sha256': lock}


def configuration(lay: Layout) -> dict:
    """The process's whole configuration (its configuration snapshot): no credential, no secret-shaped value."""
    return {'address': LOOPBACK, 'port': PORT, 'state_dir': str(lay.state), 'logs_dir': str(lay.logs),
            'store': lay.store.name, 'environment_names': list(ENVIRONMENT_NAMES)}


# ---------------------------------------------------------------- the managed environment


def supervise(lay: Layout, adapter) -> int:
    """The managed environment: enter the adapter's supervision (Windows: a new kill-on-close job), start the
    server process in it, record both, and wait for the server. When this process ends, however it ends, the
    supervision ends the server."""
    job = adapter.enter_supervision()      # every process this one starts from now on is born inside it
    me = adapter.process(os.getpid())
    for stale in (lay.server_record, lay.stop_request):
        stale.unlink(missing_ok=True)
    record = {'format': RUN_FORMAT, 'service': SERVICE, 'version': None,
              'platform': {'asset_key': adapter.asset_key, 'supervision': adapter.supervision['mechanism']},
              'state': 'starting', 'port': PORT, 'address': LOOPBACK, 'started_at': now(),
              'supervisor': {'pid': me.pid, 'created': me.created(), 'image': me.image()},
              'job': job.report(), 'harness': harness(), 'configuration': configuration(lay),
              'console_window': _console_window()}
    _write_json(lay.run_record, record)
    with open(lay.logs / 'console.log', 'ab') as console:
        console.write(f'--- {now()} supervisor {me.pid} starting the Integration process\n'.encode())
        console.flush()
        child = subprocess.Popen(server_argv(lay), env=child_environment(os.environ), cwd=str(lay.state),
                                 stdin=subprocess.DEVNULL, stdout=console, stderr=console, close_fds=True,
                                 creationflags=no_window.no_window_flags())
        record['server_launch'] = {'pid': child.pid}
        _write_json(lay.run_record, record)
        deadline = time.monotonic() + READY_CEILING_S
        while child.poll() is None and time.monotonic() < deadline:
            server = _read_json(lay.server_record)
            if server and server.get('state') == 'listening':
                proc = adapter.process(server['pid'])
                record.update(state='running', server={'pid': proc.pid, 'created': proc.created(),
                                                       'image': proc.image(),
                                                       'in_supervisor_job': job.contains(proc.handle)})
                _write_json(lay.run_record, record)
                break
            time.sleep(POLL_S)  # the server's record is its readiness signal; the bound is the ceiling above
        code = child.wait()
        console.write(f'--- {now()} the Integration process exited {code}; supervisor {me.pid} exiting\n'.encode())
    record.update(state='stopped' if record['state'] == 'running' else 'failed', stopped_at=now(), server_exit=code)
    _write_json(lay.run_record, record)
    lay.stop_request.unlink(missing_ok=True)
    return 0


def _console_window() -> bool | None:
    if os.name != 'nt':
        return None
    import ctypes
    return bool(ctypes.WinDLL('kernel32').GetConsoleWindow())


def live(adapter, record: dict | None, role: str):
    if not record or not isinstance(record.get(role), dict):
        return None
    return adapter.process_maybe(record[role].get('pid'), record[role].get('created'))


def readiness_checks(adapter, record: dict | None) -> dict:
    """The readiness of the running environment, from the processes and the kernel's TCP table only."""
    supervisor, server = live(adapter, record, 'supervisor'), live(adapter, record, 'server')
    mine = [r for r in adapter.listeners(server.pid) if r['proto'] == 'tcp'] if server else []
    on_port = [r for r in adapter.listeners() if r['proto'] == 'tcp' and r['port'] == PORT]
    return {
        'supervisor_running': supervisor is not None,
        'server_running': server is not None,
        'server_supervised': bool(server and server.in_any_job() and record['server'].get('in_supervisor_job')),
        'listener_on_declared_port': bool(server) and [(r['address'], r['port']) for r in mine] == [(LOOPBACK, PORT)],
        'loopback_only': bool(server) and bool(mine) and all(r['address'] == LOOPBACK for r in mine)
                         and not [r for r in adapter.listeners(server.pid) if r['proto'] == 'udp'],
        'port_held_by_server': bool(server) and bool(on_port) and all(r['pid'] == server.pid for r in on_port),
    }


def status(lay: Layout, adapter) -> dict:
    record = contract.read_run_record(lay.run_record)
    supervisor, server = live(adapter, record, 'supervisor'), live(adapter, record, 'server')
    checks = readiness_checks(adapter, record)
    report = {'url': f'http://{LOOPBACK}:{PORT}/', 'running': bool(supervisor and server),
              'ready': all(checks.values()), 'record_state': (record or {}).get('state'),
              'supervisor': None, 'server': None, 'checks': checks,
              'port_listeners': [r for r in adapter.listeners() if r['proto'] == 'tcp' and r['port'] == PORT]}
    report['stale_record'] = report['record_state'] in ('starting', 'running') and not report['running']
    if supervisor:
        report['supervisor'] = {'pid': supervisor.pid, 'in_a_job': supervisor.in_any_job()}
    if server:
        report['server'] = {'pid': server.pid, 'image': server.image(), 'in_a_job': server.in_any_job(),
                            'in_supervisor_job_at_start': record['server'].get('in_supervisor_job'),
                            'listeners': adapter.listeners(server.pid), 'user': adapter.user_identity(server.pid)}
    return report


def up(lay: Layout, adapter, *, python: str = sys.executable) -> dict:
    record = contract.read_run_record(lay.run_record)
    if live(adapter, record, 'supervisor') or live(adapter, record, 'server'):
        raise refused('ALREADY_RUNNING', f'the managed environment runs (supervisor {record["supervisor"]["pid"]})')
    if adapter.port_in_use(PORT, LOOPBACK):
        raise refused('PORT_IN_USE', f'{LOOPBACK}:{PORT}, or the port on another address, is in use')
    lay.stop_request.unlink(missing_ok=True)
    argv = [python, '-I', '-B', str(Path(os.path.realpath(__file__))), 'supervise',
            '--state-dir', str(lay.state), '--logs-dir', str(lay.logs)]
    with open(lay.logs / 'supervisor.log', 'ab') as log:
        supervisor = adapter.launch_supervisor(argv, log, lay.state)
    deadline = time.monotonic() + READY_CEILING_S
    while True:
        report = status(lay, adapter)
        if report['ready']:
            report['launched'] = {'pid': supervisor.pid}
            return report
        if supervisor.poll() is not None:
            raise refused('START_FAILED', f'the supervisor exited {supervisor.returncode}', refusal=False)
        if time.monotonic() > deadline:
            raise refused('START_TIMEOUT', f'not ready within {READY_CEILING_S:.0f}s', refusal=False)
        time.sleep(POLL_S)  # readiness poll interval; the bound is the ceiling above


def down(lay: Layout, adapter) -> dict:
    record = contract.read_run_record(lay.run_record)
    supervisor, server = live(adapter, record, 'supervisor'), live(adapter, record, 'server')
    if supervisor is None and server is None:
        return {'stopped': False, 'detail': 'not running', 'port_open': adapter.port_in_use(PORT, LOOPBACK)}
    lay.stop_request.write_text(f'{now()}\n', encoding='utf-8')
    method = 'stop request'
    deadline = time.monotonic() + STOP_CEILING_S
    # each wait is on the process itself (its own completion signal), bounded by what is left of the ceiling
    if not all(proc is None or proc.wait(max(0.0, deadline - time.monotonic())) for proc in (server, supervisor)):
        method = 'not stopped within the ceiling; supervisor terminated (the job ends the server)'
        (supervisor or server).terminate()
        for proc in (server, supervisor):
            if proc is not None:
                proc.wait(STOP_CEILING_S)
    lay.stop_request.unlink(missing_ok=True)
    return {'stopped': True, 'method': method,
            'server_alive': bool(server and server.alive()), 'supervisor_alive': bool(supervisor and supervisor.alive()),
            'port_open': adapter.port_in_use(PORT, LOOPBACK)}


class Operations(contract.ServiceOperations):
    """What the contract's restart needs: observe, stop, start, ready."""

    def __init__(self, lay: Layout, adapter):
        self.lay, self.adapter = lay, adapter

    def _version(self):
        return harness()['commit'] or 'checkout'

    def observe(self) -> dict:
        report = status(self.lay, self.adapter)
        version = self._version()
        return {'running': report['running'], 'ready': report['ready'],
                'running_version': version if report['running'] else None, 'desired_version': version}

    def stop(self) -> dict:
        return down(self.lay, self.adapter)

    def start(self, version=None) -> dict:
        return {'ready': up(self.lay, self.adapter)['ready']}

    def ready(self, version=None) -> bool:
        return status(self.lay, self.adapter)['ready']


def restart(lay: Layout, adapter) -> dict:
    log = contract.TransitionLog(lay.transitions, SERVICE, adapter.asset_key)
    log.refuse_if_pending()
    return contract.restart(log, Operations(lay, adapter))


def readiness(lay: Layout, adapter) -> dict:
    return contract.readiness_record(SERVICE, adapter, readiness_checks(adapter, contract.read_run_record(
        lay.run_record)))


def inspect(lay: Layout, adapter) -> dict:
    log = contract.TransitionLog(lay.transitions, SERVICE, adapter.asset_key)
    return {'platform': adapter.record(), 'status': status(lay, adapter), 'readiness': readiness(lay, adapter),
            'run_record': contract.read_run_record(lay.run_record), 'server_record': _read_json(lay.server_record),
            'configuration': configuration(lay), 'latest_transition': log.latest()}


def main(argv=None, *, config=None) -> int:
    """The lifecycle command. CONFIG is passed to the managed-root resolver (None: the checkout's config.yml)."""
    parser = argparse.ArgumentParser(prog='service.py', description='The Integration process (U-01.3) through the '
                                     'host-service lifecycle contract. Exit 0 done, 1 failed, 2 refused.')
    sub = parser.add_subparsers(dest='command', required=True)
    for name, text in (('up', 'start the managed environment and wait until the server listens'),
                       ('down', 'ask the server to stop, then the supervisor; terminating it ends the server'),
                       ('restart', 'down (when running) and up again, under a write-ahead transition record'),
                       ('status', 'report the processes, listeners and job; changes nothing'),
                       ('inspect', 'report the platform, records, configuration and readiness; changes nothing'),
                       ('verify', 'print the aieh-readiness/1 record; exit 0 only when it passes')):
        sub.add_parser(name, help=text)
    sup = sub.add_parser('supervise', help='internal: the managed environment process started by up')
    sup.add_argument('--state-dir', required=True, type=Path)
    sup.add_argument('--logs-dir', required=True, type=Path)
    args = parser.parse_args(argv)
    out = sys.stdout
    if hasattr(out, 'reconfigure'):
        out.reconfigure(encoding='utf-8')
    try:
        adapter = contract.select_adapter()
        if args.command == 'supervise':
            return supervise(Layout(args.state_dir, args.logs_dir), adapter)
        lay = layout(paths.resolve(config=config))
        report = {'up': up, 'down': down, 'restart': restart, 'status': status, 'inspect': inspect,
                  'verify': readiness}[args.command](lay, adapter)
    except LifecycleError as exc:
        sys.stderr.write(f'owner-host: {exc}\n')
        return 2 if exc.refusal else 1
    except paths.PathsError as exc:
        sys.stderr.write(f'owner-host: {exc}\n')
        return 2
    out.write(json.dumps(report, indent=2) + '\n')
    return 0 if args.command != 'verify' or report['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
