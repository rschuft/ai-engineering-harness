"""Qualification-only commands of the inference broker (plan leaf S-03.2, slice 4; decision 0015 sections 2 and 6
as amended; the Overseer's ruling on the synthetic-key launcher, evidence/S-03.2-plan-amendment-proposal-child-
clause.md section 5). Neither is a production path. Running either is part of the Owner's act A2.

- broker: the qualification launcher. It starts the broker of inference_broker.py through the broker's own
  command line (main(['serve'], context)) with a synthetic provider key held in memory, so that a qualification
  against a fake upstream can show the key substituted for the attempt token and give the provider-key needle a
  fingerprint. Its four constraints:
  1. it refuses to start unless every configured family's upstream is plain http to a loopback IP literal
     (Origin.loopback) and at least one of them is keyed to --provider; the broker then serves exactly that
     configuration, read once;
  2. the key comes from standard input only (a terminal is refused) and must be a synthetic key: the prefix
     aieh-qualification-synthetic- and 16 to 128 URL-safe characters, sent upstream verbatim, prefix included,
     so a real provider key is refused as it is and invalid at its provider with the prefix added;
  3. the broker's start receipt (aieh-inference-broker-start/1) records the key's fingerprint with the source
     stdin-qualification (the name of this command's credential provider), never the key;
  4. it is a separately named command: serve has no flag or variable for it, the harness's credential factory
     (credentials.select_provider) never returns its provider, and that provider writes nothing (set and delete
     refuse).
  The broker's receipts and audit lines go where serve writes them (the managed integration store and logs);
  the key is written nowhere.
- fake-upstream: one declared family's fake provider on a loopback IPv4 address (127.0.0.1 by default) and the
  given port, and no other address. A request on one of the family's declared routes is answered with one fixed,
  well-formed answer that is not a model's (the family's JSON shape with the usage counts 1 and 1, which the
  broker's usage extractor reads); anything else is answered 404, a body without a length 411. It writes one JSON
  line per request to standard output: the method, the path (a declared route only), the header names, and the
  fingerprints of the values of the family's auth header; never a header value or a body. The qualification
  compares that fingerprint with the provider key's in the broker's start receipt.

  <synthetic key> | <tools python> -I -B integrations/inference/inference_qualification.py broker --provider ID
  <tools python> -I -B integrations/inference/inference_qualification.py fake-upstream --family ID --port PORT

Exit 0 done, 1 failed, 2 refused (a stable code). Standard library only.
"""
from __future__ import annotations

import argparse
import copy
import dataclasses
import http.server
import importlib.util
import ipaddress
import json
import os
import re
import socket
import socketserver
import sys
import threading
import types
from pathlib import Path

HERE = Path(os.path.realpath(__file__)).parent


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


broker = _load('aieh_inference_broker', HERE / 'inference_broker.py')
contract = broker.contract

KEY_SOURCE = 'stdin-qualification'
SYNTHETIC_PREFIX = 'aieh-qualification-synthetic-'
SYNTHETIC_SHAPE = re.compile(re.escape(SYNTHETIC_PREFIX) + r'[A-Za-z0-9_-]{16,128}')
FAKE_FORMAT = 'aieh-inference-fake-upstream/1'
FAKE_TEXT = 'aieh fake upstream: a fixed answer, not a model'
FAKE_BODY_LIMIT = 256 * broker.MIB
CODES = {
    'QUALIFICATION_UPSTREAM_REFUSED': 'give every configured family an upstream of plain http to a loopback IP '
                                      'literal (a fake upstream): the qualification launcher never reaches a '
                                      'provider',
    'QUALIFICATION_NO_FAMILY': 'configure at least one family with this provider id and a loopback http upstream',
    'KEY_NOT_SYNTHETIC': f'pipe a synthetic key: {SYNTHETIC_PREFIX} and 16 to 128 letters, digits, "_" or "-"; '
                         'a real provider key is never used here',
    'KEY_NEVER_WRITTEN': 'nothing to do: the synthetic key is held in memory only',
    'FAKE_FAMILY_UNKNOWN': 'name a family declared in integrations/inference/families.json',
    'FAKE_ADDRESS_REFUSED': 'serve the fake upstream on a loopback IPv4 address (127.0.0.1)',
    'FAKE_PORT_INVALID': 'give the port as an integer from 1024 to 65535',
}


