"""The inference broker (plan leaf S-03.2, slice 1: the broker core, built and tested offline; decision 0015 as
amended by its amendment 1; decisions 0007 points 4 and 5, 0009 and 0013 point 6).

A host-side process in the trusted management domain (inventory principal inference-broker), the sole holder of
the model provider's key. It serves two listeners, both bound to 127.0.0.1 only:

- the control listener (issue, revoke, status; never forwarded; same-account only, disclosed under decision
  0013 point 6): it issues one random attempt token per attempt, bound to the attempt and its conversation, to
  one declared API family, to a model list, to a budget of requests and of usage tokens and to an expiry. The
  token is returned once and kept only as its sha256 digest; the grant is journaled by the token's fingerprint
  in the integration store (operation key inference/attempt/<attempt id>/grant, format aieh-inference-grant/1).
  Revocation is immediate (the next request answers 401) and leaves a receipt with the per-attempt summary
  (inference/attempt/<attempt id>/revocation, format aieh-inference-revocation/1): fingerprint, attempt,
  trigger, revoker, requests, usage, refusals. Never the effects store.
- the inference listener (the only forward target): a request is admitted only with a valid, unrevoked,
  unexpired token in its family's auth header, a method and path in that family's declared route set, a
  `model` in both the token's list and the family's allowlist, and budget left. It is then passed through
  untranslated to that family's one upstream origin, with the provider key in the family's auth header in
  place of the token (the token never leaves the host toward the upstream), and the answer is streamed back
  as it arrives. Every refusal answers with a stable code (CODES).

The families are declared in families.json beside this module (format aieh-inference-families/1): each has an
id, its exact method and path set (provisional until pinned from observed traffic, amendment 1 point 3), its
query rule, the auth header shape it reads and forwards, and its usage extractor. The Owner's settings live in
components.inference_broker of the managed config.yml (decision 0009; no secret: the loader refuses
secret-shaped keys): the two listener ports, and per family the provider id, the upstream origin and the model
allowlist. The shipped allowlists are empty, so every issuance is refused until the Owner names models.

Egress: the broker opens a connection only in connect_upstream, and only to the configured upstream origin of
the admitted token's family (https with the system's trust roots, or http to a loopback address for a local
model server). It imports no litellm, fetches no cost map, sends no telemetry and checks for no update; it
honours no proxy variable.

Audit: one append-only JSON line per request in <managed root>/persistent/logs/inference/ (time, attempt and
conversation id, token fingerprint, family, method, path, model, byte counts, status and upstream status,
latency, usage), never a body, a header, the token or the provider key; every line, response and receipt
passes the I7 no-exposure scan of F-06.3 first, and a line that fails it is withheld.

The provider key is one entry of the harness's credential provider (F-06.3): name "AIEH model provider", user
the provider id. Only the Owner-run credential-set command writes it, reading the key from standard input only
(never argv, the environment, a file or config.yml), and it writes an aieh-credential-act/1 receipt with the
fingerprint only.

  <tools python> -I -B integrations/inference/inference_broker.py config
  <tools python> -I -B integrations/inference/inference_broker.py credential-set --provider ID   (key on stdin)
  <tools python> -I -B integrations/inference/inference_broker.py serve

Exit 0 done, 1 failed, 2 refused (a stable code).
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime
import hashlib
import http.client
import http.server
import importlib.util
import ipaddress
import json
import os
import re
import secrets
import socket
import socketserver
import ssl
import sys
import threading
import time
import urllib.parse
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

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


credentials = _load('aieh_credential_provider', REPO / 'integrations' / 'credentials' / 'credential_provider.py')
contract = credentials.contract
paths = _load('aieh_paths', REPO / 'integrations' / 'paths' / 'aieh_paths.py')

FAMILIES_PATH = HERE / 'families.json'
DECLARATION_FORMAT = 'aieh-inference-families/1'
COMPONENT = 'inference_broker'
ENTRY = 'AIEH model provider'
SERVICE = 'inference-broker'
GRANT_FORMAT = 'aieh-inference-grant/1'
REVOCATION_FORMAT = 'aieh-inference-revocation/1'
START_FORMAT = 'aieh-inference-broker-start/1'
AUDIT_FORMAT = 'aieh-inference-audit/1'
STATUS_FORMAT = 'aieh-inference-broker-status/1'
CONFIG_FORMAT = 'aieh-inference-config/1'
CREDENTIAL_SET_FORMAT = 'aieh-inference-credential-set/1'
LOOPBACK = '127.0.0.1'
TOKEN_PREFIX = 'aieh-inf-'
TOKEN_SHAPE = re.compile(r'aieh-inf-[A-Za-z0-9_-]{43}')
FINGERPRINT_SHAPE = re.compile(r'sha256:[0-9a-f]{16}')
TRIGGERS = ('attempt end', 'suspected exposure', 'definition revocation', 'policy revision', 'expiry',
            'owner direction')  # decision 0007 point 5
EXPIRY_REVOKER = 'inference-broker (expiry)'
FAMILY_ID = re.compile(r'[a-z0-9][a-z0-9-]{0,63}')
PROVIDER_ID = re.compile(r'[a-z0-9][a-z0-9._-]{0,63}')
MODEL_NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:@/-]{0,127}')
WILDCARD = re.compile(r'[*?\[\]]')
HEADER_NAME = re.compile(r'[a-z0-9][a-z0-9-]{0,63}')
HOST_NAME = re.compile(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*')
ROUTE_PATH = re.compile(r'/(?:[A-Za-z0-9._~-]+/)*[A-Za-z0-9._~-]+')
METHODS = ('GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS', 'CONNECT', 'TRACE')
USAGE_KINDS = ('anthropic-messages', 'openai-responses', 'openai-chat')
MIB = 1024 * 1024
DEFAULTS = {'max_request_bytes': 32 * MIB, 'max_ttl_s': 86400, 'upstream_timeout_s': 600}
LIMITS = {'max_request_bytes': (1, 256 * MIB), 'max_ttl_s': (1, 7 * 86400), 'upstream_timeout_s': (1, 3600)}
BUDGET_LIMITS = {'requests': 1_000_000, 'tokens': 10_000_000_000}
CONTROL_BODY_LIMIT = 64 * 1024
DRAIN_LIMIT = MIB
# The refused-request audit (D-4 of the S-03.3 slice plan, an Overseer ruling): a path segment or a query parameter name is
# recorded only in this grammar (bounded length and charset), so that no credential-length run is; at most
# OBSERVED_NAMES names per line; the model only in MODEL_NAME's.
OBSERVED_WORD = re.compile(r'[A-Za-z0-9][A-Za-z0-9._~-]{0,31}')
OBSERVED_SEGMENTS = 16
OBSERVED_NAMES = 16
USAGE_BODY_LIMIT = 16 * MIB
SSE_LINE_LIMIT = 4 * MIB
KEY_LIMIT = 4096
# Request headers never forwarded upstream: hop-by-hop, the ones the broker sets, and every credential-bearing
# header (the family's own auth header is set from the provider key).
HOP_BY_HOP = frozenset({'connection', 'keep-alive', 'proxy-connection', 'proxy-authenticate', 'proxy-authorization',
                        'te', 'trailer', 'trailers', 'transfer-encoding', 'upgrade'})
NOT_FORWARDED = HOP_BY_HOP | frozenset({'host', 'content-length', 'accept-encoding', 'expect', 'authorization',
                                        'x-api-key', 'api-key', 'cookie', 'forwarded', 'x-forwarded-for',
                                        'x-forwarded-host', 'x-forwarded-proto', 'x-real-ip'})
NOT_RELAYED = HOP_BY_HOP | frozenset({'content-length'})

# Every stable code: (HTTP status on a listener, remedy).
CODES = {
    # configuration and the family declarations
    'DECLARATION_INVALID': (500, 'restore integrations/inference/families.json to its committed, reviewed text'),
    'CONFIG_NOT_A_MAPPING': (500, 'make components.inference_broker and each of its families a mapping'),
    'CONFIG_UNKNOWN_KEY': (500, 'use only the keys the inference broker README lists'),
    'CONFIG_SECRET_SHAPED_KEY': (500, 'remove it: the provider key lives only in the credential provider entry '
                                      '"AIEH model provider" (credential-set), never in config.yml'),
    'CONFIG_FAMILY_UNKNOWN': (500, 'name only a family declared in integrations/inference/families.json'),
    'CONFIG_PORT_INVALID': (500, 'give control_port and inference_port as two different integers from 1024 to '
                                 '65535'),
    'CONFIG_LIMIT_INVALID': (500, 'give the limit as an integer within its documented range'),
    'CONFIG_PROVIDER_INVALID': (500, 'give the provider id in lower case: letters, digits, ".", "_", "-"'),
    'CONFIG_PROVIDER_REQUIRED': (500, 'name the provider whose key the family forwards; only a loopback upstream '
                                      '(a local model server) may have none'),
    'CONFIG_ORIGIN_INVALID': (500, 'give the upstream as an origin only: https://host[:port], or http:// with a '
                                   'loopback IP literal; no path, query, fragment or user information'),
    'CONFIG_MODEL_INVALID': (500, 'list exact, verified model identifiers: no wildcard, no duplicate'),
    'CONFIG_INCOMPLETE': (500, 'set control_port and inference_port in components.inference_broker of config.yml'),
    # the control listener
    'CONTROL_ROUTE_UNKNOWN': (404, 'use POST /v1/grants, POST /v1/grants/revoke, GET /v1/grants/<fingerprint> or '
                                   'GET /v1/status'),
    'CONTROL_CALLER_REFUSED': (403, 'call the control listener directly on 127.0.0.1 with its port as the Host, '
                                    'with no Origin header'),
    'CONTROL_CONTENT_TYPE': (415, 'send the body as application/json'),
    'CONTROL_BODY_INVALID': (400, 'send one JSON object with exactly the documented fields'),
    'CONVERSATION_ID_INVALID': (400, 'give the reserved conversation id as a canonical lower-case UUID'),
    'ATTEMPT_ID_INVALID': (400, 'give the attempt id as a canonical lower-case UUID'),
    'FAMILY_UNKNOWN': (400, 'name a declared family (GET /v1/status lists them)'),
    'FAMILY_NOT_READY': (409, 'configure the family (upstream, provider, models) and load its provider key '
                              '(credential-set), then restart the broker'),
    'MODELS_INVALID': (400, 'give a non-empty list of distinct model identifiers'),
    'MODEL_NOT_ALLOWLISTED': (403, "name only models of the family's allowlist in config.yml; the Owner verifies "
                                   'and approves every identifier'),
    'BUDGET_INVALID': (400, 'give budget.requests and budget.tokens as positive integers within the limits'),
    'TTL_INVALID': (400, 'give ttl_s as a positive integer no larger than max_ttl_s'),
    'ATTEMPT_HAS_GRANT': (409, 'an attempt has one token for its whole life: start a new attempt'),
    'TRIGGER_UNKNOWN': (400, 'give one of the decision 0007 point 5 triggers'),
    'REVOKER_INVALID': (400, 'name the revoker in 1 to 200 printable characters'),
    'GRANT_UNKNOWN': (404, 'give the fingerprint the issue answer returned'),
    'GRANT_ALREADY_REVOKED': (409, 'nothing to do: the grant is revoked'),
    'JOURNAL_FAILED': (500, 'check the integration store; a revocation still holds, and its receipt is retried at '
                            'the next control call'),
    'EXPOSURE_FOUND': (500, 'the output was withheld: treat every token and the provider key as exposed'),
    # the inference listener
    'TOKEN_MISSING': (401, "send the attempt token in the family's auth header"),
    'TOKEN_AMBIGUOUS': (401, 'send exactly one attempt token'),
    'TOKEN_UNKNOWN': (401, 'use the token the broker issued for this attempt'),
    'TOKEN_REVOKED': (401, 'the token is revoked: the attempt has ended or was stopped'),
    'TOKEN_EXPIRED': (401, 'the token is expired: the attempt needs a new grant'),
    'TOKEN_WRONG_HEADER': (401, "send the token in its family's auth header shape"),
    'ROUTE_NOT_ALLOWED': (404, "use only the method and path set of the token's family"),
    'QUERY_NOT_ALLOWED': (400, "send no query string: the token's family admits none"),
    'BUDGET_REQUESTS_EXHAUSTED': (429, "the attempt's request budget is spent"),
    'BUDGET_TOKENS_EXHAUSTED': (429, "the attempt's usage-token budget is spent"),
    'BUDGET_USAGE_UNKNOWN': (429, 'a successful answer reported no usage, so the token budget cannot be enforced: '
                                  'the attempt is refused further requests (fail closed)'),
    'BODY_LENGTH_REQUIRED': (411, 'send the body with a Content-Length, not chunked'),
    'BODY_LENGTH_INVALID': (400, 'send one valid Content-Length'),
    'BODY_TOO_LARGE': (413, 'send a body no larger than max_request_bytes'),
    'BODY_NOT_JSON': (400, 'send the body as one uncompressed JSON object'),
    'MODEL_MISSING': (400, 'send the model as a string field "model"'),
    'MODEL_NOT_ALLOWED': (403, "use a model of the token's list"),
    'TOKEN_IN_REQUEST': (400, 'the attempt token is only ever the auth header: remove it from the path, other '
                              'headers and the body'),
    'PROVIDER_KEY_ABSENT': (503, "store the family's provider key (credential-set) and restart the broker"),
    'UPSTREAM_NOT_CONFIGURED': (503, 'set the family upstream origin in config.yml and restart the broker'),
    'UPSTREAM_UNREACHABLE': (502, 'check the upstream origin and the host network'),
    # credential-set
    'PROVIDER_ID_INVALID': (400, 'give the provider id in lower case: letters, digits, ".", "_", "-"'),
    'KEY_STDIN_TTY': (400, 'pipe the key on standard input (it is never read from a terminal, argv, the '
                           'environment, a file or config.yml)'),
    'KEY_INVALID': (400, 'pipe exactly the key: printable ASCII without spaces, 8 to 4096 characters, '
                         'optionally followed by one newline'),
    'KEY_READ_BACK_FAILED': (500, 'the entry did not read back as written: rerun credential-set'),
}
REMEDIES = {code: remedy for code, (_, remedy) in CODES.items()}


class InferenceError(Exception):
    """A refusal (exit 2) or a failure (exit 1) with a stable code, its HTTP status on a listener and its remedy.
    grant, when set, is the grant the refused request presented (for its counters and the audit line)."""

    def __init__(self, code: str, detail: str, *, refusal: bool = True, grant=None):
        self.code, self.detail, self.refusal, self.grant = code, detail, refusal, grant
        self.status, self.remedy = CODES[code]
        super().__init__(f'{code}: {detail}. Remedy: {self.remedy}.')


def now_iso(epoch: float) -> str:
    return datetime.datetime.fromtimestamp(epoch, datetime.timezone.utc).isoformat(timespec='milliseconds')


def digest(token: str) -> str:
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


# ---------------------------------------------------------------- the family declarations and the configuration


@dataclasses.dataclass(frozen=True)
class Origin:
    """An upstream origin: scheme, host and port only."""
    scheme: str
    host: str
    port: int

    @property
    def loopback(self) -> bool:
        try:
            return ipaddress.ip_address(self.host).is_loopback
        except ValueError:
            return False

    @property
    def authority(self) -> str:
        host = f'[{self.host}]' if ':' in self.host else self.host
        return f'{host}:{self.port}'

    def text(self) -> str:
        return f'{self.scheme}://{self.authority}'


def parse_origin(value) -> Origin:
    """https://host[:port], or http://<loopback IP literal>[:port]; nothing else (CONFIG_ORIGIN_INVALID)."""
    def refuse(why):
        return InferenceError('CONFIG_ORIGIN_INVALID', f'the upstream origin {why}')
    if not isinstance(value, str) or not value or len(value) > 300 or any(c.isspace() for c in value):
        raise refuse('must be a non-empty string without spaces')
    try:
        parts = urllib.parse.urlsplit(value)
        port = parts.port
    except ValueError:
        raise refuse('is not a URL') from None
    if parts.scheme not in ('https', 'http'):
        raise refuse('must use https (or http to a loopback address)')
    if parts.username is not None or parts.password is not None or '@' in parts.netloc:
        raise refuse('must carry no user information')
    if parts.path not in ('', '/') or parts.query or parts.fragment or '?' in value or '#' in value:
        raise refuse('must be an origin only: no path, query or fragment')
    host = (parts.hostname or '').lower()
    try:
        ipaddress.ip_address(host)
    except ValueError:
        if not HOST_NAME.fullmatch(host):
            raise refuse('has a host that is neither a DNS name nor an IP literal') from None
    origin = Origin(parts.scheme, host, port or (443 if parts.scheme == 'https' else 80))
    if origin.scheme == 'http' and not origin.loopback:
        raise refuse('uses http to a non-loopback host: only a loopback IP literal may be plain http')
    return origin


