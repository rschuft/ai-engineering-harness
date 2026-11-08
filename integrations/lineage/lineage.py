"""Typed lineage references and the resolver interface (plan leaf P-03.1).

Blueprint section ``#authority``: "Each source record keeps its native ID. The
integration only needs a small envelope containing stable pointers", and "Other
systems carry references and projections, not competing lifecycle states". This
module is that envelope. For every reference kind it has a typed, immutable value,
a canonical text form with a parser and a formatter that round-trip, and the
machine-readable schema in ``lineage_schema.json``, which states each kind's
authority, stable identity, revision anchor and validation rule.

It also defines the resolver interface:

- ``Resolution``: the answer to one resolution. It is ``resolved`` or names
  exactly why not (``missing``, ``revision-mismatch``, ``digest-mismatch``,
  ``authority-unavailable``, ``unsupported-kind``, ``ambiguous``). It has no truth
  value, so it cannot be mistaken for a success.
- ``Resolver``: ``resolve(reference) -> Resolution`` (the pinned revision, when the
  reference has one) and ``current(reference) -> Resolution`` (the same identity at
  the authority's current revision). Resolvers are read-only.
- ``Registry``: resolves any reference. A kind whose authority does not exist yet
  answers ``authority-unavailable`` and names the leaf that will supply it; a kind
  whose identity is not settled answers ``unsupported-kind``.

The concrete read-only resolvers are in ``lineage_resolve.py``. This module runs no
tool and opens no store. Standard library only; the ``design`` kind reuses the P-02.1
pointer code in ``integrations/planning/planning_adapter.py`` unchanged.
"""
import hashlib
import importlib.util
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import ClassVar, Protocol

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
SCHEMA_PATH = HERE / 'lineage_schema.json'
SCHEMA_FORMAT = 'lineage-reference-schema/v1'
SCHEMA_VERSION = 1


def _load(name, path):
    """Load a sibling module by path once (``python -I`` adds no script directory)."""
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module


planning = _load('planning_adapter', REPO / 'integrations' / 'planning' / 'planning_adapter.py')

# ---------------------------------------------------------------------------
# Outcomes

RESOLVED = 'resolved'
MISSING = 'missing'
REVISION_MISMATCH = 'revision-mismatch'
DIGEST_MISMATCH = 'digest-mismatch'
AUTHORITY_UNAVAILABLE = 'authority-unavailable'
UNSUPPORTED_KIND = 'unsupported-kind'
AMBIGUOUS = 'ambiguous'
OUTCOMES = (RESOLVED, MISSING, REVISION_MISMATCH, DIGEST_MISMATCH, AUTHORITY_UNAVAILABLE,
            UNSUPPORTED_KIND, AMBIGUOUS)

STATUSES = ('implemented', 'authority-unavailable', 'unknown')
PINNING = ('required', 'optional')
NOT_YET_VERIFIED = 'not yet verified'


class MalformedReference(ValueError):
    """Text or values that do not form a reference of a known kind (a caller error)."""

    def __init__(self, code, message, text=None):
        super().__init__(f'{code}: {message}')
        self.code = code
        self.message = message
        self.text = text


# ---------------------------------------------------------------------------
# Grammar pieces

HEX64 = r'[0-9a-f]{64}'
COMMIT = planning.COMMIT                       # 40 or 64 lowercase hex digits, as P-02.1
SEGMENT = r'(?:[A-Za-z0-9._~-]|%[0-9A-F]{2})+'  # a native ID, canonically percent-encoded
NAME_PART = r'[A-Za-z0-9_][A-Za-z0-9._-]*'     # a repository name part
REPOSITORY = rf'{NAME_PART}(?:/{NAME_PART})*'
OWNER_REPOSITORY = rf'{NAME_PART}/{NAME_PART}'
COUNT = r'0|[1-9][0-9]{0,17}'
POSITIVE = r'[1-9][0-9]{0,17}'
UUID = r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
TASK_ID = r'[A-Z]+-[0-9]+(?:\.[0-9]+)*'
EFFECT_KEY = r'fx1-[0-9a-f]{64}'

_UNRESERVED = frozenset(b'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~')
_FULL = {name: re.compile(rf'^(?:{pattern})$') for name, pattern in {
    'hex64': HEX64, 'commit': COMMIT, 'segment': SEGMENT, 'repository': REPOSITORY,
    'owner_repository': OWNER_REPOSITORY, 'uuid': UUID, 'task': TASK_ID, 'effect_key': EFFECT_KEY,
}.items()}


def encode_segment(value):
    """A native ID as one canonical segment: UTF-8, every byte outside A-Z a-z 0-9 - . _ ~
    percent-encoded with upper-case hex digits."""
    if not isinstance(value, str) or not value:
        raise MalformedReference('REFERENCE_MALFORMED', f'a native ID must be non-empty text: {value!r}')
    try:
        data = value.encode('utf-8')
    except UnicodeEncodeError:
        raise MalformedReference('REFERENCE_MALFORMED', f'not encodable as UTF-8: {value!r}') from None
    return ''.join(chr(b) if b in _UNRESERVED else f'%{b:02X}' for b in data)


