"""The inference broker (plan leaf S-03.2, slice 1: the broker core, built and tested offline; decision 0015 as
amended by its amendment 1; decisions 0007 points 4 and 5, 0009 and 0013 point 6).

A host-side process in the trusted management domain (inventory principal inference-broker), the sole holder of
the model provider's key. It serves two listeners, both bound to 127.0.0.1 only:

- the control listener (issue, revoke, status; never forwarded; same-account only, disclosed under decision
  0013 point 6): it issues one random attempt token per attempt, bound to the attempt and its conversation, to
  one declared API family, to a model list and to a lifetime (within max_ttl_s), with no request or token budget
  (retired by S-03.6: an issue request carrying one is refused BUDGET_RETIRED). The token is returned once and
  kept only as its sha256 digest; the grant is journaled by the token's fingerprint in the integration store
  (operation key inference/attempt/<attempt id>/grant, format aieh-inference-grant/2).
  Revocation is immediate (the next request answers 401) and leaves a receipt with the per-attempt summary
  (inference/attempt/<attempt id>/revocation, format aieh-inference-revocation/1): fingerprint, attempt,
  trigger, revoker, requests, usage, refusals. Never the effects store. A grant is revoked by its fingerprint,
  or (E-05.6) by its conversation and attempt; one that finds no grant leaves a tombstone under the same key
  inference/attempt/<attempt id>/grant (format aieh-inference-attempt-tombstone/1), after which that attempt's
  issue is refused (GRANT_ATTEMPT_REVOKED); per attempt, an issue's receipt and registration and such a
  revocation's lookup and tombstone run one at a time.
- the inference listener (the only forward target): a request is admitted only with a valid, unrevoked,
  unexpired token in its family's auth header, a method and path in that family's declared route set, a
  `model` in both the token's list and the family's allowlist. It is then passed through untranslated to that
  family's one upstream origin, with the provider key in the family's auth header in place of the token (the
  token never leaves the host toward the upstream), and the answer is streamed back as it arrives. Every refusal
  answers with a stable code (CODES). Usage is read and counted for the audit and the per-attempt summary as
  information only: no request is refused for a request count, a usage count or an answer without usage.

The families are declared in families.json beside this module (format aieh-inference-families/1): each has an
id, its exact method and path set (provisional until pinned from observed traffic, amendment 1 point 3), its
query rule (refuse, or an exact finite set of whole query strings: S-03.3 retired pass), the auth header shape it
reads and forwards, and its usage extractor. The Owner's settings live in
components.inference_broker of the managed config.yml (decision 0009; no secret: the loader refuses
secret-shaped keys): the two listener ports, and per family the provider id, the upstream origin and the model
allowlist. The shipped allowlists are empty, so every issuance is refused until the Owner names models.

Egress: the broker opens a connection only in connect_upstream, and only to the configured upstream origin of
the admitted token's family (https with the system's trust roots, or http to a loopback address for a local
model server). It imports no litellm, fetches no cost map, sends no telemetry and checks for no update; it
honours no proxy variable. At connect time (http.client connects at the first request) the connection writes an
upstream-connect audit line with its peer address (IP and port) and local address, its origin, family and attempt,
no secret (S-03.2): the broker's own record, which the live census (inference_census.py) compares with what the
operating system shows. The status answer and the start receipt name the broker's pid, for the census.

Audit: one append-only JSON line per request in <managed root>/persistent/logs/inference/ (time, attempt and
conversation id, token fingerprint, family, method, path, model, byte counts, status and upstream status,
latency, usage), never a body, a header, the token or the provider key; every line, response and receipt
passes the I7 no-exposure scan of F-06.3 first, and a line that fails it is withheld.

The provider key is one entry of the harness's credential provider (F-06.3): name "AIEH model provider", user
the provider id. Only the Owner-run credential-set and credential-enter commands write it, and both write an
aieh-credential-act/1 receipt with the fingerprint only. credential-set reads the key from standard input only
(never argv, the environment, a file or config.yml). credential-enter (S-03.3, the Owner's act 2 of OA-12) is the
one the Owner runs in his own console window: standard input must be an interactive console (on Windows, its handle
has a console mode), else it refuses before prompting (KEY_CONSOLE_REQUIRED); the key is pasted once at a hidden
prompt (getpass: echo off, read from the console itself, never a fallback that echoes); a value that is not
key-shaped (ENTERED_KEY_RULES: sk-ant-api, then only [A-Za-z0-9_-], 40 to 512 characters; an admin key, an empty
value and any whitespace refused, never stripped) is refused naming the rule, never the value
(KEY_NOT_KEY_SHAPED); an existing entry is replaced only with --replace (KEY_ENTRY_EXISTS). The key is held in
memory only, and the command prints nothing derived from it (no fingerprint, length or prefix): only that it is
stored under the entry name, and a reminder to clear the clipboard.

The provider envelope (plan leaf S-03.5, slice 1): before it reads the provider key or opens a listener, serve
refuses any family whose upstream is not loopback (Origin.loopback: an IP literal only) unless the integration
store holds the governing, confirmed, unexpired authorization recorder receipt (decision 0012) of operation kind
provider-envelope whose target is the canonical digest of the live envelope (inference_envelope.py,
aieh-provider-envelope/2: the provider id, the one upstream origin, the expiry and the model selection, projected
from this snapshot and components.inference_broker.envelope), and whose manifest is the canonical manifest of that
envelope. The read side is integrations/owner/envelope_decisions.py, handed to serve as Context.authorization.
The broker holds the authorization it was given (authorize: an object minted in this process) and refuses, at
admission, a request of a bound family whose provider or upstream is not the held one or whose envelope has
expired. A configuration whose upstreams are all loopback starts as before, and reads no authorization.
The envelope carries no spending limit and the broker enforces no cumulative cap: S-03.6 retired the cap, its
per-run ledger in the integration store and their refusals (decision 0021 amendment 1); spending is bounded by
the provider account's own limits. Once the broker's own stop begins, a new request is refused BROKER_STOPPING.

Provider-side reach (S-03.3, before the first paid call; the OA-12 package section 3 point 5): the authorized scope
is plain model calls, so a request must not ask the provider to reach or run anything outside the request. A
family's reach checker (REACH_CHECKERS) reads every admitted request's JSON body; anthropic-messages refuses a
top-level mcp_servers or container, a tool whose type is present and not custom (every server tool and every
provider-defined tool type: fail closed), a tools value that is not a list or a tools entry that is not an object
(tools-shape: fail closed), and anywhere in the body a source of type url or file or a
container_upload block (PROVIDER_REACH_REFUSED; the audit names the rule and the key or type name, never a value).
A family with no checker (the OpenAI families today) is refused at start when its upstream is not loopback
(FAMILY_REACH_UNCHECKED).

The stop (S-03.2, before the Owner's act A2): serve waits on the broker's one stop event in slices of STOP_POLL_S,
so that an interrupt is delivered on every platform (an indefinite wait ignores Ctrl-C on Windows). SIGINT,
SIGBREAK (Windows) and SIGTERM, where the platform has them, and the control listener's POST /v1/stop (the stop
from a session with no console; inference_control.py stop) set it. From then on every new request is refused
BROKER_STOPPING; the listeners close; requests already admitted are given at most STOP_DRAIN_CEILING_S to finish,
then cut (their audit line says BROKER_STOPPED, never an upstream answer); the broker-stop audit line and the
pending receipts are written, and serve exits 0. A second interrupt during a stop that has not finished exits at
once with FORCED_EXIT, writing nothing further.

  <tools python> -I -B integrations/inference/inference_broker.py config
  <tools python> -I -B integrations/inference/inference_broker.py envelope [--operation ID]
  <tools python> -I -B integrations/inference/inference_broker.py credential-set --provider ID   (key on stdin)
  <tools python> -I -B integrations/inference/inference_broker.py credential-enter --provider ID [--replace]
  <tools python> -I -B integrations/inference/inference_broker.py serve

Exit 0 done, 1 failed, 2 refused (a stable code), 3 forced (serve: a second interrupt during the stop).
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
import signal
import socket
import socketserver
import ssl
import sys
import threading
import time
import urllib.parse
import uuid
import weakref
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
inference_envelope = _load('aieh_inference_envelope', HERE / 'inference_envelope.py')
ENVELOPE_DECISIONS = REPO / 'integrations' / 'owner' / 'envelope_decisions.py'   # the read side (managed_context)

FAMILIES_PATH = HERE / 'families.json'
DECLARATION_FORMAT = 'aieh-inference-families/1'
COMPONENT = 'inference_broker'
ENTRY = 'AIEH model provider'
SERVICE = 'inference-broker'
GRANT_FORMAT = 'aieh-inference-grant/2'      # /1 carried the request and token budget S-03.6 retired
REVOCATION_FORMAT = 'aieh-inference-revocation/1'
# E-05.6: a revocation by conversation and attempt that finds no grant leaves this tombstone under the attempt's
# grant receipt key, so that no grant of that attempt is ever registered after it (Broker.revoke).
TOMBSTONE_FORMAT = 'aieh-inference-attempt-tombstone/1'
START_FORMAT = 'aieh-inference-broker-start/1'
STOP_FORMAT = 'aieh-inference-broker-stop/1'     # the control listener's answer to POST /v1/stop
# The stop (S-03.2): serve's wait on the stop event runs in slices of STOP_POLL_S, the interval at which the
# interpreter can run a signal handler (a functional bound, not a wait for work); the stop gives requests already
# admitted at most STOP_DRAIN_CEILING_S to finish, then cuts them, and gives a cut request's own thread at most
# STOP_CUT_CEILING_S to finish writing its audit line. A second interrupt during the stop exits FORCED_EXIT.
STOP_POLL_S = 0.25
STOP_DRAIN_CEILING_S = 2.0     # with STOP_CUT_CEILING_S at most 3 s: Windows gives a closing console about 5 s
STOP_CUT_CEILING_S = 1.0
STOP_SIGNALS = ('SIGINT', 'SIGBREAK', 'SIGTERM')
FORCED_EXIT = 3
AUDIT_FORMAT = 'aieh-inference-audit/1'
STATUS_FORMAT = 'aieh-inference-broker-status/1'
CONFIG_FORMAT = 'aieh-inference-config/1'
CREDENTIAL_SET_FORMAT = 'aieh-inference-credential-set/1'
CREDENTIAL_ENTER_FORMAT = 'aieh-inference-credential-enter/1'
ENVELOPE_REPORT_FORMAT = 'aieh-provider-envelope-report/1'
LOOPBACK = '127.0.0.1'
TOKEN_PREFIX = 'aieh-inf-'
TOKEN_SHAPE = re.compile(r'aieh-inf-[A-Za-z0-9_-]{43}')
FINGERPRINT_SHAPE = re.compile(r'sha256:[0-9a-f]{16}')
TRIGGERS = ('attempt end', 'suspected exposure', 'definition revocation', 'policy revision', 'expiry',
            'owner direction')  # decision 0007 point 5
EXPIRY_REVOKER = 'inference-broker (expiry)'
REVOKER_LIMIT = 200


def valid_revoker(value) -> bool:
    """A revoker's name as a revocation takes it: 1 to REVOKER_LIMIT printable characters."""
    return isinstance(value, str) and 1 <= len(value) <= REVOKER_LIMIT and value.isprintable()