@dataclasses.dataclass(frozen=True)
class Family:
    id: str
    status: str
    routes: frozenset
    query: str
    auth_header: str
    auth_scheme: str | None
    usage: str
    provider: str | None = None
    upstream: Origin | None = None
    models: tuple = ()

    def describe(self) -> dict:
        return {'id': self.id, 'status': self.status,
                'routes': [{'method': m, 'path': p} for m, p in sorted(self.routes)], 'query': self.query,
                'auth': {'header': self.auth_header, 'scheme': self.auth_scheme}, 'usage': self.usage,
                'provider': self.provider, 'upstream': None if self.upstream is None else self.upstream.text(),
                'models': list(self.models)}


@dataclasses.dataclass(frozen=True)
class BrokerConfig:
    control_port: int | None
    inference_port: int | None
    max_request_bytes: int
    max_ttl_s: int
    upstream_timeout_s: float
    families: dict

    def describe(self) -> dict:
        return {'format': CONFIG_FORMAT, 'control_port': self.control_port, 'inference_port': self.inference_port,
                'max_request_bytes': self.max_request_bytes, 'max_ttl_s': self.max_ttl_s,
                'upstream_timeout_s': self.upstream_timeout_s,
                'families': [family.describe() for family in self.families.values()]}


def _exact_keys(node, required: tuple, optional: tuple, code: str, where: str) -> None:
    if not isinstance(node, dict):
        raise InferenceError(code, f'{where} is not a mapping', refusal=code != 'DECLARATION_INVALID')
    unknown = sorted(str(k) for k in node if k not in required + optional)
    missing = [k for k in required if k not in node]
    if unknown or missing:
        raise InferenceError(code, f'{where}: unknown {unknown}, missing {missing}',
                             refusal=code != 'DECLARATION_INVALID')