def decode_segment(text):
    """The native ID of one canonical segment; refuses any non-canonical spelling."""
    if not isinstance(text, str) or not _FULL['segment'].fullmatch(text):
        raise MalformedReference('REFERENCE_MALFORMED', f'not a segment: {text!r}', text)
    out = bytearray()
    index = 0
    while index < len(text):
        if text[index] == '%':
            out.append(int(text[index + 1:index + 3], 16))
            index += 3
        else:
            out.append(ord(text[index]))
            index += 1
    try:
        value = out.decode('utf-8')
    except UnicodeDecodeError:
        raise MalformedReference('REFERENCE_MALFORMED', f'segment is not UTF-8: {text!r}', text) from None
    if encode_segment(value) != text:
        raise MalformedReference('REFERENCE_MALFORMED', f'segment is not canonically encoded: {text!r}', text)
    return value


def _require(condition, kind, message):
    if not condition:
        raise MalformedReference('REFERENCE_MALFORMED', f'{kind}: {message}')


def _is(name, value):
    return isinstance(value, str) and bool(_FULL[name].fullmatch(value))


def _is_count(value, minimum):
    return type(value) is int and minimum <= value < 10 ** 18


def _native(kind, name, value):
    """A native ID field: non-empty text that encodes (checked by encoding it)."""
    try:
        encode_segment(value)
    except MalformedReference as exc:
        raise MalformedReference('REFERENCE_MALFORMED', f'{kind}: {name}: {exc.message}') from None


# ---------------------------------------------------------------------------
# References

@dataclass(frozen=True)
class Reference:
    """Base of every typed reference. ``text`` is its canonical form."""
    KIND: ClassVar[str] = ''
    SCHEME: ClassVar[str] = ''
    PINNING: ClassVar[str] = ''
    PATTERN: ClassVar[re.Pattern] = None

    @property
    def kind(self):
        return self.KIND

    @property
    def text(self):
        raise NotImplementedError

    @property
    def pinned(self):
        """True when the reference names an immutable revision of its source."""
        raise NotImplementedError

    def identity(self):
        """The stable identity, without any revision anchor: (kind, native id parts...)."""
        raise NotImplementedError

    def __str__(self):
        return self.text

    @classmethod
    def parse_text(cls, text):
        match = cls.PATTERN.fullmatch(text)
        return cls._from_match(match) if match else None


@dataclass(frozen=True)
class ConversationRef(Reference):
    """An Owner conversation thread; optionally as it stood through one message."""
    KIND: ClassVar[str] = 'conversation'
    SCHEME: ClassVar[str] = 'conversation'
    PINNING: ClassVar[str] = 'optional'
    PATTERN: ClassVar[re.Pattern] = re.compile(rf'^conversation:(?P<thread>{SEGMENT})(?:@(?P<through>{SEGMENT}))?$')
    thread: str
    through_message: str | None = None

    def __post_init__(self):
        _native(self.KIND, 'thread', self.thread)
        if self.through_message is not None:
            _native(self.KIND, 'through_message', self.through_message)

    @property
    def text(self):
        anchor = f'@{encode_segment(self.through_message)}' if self.through_message is not None else ''
        return f'conversation:{encode_segment(self.thread)}{anchor}'

    @property
    def pinned(self):
        return self.through_message is not None

    def identity(self):
        return (self.KIND, self.thread)

    @classmethod
    def _from_match(cls, m):
        through = m['through']
        return cls(decode_segment(m['thread']), decode_segment(through) if through else None)


@dataclass(frozen=True)
class MessageRef(Reference):
    """One durable message; optionally pinned by its content digest or by a span anchor.

    A span anchor names bytes ``[span_start, span_start + span_length)`` of the message
    content (its UTF-8 text exactly as the durable store returns it) and the sha256 of
    exactly those bytes, so a quote can be re-extracted from the source and verified
    byte for byte (Overseer ruling D2, carried from P-01.2).
    """
    KIND: ClassVar[str] = 'message'
    SCHEME: ClassVar[str] = 'conversation'
    PINNING: ClassVar[str] = 'optional'
    PATTERN: ClassVar[re.Pattern] = re.compile(
        rf'^conversation:(?P<thread>{SEGMENT})/(?P<message>{SEGMENT})'
        rf'(?:#(?:sha256:(?P<digest>{HEX64})|span:(?P<start>{COUNT})\+(?P<length>{POSITIVE}):sha256:(?P<span_digest>{HEX64})))?$')
    thread: str
    message: str
    digest: str | None = None
    span_start: int | None = None
    span_length: int | None = None

    def __post_init__(self):
        _native(self.KIND, 'thread', self.thread)
        _native(self.KIND, 'message', self.message)
        _require(self.digest is None or _is('hex64', self.digest), self.KIND,
                 'digest must be 64 lower-case hex digits')
        has_start, has_length = self.span_start is not None, self.span_length is not None
        _require(has_start == has_length, self.KIND, 'a span needs both its start and its length')
        if has_start:
            _require(_is_count(self.span_start, 0), self.KIND, 'span_start must be an integer >= 0')
            _require(_is_count(self.span_length, 1), self.KIND, 'span_length must be an integer >= 1')
            _require(self.digest is not None, self.KIND, 'a span anchor needs the sha256 of its bytes')

    @property
    def span(self):
        return (self.span_start, self.span_length) if self.span_start is not None else None

    @property
    def text(self):
        base = f'conversation:{encode_segment(self.thread)}/{encode_segment(self.message)}'
        if self.span is not None:
            return f'{base}#span:{self.span_start}+{self.span_length}:sha256:{self.digest}'
        if self.digest is not None:
            return f'{base}#sha256:{self.digest}'
        return base

    @property
    def pinned(self):
        return self.digest is not None

    def identity(self):
        return (self.KIND, self.thread, self.message)

    @classmethod
    def _from_match(cls, m):
        thread, message = decode_segment(m['thread']), decode_segment(m['message'])
        if m['span_digest']:
            return cls(thread, message, m['span_digest'], int(m['start']), int(m['length']))
        return cls(thread, message, m['digest'])