class QualificationError(Exception):
    """A refusal (exit 2) with a stable code of CODES and its remedy."""

    def __init__(self, code: str, detail: str):
        self.code, self.detail, self.remedy = code, detail, CODES[code]
        super().__init__(f'{code}: {detail}. Remedy: {self.remedy}.')


# ---------------------------------------------------------------- the qualification launcher


class SyntheticKeyProvider(contract.CredentialProvider):
    """The launcher's credential provider: one synthetic key read from standard input, held in memory. It writes
    nothing. credentials.select_provider never returns it; only launch() constructs it."""
    name = KEY_SOURCE

    def __init__(self, provider_id: str, key: str):
        self._entry = (provider_id, key)

    def get(self, name):
        return self._entry if name == broker.ENTRY else None

    def set(self, name, user, secret, comment=''):
        raise QualificationError('KEY_NEVER_WRITTEN', 'the synthetic key is never stored')

    def delete(self, name):
        raise QualificationError('KEY_NEVER_WRITTEN', 'the synthetic key is never stored')

    def describe(self) -> dict:
        return {'provider': self.name, 'mechanism': 'one synthetic key read from standard input and held in memory '
                                                    'by the qualification launcher; never stored'}


def read_synthetic_key(stream) -> str:
    """The synthetic key from STREAM (standard input): never a terminal (KEY_STDIN_TTY); one printable word
    (KEY_INVALID); the synthetic prefix and 16 to 128 URL-safe characters (KEY_NOT_SYNTHETIC). No message repeats
    what was read."""
    key = broker.read_key(stream)
    if not SYNTHETIC_SHAPE.fullmatch(key):
        raise QualificationError('KEY_NOT_SYNTHETIC', 'standard input is not a synthetic qualification key (what '
                                                      'was read is not shown)')
    return key


def check_upstreams(config, provider_id: str) -> list:
    """The ids of the families keyed to PROVIDER_ID; refused unless every configured upstream is plain http to a
    loopback IP literal and at least one family is keyed to PROVIDER_ID."""
    keyed = []
    for family in config.families.values():
        if family.upstream is None:
            continue
        if family.upstream.scheme != 'http' or not family.upstream.loopback:
            raise QualificationError('QUALIFICATION_UPSTREAM_REFUSED', f'{family.id}: {family.upstream.text()} is '
                                                                       'not plain http to a loopback IP literal')
        if family.provider == provider_id:
            keyed.append(family.id)
    if not keyed:
        raise QualificationError('QUALIFICATION_NO_FAMILY', f'no family with an upstream is keyed to {provider_id}')
    return keyed


def launch(provider_id: str, ctx) -> int:
    """Check the configuration (read once), read the synthetic key, then run the broker's own serve with a context
    whose configuration is that snapshot and whose credential provider holds the key."""
    if not isinstance(provider_id, str) or not broker.PROVIDER_ID.fullmatch(provider_id):
        raise broker.InferenceError('PROVIDER_ID_INVALID', 'not a provider id')
    raw = copy.deepcopy(ctx.component())
    keyed = check_upstreams(broker.load_config(raw, allow_ephemeral=ctx.allow_ephemeral), provider_id)
    provider = SyntheticKeyProvider(provider_id, read_synthetic_key(ctx.stdin))
    ctx.err.write(f'inference-qualification: a synthetic key from standard input '
                  f'({contract.fingerprint(provider.get(broker.ENTRY)[1])}, source {KEY_SOURCE}) for {keyed}: '
                  'substitution shown with a synthetic key\n')
    return broker.main(['serve'], dataclasses.replace(ctx, component=lambda: copy.deepcopy(raw),
                                                      provider=lambda: provider, stdin=None))


# ---------------------------------------------------------------- the fake upstream