def load_declarations(path: Path = FAMILIES_PATH) -> dict:
    """The declared families of families.json, validated (DECLARATION_INVALID), in declaration order."""
    def bad(why):
        return InferenceError('DECLARATION_INVALID', f'{path.name}: {why}', refusal=False)
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise bad(f'unreadable ({type(exc).__name__})') from None
    _exact_keys(data, ('format', 'description', 'families'), (), 'DECLARATION_INVALID', path.name)
    if data['format'] != DECLARATION_FORMAT or not isinstance(data['families'], list) or not data['families']:
        raise bad(f'format must be {DECLARATION_FORMAT} with a non-empty families list')
    families = {}
    for index, entry in enumerate(data['families']):
        where = f'families[{index}]'
        _exact_keys(entry, ('id', 'status', 'consumer', 'routes', 'query', 'auth', 'usage'), (),
                    'DECLARATION_INVALID', where)
        if not isinstance(entry['id'], str) or not FAMILY_ID.fullmatch(entry['id']) or entry['id'] in families:
            raise bad(f'{where}.id must be a distinct lower-case id')
        if entry['status'] not in ('provisional', 'pinned') or not isinstance(entry['consumer'], str):
            raise bad(f'{where}: status is provisional or pinned; consumer is text')
        if not isinstance(entry['routes'], list) or not entry['routes']:
            raise bad(f'{where}.routes must be a non-empty list')
        routes = set()
        for route in entry['routes']:
            _exact_keys(route, ('method', 'path'), (), 'DECLARATION_INVALID', f'{where}.routes[]')
            if route['method'] not in METHODS or not isinstance(route['path'], str) \
                    or not ROUTE_PATH.fullmatch(route['path']) or '..' in route['path'].split('/'):
                raise bad(f'{where}: a route is an HTTP method and an absolute path of plain segments')
            routes.add((route['method'], route['path']))
        if len(routes) != len(entry['routes']):
            raise bad(f'{where}.routes has a duplicate')
        if entry['query'] not in ('refuse', 'pass'):
            raise bad(f'{where}.query is refuse or pass')
        auth = entry['auth']
        _exact_keys(auth, ('header', 'scheme'), (), 'DECLARATION_INVALID', f'{where}.auth')
        if not isinstance(auth['header'], str) or not HEADER_NAME.fullmatch(auth['header']) \
                or auth['scheme'] not in (None, 'Bearer'):
            raise bad(f'{where}.auth is a lower-case header name and the scheme null or Bearer')
        if entry['usage'] not in USAGE_KINDS:
            raise bad(f'{where}.usage must be one of {list(USAGE_KINDS)}')
        families[entry['id']] = Family(entry['id'], entry['status'], frozenset(routes), entry['query'],
                                       auth['header'], auth['scheme'], entry['usage'])
    return families


def _refuse_secret_shaped(node, prefix: str) -> None:
    """The same rule as the decision 0009 loader (aieh_paths.SECRET_SHAPED), applied again to the component, so
    a configuration that reaches the broker by another route is refused too."""
    if isinstance(node, dict):
        for key, value in node.items():
            if paths.SECRET_SHAPED.search(str(key)):
                raise InferenceError('CONFIG_SECRET_SHAPED_KEY', f'{prefix}{key} is secret-shaped (its value is '
                                                                  'not shown)')
            _refuse_secret_shaped(value, f'{prefix}{key}.')
    elif isinstance(node, list):
        for index, value in enumerate(node):
            _refuse_secret_shaped(value, f'{prefix}[{index}].')


def _port(value, name: str, allow_ephemeral: bool):
    if value is None:
        return None
    low = 0 if allow_ephemeral else 1024
    if type(value) is not int or not low <= value <= 65535:
        raise InferenceError('CONFIG_PORT_INVALID', f'{name} must be an integer from 1024 to 65535')
    return value