@dataclass(frozen=True)
class ObjectiveRef(Reference):
    """An accepted objective by its outcome id (decision 0008): a random UUID in canonical
    lower-case text, minted when the Objective item's acceptance is recorded and declared
    under ``x-outcomes`` in the declaring change's ``.openspec.yaml``; optionally read at
    one commit of the project repository."""
    KIND: ClassVar[str] = 'objective'
    SCHEME: ClassVar[str] = 'outcome'
    PINNING: ClassVar[str] = 'optional'
    PATTERN: ClassVar[re.Pattern] = re.compile(rf'^outcome:(?P<outcome>{UUID})(?:@(?P<revision>{COMMIT}))?$')
    outcome: str
    revision: str | None = None

    def __post_init__(self):
        _require(_is('uuid', self.outcome), self.KIND,
                 f'the outcome id must be a lower-case UUID (decision 0008): {self.outcome!r}')
        _require(self.revision is None or _is('commit', self.revision), self.KIND,
                 'revision must be a full commit id')

    @property
    def text(self):
        return f'outcome:{self.outcome}' + (f'@{self.revision}' if self.revision else '')

    @property
    def pinned(self):
        return self.revision is not None

    def identity(self):
        return (self.KIND, self.outcome)

    @classmethod
    def _from_match(cls, m):
        return cls(m['outcome'], m['revision'])


@dataclass(frozen=True)
class DesignRef(Reference):
    """An OpenSpec change artifact at one design revision: the P-02.1 source pointer,
    parsed and formatted by ``planning_adapter.Pointer`` unchanged."""
    KIND: ClassVar[str] = 'design'
    SCHEME: ClassVar[str] = 'openspec'
    PINNING: ClassVar[str] = 'required'
    PATTERN: ClassVar[re.Pattern] = planning.POINTER_RE
    change: str
    artifact: str
    revision: str
    digest: str

    def __post_init__(self):
        _require(isinstance(self.change, str) and bool(planning.CHANGE_ID_RE.fullmatch(self.change)), self.KIND,
                 f'not an OpenSpec change id: {self.change!r}')
        _require(isinstance(self.artifact, str) and bool(planning.ARTIFACT_RE.fullmatch(self.artifact)), self.KIND,
                 f'not a relative artifact path: {self.artifact!r}')
        _require(_is('commit', self.revision), self.KIND, 'revision must be a full commit id')
        _require(_is('hex64', self.digest), self.KIND, 'digest must be 64 lower-case hex digits')

    @property
    def pointer(self):
        return planning.Pointer(self.change, self.artifact, self.revision, self.digest)

    @property
    def text(self):
        return self.pointer.text

    @property
    def pinned(self):
        return True

    def identity(self):
        return (self.KIND, self.change, self.artifact)

    @classmethod
    def parse_text(cls, text):
        try:
            pointer = planning.Pointer.parse(text)
        except planning.PlanningError:
            return None
        return cls(pointer.change, pointer.artifact, pointer.revision, pointer.digest)


@dataclass(frozen=True)
class WorkRef(Reference):
    """A Backlog.md task; optionally as Backlog.md reads it at one commit of the
    repository that holds its files."""
    KIND: ClassVar[str] = 'work'
    SCHEME: ClassVar[str] = 'backlog'
    PINNING: ClassVar[str] = 'optional'
    PATTERN: ClassVar[re.Pattern] = re.compile(rf'^backlog:(?P<task>{TASK_ID})(?:@(?P<revision>{COMMIT}))?$')
    task: str
    revision: str | None = None

    def __post_init__(self):
        _require(_is('task', self.task), self.KIND, f'not a Backlog.md task id (upper case): {self.task!r}')
        _require(self.revision is None or _is('commit', self.revision), self.KIND,
                 'revision must be a full commit id')

    @property
    def text(self):
        return f'backlog:{self.task}' + (f'@{self.revision}' if self.revision else '')

    @property
    def pinned(self):
        return self.revision is not None

    def identity(self):
        return (self.KIND, self.task)

    @classmethod
    def _from_match(cls, m):
        return cls(m['task'], m['revision'])


