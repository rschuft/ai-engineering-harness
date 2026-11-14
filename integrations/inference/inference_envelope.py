"""The provider envelope (plan leaf S-03.5, slice 1; its spending limit retired by S-03.6, decision 0021
amendment 1): what the Owner authorizes before the inference broker may start a family whose upstream is not
loopback, as one canonical document, its digest and its operation manifest.

The live envelope is a projection of the one configuration snapshot ``serve`` serves, never a second copy: the
provider id, the one upstream origin and (when the envelope selects them) the model identifiers come from the
families the broker will use (``inference_broker.live_envelope``); only what has no home there is the block
``components.inference_broker.envelope`` of config.yml, checked here (``check_block``):

    envelope:
      expires_at: "2026-12-31T00:00:00Z"   # a quoted string, YYYY-MM-DDTHH:MM:SSZ (UTC): a security validity window
      selection: envelope                  # envelope | delegation

An unquoted timestamp (which YAML reads as a datetime) is refused, never normalized, so the canonical document
holds strings only. The envelope carries no spending limit: ``limit`` and its former members (``amount``,
``currency``, ``enforced_by``, ``cap``) are refused (``CONFIG_ENVELOPE_INVALID``), never ignored (S-03.6, on the
Owner's direction of 2026-11-13: spending is bounded by the provider account's own limits).

The canonical document (``FORMAT``), exactly these members, in this order: ``format``, ``provider``,
``origin`` (``https://<host>:<port>``), ``expires_at`` and ``selection`` (``{"by": "envelope", "models":
{<family>: [<ids, sorted>]}}`` or ``{"by": "delegation", "record": "decision:0018", "point": "3"}``). Its digest
(``digest``), which the Owner's authorization names as its target, is ``sha256:`` and the sha256 of the document
as canonical JSON by the integration store's own rule (storecore.canonical_json: sorted keys, no whitespace,
UTF-8, no NaN; repeated here, a test asserts them equal). The operation manifest ``operations/<operation>.json``
(``manifest_text``) is a pure function of the document and the operation id: ``operation``, ``kind``
(``provider-envelope``), ``target`` (the digest), ``expiresAt`` (the envelope's expiry) and ``envelope`` (the
document), as JSON with a two-space indent, UTF-8 kept, one final LF. A change of either form is a new format:
``/2`` dropped ``/1``'s ``limit``, so a receipt recorded over a ``/1`` document names a digest no live envelope
has, and authorizes no start.

Standard library only. It opens nothing: no file, store, credential or connection.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import re

FORMAT = 'aieh-provider-envelope/2'
KIND = 'provider-envelope'           # the manifest's kind: the receipt's subject.operationKind
BLOCK_FIELDS = ('expires_at', 'selection')
# The spending limit of aieh-provider-envelope/1 and its members, retired by S-03.6 (decision 0021 amendment 1):
# a block that still names one is refused, never ignored.
RETIRED_FIELDS = ('limit', 'amount', 'currency', 'enforced_by', 'cap')
DOCUMENT_FIELDS = ('format', 'provider', 'origin', 'expires_at', 'selection')
MANIFEST_FIELDS = ('operation', 'kind', 'target', 'expiresAt', 'envelope')
SELECTIONS = ('envelope', 'delegation')
DELEGATION = {'by': 'delegation', 'record': 'decision:0018', 'point': '3'}
TIMESTAMP = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z')
# owner_decision.OPERATION, repeated (this module imports nothing of the owner recorders; a test asserts equal).
OPERATION = re.compile(r'[a-z0-9][a-z0-9-]{0,127}')
INVALID = 'CONFIG_ENVELOPE_INVALID'


class EnvelopeError(ValueError):
    """A refusal with a stable code of the inference broker's (CODES there) and its detail."""

    def __init__(self, code: str, detail: str):
        self.code, self.detail = code, detail
        super().__init__(f'{code}: {detail}')


def _invalid(detail: str) -> EnvelopeError:
    return EnvelopeError(INVALID, f'components.inference_broker.envelope: {detail}')