def _limit(raw: dict, name: str):
    value = raw.get(name, DEFAULTS[name])
    low, high = LIMITS[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high \
            or (name != 'upstream_timeout_s' and type(value) is not int):
        raise InferenceError('CONFIG_LIMIT_INVALID', f'{name} must be a number from {low} to {high}')
    return value


def model_list(value, code: str, where: str) -> tuple:
    """A list of exact model identifiers: strings of MODEL_NAME, no wildcard, no duplicate."""
    if not isinstance(value, list):
        raise InferenceError(code, f'{where} must be a list')
    for model in value:
        if not isinstance(model, str) or WILDCARD.search(model) or not MODEL_NAME.fullmatch(model):
            raise InferenceError(code, f'{where} holds something that is not an exact model identifier')
    if len(set(value)) != len(value):
        raise InferenceError(code, f'{where} holds a duplicate')
    return tuple(value)


def load_config(raw, declarations: dict | None = None, *, allow_ephemeral: bool = False) -> BrokerConfig:
    """components.inference_broker of config.yml (None: every default, no port, nothing configured) over the
    declared families. allow_ephemeral admits port 0 (tests only)."""
    declarations = load_declarations() if declarations is None else declarations
    raw = {} if raw is None else raw
    if not isinstance(raw, dict):
        raise InferenceError('CONFIG_NOT_A_MAPPING', f'components.{COMPONENT} is not a mapping')
    _refuse_secret_shaped(raw, f'components.{COMPONENT}.')
    allowed = ('control_port', 'inference_port', 'families', *DEFAULTS)
    unknown = sorted(str(k) for k in raw if k not in allowed)
    if unknown:
        raise InferenceError('CONFIG_UNKNOWN_KEY', f'components.{COMPONENT}: unknown {unknown}')
    control = _port(raw.get('control_port'), 'control_port', allow_ephemeral)
    inference = _port(raw.get('inference_port'), 'inference_port', allow_ephemeral)
    if control is not None and control == inference and control != 0:
        raise InferenceError('CONFIG_PORT_INVALID', 'control_port and inference_port must differ')
    settings = raw.get('families') or {}
    if not isinstance(settings, dict):
        raise InferenceError('CONFIG_NOT_A_MAPPING', f'components.{COMPONENT}.families is not a mapping')
    families = {}
    for family_id, declared in declarations.items():
        families[family_id] = declared
    for family_id, entry in settings.items():
        where = f'components.{COMPONENT}.families.{family_id}'
        if family_id not in declarations:
            raise InferenceError('CONFIG_FAMILY_UNKNOWN', f'{where} is not a declared family')
        entry = {} if entry is None else entry
        if not isinstance(entry, dict):
            raise InferenceError('CONFIG_NOT_A_MAPPING', f'{where} is not a mapping')
        unknown = sorted(str(k) for k in entry if k not in ('provider', 'upstream', 'models'))
        if unknown:
            raise InferenceError('CONFIG_UNKNOWN_KEY', f'{where}: unknown {unknown}')
        provider = entry.get('provider')
        if provider is not None and (not isinstance(provider, str) or not PROVIDER_ID.fullmatch(provider)):
            raise InferenceError('CONFIG_PROVIDER_INVALID', f'{where}.provider is not a provider id')
        upstream = None if entry.get('upstream') is None else parse_origin(entry['upstream'])
        if upstream is not None and provider is None and not upstream.loopback:
            raise InferenceError('CONFIG_PROVIDER_REQUIRED', f'{where} has a non-loopback upstream and no provider')
        models = model_list(entry.get('models', []), 'CONFIG_MODEL_INVALID', f'{where}.models')
        families[family_id] = dataclasses.replace(declarations[family_id], provider=provider, upstream=upstream,
                                                  models=models)
    return BrokerConfig(control, inference, _limit(raw, 'max_request_bytes'), _limit(raw, 'max_ttl_s'),
                        _limit(raw, 'upstream_timeout_s'), families)


# ---------------------------------------------------------------- the exposure guard


class BrokerGuard(contract.ExposureGuard):
    """The F-06.3 exposure guard (I7) for a long-running process: it holds the provider key and every issued
    token, scans under a lock, and keeps counts instead of an ever-growing list of scanned names."""

    def __init__(self):
        super().__init__()
        self._lock = threading.Lock()
        self.scans = self.hits = 0

    def check(self, name: str, text) -> bool:
        with self._lock:
            clean = self.scan_text(name, text)
            self.scans += 1
            self.hits += 0 if clean else 1
            del self.scanned[:]
            del self.found[:]
            return clean


# ---------------------------------------------------------------- usage


def _count(value) -> int | None:
    return value if type(value) is int and value >= 0 else None


class UsageReader:
    """The usage counts of one answer, read as it streams: from the final usage-bearing event of a
    text/event-stream answer, else from the JSON body. 'unknown' when absent or unreadable. Provisional per
    family, like the route sets: pinned from observed traffic with them."""

    def __init__(self, kind: str, content_type: str | None):
        if kind not in USAGE_KINDS:
            raise ValueError(f'{kind!r} is not a usage extractor')
        self.kind = kind
        self.sse = (content_type or '').split(';')[0].strip().lower() == 'text/event-stream'
        self.buffer, self.data, self.overflow = bytearray(), [], False
        self.start = self.last = None

    def feed(self, chunk: bytes) -> None:
        if self.overflow:
            return
        self.buffer += chunk
        if not self.sse:
            if len(self.buffer) > USAGE_BODY_LIMIT:
                self._overflow()
            return
        while (end := self.buffer.find(b'\n')) >= 0:
            line = bytes(self.buffer[:end]).rstrip(b'\r')
            del self.buffer[:end + 1]
            self._line(line)
        if len(self.buffer) > SSE_LINE_LIMIT:
            self._overflow()

    def _overflow(self) -> None:
        self.overflow, self.buffer, self.data = True, bytearray(), []

    def _line(self, line: bytes) -> None:
        if not line:
            self._dispatch()
        elif line.startswith(b'data:'):
            self.data.append(line[5:][1:] if line[5:6] == b' ' else line[5:])

    def _dispatch(self) -> None:
        data, self.data = b'\n'.join(self.data), []
        if data and data != b'[DONE]':
            self._event(data)

    def _event(self, data: bytes) -> None:
        try:
            event = json.loads(data)
        except (ValueError, UnicodeDecodeError):
            return
        if not isinstance(event, dict):
            return
        if self.kind == 'anthropic-messages':
            message = event.get('message')
            if event.get('type') == 'message_start' and isinstance(message, dict) \
                    and isinstance(message.get('usage'), dict):
                self.start = message['usage']
            if isinstance(event.get('usage'), dict):
                self.last = event['usage']
        elif self.kind == 'openai-responses':
            response = event.get('response')
            if isinstance(response, dict) and isinstance(response.get('usage'), dict):
                self.last = response['usage']
            elif isinstance(event.get('usage'), dict):
                self.last = event['usage']
        elif isinstance(event.get('usage'), dict):
            self.last = event['usage']

    def finish(self):
        """{'input': n, 'output': n, 'total': n}, or 'unknown'."""
        if self.overflow:
            return 'unknown'
        if self.sse:
            if self.buffer:
                self._line(bytes(self.buffer).rstrip(b'\r'))
                self.buffer = bytearray()
            self._dispatch()
        elif self.buffer:
            self._event(bytes(self.buffer))
        if self.last is None:
            return 'unknown'
        if self.kind == 'anthropic-messages':
            output = _count(self.last.get('output_tokens'))
            start = self.start or {}
            parts = {name: _count(self.last.get(name)) if _count(self.last.get(name)) is not None
                     else _count(start.get(name))
                     for name in ('input_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens')}
            if output is None or parts['input_tokens'] is None:
                return 'unknown'
            used = sum(v for v in parts.values() if v is not None)
            return {'input': used, 'output': output, 'total': used + output}
        names = ('input_tokens', 'output_tokens') if self.kind == 'openai-responses' else \
            ('prompt_tokens', 'completion_tokens')
        used, output = _count(self.last.get(names[0])), _count(self.last.get(names[1]))
        if used is None or output is None:
            return 'unknown'
        total = _count(self.last.get('total_tokens'))
        return {'input': used, 'output': output, 'total': used + output if total is None else total}


# ---------------------------------------------------------------- the journal (integration store receipts)


class Journal:
    """The broker's receipts in the integration store (decision 0007 point 5; never the effects store): reserved,
    dispatched, confirmed with their detail, then read back. A sqlite connection belongs to the thread that
    opened it, so every store call runs on one journal thread; store_factory opens the store there. Every intent
    and detail passes the I7 scan before it is written; the read-back must equal what was scanned."""

    def __init__(self, store_factory: Callable, guard: BrokerGuard, actor: str = SERVICE):
        self._factory, self.guard, self.actor = store_factory, guard, actor
        self._pool = ThreadPoolExecutor(1, thread_name_prefix='aieh-inference-journal')
        self._store = None

    def _run(self, work: Callable):
        try:
            return self._pool.submit(work).result()
        except InferenceError:
            raise
        except Exception as exc:  # noqa: BLE001 - any store error is the journal's failure
            raise InferenceError('JOURNAL_FAILED', f'the integration store refused or failed '
                                                   f'({type(exc).__name__})', refusal=False) from None

    def _open(self):
        if self._store is None:
            self._store = self._factory()
        return self._store

    def record(self, key: str, intent: dict, detail: dict, *, conflict: str) -> dict:
        """Write one receipt and read it back; resumes a receipt an earlier call left unfinished (the same
        intent). Another intent under the key is CONFLICT."""
        def work():
            store = self._open()
            if not self.guard.check('receipt', json.dumps([intent, detail], sort_keys=True)):
                raise InferenceError('EXPOSURE_FOUND', f'the receipt {key} would hold a secret', refusal=False)
            try:
                record = store.reserve(key, intent, actor=self.actor).reservation
            except Exception as exc:
                if type(exc).__name__ == 'ConflictingReservation':
                    raise InferenceError(conflict, f'{key} already holds another receipt') from None
                raise
            if record.state == 'reserved':
                record = store.transition(key, 'dispatched', actor=self.actor, reason='journaled',
                                          expected_from='reserved')
            if record.state == 'dispatched':
                store.transition(key, 'confirmed', actor=self.actor, reason='journaled', detail=detail,
                                 expected_from='dispatched')
            held, events = store.get(key), store.events(key)
            if held is None or held.state != 'confirmed' or json.loads(held.intent_json) != json.loads(
                    json.dumps(intent)) or json.loads(events[-1].detail_json or 'null') != json.loads(
                    json.dumps(detail)):
                raise InferenceError('JOURNAL_FAILED', f'{key} did not read back as written', refusal=False)
            return {'operation_key': key, 'format': intent['format'], 'state': held.state,
                    'events': [event.to_state for event in events], 'read_back': True}
        return self._run(work)

    def close(self) -> None:
        """Close the store (best effort: a store that fails to close is dropped) and the journal thread."""
        def work():
            store, self._store = self._store, None
            if store is not None:
                try:
                    store.close()
                except Exception:  # noqa: BLE001 - nothing is left to write through it
                    pass
        try:
            self._pool.submit(work).result()
        finally:
            self._pool.shutdown(wait=True)


# ---------------------------------------------------------------- the audit


class AuditLog:
    """Append-only JSON lines, one per request, in DIRECTORY (the managed logs/inference category). A line that
    fails the I7 scan is withheld: only its time and EXPOSURE_FOUND are written."""

    def __init__(self, directory: Path, guard: BrokerGuard, clock: Callable = time.time):
        self.guard, self.clock = guard, clock
        stamp = datetime.datetime.fromtimestamp(clock(), datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        self.path = Path(directory) / f'audit-{stamp}-{secrets.token_hex(4)}.jsonl'
        self._lock = threading.Lock()
        self._file = open(self.path, 'x', encoding='utf-8', newline='\n')
        self.lines = self.withheld = 0

    def write(self, record: dict) -> None:
        record = {'format': AUDIT_FORMAT, 'time': now_iso(self.clock()), **record}
        text = json.dumps(record, sort_keys=True, separators=(',', ':'))
        if not self.guard.check('audit line', text):
            text = json.dumps({'format': AUDIT_FORMAT, 'time': record['time'], 'withheld': 'EXPOSURE_FOUND'},
                              sort_keys=True, separators=(',', ':'))
            self.withheld += 1
        with self._lock:
            self._file.write(text + '\n')
            self._file.flush()
            self.lines += 1

    def close(self) -> None:
        with self._lock:
            self._file.close()


# ---------------------------------------------------------------- egress

_TLS = None


def connect_upstream(origin: Origin, timeout: float) -> http.client.HTTPConnection:
    """The broker's only outbound connection: to ORIGIN, the configured upstream of the admitted token's family.
    https verifies against the system's trust roots; plain http only to a loopback address. http.client reads
    no proxy variable."""
    global _TLS
    if origin.scheme == 'https':
        if _TLS is None:
            _TLS = ssl.create_default_context()
        return http.client.HTTPSConnection(origin.host, origin.port, timeout=timeout, context=_TLS)
    if origin.scheme == 'http' and origin.loopback:
        return http.client.HTTPConnection(origin.host, origin.port, timeout=timeout)
    raise InferenceError('UPSTREAM_NOT_CONFIGURED', f'{origin.text()} is not an admissible upstream')


# ---------------------------------------------------------------- grants


@dataclasses.dataclass
class Grant:
    """One attempt's inference access. The token itself is never kept: only its sha256 digest and fingerprint."""
    digest: str
    fingerprint: str
    conversation_id: str
    attempt_id: str
    family: str
    models: tuple
    max_requests: int
    max_tokens: int
    issued_at: float
    expires_at: float
    requests: int = 0
    refused: int = 0
    in_flight: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    unknown_usage: int = 0
    bytes_in: int = 0
    bytes_out: int = 0
    revocation: dict | None = None      # trigger, revoker, revoked_at, the receipt's intent
    receipt: dict | None = None         # the revocation receipt, once read back

    def summary(self) -> dict:
        return {'requests': self.requests, 'refused': self.refused, 'in_flight': self.in_flight,
                'usage': {'input': self.input_tokens, 'output': self.output_tokens, 'total': self.total_tokens,
                          'unknown_responses': self.unknown_usage},
                'bytes': {'request': self.bytes_in, 'response': self.bytes_out}}

    def describe(self) -> dict:
        return {'token_fingerprint': self.fingerprint, 'attempt_id': self.attempt_id,
                'conversation_id': self.conversation_id, 'family': self.family, 'models': list(self.models),
                'budget': {'requests': self.max_requests, 'tokens': self.max_tokens},
                'issued_at': now_iso(self.issued_at), 'expires_at': now_iso(self.expires_at),
                'state': 'live' if self.revocation is None else 'revoked',
                'revocation': None if self.revocation is None else {
                    k: self.revocation[k] for k in ('trigger', 'revoker', 'revoked_at')},
                'receipt': self.receipt, **self.summary()}


@dataclasses.dataclass(frozen=True)
class ProviderKey:
    """The loaded provider key, the provider id it was stored under, and its source: the name of the credential
    provider it was read from."""
    provider: str
    key: str = dataclasses.field(repr=False)
    source: str = dataclasses.field(kw_only=True)

    @property
    def fingerprint(self) -> str:
        return contract.fingerprint(self.key)


@dataclasses.dataclass
class Admission:
    grant: Grant
    family: Family
    method: str
    target: str
    path: str
    model: str
    body: bytes
    headers: list


def _uuid(value, code: str, what: str) -> str:
    try:
        if isinstance(value, str) and str(uuid.UUID(value)) == value:
            return value
    except ValueError:
        pass
    raise InferenceError(code, f'{what} is not a canonical lower-case UUID')


class Broker:
    """The broker's state and decisions (socket-free: issue, revoke, admit, status) and its two listeners
    (start, stop). provider_key is the loaded key (None: no entry). connect stands in for connect_upstream in
    tests; clock for time.time."""

    def __init__(self, config: BrokerConfig, *, provider_key: ProviderKey | None, journal: Journal,
                 audit: AuditLog, guard: BrokerGuard, clock: Callable = time.time, connect: Callable | None = None):
        self.config, self.provider_key, self.journal, self.audit, self.guard = config, provider_key, journal, \
            audit, guard
        self.clock, self._connect = clock, connect or connect_upstream
        if provider_key is not None:
            guard.hold(provider_key.key)
        self._lock = threading.RLock()
        self._grants: dict[str, Grant] = {}     # sha256 digest of the token -> grant
        self._by_fingerprint: dict[str, Grant] = {}
        self._servers: list = []
        self.listeners: dict = {}
        self.start_receipt = None
        self._stopped = False

    # -- readiness

    def readiness(self, family: Family) -> str | None:
        """None when a token of FAMILY can be served; else why not."""
        if family.upstream is None:
            return 'no upstream origin is configured'
        if family.provider is not None and (self.provider_key is None
                                            or self.provider_key.provider != family.provider):
            return f'the key of provider {family.provider!r} is not loaded'
        return None

    def _key_for(self, family: Family) -> str | None:
        return None if family.provider is None else self.provider_key.key

    # -- control: issue, revoke, status

    def issue(self, body) -> dict:
        """One attempt token, journaled before it is returned: aieh-inference-grant/1."""
        self.housekeeping()
        _exact_keys(body, ('conversation_id', 'attempt_id', 'family', 'models', 'budget', 'ttl_s'), (),
                    'CONTROL_BODY_INVALID', 'the issue request')
        conversation = _uuid(body['conversation_id'], 'CONVERSATION_ID_INVALID', 'conversation_id')
        attempt = _uuid(body['attempt_id'], 'ATTEMPT_ID_INVALID', 'attempt_id')
        family = self.config.families.get(body['family']) if isinstance(body['family'], str) else None
        if family is None:
            raise InferenceError('FAMILY_UNKNOWN', 'family is not a declared family')
        models = model_list(body['models'], 'MODELS_INVALID', 'models')
        if not models:
            raise InferenceError('MODELS_INVALID', 'models is empty')
        refused = [m for m in models if m not in family.models]
        if refused:
            raise InferenceError('MODEL_NOT_ALLOWLISTED', f'{len(refused)} of the models are not in the '
                                                          f'{family.id} allowlist ({len(family.models)} allowed)')
        budget = body['budget']
        _exact_keys(budget, ('requests', 'tokens'), (), 'BUDGET_INVALID', 'budget')
        for name, high in BUDGET_LIMITS.items():
            if type(budget[name]) is not int or not 1 <= budget[name] <= high:
                raise InferenceError('BUDGET_INVALID', f'budget.{name} must be an integer from 1 to {high}')
        ttl = body['ttl_s']
        if type(ttl) is not int or not 1 <= ttl <= self.config.max_ttl_s:
            raise InferenceError('TTL_INVALID', f'ttl_s must be an integer from 1 to {self.config.max_ttl_s}')
        why = self.readiness(family)
        if why is not None:
            raise InferenceError('FAMILY_NOT_READY', f'{family.id}: {why}')
        token = TOKEN_PREFIX + secrets.token_urlsafe(32)
        self.guard.hold(token)
        issued = self.clock()
        grant = Grant(digest(token), contract.fingerprint(token), conversation, attempt, family.id, models,
                      budget['requests'], budget['tokens'], issued, issued + ttl)
        intent = {'format': GRANT_FORMAT, 'issuer': SERVICE, 'attempt_id': attempt, 'conversation_id': conversation,
                  'token_fingerprint': grant.fingerprint, 'family': family.id, 'models': list(models),
                  'budget': {'requests': grant.max_requests, 'tokens': grant.max_tokens},
                  'issued_at': now_iso(issued), 'expires_at': now_iso(grant.expires_at),
                  'upstream': family.upstream.text()}
        # One grant per attempt, durably: the journal refuses a second grant receipt under the attempt's key.
        receipt = self.journal.record(f'inference/attempt/{attempt}/grant', intent, {'state': 'live'},
                                      conflict='ATTEMPT_HAS_GRANT')
        with self._lock:
            self._grants[grant.digest] = self._by_fingerprint[grant.fingerprint] = grant
        return {'format': GRANT_FORMAT, 'token': token, **grant.describe(), 'grant_receipt': receipt}

    def revoke(self, body) -> dict:
        """Revoke a grant at once (its next request answers 401), then write its revocation receipt with the
        per-attempt summary."""
        self.housekeeping()
        _exact_keys(body, ('token_fingerprint', 'trigger', 'revoker'), (), 'CONTROL_BODY_INVALID',
                    'the revoke request')
        fingerprint, trigger, revoker = body['token_fingerprint'], body['trigger'], body['revoker']
        if trigger not in TRIGGERS:
            raise InferenceError('TRIGGER_UNKNOWN', f'trigger must be one of {list(TRIGGERS)}')
        if not isinstance(revoker, str) or not 1 <= len(revoker) <= 200 or not revoker.isprintable():
            raise InferenceError('REVOKER_INVALID', 'revoker must be 1 to 200 printable characters')
        with self._lock:
            grant = self._by_fingerprint.get(fingerprint) if isinstance(fingerprint, str) else None
            if grant is None:
                raise InferenceError('GRANT_UNKNOWN', 'no grant has that fingerprint')
            if grant.revocation is not None:
                raise InferenceError('GRANT_ALREADY_REVOKED', f'revoked at {grant.revocation["revoked_at"]}')
            self._mark_revoked(grant, trigger, revoker)
        self._write_revocation(grant)
        return {'format': REVOCATION_FORMAT, **grant.describe()}

    def _mark_revoked(self, grant: Grant, trigger: str, revoker: str) -> None:
        revoked_at = now_iso(self.clock())
        grant.revocation = {'trigger': trigger, 'revoker': revoker, 'revoked_at': revoked_at, 'intent': {
            'format': REVOCATION_FORMAT, 'attempt_id': grant.attempt_id, 'conversation_id': grant.conversation_id,
            'token_fingerprint': grant.fingerprint, 'family': grant.family, 'trigger': trigger, 'revoker': revoker,
            'revoked_at': revoked_at, 'summary': grant.summary()}}

    def _write_revocation(self, grant: Grant) -> None:
        grant.receipt = self.journal.record(f'inference/attempt/{grant.attempt_id}/revocation',
                                            grant.revocation['intent'], {'state': 'revoked'},
                                            conflict='GRANT_ALREADY_REVOKED')

    def housekeeping(self) -> None:
        """Revoke every expired grant (trigger expiry) and retry every revocation receipt not yet written."""
        now = self.clock()
        with self._lock:
            for grant in self._grants.values():
                if grant.revocation is None and now >= grant.expires_at:
                    self._mark_revoked(grant, 'expiry', EXPIRY_REVOKER)
            pending = [g for g in self._grants.values() if g.revocation is not None and g.receipt is None]
        for grant in pending:
            try:
                self._write_revocation(grant)
            except InferenceError:
                pass  # kept pending: retried at the next control call; status shows it

    def grant_status(self, fingerprint: str) -> dict:
        self.housekeeping()
        with self._lock:
            grant = self._by_fingerprint.get(fingerprint)
            if grant is None:
                raise InferenceError('GRANT_UNKNOWN', 'no grant has that fingerprint')
            return grant.describe()

    def status(self) -> dict:
        self.housekeeping()
        with self._lock:
            grants = list(self._grants.values())
        return {'format': STATUS_FORMAT, 'listeners': dict(self.listeners),
                'provider_key': None if self.provider_key is None else {
                    'provider': self.provider_key.provider, 'fingerprint': self.provider_key.fingerprint,
                    'source': self.provider_key.source},
                'families': [{**family.describe(), 'ready': self.readiness(family) is None,
                              'not_ready': self.readiness(family)} for family in self.config.families.values()],
                'grants': {'live': sum(g.revocation is None for g in grants),
                           'revoked': sum(g.revocation is not None for g in grants),
                           'receipts_pending': sum(g.revocation is not None and g.receipt is None for g in grants)},
                'audit': {'file': self.audit.path.name, 'lines': self.audit.lines, 'withheld': self.audit.withheld},
                'start_receipt': self.start_receipt}

    # -- inference: admission

    def _presented(self, headers) -> tuple[str, set]:
        """The one token the request presents, and the auth headers that carry it."""
        found: dict[str, set] = {}
        shapes = {(f.auth_header, f.auth_scheme) for f in self.config.families.values()}
        for header, scheme in sorted(shapes, key=str):
            for value in headers.get_all(header) or []:
                value = value.strip()
                if scheme is not None:
                    word, _, value = value.partition(' ')
                    if word.lower() != scheme.lower():
                        continue
                    value = value.strip()
                if value:
                    found.setdefault(value, set()).add((header, scheme))
        if not found:
            raise InferenceError('TOKEN_MISSING', 'no attempt token in any auth header')
        if len(found) > 1:
            raise InferenceError('TOKEN_AMBIGUOUS', f'{len(found)} different tokens')
        (token, carriers), = found.items()
        return token, carriers

    def _refuse(self, code: str, detail: str, grant: Grant | None) -> InferenceError:
        if grant is not None:
            with self._lock:
                grant.refused += 1
        return InferenceError(code, detail, grant=grant)

    def _budget(self, grant: Grant) -> None:
        if grant.requests >= grant.max_requests:
            raise self._refuse('BUDGET_REQUESTS_EXHAUSTED', f'{grant.requests} of {grant.max_requests}', grant)
        if grant.unknown_usage:
            raise self._refuse('BUDGET_USAGE_UNKNOWN', f'{grant.unknown_usage} answer(s) reported no usage', grant)
        if grant.total_tokens >= grant.max_tokens:
            raise self._refuse('BUDGET_TOKENS_EXHAUSTED', f'{grant.total_tokens} of {grant.max_tokens}', grant)

    def _live(self, grant: Grant) -> None:
        if grant.revocation is not None:
            code = 'TOKEN_EXPIRED' if grant.revocation['trigger'] == 'expiry' else 'TOKEN_REVOKED'
            raise self._refuse(code, f'at {grant.revocation["revoked_at"]}', grant)
        if self.clock() >= grant.expires_at:
            with self._lock:
                if grant.revocation is None:
                    self._mark_revoked(grant, 'expiry', EXPIRY_REVOKER)
            try:
                self._write_revocation(grant)
            except InferenceError:
                pass  # pending: retried at the next control call
            raise self._refuse('TOKEN_EXPIRED', f'at {now_iso(grant.expires_at)}', grant)

    def _read_body(self, headers, read: Callable, grant: Grant) -> bytes:
        if headers.get('transfer-encoding') is not None:
            raise self._refuse('BODY_LENGTH_REQUIRED', 'a chunked body', grant)
        lengths = headers.get_all('content-length') or []
        if not lengths:
            raise self._refuse('BODY_LENGTH_REQUIRED', 'no Content-Length', grant)
        if len(lengths) != 1 or not lengths[0].strip().isdigit():
            raise self._refuse('BODY_LENGTH_INVALID', 'not one decimal Content-Length', grant)
        length = int(lengths[0])
        if length > self.config.max_request_bytes:
            raise self._refuse('BODY_TOO_LARGE', f'{length} bytes', grant)
        body = read(length) if length else b''
        if len(body) != length:
            raise self._refuse('BODY_LENGTH_INVALID', 'the body ended early', grant)
        return body

    def _forward_headers(self, headers, family: Family) -> list:
        named = {v.strip().lower() for value in headers.get_all('connection') or [] for v in value.split(',')}
        stripped = NOT_FORWARDED | named | {f.auth_header for f in self.config.families.values()}
        return [(name, value) for name, value in headers.items() if name.lower() not in stripped]

    def admit(self, method: str, target: str, headers, read: Callable) -> Admission:
        """Admit one inference request or refuse it with a stable code: the token first, then the route, the
        budget, the body and its model, then the token's absence from what is forwarded. The request is counted
        against the budget atomically at the end."""
        token, carriers = self._presented(headers)
        with self._lock:
            grant = self._grants.get(digest(token)) if TOKEN_SHAPE.fullmatch(token) else None
        if grant is None:
            raise InferenceError('TOKEN_UNKNOWN', 'not a token this broker issued')
        self._live(grant)
        family = self.config.families[grant.family]
        if (family.auth_header, family.auth_scheme) not in carriers:
            raise self._refuse('TOKEN_WRONG_HEADER', f'the {family.id} family reads {family.auth_header}', grant)
        path, has_query, _ = target.partition('?')
        if (method, path) not in family.routes:
            raise self._refuse('ROUTE_NOT_ALLOWED', f'not a {family.id} route', grant)
        if has_query and family.query != 'pass':
            raise self._refuse('QUERY_NOT_ALLOWED', f'the {family.id} family admits no query', grant)
        with self._lock:
            self._budget(grant)
        body = self._read_body(headers, read, grant)
        try:
            document = json.loads(body)
        except (ValueError, UnicodeDecodeError):
            raise self._refuse('BODY_NOT_JSON', 'the body is not JSON', grant) from None
        if not isinstance(document, dict):
            raise self._refuse('BODY_NOT_JSON', 'the body is not a JSON object', grant)
        model = document.get('model')
        if not isinstance(model, str) or not model:
            raise self._refuse('MODEL_MISSING', 'no string model field', grant)
        if model not in grant.models or model not in family.models:
            raise self._refuse('MODEL_NOT_ALLOWED', "not in the token's model list", grant)
        forward = self._forward_headers(headers, family)
        if token in target or any(token in value for _, value in forward) or token.encode('ascii') in body:
            raise self._refuse('TOKEN_IN_REQUEST', 'the token is in the path, a forwarded header or the body', grant)
        if family.upstream is None:
            raise self._refuse('UPSTREAM_NOT_CONFIGURED', family.id, grant)
        if self.readiness(family) is not None:
            raise self._refuse('PROVIDER_KEY_ABSENT', family.id, grant)
        with self._lock:
            self._live(grant)
            self._budget(grant)
            grant.requests += 1
            grant.in_flight += 1
            grant.bytes_in += len(body)
        return Admission(grant, family, method, target, path, model, body, forward)

    def _recordable(self, what: str, text: str, shape: re.Pattern) -> bool:
        return shape.fullmatch(text) is not None and TOKEN_PREFIX not in text and self.guard.check(what, text)

    def observed_request(self, target, body: bytes | None) -> dict:
        """What the audit records of a refused request, for route and model discovery without a model call: the
        path, the query parameter names and, when the body of a request presenting a grant's token was read, its
        ``model``. Never a query value, a header, any other part of the body or a credential: a path segment or a
        name outside OBSERVED_WORD, a model outside MODEL_NAME, anything holding the token prefix, and anything the
        I7 scan finds (the provider key, every issued token, 40-hex runs) is counted under ``unrecorded`` instead."""
        unrecorded = {}
        path, _, query = target.partition('?')
        segments = path[1:].split('/')
        recorded_path = None
        if path.startswith('/') and len(segments) <= OBSERVED_SEGMENTS and (path == '/' or all(
                self._recordable('audit path', segment, OBSERVED_WORD) for segment in segments)):
            recorded_path = path
        else:
            unrecorded['path'] = 1
        names = [part.partition('=')[0] for part in query.split('&') if part]
        kept = sorted({name for name in names if self._recordable('audit query name', name, OBSERVED_WORD)})
        dropped = sum(1 for name in names if name not in kept) + max(0, len(kept) - OBSERVED_NAMES)
        if dropped:
            unrecorded['query_names'] = dropped
        model = None
        try:
            document = json.loads(body) if body else None
        except (ValueError, UnicodeDecodeError):
            document = None
        if isinstance(document, dict) and 'model' in document:
            candidate = document['model']
            if isinstance(candidate, str) and self._recordable('audit model', candidate, MODEL_NAME):
                model = candidate
            else:
                unrecorded['model'] = 1
        return {'path': recorded_path, 'query_names': kept[:OBSERVED_NAMES] if names else None, 'model': model,
                'unrecorded': unrecorded or None}

    # -- inference: the pass-through

    def serve_inference(self, handler) -> None:
        """One request on the inference listener: admit, pass through, account, audit. The accounting and the
        audit line happen before the last byte of the answer is sent, so that a client's next request already
        meets them."""
        started = time.monotonic()
        line = {'event': 'request', 'attempt_id': None, 'conversation_id': None, 'token_fingerprint': None,
                'family': None, 'method': handler.command if handler.command in METHODS else 'other',
                'path': None, 'query_names': None, 'model': None, 'unrecorded': None, 'request_bytes': 0,
                'response_bytes': 0, 'status': None, 'upstream_status': None, 'latency_ms': None, 'usage': None,
                'code': None}
        captured = []

        def audit(**fields):
            line.update(fields, latency_ms=round((time.monotonic() - started) * 1000, 1))
            self.audit.write(line)

        def read(length: int) -> bytes:
            handler.body_consumed = True
            captured.append(handler.rfile.read(length))
            return captured[-1]
        try:
            admission = self.admit(handler.command, handler.path, handler.headers, read)
        except InferenceError as exc:
            body = None
            if exc.grant is not None:
                line.update(attempt_id=exc.grant.attempt_id, conversation_id=exc.grant.conversation_id,
                            token_fingerprint=exc.grant.fingerprint, family=exc.grant.family)
                body = captured[0] if captured else _drain(handler)
            line.update(self.observed_request(handler.path, body))
            audit(status=exc.status, code=exc.code)
            _send_refusal(handler, exc)
            return
        grant, family = admission.grant, admission.family
        line.update(attempt_id=grant.attempt_id, conversation_id=grant.conversation_id,
                    token_fingerprint=grant.fingerprint, family=family.id, path=admission.path,
                    model=admission.model, request_bytes=len(admission.body))
        settled = []

        def settle(usage, sent: int, status, upstream_status, code) -> None:
            """Account the answer against the grant and write its audit line, once."""
            if settled:
                return
            settled.append(True)
            with self._lock:
                grant.in_flight -= 1
                grant.bytes_out += sent
                if isinstance(usage, dict):
                    grant.input_tokens += usage['input']
                    grant.output_tokens += usage['output']
                    grant.total_tokens += usage['total']
                elif upstream_status is not None and 200 <= upstream_status < 300:
                    grant.unknown_usage += 1
            audit(status=status, upstream_status=upstream_status, response_bytes=sent, usage=usage, code=code)
        try:
            self._relay(handler, admission, settle)
        finally:
            settle('unknown', 0, None, None, 'BROKER_ERROR')

    def _relay(self, handler, admission: Admission, settle: Callable) -> None:
        """Send the admitted request to the family's upstream and stream the answer back as it arrives; settle
        is called before the answer's last bytes are sent."""
        family = admission.family
        headers = list(admission.headers) + [('Host', family.upstream.authority),
                                             ('Content-Length', str(len(admission.body))),
                                             ('Accept-Encoding', 'identity')]
        key = self._key_for(family)
        if key is not None:
            headers.append((family.auth_header, f'{family.auth_scheme} {key}' if family.auth_scheme else key))
        connection = None
        try:
            connection = self._connect(family.upstream, self.config.upstream_timeout_s)
            connection.putrequest(admission.method, admission.target, skip_host=True, skip_accept_encoding=True)
            for name, value in headers:
                connection.putheader(name, value)
            connection.endheaders(admission.body)
            response = connection.getresponse()
        except (OSError, http.client.HTTPException, ValueError, InferenceError) as exc:
            if connection is not None:
                connection.close()
            error = InferenceError('UPSTREAM_UNREACHABLE', type(exc).__name__, grant=admission.grant)
            settle('unknown', 0, error.status, None, error.code)
            _send_refusal(handler, error)
            return
        status, total = response.status, response.length
        reader = UsageReader(family.usage, response.getheader('content-type'))
        sent, code = 0, None
        try:
            handler.send_response_only(status, response.reason)
            for name, value in response.getheaders():
                if name.lower() not in NOT_RELAYED:
                    handler.send_header(name, value)
            chunked = total is None
            if chunked:
                handler.send_header('Transfer-Encoding', 'chunked')
            else:
                handler.send_header('Content-Length', str(total))
            handler.end_headers()
            while True:
                try:
                    data = response.read1(65536)
                except (OSError, http.client.HTTPException):
                    code = 'UPSTREAM_STREAM_BROKEN'
                    handler.close_connection = True
                    break
                if not data:
                    if chunked:
                        settle(reader.finish(), sent, status, status, None)
                        handler.wfile.write(b'0\r\n\r\n')
                    break
                reader.feed(data)
                if not chunked and sent + len(data) >= total:
                    settle(reader.finish(), sent + len(data), status, status, None)
                handler.wfile.write(b'%x\r\n%s\r\n' % (len(data), data) if chunked else data)
                sent += len(data)
        except OSError:
            code = 'CLIENT_GONE'
            handler.close_connection = True
        finally:
            connection.close()
        settle(reader.finish() if code is None else 'unknown', sent, status, status, code)

    # -- the listeners

    def start(self) -> dict:
        """Bind both listeners to 127.0.0.1, write the start receipt (the provider key's fingerprint, recorded
        once), then serve. Returns the bound ports."""
        if self.config.control_port is None or self.config.inference_port is None:
            raise InferenceError('CONFIG_INCOMPLETE', 'a listener port is not configured')
        try:
            for name, port, handler in (('control', self.config.control_port, _ControlHandler),
                                        ('inference', self.config.inference_port, _InferenceHandler)):
                server = _Server((LOOPBACK, port), handler, self)
                self._servers.append(server)
                self.listeners[name] = {'address': LOOPBACK, 'port': server.server_address[1]}
            stamp = now_iso(self.clock())
            intent = {'format': START_FORMAT, 'service': SERVICE, 'started_at': stamp, 'pid': os.getpid(),
                      'listeners': self.listeners, 'audit_file': self.audit.path.name,
                      'provider_key': None if self.provider_key is None else {
                          'entry': ENTRY, 'provider': self.provider_key.provider,
                          'fingerprint': self.provider_key.fingerprint, 'source': self.provider_key.source},
                      'families': [{'id': f.id, 'status': f.status, 'upstream': None if f.upstream is None
                                    else f.upstream.text(), 'provider': f.provider, 'models': list(f.models)}
                                   for f in self.config.families.values()]}
            self.start_receipt = self.journal.record(f'inference/broker-start/{stamp}-{secrets.token_hex(4)}',
                                                     intent, {'state': 'started'}, conflict='JOURNAL_FAILED')
            self.audit.write({'event': 'broker-start', 'receipt': self.start_receipt['operation_key']})
        except BaseException:
            self._close_servers()
            raise
        for server in self._servers:
            threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.05},
                             name=f'aieh-inference-{server.server_address[1]}', daemon=True).start()
        return dict(self.listeners)

    def _close_servers(self) -> None:
        for server in self._servers:
            server.server_close()
        self._servers.clear()

    def stop(self) -> None:
        """Stop both listeners, write the pending receipts, and close the journal and the audit. Live grants
        end with the process (an audit line counts them)."""
        if self._stopped:
            return
        self._stopped = True
        stoppers = [threading.Thread(target=server.shutdown) for server in self._servers]
        for stopper in stoppers:
            stopper.start()
        for stopper in stoppers:
            stopper.join()
        self._close_servers()
        try:
            self.housekeeping()
            with self._lock:
                live = [g.fingerprint for g in self._grants.values() if g.revocation is None]
            self.audit.write({'event': 'broker-stop', 'live_grants_ended': live})
        finally:
            self.journal.close()
            self.audit.close()