@dataclass(frozen=True)
class AttemptRef(Reference):
    """An execution attempt: the OpenHands Agent Server's native conversation id;
    optionally pinned to one of its native events."""
    KIND: ClassVar[str] = 'attempt'
    SCHEME: ClassVar[str] = 'openhands'
    PINNING: ClassVar[str] = 'optional'
    PATTERN: ClassVar[re.Pattern] = re.compile(
        rf'^openhands:conversation/(?P<conversation>{UUID})(?:@(?P<event>{SEGMENT}))?$')
    conversation: str
    event: str | None = None

    def __post_init__(self):
        _require(_is('uuid', self.conversation), self.KIND,
                 'conversation must be a lower-case UUID (the native conversation id)')
        if self.event is not None:
            _native(self.KIND, 'event', self.event)

    @property
    def text(self):
        anchor = f'@{encode_segment(self.event)}' if self.event is not None else ''
        return f'openhands:conversation/{self.conversation}{anchor}'

    @property
    def pinned(self):
        return self.event is not None

    def identity(self):
        return (self.KIND, self.conversation)

    @classmethod
    def _from_match(cls, m):
        return cls(m['conversation'], decode_segment(m['event']) if m['event'] else None)


@dataclass(frozen=True)
class CommitRef(Reference):
    """An exact commit of a named repository; the full commit id is both the identity
    and the immutable revision."""
    KIND: ClassVar[str] = 'commit'
    SCHEME: ClassVar[str] = 'git'
    PINNING: ClassVar[str] = 'required'
    PATTERN: ClassVar[re.Pattern] = re.compile(rf'^git:(?P<repository>{REPOSITORY})@(?P<commit>{COMMIT})$')
    repository: str
    commit: str

    def __post_init__(self):
        _require(_is('repository', self.repository), self.KIND, f'not a repository name: {self.repository!r}')
        _require(_is('commit', self.commit), self.KIND, 'commit must be a full commit id')

    @property
    def text(self):
        return f'git:{self.repository}@{self.commit}'

    @property
    def pinned(self):
        return True

    def identity(self):
        return (self.KIND, self.repository, self.commit)

    @classmethod
    def _from_match(cls, m):
        return cls(m['repository'], m['commit'])


@dataclass(frozen=True)
class ReviewRef(Reference):
    """A Gitea pull-request review, bound to the exact commit it reviewed."""
    KIND: ClassVar[str] = 'review'
    SCHEME: ClassVar[str] = 'gitea'
    PINNING: ClassVar[str] = 'required'
    PATTERN: ClassVar[re.Pattern] = re.compile(
        rf'^gitea:(?P<repository>{OWNER_REPOSITORY})/pulls/(?P<pull>{POSITIVE})/reviews/(?P<review>{POSITIVE})'
        rf'@(?P<commit>{COMMIT})$')
    repository: str
    pull: int
    review: int
    commit: str

    def __post_init__(self):
        _require(_is('owner_repository', self.repository), self.KIND,
                 f'not an owner/name repository: {self.repository!r}')
        _require(_is_count(self.pull, 1) and _is_count(self.review, 1), self.KIND,
                 'pull and review must be positive integers')
        _require(_is('commit', self.commit), self.KIND, 'commit must be a full commit id')

    @property
    def text(self):
        return f'gitea:{self.repository}/pulls/{self.pull}/reviews/{self.review}@{self.commit}'

    @property
    def pinned(self):
        return True

    def identity(self):
        return (self.KIND, self.repository, self.pull, self.review)

    @classmethod
    def _from_match(cls, m):
        return cls(m['repository'], int(m['pull']), int(m['review']), m['commit'])


@dataclass(frozen=True)
class CIRef(Reference):
    """A Gitea Actions run, bound to the exact commit it tested."""
    KIND: ClassVar[str] = 'ci'
    SCHEME: ClassVar[str] = 'gitea'
    PINNING: ClassVar[str] = 'required'
    PATTERN: ClassVar[re.Pattern] = re.compile(
        rf'^gitea:(?P<repository>{OWNER_REPOSITORY})/actions/runs/(?P<run>{POSITIVE})@(?P<commit>{COMMIT})$')
    repository: str
    run: int
    commit: str

    def __post_init__(self):
        _require(_is('owner_repository', self.repository), self.KIND,
                 f'not an owner/name repository: {self.repository!r}')
        _require(_is_count(self.run, 1), self.KIND, 'run must be a positive integer')
        _require(_is('commit', self.commit), self.KIND, 'commit must be a full commit id')

    @property
    def text(self):
        return f'gitea:{self.repository}/actions/runs/{self.run}@{self.commit}'

    @property
    def pinned(self):
        return True

    def identity(self):
        return (self.KIND, self.repository, self.run)

    @classmethod
    def _from_match(cls, m):
        return cls(m['repository'], int(m['run']), m['commit'])