def _exact(node, required: tuple, optional: tuple, where: str) -> None:
    if not isinstance(node, dict):
        raise _invalid(f'{where} is not a mapping')
    unknown = sorted(str(k) for k in node if k not in required + optional)
    missing = [k for k in required if k not in node]
    if unknown or missing:
        raise _invalid(f'{where}: unknown {unknown}, missing {missing}')


def _quoted(value, what: str, where: str) -> str:
    if isinstance(value, (datetime.date, datetime.datetime, float, int)) and not isinstance(value, bool):
        raise _invalid(f'{where} is read as a {type(value).__name__}: quote it, as {what}')
    if not isinstance(value, str):
        raise _invalid(f'{where} must be {what}')
    return value


def parse_expiry(text: str) -> datetime.datetime | None:
    """TEXT (YYYY-MM-DDTHH:MM:SSZ) as an aware UTC datetime, or None."""
    if not isinstance(text, str) or not TIMESTAMP.fullmatch(text):
        return None
    try:
        return datetime.datetime.strptime(text, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=datetime.timezone.utc)
    except ValueError:
        return None


def check_block(raw) -> dict | None:
    """components.inference_broker.envelope, checked (CONFIG_ENVELOPE_INVALID), as {expires_at, selection}; None
    when it is absent or null. A retired spending key (RETIRED_FIELDS) is refused by name."""
    if raw is None:
        return None
    if isinstance(raw, dict):
        retired = sorted(str(k) for k in raw if k in RETIRED_FIELDS)
        if retired:
            raise _invalid(f'{retired} retired with the spending limit (S-03.6, decision 0021 amendment 1): the '
                           'envelope carries no limit, amount, currency, enforcement or cap; remove them')
    _exact(raw, BLOCK_FIELDS, (), 'the block')
    expires = _quoted(raw['expires_at'], 'a "YYYY-MM-DDTHH:MM:SSZ" string', 'expires_at')
    if parse_expiry(expires) is None:
        raise _invalid('expires_at must be a UTC time, YYYY-MM-DDTHH:MM:SSZ')
    selection = raw['selection']
    if selection not in SELECTIONS:
        raise _invalid(f'selection must be one of {list(SELECTIONS)}')
    return {'expires_at': expires, 'selection': selection}


def document(block: dict, provider: str, origin: str, models: dict) -> dict:
    """The canonical envelope document of BLOCK (check_block's) over the bound families: PROVIDER, ORIGIN (the
    origin's text) and MODELS ({family: [ids]}, read only when the envelope selects the models)."""
    if block['selection'] == 'envelope':
        selection = {'by': 'envelope', 'models': {family: sorted(models[family]) for family in sorted(models)}}
    else:
        selection = dict(DELEGATION)
    return {'format': FORMAT, 'provider': provider, 'origin': origin, 'expires_at': block['expires_at'],
            'selection': selection}


def canonical_json(value) -> str:
    """storecore.canonical_json, repeated: sorted keys, no whitespace, UTF-8 kept, no NaN."""
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def digest(doc: dict) -> str:
    """The envelope's canonical digest: the target of the Owner's provider-envelope authorization."""
    return 'sha256:' + hashlib.sha256(canonical_json(doc).encode('utf-8')).hexdigest()


def manifest_path(operation: str) -> str:
    return f'operations/{operation}.json'


def manifest_text(doc: dict, operation: str) -> str:
    """The canonical operation manifest of DOC under OPERATION: the text the Owner is shown and authorizes."""
    if not isinstance(operation, str) or not OPERATION.fullmatch(operation):
        raise ValueError('the operation id is lower-case letters, digits and hyphens (at most 128)')
    manifest = {'operation': operation, 'kind': KIND, 'target': digest(doc), 'expiresAt': doc['expires_at'],
                'envelope': doc}
    return json.dumps(manifest, indent=2, ensure_ascii=False) + '\n'


def manifest_digest(doc: dict, operation: str) -> str:
    """sha256 of the canonical manifest's bytes, as the authorization receipt records its manifest blob's."""
    return 'sha256:' + hashlib.sha256(manifest_text(doc, operation).encode('utf-8')).hexdigest()