FAMILY_ID = re.compile(r'[a-z0-9][a-z0-9-]{0,63}')
PROVIDER_ID = re.compile(r'[a-z0-9][a-z0-9._-]{0,63}')
MODEL_NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:@/-]{0,127}')
WILDCARD = re.compile(r'[*?\[\]]')
HEADER_NAME = re.compile(r'[a-z0-9][a-z0-9-]{0,63}')
HEADER_PREFIX = re.compile(r'[a-z0-9][a-z0-9-]{0,62}-')     # a declared forwarded-header prefix ends with '-'
HEADER_CONTROL = re.compile(r'[\x00-\x08\x0a-\x1f\x7f]')     # a control character in a header value (HTAB allowed)
HOST_NAME = re.compile(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*')
ROUTE_PATH = re.compile(r'/(?:[A-Za-z0-9._~-]+/)*[A-Za-z0-9._~-]+')
# A declared whole query string (S-03.3): name=value pairs of plain characters joined by '&', compared byte for byte
# with the request target's raw query (no parsing, decoding, reordering or case folding).
QUERY_STRING = re.compile(r'[A-Za-z0-9._~-]+=[A-Za-z0-9._~-]*(?:&[A-Za-z0-9._~-]+=[A-Za-z0-9._~-]*)*')
QUERY_STRING_LIMIT = 256
DECIMAL = re.compile(r'[0-9]{1,15}')     # a Content-Length: ASCII digits only (str.isdigit admits other scripts)
METHODS = ('GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS', 'CONNECT', 'TRACE')
USAGE_KINDS = ('anthropic-messages', 'openai-responses', 'openai-chat')
MIB = 1024 * 1024
DEFAULTS = {'max_request_bytes': 32 * MIB, 'max_ttl_s': 86400, 'upstream_timeout_s': 600}
LIMITS = {'max_request_bytes': (1, 256 * MIB), 'max_ttl_s': (1, 7 * 86400), 'upstream_timeout_s': (1, 3600)}
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
# S-03.3 (OA-12 package section 3 point 5): request headers that select the provider account's scope (a workspace or an
# organization) are never forwarded, whatever follows the prefix: stripped, not refused, and named in the audit. Since
# the security review's S1 a family forwards only the request headers it declares (families.json, headers), and no
# declaration may name or cover these.
ACCOUNT_SCOPE_PREFIXES = ('anthropic-workspace', 'anthropic-organization')
# The request headers the broker itself consumes or sets again: never forwarded and never audited as stripped.
CONSUMED = frozenset({'host', 'content-length', 'accept-encoding', 'connection'})

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
    'CONFIG_ENVELOPE_INVALID': (500, 'give components.inference_broker.envelope exactly as the inference broker '
                                     'README shows it: expires_at quoted and selection, nothing else (the limit, '
                                     'amount, currency, enforced_by and cap are retired)'),
    # the provider envelope (S-03.5): a family whose upstream is not loopback
    'ENVELOPE_NOT_CONFIGURED': (500, 'a family has an upstream that is not loopback: add the envelope block to '
                                     'components.inference_broker and have the Owner authorize it'),
    'ENVELOPE_FAMILIES_UNBOUND': (500, 'bind every family whose upstream is not loopback to one provider and one '
                                       'origin, and name that provider in no loopback family'),
    'ENVELOPE_NOT_AUTHORIZED': (503, 'record the Owner\'s authorization of the envelope (inference_broker.py '
                                     'envelope --operation ID, then authorization_recorder.py prepare and record), '
                                     'then start the broker again'),
    'ENVELOPE_RECORD_INVALID': (500, 'the integration store holds an authorization receipt the broker cannot trust: '
                                     'investigate the store before starting the broker'),
    'ENVELOPE_AUTHORIZATION_UNRESOLVED': (500, 'resolve the later provider-envelope authorization '
                                               '(authorization_recorder.py resolve --challenge <nonce>), then start '
                                               'the broker again'),
    'ENVELOPE_REPLAYED': (500, 'a later authorization supersedes this envelope: configure the envelope the Owner '
                               'authorized last, or have the Owner authorize this one again'),
    'ENVELOPE_MISMATCH': (503, 'the live envelope is not the one the Owner authorized: restore the authorized '
                               'configuration (inference_broker.py envelope shows the live one), or have the Owner '
                               'authorize it'),
    'ENVELOPE_EXPIRED': (403, 'the Owner\'s authorization of the envelope has expired: have the Owner authorize a '
                              'new envelope'),
    'MODEL_SELECTION_MISSING': (500, 'select the models: name them in the families whose upstream is not loopback '
                                     '(selection: envelope), or record the delegated selection on the governing '
                                     'envelope receipt (selection_recorder.py delegate; selection: delegation)'),
    'MODEL_SELECTION_NOT_AUTHORIZED': (500, 'the governing model selection is not a select-models record of '
                                            'decision 0018 point 3 by agent:engineering-manager written by the '
                                            'selection recorder: record a new selection (selection_recorder.py '
                                            'delegate)'),
    'MODEL_SELECTION_RECEIPT_MISMATCH': (500, 'the governing model selection rests on another envelope '
                                              'authorization: record a selection on the governing one '
                                              '(selection_recorder.py delegate)'),
    'MODEL_NOT_SELECTED': (403, 'use only a model the held selection selects; configure no other model for a '
                                'family whose upstream is not loopback'),
    'FAMILY_REACH_UNCHECKED': (500, 'the broker has no check of provider-side reach for the family: give it a '
                                    'loopback upstream only, or no upstream; only a family with a reach checker '
                                    '(anthropic-messages) may name an upstream that is not loopback'),
    # the broker's own stop
    'BROKER_STOPPING': (503, 'the broker is stopping: no new request is admitted; send it again once the broker '
                             'has been started again'),
    # the control listener
    'CONTROL_ROUTE_UNKNOWN': (404, 'use POST /v1/grants, POST /v1/grants/revoke, GET /v1/grants/<fingerprint>, '
                                   'GET /v1/status or POST /v1/stop'),
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
    'BUDGET_RETIRED': (400, 'send no budget: a grant has no request or token budget (retired by S-03.6); give the '
                            'lifetime as ttl_s'),
    'TTL_INVALID': (400, 'give ttl_s as a positive integer no larger than max_ttl_s'),
    'ATTEMPT_HAS_GRANT': (409, 'an attempt has one token for its whole life: start a new attempt'),
    'GRANT_ATTEMPT_REVOKED': (409, 'the attempt was revoked by its conversation and attempt before a grant was '
                                   'registered: start a new attempt'),
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
    'QUERY_NOT_ALLOWED': (400, "send no query string, or exactly one of the whole query strings the token's "
                               'family declares in families.json (anthropic-messages: beta=true), byte for byte: '
                               'no other order, case, encoding, repetition, addition or fragment, and no empty '
                               'query'),
    'BODY_LENGTH_REQUIRED': (411, 'send the body with a Content-Length, not chunked'),
    'BODY_LENGTH_INVALID': (400, 'send one valid Content-Length'),
    'BODY_TOO_LARGE': (413, 'send a body no larger than max_request_bytes'),
    'BODY_NOT_JSON': (400, 'send the body as one uncompressed JSON object'),
    'HEADER_VALUE_INVALID': (400, 'send no header value holding a control character (only HTAB is allowed; no '
                                  'CR or LF, so no obsolete line folding)'),
    'CONTENT_ENCODING_REFUSED': (415, 'send the body uncompressed: no Content-Encoding, or identity'),
    'CONTENT_TYPE_REFUSED': (415, 'send the body with one Content-Type: application/json, optionally with '
                                  'charset=utf-8 and no other parameter'),
    'BODY_ENCODING_INVALID': (400, 'send the body as UTF-8 without a byte order mark (no UTF-16 or UTF-32)'),
    'BODY_DUPLICATE_KEY': (400, 'send each key of a JSON object once, at every depth: a body whose objects repeat a '
                                'key is read differently by different parsers'),
    'MODEL_MISSING': (400, 'send the model as a string field "model"'),
    'MODEL_NOT_ALLOWED': (403, "use a model of the token's list"),
    'PROVIDER_REACH_REFUSED': (400, 'send a plain model call: no mcp_servers or container, tools as a list of '
                                    'objects, no tool whose type is '
                                    'not custom (no server tool or provider-defined tool), no content whose source '
                                    'is a url or a file, no container_upload block; the provider is never asked to '
                                    'reach or run anything outside the request'),
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
    # credential-enter (S-03.3: the Owner's act 2 of OA-12, in his own console window)
    'KEY_CONSOLE_REQUIRED': (400, 'run credential-enter in your own console window, at its prompt: standard input '
                                  'must be an interactive console (not a pipe, a file or a redirection), and the '
                                  'key is read with echo off from that console only'),
    'KEY_NOT_KEY_SHAPED': (400, 'paste the dedicated provider key again, exactly as the provider shows it: '
                                'sk-ant-api followed only by letters, digits, "_" and "-", 40 to 512 characters, '
                                'no space or line break inside it; an admin key (sk-ant-admin) is never stored'),
    'KEY_ENTRY_EXISTS': (409, 'the entry "AIEH model provider" exists: run credential-enter --replace to replace '
                              'it, then restart the broker'),
    'KEY_ENTRY_CANCELLED': (400, 'the prompt was cancelled and nothing was stored: run credential-enter again'),
}
REMEDIES = {code: remedy for code, (_, remedy) in CODES.items()}


class InferenceError(Exception):
    """A refusal (exit 2) or a failure (exit 1) with a stable code, its HTTP status on a listener and its remedy.
    grant, when set, is the grant the refused request presented (for its counters and the audit line)."""

    def __init__(self, code: str, detail: str, *, refusal: bool = True, grant=None, audit: dict | None = None):
        self.code, self.detail, self.refusal, self.grant = code, detail, refusal, grant
        self.audit = audit       # fields the refused request's audit line adds (bounded names only)
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
    query: str | frozenset     # 'refuse', or the exact whole query strings admitted
    auth_header: str
    auth_scheme: str | None
    usage: str
    provider: str | None = None
    upstream: Origin | None = None
    models: tuple = ()
    header_names: frozenset = frozenset()     # the request header names forwarded (lower case)
    header_prefixes: tuple = ()               # and every name starting with one of these

    def describe(self) -> dict:
        return {'id': self.id, 'status': self.status,
                'routes': [{'method': m, 'path': p} for m, p in sorted(self.routes)], 'query': self.query_rule(),
                'auth': {'header': self.auth_header, 'scheme': self.auth_scheme}, 'usage': self.usage,
                'headers': {'names': sorted(self.header_names), 'prefixes': list(self.header_prefixes)},
                'provider': self.provider, 'upstream': None if self.upstream is None else self.upstream.text(),
                'models': list(self.models)}

    def forwards(self, name: str) -> bool:
        """Whether the family forwards a request header of lower-case NAME: a declared name, or one starting with a
        declared prefix (never an account-scope header: the declarations cannot cover one)."""
        return (name in self.header_names or name.startswith(self.header_prefixes)) \
            and not name.startswith(ACCOUNT_SCOPE_PREFIXES)

    def query_rule(self):
        """The query rule as declared: 'refuse', or the sorted list of the whole query strings admitted."""
        return self.query if self.query == 'refuse' else sorted(self.query)

    def admits_query(self, query: str) -> bool:
        """Whether the raw query of a request target (the text after its first '?') is admitted: only when the
        family declares a set and QUERY is byte-equal to one of its members."""
        return self.query != 'refuse' and query in self.query