@dataclass(frozen=True)
class AuthorizationRef(Reference):
    """An Owner authorization: the merge revision of a protected Gitea branch and the
    digest of the manifest it authorizes."""
    KIND: ClassVar[str] = 'authorization'
    SCHEME: ClassVar[str] = 'gitea'
    PINNING: ClassVar[str] = 'required'
    PATTERN: ClassVar[re.Pattern] = re.compile(
        rf'^gitea:(?P<repository>{OWNER_REPOSITORY})/branches/(?P<branch>{SEGMENT})@(?P<commit>{COMMIT})'
        rf'#sha256:(?P<digest>{HEX64})$')
    repository: str
    branch: str
    commit: str
    manifest_digest: str

    def __post_init__(self):
        _require(_is('owner_repository', self.repository), self.KIND,
                 f'not an owner/name repository: {self.repository!r}')
        _native(self.KIND, 'branch', self.branch)
        _require(_is('commit', self.commit), self.KIND, 'commit must be a full commit id')
        _require(_is('hex64', self.manifest_digest), self.KIND, 'manifest_digest must be 64 lower-case hex digits')

    @property
    def text(self):
        return (f'gitea:{self.repository}/branches/{encode_segment(self.branch)}@{self.commit}'
                f'#sha256:{self.manifest_digest}')

    @property
    def pinned(self):
        return True

    def identity(self):
        return (self.KIND, self.repository, self.branch, self.commit)

    @classmethod
    def _from_match(cls, m):
        return cls(m['repository'], decode_segment(m['branch']), m['commit'], m['digest'])


@dataclass(frozen=True)
class EffectReceiptRef(Reference):
    """A receipt in the privileged effects store by its one-time effect key; optionally
    pinned to one journal event of that receipt and the event's hash-chain value."""
    KIND: ClassVar[str] = 'effect-receipt'
    SCHEME: ClassVar[str] = 'effect'
    PINNING: ClassVar[str] = 'optional'
    PATTERN: ClassVar[re.Pattern] = re.compile(
        rf'^effect:(?P<key>{EFFECT_KEY})(?:@(?P<seq>{POSITIVE})#sha256:(?P<hash>{HEX64}))?$')
    effect_key: str
    seq: int | None = None
    event_hash: str | None = None

    def __post_init__(self):
        _require(_is('effect_key', self.effect_key), self.KIND, 'effect_key must be fx1- and 64 hex digits')
        _require((self.seq is None) == (self.event_hash is None), self.KIND,
                 'a journal anchor needs both the event sequence number and its hash')
        if self.seq is not None:
            _require(_is_count(self.seq, 1), self.KIND, 'seq must be a positive integer')
            _require(_is('hex64', self.event_hash), self.KIND, 'event_hash must be 64 lower-case hex digits')

    @property
    def text(self):
        anchor = f'@{self.seq}#sha256:{self.event_hash}' if self.seq is not None else ''
        return f'effect:{self.effect_key}{anchor}'

    @property
    def pinned(self):
        return self.seq is not None

    def identity(self):
        return (self.KIND, self.effect_key)

    @classmethod
    def _from_match(cls, m):
        return cls(m['key'], int(m['seq']) if m['seq'] else None, m['hash'])


REFERENCE_TYPES = (ConversationRef, MessageRef, ObjectiveRef, DesignRef, WorkRef, AttemptRef, CommitRef,
                   ReviewRef, CIRef, AuthorizationRef, EffectReceiptRef)
BY_KIND = {cls.KIND: cls for cls in REFERENCE_TYPES}
SCHEMES = sorted({cls.SCHEME for cls in REFERENCE_TYPES})
_SCHEME = re.compile(r'^([a-z][a-z0-9+.-]*):')


def parse(text):
    """The typed reference of a canonical reference text; raises MalformedReference."""
    if not isinstance(text, str):
        raise MalformedReference('REFERENCE_MALFORMED', f'a reference is text, not {type(text).__name__}')
    scheme = _SCHEME.match(text)
    if not scheme:
        raise MalformedReference('REFERENCE_MALFORMED', f'no scheme: {text!r}', text)
    candidates = [cls for cls in REFERENCE_TYPES if cls.SCHEME == scheme.group(1)]
    if not candidates:
        raise MalformedReference('REFERENCE_UNSUPPORTED_SCHEME',
                                 f'no reference kind uses the scheme {scheme.group(1)!r}', text)
    for cls in candidates:
        reference = cls.parse_text(text)
        if reference is not None:
            if reference.text != text:  # every accepted text is canonical
                raise MalformedReference('REFERENCE_MALFORMED', f'not canonical: {text!r}', text)
            return reference
    kinds = ' or '.join(cls.KIND for cls in candidates)
    raise MalformedReference('REFERENCE_MALFORMED', f'not a well-formed {kinds} reference: {text!r}', text)


def format_reference(reference):
    """The canonical text of a typed reference."""
    if not isinstance(reference, Reference) or type(reference) not in REFERENCE_TYPES:
        raise MalformedReference('REFERENCE_MALFORMED', f'not a typed reference: {reference!r}')
    return reference.text


# ---------------------------------------------------------------------------
# Span anchors (message kind)