class _Server(http.server.ThreadingHTTPServer):
    """A loopback listener: no address reuse (on Windows, exclusive use of the port), no name lookup."""
    allow_reuse_address = False
    daemon_threads = True

    def __init__(self, address, handler, broker: Broker):
        self.broker = broker
        super().__init__(address, handler)

    def server_bind(self):
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = LOOPBACK, self.server_address[1]

    def handle_error(self, request, client_address):
        """An unexpected error in a handler: an audit line naming its type, never a traceback on stderr."""
        try:
            self.broker.audit.write({'event': 'handler-error', 'error': type(sys.exc_info()[1]).__name__})
        except Exception:  # noqa: BLE001 - nothing more can be recorded
            pass


class _Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    server_version, sys_version = 'aieh-inference-broker', ''
    timeout = 120

    def log_message(self, format, *args):  # noqa: A002 - the audit is the broker's only log
        pass

    def version_string(self):
        return self.server_version


def _send_json(handler, status: int, payload: dict, *, close: bool) -> None:
    data = (json.dumps(payload, sort_keys=True) + '\n').encode('utf-8')
    handler.send_response_only(status)
    handler.send_header('Content-Type', 'application/json')
    handler.send_header('Content-Length', str(len(data)))
    if close:
        handler.send_header('Connection', 'close')
        handler.close_connection = True
    handler.end_headers()
    handler.wfile.write(data)