@dataclasses.dataclass(frozen=True)
class BrokerConfig:
    control_port: int | None
    inference_port: int | None
    max_request_bytes: int
    max_ttl_s: int
    upstream_timeout_s: float
    families: dict
    envelope: dict | None = None    # components.inference_broker.envelope, checked (inference_envelope.check_block)

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
        _exact_keys(entry, ('id', 'status', 'consumer', 'routes', 'query', 'auth', 'headers', 'usage'), (),
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
        query = entry['query']
        if isinstance(query, list):
            if not query or len(set(map(str, query))) != len(query) or not all(
                    isinstance(q, str) and len(q) <= QUERY_STRING_LIMIT and QUERY_STRING.fullmatch(q)
                    for q in query):
                raise bad(f'{where}.query is refuse or a non-empty list of distinct whole query strings '
                          '(name=value pairs of plain characters joined by &)')
            query = frozenset(query)
        elif query != 'refuse':
            raise bad(f'{where}.query is refuse or a list of whole query strings (pass is retired)')
        auth = entry['auth']
        _exact_keys(auth, ('header', 'scheme'), (), 'DECLARATION_INVALID', f'{where}.auth')
        if not isinstance(auth['header'], str) or not HEADER_NAME.fullmatch(auth['header']) \
                or auth['scheme'] not in (None, 'Bearer'):
            raise bad(f'{where}.auth is a lower-case header name and the scheme null or Bearer')
        if entry['usage'] not in USAGE_KINDS:
            raise bad(f'{where}.usage must be one of {list(USAGE_KINDS)}')
        names, prefixes = _declared_headers(entry['headers'], where, bad)
        families[entry['id']] = Family(entry['id'], entry['status'], frozenset(routes), query,
                                       auth['header'], auth['scheme'], entry['usage'], header_names=names,
                                       header_prefixes=prefixes)
    return families


def _declared_headers(node, where: str, bad) -> tuple[frozenset, tuple]:
    """A family's forwarded request headers (S-03.3, the security review's S1): {names, prefixes}, each a list of
    distinct lower-case names (HEADER_NAME) and prefixes (HEADER_PREFIX, ending with '-'). None may name a header the
    broker never forwards (NOT_FORWARDED, its own CONSUMED ones) or cover one, nor name, cover or fall under an
    account-scope prefix."""
    _exact_keys(node, ('names', 'prefixes'), (), 'DECLARATION_INVALID', f'{where}.headers')
    names, prefixes = node['names'], node['prefixes']
    if not isinstance(names, list) or not names or not isinstance(prefixes, list):
        raise bad(f'{where}.headers: names is a non-empty list, prefixes a list')
    if not all(isinstance(n, str) and HEADER_NAME.fullmatch(n) for n in names) \
            or not all(isinstance(p, str) and HEADER_PREFIX.fullmatch(p) for p in prefixes) \
            or len(set(names)) != len(names) or len(set(prefixes)) != len(prefixes):
        raise bad(f'{where}.headers: distinct lower-case header names, and prefixes ending with -')
    never = NOT_FORWARDED | CONSUMED
    if any(n in never or n.startswith(ACCOUNT_SCOPE_PREFIXES) for n in names) \
            or any(n.startswith(p) for n in never for p in prefixes) \
            or any(a.startswith(p) or p.startswith(a) for a in ACCOUNT_SCOPE_PREFIXES for p in prefixes):
        raise bad(f'{where}.headers names or covers a header the broker never forwards or an account-scope header')
    return frozenset(names), tuple(prefixes)


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
    allowed = ('control_port', 'inference_port', 'families', 'envelope', *DEFAULTS)
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
    limits = (_limit(raw, 'max_request_bytes'), _limit(raw, 'max_ttl_s'), _limit(raw, 'upstream_timeout_s'))
    try:
        block = inference_envelope.check_block(raw.get('envelope'))
    except inference_envelope.EnvelopeError as exc:
        raise InferenceError(exc.code, exc.detail) from None
    # The block is only shape-checked here: whether a family needs it is serve's question (start), never the
    # loader's, whose other callers (the qualification launcher, the dispatcher's side) keep their codes.
    return BrokerConfig(control, inference, *limits, families, block)


# ---------------------------------------------------------------- the provider envelope (S-03.5)

# The codes the read side (integrations/owner/envelope_decisions.REFUSALS) answers; a test asserts them equal.
AUTHORIZATION_REFUSALS = ('ENVELOPE_RECORD_INVALID', 'ENVELOPE_NOT_AUTHORIZED', 'ENVELOPE_AUTHORIZATION_UNRESOLVED',
                          'ENVELOPE_REPLAYED', 'ENVELOPE_MISMATCH', 'ENVELOPE_EXPIRED')
AUTHORIZATION_VIEW = ('receipt', 'operation', 'decisionId', 'target', 'digest', 'expiresAt')
# The selection codes the read side (envelope_decisions.SELECTION_REFUSALS) answers, and its view; a test asserts
# them equal.
SELECTION_REFUSALS = ('MODEL_SELECTION_MISSING', 'MODEL_SELECTION_NOT_AUTHORIZED', 'MODEL_SELECTION_RECEIPT_MISMATCH')
SELECTION_VIEW = ('receipt', 'decisionId', 'record', 'point', 'basis', 'models')
SELECTION_KEY = re.compile(r'model-selection/v1/[1-9][0-9]*')
RECEIPT_KEY = re.compile(r'owner-authorization/v1/[0-9a-f]{32}')
DECISION_ID = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}')
SHA256_DIGEST = re.compile(r'sha256:[0-9a-f]{64}')


def bound_families(config: BrokerConfig) -> list:
    """The families the envelope binds: those whose upstream is configured and is not loopback."""
    return [f for f in config.families.values() if f.upstream is not None and not f.upstream.loopback]


def live_envelope(config: BrokerConfig) -> tuple[dict, str]:
    """(the canonical envelope document, its digest), projected from CONFIG: the bound families' one provider and
    one origin, their models, and the envelope block. ENVELOPE_NOT_CONFIGURED without a block;
    ENVELOPE_FAMILIES_UNBOUND unless the bound families share exactly one provider and one origin and no loopback
    family names that provider (under an envelope the provider key goes to the envelope's origin only)."""
    if config.envelope is None:
        raise InferenceError('ENVELOPE_NOT_CONFIGURED', f'components.{COMPONENT}.envelope is absent')
    bound = bound_families(config)
    if not bound:
        raise InferenceError('ENVELOPE_FAMILIES_UNBOUND', 'no family has an upstream that is not loopback: there is '
                                                          'nothing to bind')
    providers, origins = {f.provider for f in bound}, {f.upstream for f in bound}
    if len(providers) != 1 or len(origins) != 1:
        raise InferenceError('ENVELOPE_FAMILIES_UNBOUND', f'the families whose upstream is not loopback name '
                                                          f'{len(providers)} providers and {len(origins)} origins')
    (provider,), (origin,) = providers, origins
    beside = sorted(f.id for f in config.families.values()
                    if f.upstream is not None and f.upstream.loopback and f.provider == provider)
    if beside:
        raise InferenceError('ENVELOPE_FAMILIES_UNBOUND', f'the loopback families {beside} name the envelope\'s '
                                                          f'provider {provider!r}')
    document = inference_envelope.document(config.envelope, provider, origin.text(),
                                           {f.id: list(f.models) for f in bound})
    return document, inference_envelope.digest(document)


@dataclasses.dataclass(frozen=True)
class Authorization:
    """The provider-envelope authorization the broker holds: the governing receipt, the envelope's digest and
    manifest digest, its expiry, the bound provider and origin, and the selected models per bound family. Only
    authorize() makes one the broker accepts."""
    receipt: str
    operation: str
    decision: str
    digest: str
    manifest_digest: str
    expires_at: str
    expires: float = dataclasses.field(repr=False)
    provider: str
    origin: Origin
    selection: str
    models: tuple       # ((family, (model, ...)), ...)
    selection_record: dict | None = None    # a delegated selection: {record, point, receipt, decision}

    def describe(self) -> dict:
        """The start receipt's and the status answer's authorization member."""
        selection = {'by': self.selection, 'models': {family: list(ids) for family, ids in self.models}}
        if self.selection_record is not None:
            selection.update(self.selection_record)
        return {'receipt': self.receipt, 'operation': self.operation, 'decision': self.decision,
                'digest': self.digest, 'expires_at': self.expires_at, 'selection': selection}

    def selects(self, family: str, model: str) -> bool:
        """Whether the held selection selects MODEL for FAMILY."""
        return model in dict(self.models).get(family, ())


# The Authorization objects authorize() returned in this process, by identity. A caller cannot add one:
# dataclasses.replace, a copy or a hand-built Authorization is another object, which is not here. It is a guard
# against convenience and accident (a caller that builds a Broker without the start check), not against code of
# the same account in this process, which decision 0010 point 1 places outside the threat model.
_MINTED: 'weakref.WeakValueDictionary[int, Authorization]' = weakref.WeakValueDictionary()


def minted(authorization) -> bool:
    return authorization is not None and _MINTED.get(id(authorization)) is authorization


def _record_invalid(detail: str) -> InferenceError:
    return InferenceError('ENVELOPE_RECORD_INVALID', detail)


def authorize(config: BrokerConfig, decisions: Callable | None, store_factory: Callable,
              clock: Callable = time.time) -> Authorization:
    """The start precondition for CONFIG's bound families, before the provider key is read or a listener opened:
    the live envelope and its digest; the governing provider-envelope receipt from DECISIONS (a callable
    ``decisions(store) -> source``: envelope_decisions.verifier, whose source is called as ``verify(target,
    manifest_digest, now)`` and, for a delegated selection, asked ``source.selection(receipt)``) over the store
    STORE_FACTORY opens (closed again; nothing is written); the model selection. Returns the Authorization the
    Broker holds, or raises the stable code."""
    document, digest = live_envelope(config)
    if decisions is None:
        raise InferenceError('ENVELOPE_NOT_AUTHORIZED', 'no decision source was given: a family whose upstream is '
                                                        'not loopback starts only on a recorded authorization')
    now = datetime.datetime.fromtimestamp(clock(), datetime.timezone.utc)
    store = store_factory()
    try:
        return _authorize(config, decisions, store, document, digest, now)
    finally:
        store.close()


def _asked(call, *args):
    """CALL(*ARGS); whatever the decision source raises is an answer not to trust (ENVELOPE_RECORD_INVALID)."""
    failure = None
    try:
        return call(*args)
    except Exception as exc:  # noqa: BLE001 - whatever the decision source raises is an answer not to trust
        failure = exc
    raise _record_invalid(f'the decision source raised {type(failure).__name__}')


def _verdict(answer, codes: tuple):
    """(code, detail, view) of a well-formed verdict whose code is None or one of CODES."""
    if not isinstance(answer, tuple) or len(answer) != 3 or not isinstance(answer[1], str) \
            or answer[0] not in (None, *codes):
        raise _record_invalid(f'the decision source answered {type(answer).__name__}, not a well-formed verdict')
    return answer


def _selected(config: BrokerConfig, source, receipt: str, document: dict) -> tuple:
    """(the authority that selected the models, {family: selected ids}, the delegated selection's view or None)."""
    bound = bound_families(config)
    if document['selection']['by'] == 'envelope':
        return 'envelope', {f.id: set(f.models) for f in bound}, None
    asked = getattr(source, 'selection', None)
    if not callable(asked):
        raise InferenceError('MODEL_SELECTION_MISSING', 'the envelope delegates the model selection (decision 0018 '
                                                        'point 3), and the decision source reads no selection')
    code, detail, view = _verdict(_asked(asked, receipt), SELECTION_REFUSALS)
    if code is not None:
        raise InferenceError(code, detail[:500])
    models = view.get('models') if isinstance(view, dict) else None
    if not isinstance(view, dict) or tuple(view) != SELECTION_VIEW or view['basis'] != receipt \
            or (view['record'], view['point']) != ('decision:0018', '3') \
            or not isinstance(view['decisionId'], str) or not DECISION_ID.fullmatch(view['decisionId']) \
            or not isinstance(view['receipt'], str) or not SELECTION_KEY.fullmatch(view['receipt']) \
            or not isinstance(models, dict) or not all(
                isinstance(ids, list) and all(isinstance(m, str) and MODEL_NAME.fullmatch(m) for m in ids)
                for ids in models.values()):
        raise _record_invalid('the decision source answered a selection view that does not bind the governing '
                              'authorization')
    return 'delegation', {family: set(ids) for family, ids in models.items()}, view