def message_bytes_digest(content):
    return hashlib.sha256(content).hexdigest()


def message_reference(thread, message, content):
    """A message reference pinned by the sha256 of its whole content."""
    _require(isinstance(content, (bytes, bytearray)), 'message', 'content must be bytes')
    return MessageRef(thread, message, message_bytes_digest(bytes(content)))


def _utf8_boundary(content, index):
    return index == len(content) or (content[index] & 0xC0) != 0x80


def span_reference(thread, message, content, start, length):
    """A span anchor over CONTENT (the message's durable bytes): the bytes
    ``[start, start + length)``, which must be whole UTF-8 characters, and their sha256."""
    _require(isinstance(content, (bytes, bytearray)), 'message', 'content must be bytes')
    _require(_is_count(start, 0) and _is_count(length, 1), 'message', 'start >= 0 and length >= 1')
    content = bytes(content)
    end = start + length
    _require(end <= len(content), 'message', f'span {start}+{length} exceeds the {len(content)} bytes')
    _require(_utf8_boundary(content, start) and _utf8_boundary(content, end), 'message',
             'a span must start and end on a UTF-8 character boundary')
    return MessageRef(thread, message, message_bytes_digest(content[start:end]), start, length)


# ---------------------------------------------------------------------------
# Resolution

@dataclass(frozen=True)
class Resolution:
    """The answer to one resolution. ``resolved`` or exactly one named reason why not.

    ``query`` is ``reference`` for ``resolve`` (the pinned revision when the reference
    has one) and ``current`` for ``current`` (the identity at the authority's current
    revision). ``observed_revision`` and ``observed_digest`` are what the authority
    showed, when it has such anchors. ``code`` is a stable reason code; it is empty
    exactly when the outcome is ``resolved``. ``supplied_by`` names the plan leaves that
    will supply a missing authority. ``facts`` holds the fields of the authority's own
    record that a traversal follows (for an objective: its declaring change, item,
    acceptance, source and accepted criteria), as JSON-compatible values.
    """
    reference: str
    kind: str
    outcome: str
    authority: str
    code: str | None = None
    detail: str = ''
    observed_revision: str | None = None
    observed_digest: str | None = None
    query: str = 'reference'
    supplied_by: tuple = field(default_factory=tuple)
    facts: dict | None = None

    def __post_init__(self):
        if self.facts is not None and not isinstance(self.facts, dict):
            raise ValueError('facts must be a JSON object')
        if self.outcome not in OUTCOMES:
            raise ValueError(f'not a resolution outcome: {self.outcome!r}')
        if (self.outcome == RESOLVED) != (self.code is None):
            raise ValueError('a resolved resolution has no code; every other outcome has one')
        if self.code is not None and (not isinstance(self.code, str) or not self.code):
            raise ValueError('code must be non-empty text')
        if self.query not in ('reference', 'current'):
            raise ValueError(f'not a query: {self.query!r}')
        if not isinstance(self.supplied_by, tuple) or not all(isinstance(s, str) for s in self.supplied_by):
            raise ValueError('supplied_by must be a tuple of plan leaf ids')

    @property
    def resolved(self):
        return self.outcome == RESOLVED

    def __bool__(self):
        raise TypeError('a Resolution has no truth value: test .resolved or .outcome')

    def to_json(self):
        data = asdict(self)
        data['supplied_by'] = list(self.supplied_by)
        return data


class Resolver(Protocol):
    """A read-only resolver for one reference kind."""
    kind: str
    authority: str
    outcomes: frozenset

    def resolve(self, reference: Reference) -> Resolution:
        """Resolve REFERENCE as written: its pinned revision when it has one."""

    def current(self, reference: Reference) -> Resolution:
        """Resolve REFERENCE's identity at the authority's current revision, ignoring its anchors."""


def answer(reference, outcome, authority, code=None, detail='', **extra):
    """A Resolution for REFERENCE (a helper for resolvers)."""
    return Resolution(reference.text, reference.kind, outcome, authority, code, detail, **extra)


MESSAGE_AUTHORITY = 'Owner conversation store'