def _drain(handler) -> bytes | None:
    """Read an unread request body of at most DRAIN_LIMIT bytes before a refusal, so that the closing connection
    does not reset the refusal away, and return it (the refused-request audit reads its model, nothing else); a
    larger or chunked body is left and the connection closed."""
    if getattr(handler, 'body_consumed', False):
        return None
    handler.body_consumed = True
    length = handler.headers.get('content-length') or ''
    if handler.headers.get('transfer-encoding') is None and length.isdigit() and int(length) <= DRAIN_LIMIT:
        try:
            return handler.rfile.read(int(length))
        except OSError:
            pass
    return None


def _send_refusal(handler, exc: InferenceError) -> None:
    _drain(handler)
    payload = {'aieh_refusal': {'code': exc.code, 'detail': exc.detail, 'remedy': exc.remedy}}
    if not handler.server.broker.guard.check('refusal', json.dumps(payload)):
        payload = {'aieh_refusal': {'code': 'EXPOSURE_FOUND', 'detail': 'withheld', 'remedy': REMEDIES[
            'EXPOSURE_FOUND']}}
    try:
        _send_json(handler, exc.status, payload, close=True)
    except OSError:
        handler.close_connection = True


class _InferenceHandler(_Handler):
    def _serve(self):
        self.body_consumed = False
        self.server.broker.serve_inference(self)

    do_GET = do_HEAD = do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = do_CONNECT = do_TRACE = _serve