def _authorize(config: BrokerConfig, decisions: Callable, store, document: dict, digest: str,
               now: datetime.datetime) -> Authorization:
    def manifest_digest(operation: str) -> str:
        return inference_envelope.manifest_digest(document, operation)
    source = _asked(decisions, store)
    code, detail, view = _verdict(_asked(source, digest, manifest_digest, now), AUTHORIZATION_REFUSALS)
    if code is not None:
        raise InferenceError(code, detail[:500])
    if not isinstance(view, dict) or tuple(view) != AUTHORIZATION_VIEW \
            or not isinstance(view['receipt'], str) or not RECEIPT_KEY.fullmatch(view['receipt']) \
            or not isinstance(view['decisionId'], str) or not DECISION_ID.fullmatch(view['decisionId']) \
            or not isinstance(view['operation'], str) or not inference_envelope.OPERATION.fullmatch(view['operation']) \
            or view['target'] != digest or view['expiresAt'] != document['expires_at'] \
            or not isinstance(view['digest'], str) or not SHA256_DIGEST.fullmatch(view['digest']) \
            or view['digest'] != manifest_digest(view['operation']):
        raise _record_invalid('the decision source answered a view that does not bind the live envelope and its '
                              'canonical manifest')
    expires = inference_envelope.parse_expiry(document['expires_at'])
    if now >= expires:
        raise InferenceError('ENVELOPE_EXPIRED', f'the authorization {view["receipt"]} expired at '
                                                 f'{document["expires_at"]}')
    bound = bound_families(config)
    by, selected, chosen = _selected(config, source, view['receipt'], document)
    outside = sorted(f'{f.id}: {m}' for f in bound for m in f.models if m not in selected.get(f.id, ()))
    if outside:
        raise InferenceError('MODEL_NOT_SELECTED', f'the configuration names {len(outside)} model(s) the {by} '
                                                   f'selection does not select: {", ".join(outside)}')
    if not any(f.models for f in bound):
        raise InferenceError('MODEL_SELECTION_MISSING', f'the {by} selection leaves no family whose upstream is not '
                                                        'loopback with a selected model')
    (provider,), (origin,) = {f.provider for f in bound}, {f.upstream for f in bound}
    record = None if chosen is None else {'record': chosen['record'], 'point': chosen['point'],
                                          'receipt': chosen['receipt'], 'decision': chosen['decisionId']}
    held = Authorization(view['receipt'], view['operation'], view['decisionId'], digest, view['digest'],
                         document['expires_at'], expires.timestamp(), provider, origin, by,
                         tuple((f.id, tuple(sorted(f.models))) for f in sorted(bound, key=lambda f: f.id)),
                         record)
    _MINTED[id(held)] = held
    return held


def envelope_report(config: BrokerConfig, operation: str | None) -> dict:
    """The envelope command's report: the live envelope document and its digest and, with OPERATION, the canonical
    manifest's path, text (a JSON string, so that no console changes its line endings) and sha256. It reads no
    credential, store or listener, and proposes nothing."""
    document, digest = live_envelope(config)
    manifest = None
    if operation is not None:
        manifest = {'path': inference_envelope.manifest_path(operation),
                    'text': inference_envelope.manifest_text(document, operation),
                    'digest': inference_envelope.manifest_digest(document, operation)}
    return {'format': ENVELOPE_REPORT_FORMAT, 'document': document, 'digest': digest, 'operation': operation,
            'manifest': manifest}


# ---------------------------------------------------------------- strict JSON (S-03.3)


class BodyEncoding(ValueError):
    """A checked body that is not strict UTF-8 without a byte order mark (strict_json)."""


class DuplicateKey(ValueError):
    """A JSON object repeats a key (strict_json). Its text names no key."""


def _unique_pairs(pairs) -> dict:
    seen = {}
    for key, value in pairs:
        if key in seen:
            raise DuplicateKey('a JSON object repeats a key')
        seen[key] = value
    return seen


def strict_json(data):
    """json.loads of DATA, with every object's keys distinct at any depth (after escapes are decoded): DuplicateKey
    otherwise. Every body the broker checks is read this way, so that what it checks is what any parser upstream
    reads (json.loads alone keeps the last of a repeated key; another parser may keep the first). Bytes must be
    strict UTF-8 with no byte order mark (BodyEncoding otherwise): json.loads alone would also read UTF-16, UTF-32
    and a BOM, which the broker's checks and a parser upstream may read differently."""
    if isinstance(data, (bytes, bytearray)):
        if bytes(data[:3]) == b'\xef\xbb\xbf':
            raise BodyEncoding('the body starts with a byte order mark')
        try:
            data = bytes(data).decode('utf-8', 'strict')
        except UnicodeDecodeError:
            raise BodyEncoding('the body is not UTF-8') from None
    return json.loads(data, object_pairs_hook=_unique_pairs)


# ---------------------------------------------------------------- provider-side reach (S-03.3)

REACH_KEYS = ('mcp_servers', 'container')       # top-level keys refused whatever their value (and any case-folding)
# The security review's S2: allowlists, not deny lists. A content block (in messages[].content, in system when it is a
# list, and in the content of a tool_result, a search_result and a source of type content) is admitted only with one
# of these types; a source object, anywhere in the body, only with one of these types. Everything else (server tool
# use and results, mcp_tool_use, container_upload, a url or file source, a type not yet known) is refused. S-03.3's
# discovery run may show the pinned client needs another type: adding one is a reviewed change.
CONTENT_BLOCK_TYPES = ('text', 'image', 'document', 'tool_use', 'tool_result', 'thinking', 'redacted_thinking',
                       'search_result')
SOURCE_TYPES = ('base64', 'text', 'content')


def _blocks(document: dict):
    """(rule, name) of the first content block outside CONTENT_BLOCK_TYPES, of a content that is neither a string
    nor a list of objects, or of a block's source outside SOURCE_TYPES, in the block lists of an anthropic-messages
    body; or None. A source is checked where the provider interprets it, on an admitted content block: an object
    source of any block, and the source of an image or a document, which must be an object. A tool's input_schema
    and a tool_use's input are never read: they are opaque to the provider (the engineering manager's ruling after
    the re-review)."""
    lists = []
    if 'system' in document and not isinstance(document['system'], str):
        lists.append(document['system'])
    messages = document.get('messages')
    for message in messages if isinstance(messages, list) else ():
        if isinstance(message, dict) and 'content' in message and not isinstance(message['content'], str):
            lists.append(message['content'])
    while lists:
        blocks = lists.pop()
        if not isinstance(blocks, list):
            return 'content-shape', 'content'
        for block in blocks:
            if not isinstance(block, dict):
                return 'content-shape', 'content'
            kind = block.get('type')
            if not isinstance(kind, str) or kind not in CONTENT_BLOCK_TYPES:
                return 'block-type', kind
            if kind in ('tool_result', 'search_result') and 'content' in block \
                    and not isinstance(block['content'], str):
                lists.append(block['content'])
            source = block.get('source')
            if isinstance(source, dict) or (kind in ('image', 'document') and 'source' in block):
                if not isinstance(source, dict) or not isinstance(source.get('type'), str) \
                        or source['type'] not in SOURCE_TYPES:
                    return 'source-type', source.get('type') if isinstance(source, dict) else None
            if isinstance(source, dict) and source.get('type') == 'content' and 'content' in source \
                    and not isinstance(source['content'], str):
                lists.append(source['content'])
    return None


def anthropic_reach(document: dict):
    """(rule, name) of the first thing in an anthropic-messages request body that asks the provider to reach or
    run something outside the request, or None. NAME is the key or the type as the body gives it (the caller
    records it only in the audit's bounded name grammar). Fail closed: a top-level mcp_servers or container (any
    case-folding); a tools value that is not a list of objects, or a tool whose type is present and not custom; a
    content block outside CONTENT_BLOCK_TYPES (container_upload included) and a block's source outside
    SOURCE_TYPES, wherever a content block is read (_blocks). The walk is iterative (no recursion limit)."""
    for key in document:
        if isinstance(key, str) and key.casefold() in REACH_KEYS:   # the exact key, or one that case-folds to it
            return 'top-level-key', key
    if 'tools' in document:
        tools = document['tools']
        if not isinstance(tools, list):       # fail closed: a shape the rule cannot read is not passed on
            return 'tools-shape', 'tools'
        for tool in tools:
            if not isinstance(tool, dict):
                return 'tools-shape', 'tools'
            if 'type' in tool and tool['type'] != 'custom':
                return 'tool-type', tool['type']
    return _blocks(document)


# The families whose request bodies the broker checks for provider-side reach, by family id. A family absent here
# is refused at start when its upstream is not loopback (FAMILY_REACH_UNCHECKED): fail closed until it is qualified.
REACH_CHECKERS = {'anthropic-messages': anthropic_reach}


def check_reach(config: BrokerConfig) -> None:
    """FAMILY_REACH_UNCHECKED when a family whose upstream is not loopback has no reach checker."""
    unchecked = sorted(f.id for f in config.families.values()
                       if f.upstream is not None and not f.upstream.loopback and f.id not in REACH_CHECKERS)
    if unchecked:
        raise InferenceError('FAMILY_REACH_UNCHECKED', f'{unchecked} name an upstream that is not loopback and have '
                                                       'no check of provider-side reach')


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
        except (ValueError, UnicodeDecodeError, RecursionError):
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

    def intent(self, key: str):
        """The intent of the receipt under KEY, or None (read on the journal thread)."""
        def work():
            held = self._open().get(key)
            return None if held is None else json.loads(held.intent_json)
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


class CutByStop(OSError):
    """Raised by the connect hook when the stop cut the request while its upstream connection was being made."""


class _UpstreamConnection:
    """The upstream connection's connect hook (S-03.2): once http.client has made the connection (at the first
    request; building it opens nothing), on_connect, when the pass-through set it, is called with the socket, so
    that the broker records the peer it reached at connect time."""
    on_connect = None

    def connect(self):
        super().connect()
        if self.on_connect is not None:
            self.on_connect(self.sock)


class _UpstreamHTTPConnection(_UpstreamConnection, http.client.HTTPConnection):
    pass


class _UpstreamHTTPSConnection(_UpstreamConnection, http.client.HTTPSConnection):
    pass


def connect_upstream(origin: Origin, timeout: float) -> http.client.HTTPConnection:
    """The broker's only outbound connection: to ORIGIN, the configured upstream of the admitted token's family.
    https verifies against the system's trust roots; plain http only to a loopback address. http.client reads
    no proxy variable. The connection is made at its first request, and reports its socket to its on_connect."""
    global _TLS
    if origin.scheme == 'https':
        if _TLS is None:
            _TLS = ssl.create_default_context()
        return _UpstreamHTTPSConnection(origin.host, origin.port, timeout=timeout, context=_TLS)
    if origin.scheme == 'http' and origin.loopback:
        return _UpstreamHTTPConnection(origin.host, origin.port, timeout=timeout)
    raise InferenceError('UPSTREAM_NOT_CONFIGURED', f'{origin.text()} is not an admissible upstream')


def socket_address(address) -> dict:
    """{'address', 'port'} of a socket address (getpeername or getsockname): the IP as canonical text, without a
    scope."""
    return {'address': ipaddress.ip_address(str(address[0]).split('%', 1)[0]).compressed, 'port': int(address[1])}


# ---------------------------------------------------------------- grants


@dataclasses.dataclass
class Grant:
    """One attempt's inference access, bound to its conversation and attempt, its family, its model list and its
    lifetime. The token itself is never kept: only its sha256 digest and fingerprint. The counts and the usage are
    information for the audit and the per-attempt summary; none of them refuses a request (S-03.6)."""
    digest: str
    fingerprint: str
    conversation_id: str
    attempt_id: str
    family: str
    models: tuple
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
    stripped: tuple = ()     # the header names stripped (lower case, sorted, distinct)


@dataclasses.dataclass(eq=False)
class Flight:
    """One request on the inference listener from its admission until it is settled (counted and audited once):
    what the stop needs to cut it. LINE is its audit line, STARTED its monotonic start; the pass-through records
    the upstream connection, the status sent and the bytes sent as it goes. CUT is set, under the broker's lock,
    by a stop that cut it; SETTLED once its accounting is claimed."""
    line: dict
    started: float
    handler: object = None
    grant: Grant | None = None
    connection: object = None
    status: int | None = None
    upstream_status: int | None = None
    sent: int = 0
    cut: bool = False
    settled: bool = False

    def interrupt(self) -> None:
        """Shut the client's socket first (so that nothing more, a stream's terminating chunk included, reaches
        it), then shut and close the upstream's, so that a pass-through blocked on the upstream wakes. On Windows a
        shutdown alone does not wake a thread blocked in recv (measured: it stays until the peer closes), and
        socket.close() is deferred while http.client's response holds a makefile of it: the handle is detached
        from the socket object and closed (socket.close(fd)), which ends the blocked call; the object is left
        closed, so later calls on it fail."""
        client = getattr(self.handler, 'connection', None)
        if client is not None:
            try:
                client.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        upstream = getattr(self.connection, 'sock', None)
        if upstream is not None:
            try:
                upstream.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                handle = upstream.detach()
                if handle is not None and handle >= 0:
                    socket.close(handle)
            except OSError:
                pass