def check_message_content(reference, content, authority=MESSAGE_AUTHORITY):
    """The message kind's validation rule, applied to CONTENT: the message's durable bytes
    as a future message resolver (U-02.1) reads them from the store.

    Unpinned: resolved, reporting the content's sha256. With a content digest: the
    content's sha256 must equal it. With a span: the span must lie within the content on
    UTF-8 character boundaries and its bytes' sha256 must equal the anchor's; the
    resolution then reports the span's digest, and ``span_bytes`` gives the quote.
    Anything else is a digest-mismatch. It reads nothing itself.
    """
    if not isinstance(reference, MessageRef):
        raise MalformedReference('REFERENCE_MALFORMED', 'check_message_content takes a message reference')
    if not isinstance(content, (bytes, bytearray)):
        raise TypeError('content must be the message bytes')
    content = bytes(content)
    whole = message_bytes_digest(content)
    if reference.span is None:
        if reference.digest is not None and reference.digest != whole:
            return answer(reference, DIGEST_MISMATCH, authority, 'MESSAGE_DIGEST_MISMATCH',
                          f'the message content has sha256 {whole}', observed_digest=whole)
        return answer(reference, RESOLVED, authority, observed_digest=whole)
    start, length = reference.span
    end = start + length
    if end > len(content):
        return answer(reference, DIGEST_MISMATCH, authority, 'SPAN_OUT_OF_RANGE',
                      f'span {start}+{length} exceeds the {len(content)} content bytes', observed_digest=whole)
    if not (_utf8_boundary(content, start) and _utf8_boundary(content, end)):
        return answer(reference, DIGEST_MISMATCH, authority, 'SPAN_NOT_ON_CHARACTER_BOUNDARY',
                      f'span {start}+{length} splits a UTF-8 character', observed_digest=whole)
    actual = message_bytes_digest(content[start:end])
    if actual != reference.digest:
        return answer(reference, DIGEST_MISMATCH, authority, 'SPAN_DIGEST_MISMATCH',
                      f'the span bytes have sha256 {actual}', observed_digest=actual)
    return answer(reference, RESOLVED, authority, observed_digest=actual)


def span_bytes(reference, content):
    """The quote a verified span anchor names: the exact bytes of CONTENT it covers.
    Raises unless ``check_message_content`` resolves it."""
    result = check_message_content(reference, content)
    if not result.resolved or reference.span is None:
        raise MalformedReference(result.code or 'REFERENCE_MALFORMED',
                                 result.detail or 'the reference has no span anchor')
    start, length = reference.span
    return bytes(content)[start:start + length]


# ---------------------------------------------------------------------------
# Schema

def load_schema(path=SCHEMA_PATH):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def schema_kinds(schema):
    return {entry['kind']: entry for entry in schema['kinds']}


def check_schema(schema):
    """Problems in the schema, and between the schema and the typed references (empty: PASS)."""
    problems = []

    def need(condition, message):
        if not condition:
            problems.append(message)

    need(schema.get('format') == SCHEMA_FORMAT, f'format must be {SCHEMA_FORMAT}')
    need(schema.get('schema_version') == SCHEMA_VERSION, f'schema_version must be {SCHEMA_VERSION}')
    need(sorted(schema.get('outcomes', {})) == sorted(OUTCOMES), 'outcomes must define exactly ' + ', '.join(OUTCOMES))
    entries = schema.get('kinds')
    if not isinstance(entries, list) or not entries:
        return problems + ['kinds must be a non-empty list']
    names = [e.get('kind') if isinstance(e, dict) else None for e in entries]
    need(len(set(names)) == len(names), 'kinds must be unique')
    for entry in entries:
        if not isinstance(entry, dict):
            problems.append('every kind entry must be an object')
            continue
        kind = entry.get('kind')
        where = f'kind {kind!r}'
        status = entry.get('status')
        need(status in STATUSES, f'{where}: status must be one of {STATUSES}')
        authority = entry.get('authority') or {}
        need(isinstance(authority.get('name'), str) and authority['name'].strip(),
             f'{where}: authority.name is required')
        need(isinstance(authority.get('system_of_record'), str) and authority['system_of_record'].strip(),
             f'{where}: authority.system_of_record is required')
        need(isinstance(authority.get('blueprint'), str) and authority['blueprint'].strip(),
             f'{where}: authority.blueprint (the governing passage) is required')
        identity = entry.get('identity') or {}
        revision = entry.get('revision') or {}
        need(isinstance(identity.get('settled'), bool), f'{where}: identity.settled must be true or false')
        need(isinstance(entry.get('validation_rule'), str) and entry['validation_rule'].strip(),
             f'{where}: validation_rule is required')
        need(isinstance(entry.get('citations'), list) and entry['citations'], f'{where}: citations are required')
        if identity.get('settled') is True:
            need(isinstance(identity.get('native_id'), str) and identity['native_id'].strip(),
                 f'{where}: identity.native_id is required')
            need(revision.get('pinning') in PINNING, f'{where}: revision.pinning must be required or optional')
            need(isinstance(revision.get('anchor'), str) and revision['anchor'].strip(),
                 f'{where}: revision.anchor is required')
        need((status == 'unknown') == (identity.get('settled') is False),
             f'{where}: status unknown exactly when the identity is not settled')
        if status == 'unknown':
            need(isinstance(entry.get('open'), list) and entry['open'], f'{where}: an unknown kind lists what is open')
        if status == 'authority-unavailable':
            need(isinstance(entry.get('supplied_by'), list) and entry['supplied_by'],
                 f'{where}: an unavailable authority names the leaves that supply it')
        if status != 'implemented':
            need(entry.get('verified') == NOT_YET_VERIFIED, f'{where}: verified must be {NOT_YET_VERIFIED!r}')
            need(entry.get('resolver') is None, f'{where}: only an implemented kind names a resolver')
        else:
            need(isinstance(entry.get('resolver'), str) and entry['resolver'], f'{where}: resolver is required')
            outcomes = entry.get('outcomes')
            need(isinstance(outcomes, list) and set(outcomes) <= set(OUTCOMES)
                 and {RESOLVED, AUTHORITY_UNAVAILABLE} <= set(outcomes) and UNSUPPORTED_KIND not in outcomes,
                 f'{where}: outcomes must list the resolver\'s outcomes, with resolved and authority-unavailable')
        cls = BY_KIND.get(kind)
        form = entry.get('canonical_form')
        if form is None:
            need(cls is None, f'{where}: a typed reference exists, so canonical_form is required')
            need(status == 'unknown', f'{where}: only an unknown kind may lack a canonical form')
            continue
        if cls is None:
            problems.append(f'{where}: no typed reference implements it')
            continue
        need(entry.get('scheme') == cls.SCHEME, f'{where}: scheme must be {cls.SCHEME!r}')
        if identity.get('settled') is True:
            need(revision.get('pinning') == cls.PINNING, f'{where}: revision.pinning must be {cls.PINNING!r}')
        examples = entry.get('examples')
        need(isinstance(examples, list) and examples, f'{where}: examples are required')
        for text in examples or []:
            try:
                reference = parse(text)
            except MalformedReference as exc:
                problems.append(f'{where}: example {text!r} does not parse: {exc}')
                continue
            need(reference.kind == kind, f'{where}: example {text!r} parses as {reference.kind}')
            need(format_reference(reference) == text, f'{where}: example {text!r} does not round-trip')
    for cls in REFERENCE_TYPES:
        need(cls.KIND in names, f'typed reference {cls.KIND!r} has no schema entry')
    return problems