class _ControlHandler(_Handler):
    def _serve(self):
        self.body_consumed = False
        broker = self.server.broker
        try:
            if self.headers.get('host') != f'{LOOPBACK}:{self.server.server_address[1]}' \
                    or self.headers.get('origin') is not None:
                raise InferenceError('CONTROL_CALLER_REFUSED', 'not a direct loopback call')
            path = self.path
            if self.command == 'GET' and path == '/v1/status':
                status, payload = 200, broker.status()
            elif self.command == 'GET' and path.startswith('/v1/grants/'):
                status, payload = 200, broker.grant_status(path[len('/v1/grants/'):])
            elif self.command == 'POST' and path in ('/v1/grants', '/v1/grants/revoke'):
                body = self._json_body()
                status, payload = (201, broker.issue(body)) if path == '/v1/grants' else (200, broker.revoke(body))
            else:
                raise InferenceError('CONTROL_ROUTE_UNKNOWN', f'{self.command} is not a control route here')
        except InferenceError as exc:
            _send_refusal(self, exc)
            return
        text = json.dumps(payload, sort_keys=True)
        if status != 201 and not broker.guard.check('control answer', text):
            _send_refusal(self, InferenceError('EXPOSURE_FOUND', 'the answer was withheld', refusal=False))
            return
        _send_json(self, status, payload, close=False)

    def _json_body(self):
        if (self.headers.get('content-type') or '').split(';')[0].strip().lower() != 'application/json':
            raise InferenceError('CONTROL_CONTENT_TYPE', 'not application/json')
        length = self.headers.get('content-length')
        if self.headers.get('transfer-encoding') is not None or length is None or not length.isdigit() \
                or int(length) > CONTROL_BODY_LIMIT:
            raise InferenceError('CONTROL_BODY_INVALID', 'a Content-Length of at most 64 KiB is required')
        self.body_consumed = True
        try:
            return json.loads(self.rfile.read(int(length)))
        except (ValueError, UnicodeDecodeError):
            raise InferenceError('CONTROL_BODY_INVALID', 'the body is not JSON') from None

    do_GET = do_HEAD = do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = do_CONNECT = do_TRACE = _serve


