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

Route and model discovery (plan leaf S-03.3, slice 3 part two; the slice plan's D-4 as accepted): learning, before
any key or paid call, which routes and which model names (any secondary model included) a pinned client sends.

- discover: the qualification launcher in its discovery mode. It refuses as broker does (constraints 1 to 4 above,
  the same code path) and also unless each keyed family's upstream is an IPv4 loopback literal on which it can
  bind that family's fake upstream itself, before the key is read: the broker's upstream is then this process's
  fake and nothing else. When the broker stops (the Owner's interrupt), it reads that run's audit file and writes
  the proposed family pin (propose-pin below) to --out, a new file outside the checkout, with a summary of what
  the fake upstreams received (route counts, and whether each credential they saw was the synthetic key's
  fingerprint). It writes nowhere else.
- propose-pin: the reader. It turns one broker run's audit file (persistent/logs/inference/audit-*.jsonl) into a
  PROPOSED family pin: per family, the exact method and path pairs and the exact model names the grants' requests
  carried (no wildcard: only strings inside the audit's own grammars are carried; anything else is counted), with
  what each was answered, the query parameter names, and flags for what the pin cannot rest on (a request whose
  model is not the body's top-level model, the field the broker's per-request check reads (S-03.5's F7); an
  unrecorded or withheld value; a query string where the family refuses one; requests without a grant's token;
  a path the declarations cannot hold). It never applies anything: families.json and config.yml are not
  written. The routes are for the Owner's approval (slice plan 6b), the model identifiers for the engineering
  manager's selection (decision 0018 point 3, integrations/owner/selection_recorder.py select-models).

  <synthetic key> | <tools python> -I -B integrations/inference/inference_qualification.py broker --provider ID
  <tools python> -I -B integrations/inference/inference_qualification.py fake-upstream --family ID --port PORT
  <synthetic key> | <tools python> -I -B integrations/inference/inference_qualification.py discover --provider ID \\
      --out FILE
  <tools python> -I -B integrations/inference/inference_qualification.py propose-pin --audit FILE --out FILE \\
      [--attempt-id UUID]

Exit 0 done, 1 failed, 2 refused (a stable code). Standard library only.
"""
from __future__ import annotations

import argparse
import collections
import copy
import dataclasses
import hashlib
import http.server
import importlib.util
import io
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
    'DISCOVERY_PORT_TAKEN': 'free the configured upstream port: discovery binds its own fake upstream there, so that '
                            'the broker reaches nothing else',
    'PROPOSAL_OUT_REFUSED': 'give --out as a new file in an existing directory outside the checkout: a proposal is '
                            'never written over a file, nor into the repository (families.json is never written)',
    'AUDIT_UNREADABLE': 'give one broker run\'s audit file (persistent/logs/inference/audit-*.jsonl), a regular file '
                        'of at most 256 MiB',
    'ATTEMPT_ID_INVALID': 'give --attempt-id as the grant\'s attempt id, a UUID',
    'PROPOSAL_EXPOSURE': 'nothing to do here: the proposal would have held the synthetic key and was not written',
}
PROPOSAL_FORMAT = 'aieh-inference-family-pin-proposal/1'
AUDIT_LIMIT = 256 * broker.MIB
PASSED = '(passed)'                 # the codes column of a request answered without a refusal code
CODE_SHAPE = re.compile(r'[A-Z][A-Z0-9_]{0,63}')
UUID_SHAPE = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')
OBSERVED_FIELDS = ('path', 'query_names', 'model')
PROPOSAL_STATEMENT = (
    'PROPOSED, never applied: read from one broker run\'s audit file; this reader writes neither families.json nor '
    'config.yml. The exact routes are for the Owner\'s approval (S-03.3 slice plan 6b: the family\'s routes, no '
    'wildcard); the exact model identifiers, any secondary model included, are for the engineering manager\'s '
    'selection inside the Owner\'s provider envelope (decision 0018 point 3; integrations/owner/'
    'selection_recorder.py select-models), verified against current provider information and presented to the '
    'Owner before the first paid call. Every route and model below is an exact string observed in the audit.')
NOT_SHOWN = (
    'a model named in a body field other than the top-level "model" of a request that has one: the audit records '
    'the top-level model only (the slice plan\'s D-4 as accepted: no body), so the absence of a MODEL_NOT_TOP_LEVEL '
    'flag does not show that no request names a second model elsewhere; the broker\'s per-request check reads the '
    'top-level model only (S-03.5, F7)',
    'query parameter values, header names and values, and bodies: never recorded',
    'what a request would have done had it been admitted: a refused request was answered by the broker, not by the '
    'fake upstream',
    'requests the client never sent because an earlier one was refused',
)


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


# ---------------------------------------------------------------- the proposed family pin (the reader)


def proposal_target(value) -> Path:
    """--out: a new file in an existing directory, outside the checkout (PROPOSAL_OUT_REFUSED)."""
    if not isinstance(value, str) or not value.strip():
        raise QualificationError('PROPOSAL_OUT_REFUSED', 'no path given')
    target = Path(value).resolve()
    repo = Path(os.path.realpath(broker.REPO))
    if os.path.lexists(target) or not target.parent.is_dir() or target == repo or target.is_relative_to(repo):
        raise QualificationError('PROPOSAL_OUT_REFUSED', f'{str(value)[:200]!r} exists, has no directory or lies '
                                                         'inside the checkout')
    return target


def read_audit(path) -> tuple[list, dict]:
    """The request records of one audit file, and what was read: its name, size and sha256, the lines, and the
    lines that are not audit records (unreadable) or that the broker withheld (EXPOSURE_FOUND)."""
    path = Path(path)
    try:
        if not path.is_file() or path.stat().st_size > AUDIT_LIMIT:
            raise OSError('not a regular file within the limit')
        data = path.read_bytes()
    except OSError as exc:
        raise QualificationError('AUDIT_UNREADABLE', f'{path.name[:120]!r}: {type(exc).__name__}') from None
    records, counts = [], collections.Counter()
    for raw in data.splitlines():
        if not raw.strip():
            continue
        counts['lines'] += 1
        try:
            record = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            record = None
        if not isinstance(record, dict) or record.get('format') != broker.AUDIT_FORMAT:
            counts['unreadable'] += 1
        elif 'withheld' in record:
            counts['withheld'] += 1
        elif record.get('event') == 'request':
            records.append(record)
    return records, {'audit_file': path.name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
                     'lines': counts['lines'], 'requests': len(records), 'unreadable': counts['unreadable'],
                     'withheld': counts['withheld']}


def _observed_path(value):
    """VALUE when it is a path in the audit's grammar ('/' or at most 16 segments of the observed word), else None."""
    if not isinstance(value, str) or broker.TOKEN_PREFIX in value or not value.startswith('/'):
        return None
    if value == '/':
        return value
    segments = value[1:].split('/')
    if len(segments) > broker.OBSERVED_SEGMENTS or not all(broker.OBSERVED_WORD.fullmatch(s) for s in segments):
        return None
    return value


def _observed_names(value):
    """(names, dropped): the query parameter names in the audit's grammar, sorted; None when no query was sent."""
    if value is None:
        return None, 0
    if not isinstance(value, list):
        return [], 1
    kept = sorted({n for n in value if isinstance(n, str) and broker.OBSERVED_WORD.fullmatch(n)
                   and broker.TOKEN_PREFIX not in n})
    return kept, sum(1 for n in value if n not in kept)


def _observed_model(value):
    """VALUE when it is an exact model name in the broker's grammar (no wildcard, no token prefix), else None."""
    if isinstance(value, str) and broker.MODEL_NAME.fullmatch(value) and not broker.WILDCARD.search(value) \
            and broker.TOKEN_PREFIX not in value:
        return value
    return None


def _flag(code: str, detail: str, **where) -> dict:
    return {'code': code, **where, 'detail': detail}


def propose_pin(records, declarations: dict, *, attempt_id: str | None = None, source: dict | None = None) -> dict:
    """The proposed family pin of RECORDS (an audit file's request records, read_audit): per declared family, the
    exact routes and models of the requests that presented one of its grants (of ATTEMPT_ID only, when given),
    with their answers, query parameter names and flags; the requests without a grant counted apart. Nothing is
    applied anywhere."""
    families, unattributed, attempts = {}, {}, {}
    broker_unrecorded, reader_dropped = collections.Counter(), collections.Counter()
    for record in records:
        attempt, fingerprint, family_id = (record.get('attempt_id'), record.get('token_fingerprint'),
                                           record.get('family'))
        attributed = isinstance(fingerprint, str) and broker.FINGERPRINT_SHAPE.fullmatch(fingerprint) is not None \
            and family_id in declarations and isinstance(attempt, str) and UUID_SHAPE.fullmatch(attempt) is not None
        if attributed and attempt_id is not None and attempt != attempt_id:
            continue
        method = record.get('method') if record.get('method') in broker.METHODS else 'other'
        path = _observed_path(record.get('path'))
        if record.get('path') is not None and path is None:
            reader_dropped['path'] += 1
        names, dropped = _observed_names(record.get('query_names'))
        reader_dropped['query_names'] += dropped
        model = _observed_model(record.get('model'))
        if record.get('model') is not None and model is None:
            reader_dropped['model'] += 1
        given, unrecorded = record.get('unrecorded') or {}, {}
        if not isinstance(given, dict):
            reader_dropped['unrecorded'] += 1
            given = {}
        for field, count in given.items():
            if field in OBSERVED_FIELDS and isinstance(count, int) and not isinstance(count, bool) and count > 0:
                unrecorded[field] = count
                broker_unrecorded[field] += count
            else:
                reader_dropped['unrecorded'] += 1
        code = record.get('code')
        code = PASSED if code is None else code if isinstance(code, str) and CODE_SHAPE.fullmatch(code) else '(other)'
        if not attributed:
            row = unattributed.setdefault((method, path), {'method': method, 'path': path, 'requests': 0,
                                                           'query_names': set(), 'codes': collections.Counter()})
            row['requests'] += 1
            row['query_names'].update(names or ())
            row['codes'][code] += 1
            continue
        attempts[attempt] = {'attempt_id': attempt, 'token_fingerprint': fingerprint, 'family': family_id}
        family = families.setdefault(family_id, {'routes': {}, 'models': {}, 'unrecorded': collections.Counter()})
        route = family['routes'].setdefault((method, path), {
            'method': method, 'path': path, 'requests': 0, 'codes': collections.Counter(), 'with_query': 0,
            'query_names': set(), 'models': set(), 'no_model': 0, 'model_unrecorded': 0})
        route['requests'] += 1
        route['codes'][code] += 1
        if names is not None:
            route['with_query'] += 1
            route['query_names'].update(names)
        family['unrecorded'].update(unrecorded)
        if model is not None:
            route['models'].add(model)
            entry = family['models'].setdefault(model, {'model': model, 'requests': 0, 'routes': set(),
                                                        'codes': collections.Counter()})
            entry['requests'] += 1
            entry['routes'].add(f'{method} {path}')
            entry['codes'][code] += 1
        elif 'model' in unrecorded or record.get('model') is not None:
            route['model_unrecorded'] += 1
        else:
            route['no_model'] += 1
    out_families, flags = [], []
    for family_id in sorted(families):
        family, declared = families[family_id], declarations[family_id]
        routes, proposed_routes = [], []
        for (method, path), route in sorted(families[family_id]['routes'].items(),
                                            key=lambda item: (item[0][1] or '', item[0][0])):
            where = {'family': family_id, 'route': f'{method} {path}'}
            declarable = method != 'other' and path is not None and broker.ROUTE_PATH.fullmatch(path) is not None
            routes.append({'method': method, 'path': path, 'requests': route['requests'],
                           'codes': dict(sorted(route['codes'].items())), 'with_query': route['with_query'],
                           'query_names': sorted(route['query_names']), 'models': sorted(route['models']),
                           'no_top_level_model': route['no_model'], 'model_unrecorded': route['model_unrecorded'],
                           'declared': (method, path) in declared.routes, 'declarable': declarable})
            if declarable:
                proposed_routes.append({'method': method, 'path': path})
            elif path is None:
                flags.append(_flag('PATH_UNRECORDED', f'{route["requests"]} request(s) whose path the audit does not '
                                   'hold: their route cannot be proposed', **where))
            else:
                flags.append(_flag('ROUTE_NOT_DECLARABLE', 'the method or path is outside the declarations\' route '
                                   'grammar', **where))
            if route['no_model']:
                flags.append(_flag('MODEL_NOT_TOP_LEVEL', f'{route["no_model"]} request(s) without a top-level '
                                   '"model": the broker\'s per-request check reads that field only (S-03.5, F7), so '
                                   'a request whose model is named elsewhere, or not at all, is not admitted; this '
                                   'route is not declared without its own check', **where))
            if route['model_unrecorded']:
                flags.append(_flag('MODEL_UNRECORDED', f'{route["model_unrecorded"]} request(s) whose model is outside '
                                   'the audit\'s grammar or was not recorded: it cannot be proposed', **where))
            if route['with_query'] and declared.query != 'pass':
                flags.append(_flag('QUERY_OBSERVED', f'{route["with_query"]} request(s) with a query string, names '
                                   f'{sorted(route["query_names"])}; the family\'s query rule is {declared.query!r} '
                                   'and the declarations hold refuse or pass only, so admitting them is a decision '
                                   'of its own', **where))
        if family['unrecorded']['query_names']:
            flags.append(_flag('QUERY_NAMES_UNRECORDED', f'{family["unrecorded"]["query_names"]} query parameter '
                               'name(s) outside the audit\'s grammar were counted, not recorded', family=family_id))
        models = [{'model': m['model'], 'requests': m['requests'], 'routes': sorted(m['routes']),
                   'codes': dict(sorted(m['codes'].items()))} for _, m in sorted(family['models'].items())]
        observed = {(r['method'], r['path']) for r in proposed_routes}
        out_families.append({
            'family': family_id,
            'declared': {'status': declared.status, 'query': declared.query,
                         'routes': [{'method': m, 'path': p} for m, p in sorted(declared.routes)]},
            'proposed': {'routes': proposed_routes, 'models': [m['model'] for m in models]},
            'compared': {'declared_not_observed': [{'method': m, 'path': p} for m, p in sorted(declared.routes)
                                                   if (m, p) not in observed],
                         'observed_not_declared': [r for r in proposed_routes
                                                   if (r['method'], r['path']) not in declared.routes]},
            'observed': {'routes': routes, 'models': models}})
    source = dict(source or {})
    if unattributed:
        flags.append(_flag('UNATTRIBUTED_REQUESTS', f'{sum(r["requests"] for r in unattributed.values())} '
                           'request(s) presented no grant of this broker: their model is never recorded and they '
                           'are not part of any family\'s pin'))
    if source.get('withheld'):
        flags.append(_flag('AUDIT_LINES_WITHHELD', f'{source["withheld"]} audit line(s) were withheld by the '
                           'broker\'s I7 scan: what they held is unknown'))
    if source.get('unreadable'):
        flags.append(_flag('AUDIT_LINES_UNREADABLE', f'{source["unreadable"]} line(s) are not audit records'))
    if +broker_unrecorded:
        flags.append(_flag('BROKER_UNRECORDED', f'values the broker counted instead of recording: '
                           f'{dict(sorted((+broker_unrecorded).items()))}'))
    if +reader_dropped:
        flags.append(_flag('READER_DROPPED', f'values outside the audit\'s grammars, not carried: '
                           f'{dict(sorted((+reader_dropped).items()))}'))
    if not families:
        flags.append(_flag('NO_GRANT_REQUESTS', 'no request presented a grant: nothing is proposed'))
    complete = bool(families) and not (+broker_unrecorded or +reader_dropped or source.get('withheld')
                                       or source.get('unreadable'))
    return {'format': PROPOSAL_FORMAT, 'status': 'proposed', 'applied': False, 'statement': PROPOSAL_STATEMENT,
            'source': {**source, 'attempt_filter': attempt_id}, 'complete': complete,
            'attempts': [attempts[a] for a in sorted(attempts)], 'families': out_families,
            'unattributed': [{**{k: r[k] for k in ('method', 'path', 'requests')},
                              'query_names': sorted(r['query_names']), 'codes': dict(sorted(r['codes'].items()))}
                             for _, r in sorted(unattributed.items(), key=lambda i: (i[0][1] or '', i[0][0]))],
            'flags': flags, 'not_shown': list(NOT_SHOWN)}


def write_proposal(target: Path, proposal: dict) -> None:
    """Write PROPOSAL to TARGET, a new file (never over one)."""
    text = json.dumps(proposal, indent=2, sort_keys=True) + '\n'
    if SYNTHETIC_PREFIX in text:
        raise QualificationError('PROPOSAL_EXPOSURE', 'the proposal holds the synthetic key\'s prefix')
    with open(target, 'x', encoding='utf-8', newline='\n') as handle:
        handle.write(text)


def proposal_summary(target: Path, proposal: dict) -> dict:
    return {'format': PROPOSAL_FORMAT, 'out': str(target), 'complete': proposal['complete'],
            'families': {f['family']: {'routes': len(f['proposed']['routes']), 'models': f['proposed']['models']}
                         for f in proposal['families']},
            'flags': sorted({flag['code'] for flag in proposal['flags']})}


def propose_command(audit, attempt_id, out_value, out) -> int:
    """propose-pin: read AUDIT, write the proposal to OUT_VALUE, print its summary."""
    if attempt_id is not None and not UUID_SHAPE.fullmatch(str(attempt_id)):
        raise QualificationError('ATTEMPT_ID_INVALID', 'not a lower-case UUID')
    target = proposal_target(out_value)
    records, source = read_audit(audit)
    proposal = propose_pin(records, broker.load_declarations(), attempt_id=attempt_id, source=source)
    write_proposal(target, proposal)
    out.write(json.dumps(proposal_summary(target, proposal), indent=2, sort_keys=True) + '\n')
    return 0


# ---------------------------------------------------------------- discovery


def upstream_summary(fakes: dict, fingerprint) -> dict:
    """What each family's fake upstream received: requests per route and answer, and whether every credential it
    saw was the provider key's fingerprint (the synthetic key substituted for the attempt token)."""
    out = {}
    for family_id, fake in sorted(fakes.items()):
        received = [json.loads(line) for line in fake.out.getvalue().splitlines()]
        requests = [r for r in received if r.get('event') == 'request']
        out[family_id] = {
            'requests': len(requests),
            'routes': dict(sorted(collections.Counter(f'{r.get("method")} {r.get("path")} {r.get("status")}'
                                                      for r in requests).items())),
            'credential_is_the_synthetic_key': None if not requests else all(
                r.get('credential_fingerprints') == [fingerprint] for r in requests)}
    return out


def discover(provider_id: str, out_value, ctx) -> int:
    """The discovery mode: the launcher with each keyed family's fake upstream bound by this process on its
    configured upstream, then the proposal of the run's audit written to OUT_VALUE."""
    target = proposal_target(out_value)
    if not isinstance(provider_id, str) or not broker.PROVIDER_ID.fullmatch(provider_id):
        raise broker.InferenceError('PROVIDER_ID_INVALID', 'not a provider id')
    raw = copy.deepcopy(ctx.component())
    config = broker.load_config(raw, allow_ephemeral=ctx.allow_ephemeral)
    keyed = check_upstreams(config, provider_id)
    declarations = broker.load_declarations()
    fakes, seen = {}, {}
    try:
        for family_id in keyed:
            origin = config.families[family_id].upstream
            address = fake_address(origin.host)
            try:
                fakes[family_id] = FakeUpstream(declarations[family_id], address, origin.port, io.StringIO())
            except OSError as exc:
                raise QualificationError('DISCOVERY_PORT_TAKEN', f'{family_id}: {origin.text()} '
                                                                 f'({type(exc).__name__})') from None
        for fake in fakes.values():
            fake.start()

        def wait(served):
            status = served.status()
            seen.update(audit=status['audit']['file'], fingerprint=(status.get('provider_key') or {}).get(
                'fingerprint'))
            ctx.wait(served)
        code = launch(provider_id, dataclasses.replace(ctx, component=lambda: copy.deepcopy(raw), wait=wait))
    finally:
        for fake in fakes.values():
            fake.stop()
    if 'audit' not in seen:
        return code                       # the broker never served: nothing was observed, nothing is proposed
    try:
        records, source = read_audit(Path(ctx.logs()) / seen['audit'])
        proposal = propose_pin(records, declarations, source=source)
        proposal['discovery'] = {'provider': provider_id, 'families': keyed,
                                 'provider_key_fingerprint': seen['fingerprint'],
                                 'upstream': upstream_summary(fakes, seen['fingerprint'])}
        write_proposal(target, proposal)
    except QualificationError as exc:     # after the run: a failure, not a refusal
        ctx.err.write(f'inference-discovery: FAILED after the run: {exc}\n')
        return 1
    ctx.err.write('inference-discovery: ' + json.dumps(proposal_summary(target, proposal), sort_keys=True) + '\n')
    return code


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
    disc = sub.add_parser('discover', help='the launcher in its discovery mode: each keyed family\'s fake upstream '
                                           'bound by this process on its configured loopback upstream; at the stop, '
                                           'the proposed family pin of the run\'s audit written to --out')
    disc.add_argument('--provider', required=True, help='the provider id the keyed families name')
    disc.add_argument('--out', required=True, help='the proposal: a new file outside the checkout')
    pin = sub.add_parser('propose-pin', help='read one broker run\'s audit file and write the proposed family pin '
                                             '(exact routes and models, flags); never applied')
    pin.add_argument('--audit', required=True, help='the audit file (persistent/logs/inference/audit-*.jsonl)')
    pin.add_argument('--out', required=True, help='the proposal: a new file outside the checkout')
    pin.add_argument('--attempt-id', help='only the requests of this grant\'s attempt (a UUID)')
    args = parser.parse_args(argv)
    err = sys.stderr if context is None else context.err
    try:
        if args.command == 'broker':
            return launch(args.provider, context or broker.managed_context())
        if args.command == 'discover':
            return discover(args.provider, args.out, context or broker.managed_context())
        if args.command == 'propose-pin':
            return propose_command(args.audit, args.attempt_id, args.out,
                                   sys.stdout if context is None else context.out)
        return fake_upstream(args.family, args.address, args.port, context or types.SimpleNamespace(
            out=sys.stdout, err=sys.stderr, wait=broker._wait_for_interrupt, allow_ephemeral=False))
    except QualificationError as exc:
        err.write(f'inference-qualification: {exc}\n')
        return 1 if exc.code == 'PROPOSAL_EXPOSURE' else 2
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