class Registry:
    """Resolves references of every kind the schema declares.

    An implemented kind goes to its registered resolver. A kind without one answers
    explicitly: ``authority-unavailable`` (its authority does not exist yet, or the
    resolver is not configured here) or ``unsupported-kind`` (its identity is not
    settled). Nothing is ever answered as resolved without a resolver.
    """

    def __init__(self, resolvers=(), schema=None):
        self.schema = schema if schema is not None else load_schema()
        self.kinds = schema_kinds(self.schema)
        self.resolvers = {}
        for resolver in resolvers:
            entry = self.kinds.get(resolver.kind)
            if entry is None or entry['status'] != 'implemented':
                raise ValueError(f'the schema does not declare {resolver.kind!r} as implemented')
            if resolver.kind in self.resolvers:
                raise ValueError(f'two resolvers for {resolver.kind!r}')
            if set(resolver.outcomes) != set(entry['outcomes']):
                raise ValueError(f'{resolver.kind!r} resolver outcomes differ from the schema')
            if resolver.authority != entry['authority']['name']:
                raise ValueError(f'{resolver.kind!r} resolver names another authority than the schema')
            self.resolvers[resolver.kind] = resolver

    def resolve(self, reference):
        return self._ask(reference, 'resolve')

    def current(self, reference):
        return self._ask(reference, 'current')

    def _ask(self, reference, method):
        if isinstance(reference, str):
            try:
                reference = parse(reference)
            except MalformedReference as exc:
                if exc.code != 'REFERENCE_UNSUPPORTED_SCHEME':
                    raise
                return Resolution(exc.text, 'unknown', UNSUPPORTED_KIND, 'none', exc.code, exc.message,
                                  query='reference' if method == 'resolve' else 'current')
        if not isinstance(reference, Reference) or type(reference) not in REFERENCE_TYPES:
            raise MalformedReference('REFERENCE_MALFORMED', f'not a typed reference: {reference!r}')
        query = 'reference' if method == 'resolve' else 'current'
        entry = self.kinds.get(reference.kind)
        authority = entry['authority']['name'] if entry else 'none'
        resolver = self.resolvers.get(reference.kind)
        if resolver is not None:
            result = getattr(resolver, method)(reference)
            if not isinstance(result, Resolution) or result.reference != reference.text \
                    or result.kind != reference.kind or result.query != query \
                    or result.outcome not in entry['outcomes'] or result.authority != authority:
                raise RuntimeError(f'{reference.kind} resolver answered outside its contract: {result!r}')
            return result
        if entry is None:
            return Resolution(reference.text, reference.kind, UNSUPPORTED_KIND, authority, 'KIND_NOT_DECLARED',
                              'the schema declares no such kind', query=query)
        if entry['status'] == 'unknown':
            return Resolution(reference.text, reference.kind, UNSUPPORTED_KIND, authority, 'KIND_NOT_SETTLED',
                              'the identity of this kind is not settled: ' + '; '.join(entry['open']), query=query)
        if entry['status'] == 'authority-unavailable':
            return Resolution(reference.text, reference.kind, AUTHORITY_UNAVAILABLE, authority,
                              'AUTHORITY_NOT_YET_AVAILABLE',
                              f'no local authority or adapter exists yet ({NOT_YET_VERIFIED}); supplied by '
                              + ', '.join(entry['supplied_by']), query=query,
                              supplied_by=tuple(entry['supplied_by']))
        return Resolution(reference.text, reference.kind, AUTHORITY_UNAVAILABLE, authority,
                          'RESOLVER_NOT_CONFIGURED', 'this registry has no resolver configured for the kind',
                          query=query)