def fake_answer(family) -> dict:
    """The fixed answer in FAMILY's JSON shape, with the usage counts 1 and 1 its usage extractor reads."""
    if family.usage == 'anthropic-messages':
        return {'id': 'aieh-fake-upstream', 'type': 'message', 'role': 'assistant', 'stop_reason': 'end_turn',
                'content': [{'type': 'text', 'text': FAKE_TEXT}], 'usage': {'input_tokens': 1, 'output_tokens': 1}}
    if family.usage == 'openai-responses':
        return {'id': 'aieh-fake-upstream', 'object': 'response', 'status': 'completed',
                'output': [{'type': 'message', 'role': 'assistant',
                            'content': [{'type': 'output_text', 'text': FAKE_TEXT}]}],
                'usage': {'input_tokens': 1, 'output_tokens': 1, 'total_tokens': 2}}
    return {'id': 'aieh-fake-upstream', 'object': 'chat.completion',
            'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': FAKE_TEXT},
                         'finish_reason': 'stop'}],
            'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2}}


def credential_fingerprints(headers, family) -> list:
    """The fingerprint of each value of FAMILY's auth header (its scheme word removed), never the value."""
    found = []
    for value in headers.get_all(family.auth_header) or []:
        value = value.strip()
        if family.auth_scheme is not None:
            word, _, rest = value.partition(' ')
            if word.lower() == family.auth_scheme.lower():
                value = rest.strip()
        found.append(contract.fingerprint(value))
    return found


def fake_address(value) -> str:
    """VALUE when it is an IPv4 loopback literal, else FAKE_ADDRESS_REFUSED."""
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        address = None
    if address is None or address.version != 4 or not address.is_loopback or str(address) != value:
        raise QualificationError('FAKE_ADDRESS_REFUSED', f'{str(value)[:64]!r} is not a loopback IPv4 literal')
    return value


class _FakeServer(http.server.ThreadingHTTPServer):
    """A loopback listener: no address reuse (on Windows, exclusive use of the port), no name lookup."""
    allow_reuse_address = False
    daemon_threads = True

    def __init__(self, address, handler, fake: 'FakeUpstream'):
        self.fake = fake
        super().__init__(address, handler)

    def server_bind(self):
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[0], self.server_address[1]

    def handle_error(self, request, client_address):
        self.fake.record({'event': 'handler-error', 'error': type(sys.exc_info()[1]).__name__})