def _uuid(value, code: str, what: str) -> str:
    try:
        if isinstance(value, str) and str(uuid.UUID(value)) == value:
            return value
    except ValueError:
        pass
    raise InferenceError(code, f'{what} is not a canonical lower-case UUID')


class _AttemptLock:
    """One attempt id's lock out of the broker's registry: the entry is made on first use (by the broker's
    _attempt_lock_factory) and removed when its last user leaves. The registry's guard is held only to find or
    drop the entry, never while the attempt's lock is acquired."""

    def __init__(self, broker: 'Broker', attempt: str):
        self.broker, self.attempt, self.entry = broker, attempt, None

    def __enter__(self):
        broker = self.broker
        with broker._attempt_locks_guard:
            entry = broker._attempt_locks.get(self.attempt)
            if entry is None:
                entry = broker._attempt_locks[self.attempt] = [broker._attempt_lock_factory(), 0]
            entry[1] += 1
        try:
            entry[0].__enter__()
        except BaseException:
            self._leave(entry)
            raise
        self.entry = entry
        return self

    def __exit__(self, *exc):
        entry, self.entry = self.entry, None
        try:
            entry[0].__exit__(*exc)
        finally:
            self._leave(entry)

    def _leave(self, entry) -> None:
        with self.broker._attempt_locks_guard:
            entry[1] -= 1
            if entry[1] == 0 and self.broker._attempt_locks.get(self.attempt) is entry:
                del self.broker._attempt_locks[self.attempt]