# ---------------------------------------------------------------- the credential set command


def read_key(stream) -> str:
    """The provider key from STREAM (standard input): never a terminal; exactly the key, optionally followed by
    one newline."""
    if stream.isatty():
        raise InferenceError('KEY_STDIN_TTY', 'standard input is a terminal')
    raw = getattr(stream, 'buffer', stream).read(KEY_LIMIT + 3)
    try:
        text = raw.decode('utf-8') if isinstance(raw, bytes) else raw
    except UnicodeDecodeError:
        raise InferenceError('KEY_INVALID', 'standard input is not UTF-8') from None
    for ending in ('\r\n', '\n'):
        if text.endswith(ending):
            text = text[:-len(ending)]
            break
    if not 8 <= len(text) <= KEY_LIMIT or not all(33 <= ord(c) <= 126 for c in text):
        raise InferenceError('KEY_INVALID', 'standard input is not exactly one key')
    return text


def credential_set(provider, store, provider_id: str, key: str, *, guard) -> dict:
    """Store KEY as the entry "AIEH model provider" (user PROVIDER_ID) through PROVIDER, under an
    aieh-credential-act/1 receipt in STORE (provision, or rotate when an entry exists), and read it back.
    Fingerprints only."""
    if not isinstance(provider_id, str) or not PROVIDER_ID.fullmatch(provider_id):
        raise InferenceError('PROVIDER_ID_INVALID', 'not a provider id')
    guard.hold(key)
    previous = provider.get(ENTRY)
    before = None if previous is None else contract.fingerprint(previous[1])
    previous_user = None if previous is None else previous[0]
    del previous
    receipt = credentials.ActReceipt(
        store, verb='provision' if before is None else 'rotate', service=SERVICE, entry=ENTRY, user=provider_id,
        role=None, fingerprint_before=before, provider=credentials.describe(provider)['provider'],
        trigger='owner direction', revoker='Owner (inference_broker.py credential-set)',
        actor='inference_broker credential-set', guard=guard).begin()
    try:
        receipt.dispatched()
        provider.set(ENTRY, provider_id, key, 'AIEH inference broker: the model provider key (decision 0015)')
        held = provider.get(ENTRY)
        if held is None or held[0] != provider_id or held[1] != key:
            raise InferenceError('KEY_READ_BACK_FAILED', 'the entry does not hold what was written', refusal=False)
        del held
    except BaseException as exc:
        receipt.abort(exc)
        raise
    after = contract.fingerprint(key)
    result = receipt.finish({'fingerprint_after': after, 'previous_user': previous_user, 'read_back': True})
    return {'format': CREDENTIAL_SET_FORMAT, 'entry': ENTRY, 'user': provider_id,
            'verb': 'provision' if before is None else 'rotate', 'fingerprint_before': before,
            'fingerprint': after, 'receipt': result}


# ---------------------------------------------------------------- command line


@dataclasses.dataclass
class Context:
    """What the command line acts on. managed_context() is the Owner's: config.yml, the credential provider the
    harness chooses, the managed root's integration store and logs. A test passes its own, whole."""
    component: Callable          # -> the raw components.inference_broker (or None)
    provider: Callable           # -> a CredentialProvider
    store: Callable              # -> an open integration store (the caller closes it)
    logs: Callable               # -> the audit directory, existing
    stdin: object
    out: object
    err: object
    wait: Callable               # serve: blocks while the broker runs
    allow_ephemeral: bool = False


def _wait_for_interrupt(broker: Broker) -> None:
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass


def managed_context() -> Context:
    store_module = _load('integration_store', REPO / 'integrations' / 'store' / 'integration_store.py')
    res = paths.resolve()
    return Context(component=lambda: res.components.get(COMPONENT), provider=credentials.select_provider,
                   store=lambda: store_module.open_store(paths.ensure('state', res, 'integration')
                                                         / 'integration.sqlite'),
                   logs=lambda: paths.ensure('logs', res, 'inference'), stdin=sys.stdin, out=sys.stdout,
                   err=sys.stderr, wait=_wait_for_interrupt)


def _serve(ctx: Context, guard: BrokerGuard) -> dict:
    config = load_config(ctx.component(), allow_ephemeral=ctx.allow_ephemeral)
    if config.control_port is None or config.inference_port is None:
        raise InferenceError('CONFIG_INCOMPLETE', 'a listener port is not configured')
    provider = ctx.provider()
    entry = contract.WatchedProvider(provider, guard).get(ENTRY)
    provider_key = None if entry is None else ProviderKey(entry[0], entry[1],
                                                          source=credentials.describe(provider)['provider'])
    del entry
    journal = Journal(ctx.store, guard)
    try:
        audit = AuditLog(ctx.logs(), guard)
    except BaseException:
        journal.close()
        raise
    broker = Broker(config, provider_key=provider_key, journal=journal, audit=audit, guard=guard)
    try:
        broker.start()
    except BaseException:
        try:
            journal.close()
        finally:
            audit.close()
        raise
    try:
        ctx.err.write(f'inference-broker: serving: {json.dumps(broker.listeners, sort_keys=True)}\n')
        ctx.wait(broker)
        return broker.status()
    finally:
        broker.stop()


def main(argv=None, context: Context | None = None) -> int:
    parser = argparse.ArgumentParser(prog='inference_broker.py', description='The inference broker (S-03.2; '
                                     'decision 0015 as amended). Exit 0 done, 1 failed, 2 refused.')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('config', help='validate components.inference_broker and print the effective families; reads '
                                  'no credential, opens no listener')
    cred = sub.add_parser('credential-set', help='store the provider key, read from standard input only, as the '
                                                 'entry "AIEH model provider"; prints its fingerprint')
    cred.add_argument('--provider', required=True, help='the provider id (the entry\'s user name)')
    sub.add_parser('serve', help='run the broker on its two loopback listeners until interrupted')
    args = parser.parse_args(argv)
    guard = BrokerGuard()
    report, message, code = None, '', 0
    try:
        ctx = context or managed_context()
        out, err = ctx.out, ctx.err
        if args.command == 'config':
            report = load_config(ctx.component(), allow_ephemeral=ctx.allow_ephemeral).describe()
        elif args.command == 'credential-set':
            if not PROVIDER_ID.fullmatch(args.provider):
                raise InferenceError('PROVIDER_ID_INVALID', 'not a provider id')
            key = read_key(ctx.stdin)
            provider = contract.WatchedProvider(ctx.provider(), guard)
            store = ctx.store()
            try:
                report = credential_set(provider, store, args.provider, key, guard=guard)
            finally:
                store.close()
            del key
        else:
            report = _serve(ctx, guard)
    except paths.PathsError as exc:
        out, err = (context.out, context.err) if context else (sys.stdout, sys.stderr)
        message, code = f'inference-broker: {exc}\n', 2
    except (InferenceError, contract.LifecycleError) as exc:
        out, err = (context.out, context.err) if context else (sys.stdout, sys.stderr)
        message, code = f'inference-broker: {exc}\n', 2 if exc.refusal else 1
    except Exception as exc:  # noqa: BLE001 - reported by type, after the exposure scan
        out, err = (context.out, context.err) if context else (sys.stdout, sys.stderr)
        message, code = f'inference-broker: FAILED: {type(exc).__name__}: {str(exc)[:300]}\n', 1
    text = '' if report is None else json.dumps(report, indent=2, sort_keys=True) + '\n'
    clean = guard.check('report', text) and guard.check('message', message)
    guard.clear()
    if not clean:
        err.write('inference-broker: ' + str(InferenceError('EXPOSURE_FOUND', 'the output would hold a secret',
                                                            refusal=False)) + '\n')
        return 1
    err.write(message)
    out.write(text)
    err.write(f'inference-broker: I7 no-exposure scan: clean ({guard.scans} outputs scanned)\n')
    return code


if __name__ == '__main__':
    sys.exit(main())