class _FakeHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    server_version, sys_version = 'aieh-fake-upstream', ''
    timeout = 120

    def log_message(self, format, *args):  # noqa: A002 - the records on standard output are its only log
        pass

    def _serve(self):
        fake = self.server.fake
        family = fake.family
        route = (self.command, self.path) in family.routes
        entry = {'event': 'request', 'family': family.id,
                 'method': self.command if self.command in broker.METHODS else 'other',
                 'path': self.path if route else None, 'header_names': [name.lower() for name in self.headers.keys()],
                 'credential_fingerprints': credential_fingerprints(self.headers, family)}
        length = self.headers.get('content-length') or '0'
        if self.headers.get('transfer-encoding') is not None or not length.isdigit() \
                or int(length) > FAKE_BODY_LIMIT:
            status, payload = 411, {'error': {'type': 'aieh_fake_upstream', 'message': 'send a Content-Length'}}
            self.close_connection = True
        else:
            remaining = int(length)
            while remaining > 0:
                data = self.rfile.read(min(remaining, 65536))
                if not data:
                    break
                remaining -= len(data)
            status = 200 if route else 404
            payload = fake.answer if route else {'error': {'type': 'aieh_fake_upstream',
                                                           'message': f'not a declared route of {family.id}'}}
        fake.record({**entry, 'status': status})
        data = json.dumps(payload).encode('utf-8')
        self.send_response_only(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        if self.close_connection:
            self.send_header('Connection', 'close')
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(data)

    do_GET = do_HEAD = do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = do_CONNECT = do_TRACE = _serve


class FakeUpstream:
    """One declared family's fake provider on ADDRESS:PORT (bound at construction, served from start()). Each
    request's record is written to OUT as one JSON line before its answer."""

    def __init__(self, family, address: str, port: int, out):
        self.family, self.out = family, out
        self.answer = fake_answer(family)
        self.requests = 0
        self._lock = threading.Lock()
        self.server = _FakeServer((fake_address(address), port), _FakeHandler, self)
        self.address, self.port = self.server.server_address[:2]
        self._thread = None

    def record(self, entry: dict) -> None:
        line = json.dumps({'format': FAKE_FORMAT, **entry}, sort_keys=True)
        with self._lock:
            self.requests += entry['event'] == 'request'
            self.out.write(line + '\n')
            self.out.flush()

    def start(self) -> None:
        self._thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': 0.05},
                                        name=f'aieh-fake-upstream-{self.port}', daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._thread is not None:
            self.server.shutdown()
            self._thread.join()
        self.server.server_close()


def fake_upstream(family_id: str, address: str, port: int, ctx) -> int:
    """Serve FAMILY_ID's fake upstream on ADDRESS:PORT until ctx.wait returns."""
    family = broker.load_declarations().get(family_id)
    if family is None:
        raise QualificationError('FAKE_FAMILY_UNKNOWN', f'{str(family_id)[:64]!r} is not a declared family')
    if isinstance(port, bool) or not isinstance(port, int) or not (
            1024 <= port <= 65535 or port == 0 and ctx.allow_ephemeral):
        raise QualificationError('FAKE_PORT_INVALID', f'{port!r} is not a port from 1024 to 65535')
    fake = FakeUpstream(family, address, port, ctx.out)
    try:
        fake.start()
        fake.record({'event': 'start', 'family': family.id, 'address': fake.address, 'port': fake.port,
                     'routes': [{'method': m, 'path': p} for m, p in sorted(family.routes)]})
        ctx.err.write(f'inference-fake-upstream: serving {family.id} on {fake.address}:{fake.port} until '
                      'interrupted\n')
        ctx.wait(fake)
    finally:
        fake.stop()
    fake.record({'event': 'stop', 'requests': fake.requests})
    return 0


# ---------------------------------------------------------------- command line


def main(argv=None, context=None) -> int:
    parser = argparse.ArgumentParser(prog='inference_qualification.py', description='Qualification-only commands '
                                     'of the inference broker (S-03.2). Exit 0 done, 1 failed, 2 refused.')
    sub = parser.add_subparsers(dest='command', required=True)
    launcher = sub.add_parser('broker', help='run the broker with a synthetic provider key read from standard '
                                             'input, against loopback http upstreams only')
    launcher.add_argument('--provider', required=True, help='the provider id the keyed families name')
    fake = sub.add_parser('fake-upstream', help="serve one family's fake upstream on a loopback address")
    fake.add_argument('--family', required=True, help='a declared family id')
    fake.add_argument('--port', required=True, type=int, help='the port, 1024 to 65535')
    fake.add_argument('--address', default=broker.LOOPBACK, help='a loopback IPv4 address (default 127.0.0.1)')
    args = parser.parse_args(argv)
    err = sys.stderr if context is None else context.err
    try:
        if args.command == 'broker':
            return launch(args.provider, context or broker.managed_context())
        return fake_upstream(args.family, args.address, args.port, context or types.SimpleNamespace(
            out=sys.stdout, err=sys.stderr, wait=broker._wait_for_interrupt, allow_ephemeral=False))
    except QualificationError as exc:
        err.write(f'inference-qualification: {exc}\n')
        return 2
    except (broker.InferenceError, contract.LifecycleError) as exc:
        err.write(f'inference-qualification: {exc}\n')
        return 2 if exc.refusal else 1
    except broker.paths.PathsError as exc:
        err.write(f'inference-qualification: {exc}\n')
        return 2
    except Exception as exc:  # noqa: BLE001 - reported by type; no message here can hold the key
        err.write(f'inference-qualification: FAILED: {type(exc).__name__}\n')
        return 1


if __name__ == '__main__':
    sys.exit(main())