class Broker:
    """The broker's state and decisions (socket-free: issue, revoke, admit, status) and its two listeners
    (start, stop). provider_key is the loaded key (None: no entry). connect stands in for connect_upstream in
    tests; clock for time.time."""

    def __init__(self, config: BrokerConfig, *, provider_key: ProviderKey | None, journal: Journal,
                 audit: AuditLog, guard: BrokerGuard, clock: Callable = time.time, connect: Callable | None = None,
                 authorization: Authorization | None = None):
        self.config, self.provider_key, self.journal, self.audit, self.guard = config, provider_key, journal, \
            audit, guard
        self.clock, self._connect = clock, connect or connect_upstream
        self.authorization = authorization   # authorize()'s, for the families whose upstream is not loopback
        if provider_key is not None:
            guard.hold(provider_key.key)
        self._lock = threading.RLock()
        # E-05.6: per attempt, an issue's grant receipt and registration, and a revocation by attempt's lookup and
        # tombstone, happen one at a time (_attempt_lock). One lock per attempt id, in a registry held only briefly
        # and emptied as each attempt's last user leaves, so no attempt waits behind another's store write. Lock
        # order: an attempt's lock before _lock, never the reverse; the registry's guard is never held while
        # acquiring another lock. _attempt_lock_factory makes each attempt's lock (a test may observe it).
        self._attempt_locks: dict[str, list] = {}   # attempt id -> [lock, users]
        self._attempt_locks_guard = threading.Lock()
        self._attempt_lock_factory = threading.Lock
        self._grants: dict[str, Grant] = {}     # sha256 digest of the token -> grant
        self._by_fingerprint: dict[str, Grant] = {}
        self._servers: list = []
        self.listeners: dict = {}
        self.start_receipt = None
        self._stopped = False
        self._stopping = False   # set by request_stop(), under _lock, first: from then on no request is admitted
        # The stop (S-03.2): stop_event is the broker's one stop event (serve waits on it); stop_by names what asked
        # first; stop_finished is set at the end of stop(). _flights holds every admitted request not yet settled
        # (Flight), _settled is notified as each settles; drain_ceiling_s bounds the stop's wait for them.
        self.stop_event = threading.Event()
        self.stop_finished = threading.Event()
        self._stop_done = False     # a plain flag beside stop_finished: what a signal handler may read
        self.stop_by: str | None = None
        self.drain_ceiling_s = STOP_DRAIN_CEILING_S
        self._flights: dict[int, Flight] = {}
        self._settled = threading.Condition(self._lock)
        self._after_stop: list = []

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
        """One attempt token, journaled before it is returned: aieh-inference-grant/2. A request that still
        carries a budget (any value) is refused BUDGET_RETIRED: a grant has no request or token budget."""
        self.housekeeping()
        if isinstance(body, dict) and 'budget' in body:
            raise InferenceError('BUDGET_RETIRED', 'the issue request carries a budget: a grant is bound to its '
                                                   'conversation, attempt, family, models and lifetime only')
        _exact_keys(body, ('conversation_id', 'attempt_id', 'family', 'models', 'ttl_s'), (),
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
        ttl = body['ttl_s']
        if type(ttl) is not int or not 1 <= ttl <= self.config.max_ttl_s:
            raise InferenceError('TTL_INVALID', f'ttl_s must be an integer from 1 to {self.config.max_ttl_s}')
        why = self.readiness(family)
        if why is not None:
            raise InferenceError('FAMILY_NOT_READY', f'{family.id}: {why}')
        for model in models:
            self._selected(family, model, None)
        token = TOKEN_PREFIX + secrets.token_urlsafe(32)
        self.guard.hold(token)
        issued = self.clock()
        grant = Grant(digest(token), contract.fingerprint(token), conversation, attempt, family.id, models,
                      issued, issued + ttl)
        intent = {'format': GRANT_FORMAT, 'issuer': SERVICE, 'attempt_id': attempt, 'conversation_id': conversation,
                  'token_fingerprint': grant.fingerprint, 'family': family.id, 'models': list(models),
                  'issued_at': now_iso(issued), 'expires_at': now_iso(grant.expires_at),
                  'upstream': family.upstream.text()}
        # One grant per attempt, durably: the journal refuses a second grant receipt under the attempt's key, and a
        # grant receipt after a tombstone (E-05.6). The receipt and the registration happen under the attempt lock,
        # which a revocation by attempt takes too: whichever comes first, no grant is live after that revocation.
        key = f'inference/attempt/{attempt}/grant'
        with self._attempt_lock(attempt):
            try:
                receipt = self.journal.record(key, intent, {'state': 'live'}, conflict='ATTEMPT_HAS_GRANT')
            except InferenceError as exc:
                if exc.code == 'ATTEMPT_HAS_GRANT' and (self.journal.intent(key) or {}).get('format') \
                        == TOMBSTONE_FORMAT:
                    raise InferenceError('GRANT_ATTEMPT_REVOKED', 'the attempt was revoked before its grant was '
                                         'registered') from None
                raise
            with self._lock:
                self._grants[grant.digest] = self._by_fingerprint[grant.fingerprint] = grant
        return {'format': GRANT_FORMAT, 'token': token, **grant.describe(), 'grant_receipt': receipt}

    def revoke(self, body) -> dict:
        """Revoke a grant at once (its next request answers 401), then write its revocation receipt with the
        per-attempt summary. The grant is named by its token's fingerprint, or (E-05.6) by its conversation and
        attempt (``conversation_id`` and ``attempt_id`` in place of ``token_fingerprint``: one grant per attempt),
        for a dispatcher that lost the issue's answer; neither names an unknown grant (GRANT_UNKNOWN)."""
        self.housekeeping()
        by_attempt = isinstance(body, dict) and 'token_fingerprint' not in body \
            and ('attempt_id' in body or 'conversation_id' in body)
        selector = ('conversation_id', 'attempt_id') if by_attempt else ('token_fingerprint',)
        _exact_keys(body, selector + ('trigger', 'revoker'), (), 'CONTROL_BODY_INVALID', 'the revoke request')
        trigger, revoker = body['trigger'], body['revoker']
        if trigger not in TRIGGERS:
            raise InferenceError('TRIGGER_UNKNOWN', f'trigger must be one of {list(TRIGGERS)}')
        if not valid_revoker(revoker):
            raise InferenceError('REVOKER_INVALID', 'revoker must be 1 to 200 printable characters')
        if by_attempt:
            conversation = _uuid(body['conversation_id'], 'CONVERSATION_ID_INVALID', 'conversation_id')
            attempt = _uuid(body['attempt_id'], 'ATTEMPT_ID_INVALID', 'attempt_id')
            with self._attempt_lock(attempt):   # an issue of this attempt: registered already, or refused after
                with self._lock:
                    grant = next((g for g in self._grants.values()
                                  if g.attempt_id == attempt and g.conversation_id == conversation), None)
                    if grant is not None:
                        self._revoke_held(grant, trigger, revoker)
                if grant is None:
                    return self._tombstone(conversation, attempt, trigger, revoker)
        else:
            with self._lock:
                fingerprint = body['token_fingerprint']
                grant = self._by_fingerprint.get(fingerprint) if isinstance(fingerprint, str) else None
                if grant is None:
                    raise InferenceError('GRANT_UNKNOWN', 'no grant has that fingerprint')
                self._revoke_held(grant, trigger, revoker)
        self._write_revocation(grant)
        return {'format': REVOCATION_FORMAT, **grant.describe()}

    def _attempt_lock(self, attempt: str) -> '_AttemptLock':
        """The lock of one attempt id (a context manager; see __init__)."""
        return _AttemptLock(self, attempt)

    def _revoke_held(self, grant: Grant, trigger: str, revoker: str) -> None:
        """Under the lock: GRANT_ALREADY_REVOKED, or the grant marked revoked."""
        if grant.revocation is not None:
            raise InferenceError('GRANT_ALREADY_REVOKED', f'revoked at {grant.revocation["revoked_at"]}')
        self._mark_revoked(grant, trigger, revoker)

    def _tombstone(self, conversation: str, attempt: str, trigger: str, revoker: str) -> dict:
        """Under the attempt lock, for a revocation by attempt that found no grant (E-05.6): the tombstone receipt
        under the attempt's grant receipt key, so that a grant of this attempt is never registered after it (issue
        answers GRANT_ATTEMPT_REVOKED, in this run and after a restart). When that key already holds a grant
        receipt, the grant was issued in an earlier run of the broker and ended with it, or to another
        conversation: GRANT_UNKNOWN (no second grant of the attempt can be issued: ATTEMPT_HAS_GRANT)."""
        key = f'inference/attempt/{attempt}/grant'
        intent = {'format': TOMBSTONE_FORMAT, 'issuer': SERVICE, 'attempt_id': attempt, 'conversation_id': conversation}
        try:
            receipt = self.journal.record(key, intent, {'state': 'tombstoned'}, conflict='GRANT_UNKNOWN')
        except InferenceError as exc:
            if exc.code == 'GRANT_UNKNOWN':
                raise InferenceError('GRANT_UNKNOWN', 'no live grant has that conversation and attempt (a grant of '
                                     'the attempt ended with an earlier run, or is of another conversation)') from None
            raise
        self.audit.write({'event': 'attempt-tombstoned', 'attempt_id': attempt, 'conversation_id': conversation,
                          'trigger': trigger, 'revoker': revoker, 'receipt': receipt['operation_key']})
        return {'format': TOMBSTONE_FORMAT, 'state': 'tombstoned', 'conversation_id': conversation,
                'attempt_id': attempt, 'receipt': receipt}

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
        bound = {} if self.authorization is None else {'authorization': self.authorization.describe()}
        return {'format': STATUS_FORMAT, **bound, 'pid': os.getpid(), 'listeners': dict(self.listeners),
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

    def _refuse(self, code: str, detail: str, grant: Grant | None, audit: dict | None = None) -> InferenceError:
        if grant is not None:
            with self._lock:
                grant.refused += 1
        return InferenceError(code, detail, grant=grant, audit=audit)

    def _reach(self, family: Family, document: dict, grant: Grant) -> None:
        """PROVIDER_REACH_REFUSED when the family's reach checker finds something the provider would reach or run
        outside the request. The audit line records the rule and the key or type name, only in OBSERVED_WORD's
        grammar (None otherwise), never a value."""
        checker = REACH_CHECKERS.get(family.id)
        found = None if checker is None else checker(document)
        if found is None:
            return
        rule, name = found
        recorded = name if isinstance(name, str) and self._recordable('audit reach name', name, OBSERVED_WORD) \
            else None
        raise self._refuse('PROVIDER_REACH_REFUSED', f'{rule}: {recorded or "(a name outside the audit grammar)"}',
                           grant, audit={'reach': {'rule': rule, 'name': recorded}})

    def request_stop(self, by: str, *, wake: bool = True) -> bool:
        """Begin the stop: from now on every new request is refused BROKER_STOPPING. WAKE sets the stop event, on
        which serve waits (the control listener's stop sets it only once its answer is sent). True when this call
        began the stop; False when it had already begun (BY is then not recorded)."""
        with self._lock:
            first = not self._stopping
            self._stopping = True
            if first:
                self.stop_by = by
        if wake:
            self.stop_event.set()
        return first

    def after_stop(self, call: Callable) -> None:
        """Run CALL at the very end of stop() (serve's wait restores the signal handlers it installed)."""
        self._after_stop.append(call)

    def _not_stopping(self, grant: Grant) -> None:
        """Under the lock: once the broker's own stop has begun, no request is admitted (BROKER_STOPPING), before
        anything of it is written upstream."""
        if self._stopping:
            raise self._refuse('BROKER_STOPPING', 'the broker\'s stop has begun', grant)

    def _envelope(self, family: Family, grant: Grant) -> None:
        """A family whose upstream is not loopback is served only under the held authorization, for its provider
        and origin, and until its expiry (checked at admission; an answer already streaming completes)."""
        if family.upstream is None or family.upstream.loopback:
            return
        held = self.authorization
        if not minted(held):
            raise self._refuse('ENVELOPE_NOT_AUTHORIZED', f'{family.id}: no authorization of its envelope is held',
                               grant)
        if family.provider != held.provider or family.upstream != held.origin:
            raise self._refuse('ENVELOPE_MISMATCH', f'{family.id}: its provider or upstream is not the authorized '
                                                    'envelope\'s', grant)
        if self.clock() >= held.expires:
            raise self._refuse('ENVELOPE_EXPIRED', f'the authorization {held.receipt} expired at {held.expires_at}',
                               grant)

    def _selected(self, family: Family, model: str, grant: Grant | None) -> None:
        """A model of a family whose upstream is not loopback is issued and admitted only when the held selection
        selects it (beside the allowlist and the token's list: the configuration may not widen the selection)."""
        if family.upstream is None or family.upstream.loopback:
            return
        held = self.authorization
        if not minted(held):
            raise self._refuse('ENVELOPE_NOT_AUTHORIZED', f'{family.id}: no authorization of its envelope is held',
                               grant)
        if not held.selects(family.id, model):
            raise self._refuse('MODEL_NOT_SELECTED', f'{family.id}: the model is not in the held {held.selection} '
                                                     'selection', grant)

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
        if len(lengths) != 1 or not DECIMAL.fullmatch(lengths[0].strip()):
            raise self._refuse('BODY_LENGTH_INVALID', 'not one decimal Content-Length', grant)
        length = int(lengths[0])
        if length > self.config.max_request_bytes:
            raise self._refuse('BODY_TOO_LARGE', f'{length} bytes', grant)
        body = read(length) if length else b''
        if len(body) != length:
            raise self._refuse('BODY_LENGTH_INVALID', 'the body ended early', grant)
        return body

    def _forward_headers(self, headers, family: Family) -> tuple[list, tuple]:
        """(the headers forwarded, the header names stripped): only a header the family declares (Family.forwards,
        families.json: an allowlist since the security review's S1), and never a NOT_FORWARDED header, one the
        Connection header names, an auth header of any family, or an account-scope header (the provider account's
        scope is the key's, never the client's). Every other header is stripped and named, except the ones the
        broker itself consumes or sets again (CONSUMED and the family's auth header)."""
        named = {v.strip().lower() for value in headers.get_all('connection') or [] for v in value.split(',')}
        dropped = NOT_FORWARDED | named | {f.auth_header for f in self.config.families.values()}
        quiet = CONSUMED | {family.auth_header}
        forward, stripped = [], set()
        for name, value in headers.items():
            lower = name.lower()
            if family.forwards(lower) and lower not in dropped:
                forward.append((name, value))
            elif lower not in quiet:
                stripped.add(lower)
        return forward, tuple(sorted(stripped))

    def _header_shape(self, headers, body: bytes, grant: Grant) -> None:
        """Refused before anything is forwarded (the security review's S1): a header value holding a control
        character (0x00 to 0x1F except HTAB, and 0x7F; CR and LF of obsolete line folding included); a Content-Encoding other than absent or identity; a Content-Type other
        than one application/json with at most a charset=utf-8 parameter (case-insensitive), or none on a request
        with a body."""
        if any(HEADER_CONTROL.search(str(value)) for _, value in headers.items()):
            raise self._refuse('HEADER_VALUE_INVALID', 'a header value holds a control character', grant)
        encodings = headers.get_all('content-encoding') or []
        if encodings and (len(encodings) != 1 or encodings[0].strip().lower() != 'identity'):
            raise self._refuse('CONTENT_ENCODING_REFUSED', 'the body is declared encoded', grant)
        types = headers.get_all('content-type') or []
        if not types:
            if body:
                raise self._refuse('CONTENT_TYPE_REFUSED', 'a body without a Content-Type', grant)
            return
        parts = [part.strip().lower() for part in types[0].split(';')] if len(types) == 1 else []
        if not parts or parts[0] != 'application/json' or len(parts) > 2 \
                or (len(parts) == 2 and parts[1] != 'charset=utf-8'):
            raise self._refuse('CONTENT_TYPE_REFUSED', 'not one application/json Content-Type', grant)

    def stripped_names(self, names: tuple) -> dict:
        """What an admitted request's audit line records of the headers stripped from it: their names in
        OBSERVED_WORD's grammar (sorted, at most OBSERVED_NAMES), the others counted, never a value."""
        kept = [name for name in names if self._recordable('audit stripped header', name, OBSERVED_WORD)]
        return {'names': kept[:OBSERVED_NAMES], 'unrecorded': len(names) - len(kept[:OBSERVED_NAMES])}

    def admit(self, method: str, target: str, headers, read: Callable, flight: Flight | None = None) -> Admission:
        """Admit one inference request or refuse it with a stable code: the token first, then the route, the
        broker's stop and the envelope, the body and its model, then the token's absence from what is forwarded.
        The request is counted (information only) atomically at the end, and FLIGHT (serve_inference's) registered
        with it, so that a stop that begins after it finds it."""
        token, carriers = self._presented(headers)
        with self._lock:
            grant = self._grants.get(digest(token)) if TOKEN_SHAPE.fullmatch(token) else None
        if grant is None:
            raise InferenceError('TOKEN_UNKNOWN', 'not a token this broker issued')
        self._live(grant)
        family = self.config.families[grant.family]
        if (family.auth_header, family.auth_scheme) not in carriers:
            raise self._refuse('TOKEN_WRONG_HEADER', f'the {family.id} family reads {family.auth_header}', grant)
        path, has_query, query = target.partition('?')
        if (method, path) not in family.routes:
            raise self._refuse('ROUTE_NOT_ALLOWED', f'not a {family.id} route', grant)
        if has_query and not family.admits_query(query):
            raise self._refuse('QUERY_NOT_ALLOWED', f'the query is not one the {family.id} family declares', grant)
        with self._lock:
            self._not_stopping(grant)
            self._envelope(family, grant)
        body = self._read_body(headers, read, grant)
        self._header_shape(headers, body, grant)
        try:
            document = strict_json(body)
        except DuplicateKey:
            raise self._refuse('BODY_DUPLICATE_KEY', 'a JSON object of the body repeats a key', grant) from None
        except BodyEncoding as exc:
            raise self._refuse('BODY_ENCODING_INVALID', str(exc), grant) from None
        except (ValueError, UnicodeDecodeError, RecursionError):   # RecursionError: nested too deeply to parse
            raise self._refuse('BODY_NOT_JSON', 'the body is not JSON', grant) from None
        if not isinstance(document, dict):
            raise self._refuse('BODY_NOT_JSON', 'the body is not a JSON object', grant)
        model = document.get('model')
        if not isinstance(model, str) or not model:
            raise self._refuse('MODEL_MISSING', 'no string model field', grant)
        if model not in grant.models or model not in family.models:
            raise self._refuse('MODEL_NOT_ALLOWED', "not in the token's model list", grant)
        self._selected(family, model, grant)
        self._reach(family, document, grant)
        forward, stripped = self._forward_headers(headers, family)
        if token in target or any(token in value for _, value in forward) or token.encode('ascii') in body:
            raise self._refuse('TOKEN_IN_REQUEST', 'the token is in the path, a forwarded header or the body', grant)
        if family.upstream is None:
            raise self._refuse('UPSTREAM_NOT_CONFIGURED', family.id, grant)
        if self.readiness(family) is not None:
            raise self._refuse('PROVIDER_KEY_ABSENT', family.id, grant)
        with self._lock:
            self._live(grant)
            self._not_stopping(grant)
            self._envelope(family, grant)
            grant.requests += 1
            grant.in_flight += 1
            grant.bytes_in += len(body)
            if flight is not None:
                flight.grant = grant
                self._flights[id(flight)] = flight
        return Admission(grant, family, method, target, path, model, body, forward, stripped)

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
            document = strict_json(body) if body else None
        except (ValueError, UnicodeDecodeError, RecursionError):     # DuplicateKey included: no model is read
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
        flight = Flight(line, started, handler)

        def read(length: int) -> bytes:
            handler.body_consumed = True
            captured.append(handler.rfile.read(length))
            return captured[-1]
        try:
            admission = self.admit(handler.command, handler.path, handler.headers, read, flight)
        except InferenceError as exc:
            body = None
            if exc.grant is not None:
                line.update(attempt_id=exc.grant.attempt_id, conversation_id=exc.grant.conversation_id,
                            token_fingerprint=exc.grant.fingerprint, family=exc.grant.family)
                body = captured[0] if captured else _drain(handler)
            line.update(self.observed_request(handler.path, body))
            line.update(exc.audit or {})
            line.update(status=exc.status, code=exc.code, latency_ms=round((time.monotonic() - started) * 1000, 1))
            self.audit.write(line)
            _send_refusal(handler, exc)
            return
        grant, family = admission.grant, admission.family
        line.update(attempt_id=grant.attempt_id, conversation_id=grant.conversation_id,
                    token_fingerprint=grant.fingerprint, family=family.id, path=admission.path,
                    model=admission.model, request_bytes=len(admission.body))
        if admission.stripped:
            line['stripped_headers'] = self.stripped_names(admission.stripped)
        try:
            self._relay(handler, admission, flight)
        finally:
            self._settle(flight, 'unknown', 0, None, None, 'BROKER_ERROR')

    def _settle(self, flight: Flight, usage, sent: int, status, upstream_status, code) -> None:
        """Count FLIGHT's answer in its grant's summary (information only: nothing here refuses, closes or narrows
        a grant) and write its audit line, once: whoever claims it first (its pass-through, or the stop that cut
        it) settles it. It leaves the broker's flights only after its line is written, so that a stop waiting for
        it does not close the audit under it."""
        with self._lock:
            if not self._claim(flight, usage, sent, upstream_status):
                return
        self._finish(flight, usage, sent, status, upstream_status, code)

    def _claim(self, flight: Flight, usage, sent: int, upstream_status) -> bool:
        """Under the lock: claim FLIGHT's settlement and count it in its grant, once; False when already claimed."""
        if flight.settled:
            return False
        flight.settled = True
        grant = flight.grant
        grant.in_flight -= 1
        grant.bytes_out += sent
        if isinstance(usage, dict):
            grant.input_tokens += usage['input']
            grant.output_tokens += usage['output']
            grant.total_tokens += usage['total']
        elif upstream_status is not None and 200 <= upstream_status < 300:
            grant.unknown_usage += 1
        return True

    def _finish(self, flight: Flight, usage, sent: int, status, upstream_status, code) -> None:
        """Write a claimed FLIGHT's audit line, then let it leave the broker's flights."""
        try:
            flight.line.update(status=status, upstream_status=upstream_status, response_bytes=sent, usage=usage,
                               code=code, latency_ms=round((time.monotonic() - flight.started) * 1000, 1))
            self.audit.write(flight.line)
        finally:
            with self._lock:
                self._flights.pop(id(flight), None)
                self._settled.notify_all()

    def _relay(self, handler, admission: Admission, flight: Flight) -> None:
        """Send the admitted request to the family's upstream and stream the answer back as it arrives; FLIGHT is
        settled before the answer's last bytes are sent. A flight the stop cut sends nothing more: neither the
        request upstream nor any byte (a terminating chunk included) to the client."""
        family = admission.family

        def settle(usage, sent: int, status, upstream_status, code) -> None:
            self._settle(flight, usage, sent, status, upstream_status, code)
        headers = list(admission.headers) + [('Host', family.upstream.authority),
                                             ('Content-Length', str(len(admission.body))),
                                             ('Accept-Encoding', 'identity')]
        key = self._key_for(family)
        if key is not None:
            headers.append((family.auth_header, f'{family.auth_scheme} {key}' if family.auth_scheme else key))
        connection = None
        try:
            connection = self._connect(family.upstream, self.config.upstream_timeout_s)
            with self._lock:
                flight.connection, cut = connection, flight.cut
            if cut:
                connection.close()
                return                                   # the stop cut it before anything was sent upstream
            if isinstance(connection, _UpstreamConnection):
                connection.on_connect = lambda sock: self._connected(sock, admission, flight)
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
            if not flight.cut:
                _send_refusal(handler, error)
            return
        status, total = response.status, response.length
        flight.upstream_status = status
        reader = UsageReader(family.usage, response.getheader('content-type'))
        sent, code = 0, None
        try:
            if flight.cut:
                raise OSError('cut by the stop')
            handler.send_response_only(status, response.reason)
            flight.status = status
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
                if flight.cut:                           # the stop cut it: no further byte, no terminating chunk
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
                flight.sent = sent
        except OSError:
            code = 'CLIENT_GONE'
            handler.close_connection = True
        finally:
            connection.close()
        settle(reader.finish() if code is None else 'unknown', sent, status, status, code)

    def _connected(self, sock, admission: Admission, flight: Flight | None = None) -> None:
        """The upstream-connect audit line, at connect time (S-03.2): the peer the connection reached (IP and port)
        and its local address, with the origin, family and attempt; never a secret. A line that cannot be written
        leaves the connection unrecorded, which the live census judges FAIL, never PASS. Then, before any byte is
        sent (the security review's S3): a FLIGHT the stop cut while it was connecting is aborted here (CutByStop,
        an OSError: the connection is closed and nothing is sent; the stop has settled it BROKER_STOPPED)."""
        try:
            self.audit.write({'event': 'upstream-connect', 'attempt_id': admission.grant.attempt_id,
                              'family': admission.family.id, 'origin': admission.family.upstream.text(),
                              'peer': socket_address(sock.getpeername()), 'local': socket_address(sock.getsockname())})
        except (OSError, ValueError):
            pass
        if flight is not None:
            with self._lock:
                cut = flight.cut
            if cut:
                raise CutByStop('the stop cut the request while its upstream connection was made')

    # -- the listeners

    def start(self) -> dict:
        """Bind both listeners to 127.0.0.1, write the start receipt (the provider key's fingerprint, recorded
        once), then serve. Returns the bound ports."""
        if self.config.control_port is None or self.config.inference_port is None:
            raise InferenceError('CONFIG_INCOMPLETE', 'a listener port is not configured')
        bound = bound_families(self.config)
        if bound and not minted(self.authorization):
            raise InferenceError('ENVELOPE_NOT_AUTHORIZED', 'a family whose upstream is not loopback starts only under '
                                                            'an authorization authorize() returned in this process')
        for family in bound:
            if family.provider != self.authorization.provider or family.upstream != self.authorization.origin:
                raise InferenceError('ENVELOPE_MISMATCH', f'{family.id}: its provider or upstream is not the '
                                                          'authorized envelope\'s')
        check_reach(self.config)
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
            if self.authorization is not None:
                intent['authorization'] = self.authorization.describe()
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
        """The clean stop: refuse every new request (BROKER_STOPPING), close both listeners, give the requests
        already admitted at most drain_ceiling_s to finish and cut the rest (BROKER_STOPPED), write the pending
        receipts and the broker-stop audit line, and close the journal and the audit. Live grants end with the
        process (the broker-stop line names them). It never waits on a client or an upstream beyond its ceilings."""
        if self._stopped:
            return
        self._stopped = True
        # From here no request is admitted (BROKER_STOPPING), before anything of it is written upstream: a handler
        # still alive after the listeners stop (a keep-alive connection) forwards nothing more.
        self.request_stop('stop')
        try:
            stoppers = [threading.Thread(target=server.shutdown) for server in self._servers]
            for stopper in stoppers:
                stopper.start()
            for stopper in stoppers:
                stopper.join()
            self._close_servers()
            try:
                cut = self._drain()
                self.housekeeping()
                with self._lock:
                    live = [g.fingerprint for g in self._grants.values() if g.revocation is None]
                self.audit.write({'event': 'broker-stop', 'stopped_by': self.stop_by, 'requests_cut': cut,
                                  'live_grants_ended': live})
            finally:
                self.journal.close()
                self.audit.close()
        finally:
            self._stop_done = True
            self.stop_finished.set()
            for call in self._after_stop:
                call()

    def _wait_flights(self, ceiling: float) -> None:
        """Wait until no admitted request is unsettled, for at most CEILING seconds, in slices of STOP_POLL_S so
        that an interrupt is delivered meanwhile (a second interrupt then exits at once)."""
        deadline = time.monotonic() + ceiling
        with self._lock:
            while self._flights and (left := deadline - time.monotonic()) > 0:
                self._settled.wait(min(left, STOP_POLL_S))

    def _drain(self) -> int:
        """The stop's wait for the requests already admitted, bounded by drain_ceiling_s; then each one still
        unsettled is cut: marked and its settlement claimed under the lock, then its client's and its upstream's
        sockets shut (the upstream's closed), and settled here with BROKER_STOPPED (never as an upstream answer).
        Returns how many were cut."""
        self._wait_flights(self.drain_ceiling_s)
        cut = []
        with self._lock:                # marked cut and claimed before anything is interrupted: a woken pass-through
            for flight in list(self._flights.values()):         # can no longer settle it as its own failure
                if not flight.settled:
                    flight.cut = True
                    sent, status, upstream_status = flight.sent, flight.status, flight.upstream_status
                    self._claim(flight, 'unknown', sent, upstream_status)
                    cut.append((flight, sent, status, upstream_status))
        for flight, sent, status, upstream_status in cut:
            flight.interrupt()
            self._finish(flight, 'unknown', sent, status, upstream_status, 'BROKER_STOPPED')
        self._wait_flights(STOP_CUT_CEILING_S)          # a settle its own thread had already claimed
        return len(cut)


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
    if handler.headers.get('transfer-encoding') is None and DECIMAL.fullmatch(length.strip()) \
            and int(length) <= DRAIN_LIMIT:
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
            elif self.command == 'POST' and path == '/v1/stop':
                _exact_keys(self._json_body(), (), (), 'CONTROL_BODY_INVALID', 'the stop request')
                self._stop(broker)
                return
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

    def _stop(self, broker: Broker) -> None:
        """POST /v1/stop (the stop from a session with no console): the stop begins at once (every new request is
        refused BROKER_STOPPING), the answer is sent, and only then is serve woken to close the listeners."""
        first = broker.request_stop('control', wake=False)
        try:
            _send_json(self, 202, {'format': STOP_FORMAT, 'state': 'stopping', 'began': first,
                                   'stopped_by': broker.stop_by}, close=True)
        except OSError:
            self.close_connection = True
        finally:
            broker.stop_event.set()

    def _json_body(self):
        if (self.headers.get('content-type') or '').split(';')[0].strip().lower() != 'application/json':
            raise InferenceError('CONTROL_CONTENT_TYPE', 'not application/json')
        length = self.headers.get('content-length')
        if self.headers.get('transfer-encoding') is not None or length is None \
                or not DECIMAL.fullmatch(length.strip()) or int(length) > CONTROL_BODY_LIMIT:
            raise InferenceError('CONTROL_BODY_INVALID', 'a Content-Length of at most 64 KiB is required')
        self.body_consumed = True
        try:
            return strict_json(self.rfile.read(int(length)))
        except DuplicateKey:
            raise InferenceError('CONTROL_BODY_INVALID', 'a JSON object of the body repeats a key') from None
        except BodyEncoding:
            raise InferenceError('CONTROL_BODY_INVALID', 'the body is not UTF-8 without a byte order mark') from None
        except (ValueError, UnicodeDecodeError, RecursionError):   # RecursionError: nested too deeply to parse
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


# ---------------------------------------------------------------- the credential enter command (S-03.3)

ENTERED_KEY_PREFIX = 'sk-ant-api'                  # the provider's API key form
ADMIN_KEY_PREFIX = 'sk-ant-admin'                  # the provider's admin key form: never stored
ENTERED_KEY_CHARACTERS = re.compile(r'[A-Za-z0-9_-]+')
# A broad bound, not an exact length (no length is verified for the provider's keys): the whole value.
ENTERED_KEY_LENGTH = (40, 512)
# The rules a pasted value must meet, in the order they are checked; a refusal names the first one it fails.
ENTERED_KEY_RULES = (
    ('empty', 'the value is empty'),
    ('whitespace', 'the value holds a space, a tab or a line break (it is not stripped)'),
    ('admin-key', f'the value is an admin key ({ADMIN_KEY_PREFIX}...), which is never stored'),
    ('prefix', f'the value does not begin {ENTERED_KEY_PREFIX}'),
    ('characters', 'the value holds a character other than a letter, a digit, "_" or "-"'),
    ('length', f'the value is not {ENTERED_KEY_LENGTH[0]} to {ENTERED_KEY_LENGTH[1]} characters long'),
)
KEY_PROMPT = 'Paste the dedicated provider key (it is not shown), then press Enter: '
CLIPBOARD_REMINDER = ('Clear the clipboard now: the key was pasted from it, and it stays there until something else '
                      'is copied.')


def entered_key_rule(value) -> str | None:
    """The name of the first of ENTERED_KEY_RULES that VALUE fails, or None when it is key-shaped. Nothing of the
    value is returned."""
    if not isinstance(value, str) or not value:
        return 'empty'
    if any(c.isspace() for c in value):
        return 'whitespace'
    if value.startswith(ADMIN_KEY_PREFIX):
        return 'admin-key'
    if not value.startswith(ENTERED_KEY_PREFIX):
        return 'prefix'
    if not value.isascii() or not ENTERED_KEY_CHARACTERS.fullmatch(value):
        return 'characters'
    if not ENTERED_KEY_LENGTH[0] <= len(value) <= ENTERED_KEY_LENGTH[1]:
        return 'length'
    return None


def stdin_is_console(stream) -> bool:
    """Whether STREAM (standard input) is an interactive console. On Windows its handle must have a console mode
    (GetConsoleMode succeeds only on a console handle: a pipe, a file, the null device or a redirection fails), not
    merely isatty; elsewhere its descriptor must be a terminal."""
    try:
        fd = stream.fileno()
    except (AttributeError, OSError, ValueError):
        return False
    if not isinstance(fd, int) or fd < 0:
        return False
    if os.name == 'nt':
        import ctypes
        import msvcrt
        from ctypes import wintypes
        try:
            handle = msvcrt.get_osfhandle(fd)
        except OSError:
            return False
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel32.GetConsoleMode.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        kernel32.GetConsoleMode.restype = wintypes.BOOL
        mode = wintypes.DWORD()
        return bool(kernel32.GetConsoleMode(handle, ctypes.byref(mode)))
    try:
        return os.isatty(fd)
    except OSError:
        return False


class Console:
    """The Owner's console, for credential-enter: interactive() is stdin_is_console(STDIN); read_hidden(prompt)
    reads one line with echo off through getpass, which reads the console itself on Windows (msvcrt) and the
    terminal elsewhere. getpass's fallback, which would read standard input with echo, is never taken: its warning
    is an error here (KEY_CONSOLE_REQUIRED)."""

    def __init__(self, stdin):
        self.stdin = stdin

    def interactive(self) -> bool:
        return stdin_is_console(self.stdin)

    def read_hidden(self, prompt: str) -> str:
        import getpass
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter('error', getpass.GetPassWarning)
            try:
                return getpass.getpass(prompt)
            except getpass.GetPassWarning:
                raise InferenceError('KEY_CONSOLE_REQUIRED', 'echo cannot be turned off on this input') from None


def credential_enter(console, provider, store_factory: Callable, provider_id: str, *, replace: bool,
                     guard) -> dict:
    """The Owner's key entry (S-03.3; the Owner's act 2 of OA-12): refuse unless CONSOLE is interactive, and refuse
    an existing entry without REPLACE, both before prompting; read the key once at a hidden prompt; refuse a value
    that is not key-shaped (naming the rule only); store it through the custody path of credential-set (PROVIDER,
    an aieh-credential-act/1 receipt with fingerprints only in the store STORE_FACTORY opens, read back). The report
    names the entry and the receipt and reminds the Owner to clear the clipboard; nothing in it is derived from the
    key."""
    if not isinstance(provider_id, str) or not PROVIDER_ID.fullmatch(provider_id):
        raise InferenceError('PROVIDER_ID_INVALID', 'not a provider id')
    if not console.interactive():
        raise InferenceError('KEY_CONSOLE_REQUIRED', 'standard input is not an interactive console')
    existing = provider.get(ENTRY)
    exists = existing is not None
    del existing
    if exists and not replace:
        raise InferenceError('KEY_ENTRY_EXISTS', f'the entry "{ENTRY}" exists and --replace was not given')
    try:
        key = console.read_hidden(KEY_PROMPT)
    except (KeyboardInterrupt, EOFError):
        raise InferenceError('KEY_ENTRY_CANCELLED', 'the prompt ended before a key was entered') from None
    rule = entered_key_rule(key)
    if rule is not None:
        del key
        raise InferenceError('KEY_NOT_KEY_SHAPED', f'refused by the rule {rule}: {dict(ENTERED_KEY_RULES)[rule]}; '
                                                   'nothing was stored')
    guard.hold(key)
    store = store_factory()
    try:
        stored = credential_set(provider, store, provider_id, key, guard=guard)
    finally:
        store.close()
        del key
    return {'format': CREDENTIAL_ENTER_FORMAT, 'entry': ENTRY, 'user': provider_id, 'verb': stored['verb'],
            'stored': True, 'read_back': True,
            'message': f'The provider key is stored in the credential entry "{ENTRY}" (user {provider_id}).',
            'reminder': CLIPBOARD_REMINDER,
            'receipt': {k: stored['receipt'][k] for k in ('operation_key', 'format', 'state')}}


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
    # serve, for a family whose upstream is not loopback: store -> verify(target, manifest_digest, now), the read
    # side of the provider-envelope authorizations (envelope_decisions.verifier); None refuses such a start.
    authorization: Callable | None = None
    clock: Callable = time.time  # serve: the broker's clock (the envelope's expiry, at start and at admission)
    # credential-enter: the console the key is pasted at (interactive(), read_hidden(prompt)); None is the real
    # console of STDIN (Console). A test passes its own, never a real console.
    console: object = None


class StopRequest:
    """The stop a signal handler asked for: ASKED is the signal's name once one arrived. The handler touches only
    this plain attribute (no lock, no Event): Event.set() inside a handler can deadlock against the main thread's own
    wait on that event (the security review's S4); serve's wait reads it and begins the stop from the main thread."""

    def __init__(self):
        self.asked: str | None = None


def stop_signal_handler(pending: StopRequest, stopping: Callable[[], bool], finished: Callable[[], bool], *,
                        exit: Callable = os._exit) -> Callable:   # noqa: A002 - the forced exit, injectable
    """The handler of STOP_SIGNALS. The first interrupt records its name in PENDING, and nothing else; one that
    arrives once a stop was asked (PENDING, or STOPPING: a plain read, the control listener's stop included) and
    before it has finished exits at once with FORCED_EXIT, writing nothing further; one after the stop has
    FINISHED is ignored (the process is ending). STOPPING and FINISHED read plain attributes only."""
    def handler(signum, frame):
        if finished():
            return
        if pending.asked is not None or stopping():
            exit(FORCED_EXIT)
            return
        try:
            pending.asked = signal.Signals(signum).name
        except ValueError:
            pending.asked = f'signal {signum}'
    return handler


def install_stop_signals(pending: StopRequest, stopping: Callable[[], bool] = lambda: False,
                         finished: Callable[[], bool] = lambda: False) -> Callable:
    """Install stop_signal_handler for each of STOP_SIGNALS the platform has (only the main thread can); returns
    the call that restores the previous handlers (a no-op off the main thread). On Windows the C runtime delivers
    Ctrl-C as SIGINT and every other console control event (Ctrl-Break, and the console's close) as SIGBREAK."""
    if threading.current_thread() is not threading.main_thread():
        return lambda: None
    handler, previous = stop_signal_handler(pending, stopping, finished), {}
    for name in STOP_SIGNALS:
        number = getattr(signal, name, None)
        if number is not None:
            previous[number] = signal.signal(number, handler)

    def restore():
        if threading.current_thread() is threading.main_thread():
            for number, old in previous.items():
                signal.signal(number, old)
    return restore


def wait_for_stop(served, pending: StopRequest, poll_s: float = STOP_POLL_S) -> None:
    """The main thread's loop of serve's wait: in slices of POLL_S, until the stop is asked. A broker's stop event
    is set by its control listener's stop, or here, from the main thread, once a signal recorded its name in
    PENDING (request_stop takes the lock and sets the event: never inside the handler)."""
    if isinstance(served, Broker):
        while not served.stop_event.wait(poll_s):
            if pending.asked is not None:
                served.request_stop(pending.asked)
    else:
        idle = threading.Event()        # never set: the slice at which a signal handler runs
        while pending.asked is None:
            idle.wait(poll_s)


def _wait_for_interrupt(served, poll_s: float = STOP_POLL_S) -> None:
    """serve's wait (and the qualification's fake upstream's): until the stop is asked, by an interrupt (SIGINT,
    SIGBREAK, SIGTERM where the platform has them) or, for a broker, by the control listener's POST /v1/stop. It
    waits in slices of POLL_S, the interval at which the interpreter runs a signal handler (an indefinite wait ignores
    Ctrl-C on Windows). For a broker the handlers stay until its stop has finished, so that a second interrupt during
    the stop exits at once; for anything else they are restored when it returns."""
    pending = StopRequest()
    if isinstance(served, Broker):
        restore = install_stop_signals(pending, lambda: served._stopping, lambda: served._stop_done)
        served.after_stop(restore)
        wait_for_stop(served, pending, poll_s)
        return
    restore = install_stop_signals(pending)
    try:
        wait_for_stop(served, pending, poll_s)
    finally:
        restore()


def managed_context() -> Context:
    store_module = _load('integration_store', REPO / 'integrations' / 'store' / 'integration_store.py')
    res = paths.resolve()

    def authorization(store):
        return _load('envelope_decisions', ENVELOPE_DECISIONS).verifier(store)
    return Context(component=lambda: res.components.get(COMPONENT), provider=credentials.select_provider,
                   store=lambda: store_module.open_store(paths.ensure('state', res, 'integration')
                                                         / 'integration.sqlite'),
                   logs=lambda: paths.ensure('logs', res, 'inference'), stdin=sys.stdin, out=sys.stdout,
                   err=sys.stderr, wait=_wait_for_interrupt, authorization=authorization, console=Console(sys.stdin))


def _serve(ctx: Context, guard: BrokerGuard) -> dict:
    config = load_config(ctx.component(), allow_ephemeral=ctx.allow_ephemeral)   # read once: the snapshot served
    if config.control_port is None or config.inference_port is None:
        raise InferenceError('CONFIG_INCOMPLETE', 'a listener port is not configured')
    # The start precondition (S-03.5), only when a family's upstream is not loopback: before the key is read and
    # before any listener opens. A refusal exits 2 and writes nothing.
    authorization = authorize(config, ctx.authorization, ctx.store, ctx.clock) if bound_families(config) else None
    check_reach(config)     # S-03.3: a family with no reach checker serves a loopback upstream only
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
    broker = Broker(config, provider_key=provider_key, journal=journal, audit=audit, guard=guard, clock=ctx.clock,
                    authorization=authorization)
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


def _operation_id(value: str) -> str:
    if not inference_envelope.OPERATION.fullmatch(value):
        raise argparse.ArgumentTypeError('an operation id is lower-case letters, digits and hyphens (at most 128)')
    return value


def main(argv=None, context: Context | None = None) -> int:
    parser = argparse.ArgumentParser(prog='inference_broker.py', description='The inference broker (S-03.2; '
                                     'decision 0015 as amended). Exit 0 done, 1 failed, 2 refused.')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('config', help='validate components.inference_broker and print the effective families; reads '
                                  'no credential, opens no listener')
    env = sub.add_parser('envelope', help='print the live provider envelope and its digest and, with --operation, '
                                          'the canonical manifest to propose for the Owner\'s authorization (as a '
                                          'JSON string); reads no credential or store, opens no listener')
    env.add_argument('--operation', type=_operation_id, help='the operation id of the manifest '
                                                             '(operations/<id>.json)')
    cred = sub.add_parser('credential-set', help='store the provider key, read from standard input only, as the '
                                                 'entry "AIEH model provider"; prints its fingerprint')
    cred.add_argument('--provider', required=True, help='the provider id (the entry\'s user name)')
    enter = sub.add_parser('credential-enter', help='the Owner\'s key entry, in his own console window: paste the '
                                                    'provider key once at a hidden prompt; it is stored as the entry '
                                                    '"AIEH model provider"; prints nothing derived from the key')
    enter.add_argument('--provider', required=True, help='the provider id (the entry\'s user name)')
    enter.add_argument('--replace', action='store_true', help='replace an existing entry (refused without it)')
    sub.add_parser('serve', help='run the broker on its two loopback listeners until stopped (Ctrl-C, Ctrl-Break, '
                                 'SIGTERM, or inference_control.py stop)')
    args = parser.parse_args(argv)
    guard = BrokerGuard()
    report, message, code = None, '', 0
    try:
        ctx = context or managed_context()
        out, err = ctx.out, ctx.err
        if args.command == 'config':
            report = load_config(ctx.component(), allow_ephemeral=ctx.allow_ephemeral).describe()
        elif args.command == 'envelope':
            report = envelope_report(load_config(ctx.component(), allow_ephemeral=ctx.allow_ephemeral),
                                     args.operation)
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
        elif args.command == 'credential-enter':
            if not PROVIDER_ID.fullmatch(args.provider):
                raise InferenceError('PROVIDER_ID_INVALID', 'not a provider id')
            console = ctx.console if ctx.console is not None else Console(ctx.stdin)
            report = credential_enter(console, contract.WatchedProvider(ctx.provider(), guard), ctx.store,
                                      args.provider, replace=args.replace, guard=guard)
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
