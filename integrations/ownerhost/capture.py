"""Intent capture: one Owner message in the request layout becomes one intent-record/v1 OpenSpec change in the
project repository (plan leaf P-01.3; decision 0025 point 8; I1 work design R6, slice 8).

No model is called anywhere on this path. The structure comes from the Owner: the shell's request form sends **one**
message in a fixed layout, and the capture parses that layout only (``parse_request``), never anything else:

    Change: <change name, kebab-case>
    Objective: <one line>
    Acceptance criteria:
    - <one line>            (one or more)
    Suggestion: <one line>  (zero or more)

Lines are separated by LF only, with no trailing line break; every value is one non-empty line with no leading or
trailing whitespace and no control or separator character other than a tab. Anything else is
``CAPTURE_LAYOUT_INVALID``, naming the line: nothing is guessed, trimmed or reordered.

The request names a thread and a message (server-held ids) and carries the sha256 the browser computed of the
message's text. In order, each refusal with a stable code and nothing written:

1. the project configuration (``components.owner_host``, passed in by service.py: ``project_repository``, an absolute
   path to the work tree's root; ``project_repository_id``; ``backlog_command``; ``git_identities``, below):
   ``CAPTURE_PROJECT_UNCONFIGURED`` when absent, ``CAPTURE_CONFIG_INVALID`` when malformed;
2. the message, read from the Owner conversation store: it must be an Owner statement (a user message, author
   ``owner``: ``CAPTURE_NOT_A_STATEMENT``), and the sha256 of its **stored bytes** must equal the request's
   (``CAPTURE_MESSAGE_MISMATCH``);
3. the layout (``CAPTURE_LAYOUT_INVALID``); the record is then built and checked with ``tools/check_intent_record.py``
   against the stored bytes before anything is written;
4. the commit's author and committer (``capture_identities``): both are the **commissioning user's** git identity, set
   explicitly per principal under ``components.owner_host.git_identities`` and looked up by the principal of the
   authenticated session (in I1 the one enrolled Owner, ``owner``: every Owner UI session is his, and the store
   records his statements with author ``owner``). The commit is made under the user's identity, on the user's
   behalf; the harness is the user's mechanism, and no agent or component gets a git identity. It is never read
   from git configuration or the environment and never inferred; there is no shared default and no fallback.
   Absent: ``COMMIT_IDENTITY_UNAVAILABLE``; not ``Name <email>`` (no line break, no ``<`` or ``>`` in the name):
   ``COMMIT_IDENTITY_INVALID``; an invented placeholder domain (``localhost``, or under ``.invalid``,
   ``.localhost``, ``.example`` or ``.test``): ``COMMIT_IDENTITY_PLACEHOLDER``. A GitHub no-reply address, and any
   other real address the user configured, is accepted. Provenance is not git metadata: the component that wrote
   the record (``normalized_by``), the message's bytes, sha256 and session, and the receipt are in the intent
   record, the lineage and the integration store; authorship grants nothing;
5. the project repository (``CAPTURE_PROJECT_UNAVAILABLE``) and the change name, which must be new
   (``CAPTURE_CHANGE_EXISTS``).

Then the write-ahead receipt ``owner-ui/intent-capture/v1/<thread>/<message>`` is reserved in the integration store,
and one commit through ``repository_access.Repository.write_commit`` (head compare-and-swap) adds exactly
``openspec/changes/<change>/proposal.md`` and ``.openspec.yaml``. Its message carries the trailer
``Intent-Capture: <receipt key>``. Once the branch has moved the receipt goes to ``dispatched`` and ``confirmed``
with the commit id.

Idempotency, by message id. A confirmed receipt answers its commit and writes nothing. A receipt left ``reserved``
or ``dispatched`` (a process that ended between the receipt and its confirmation, or a refusal the Owner then
repaired) is settled **by reading the repository first**: the first-parent history from HEAD is searched for the
commit carrying the receipt's trailer; when it is there the receipt is confirmed with it and nothing is written
again; only when it is not there is the commit made. A refusal of the commit itself (``CAPTURE_COMMIT_REFUSED``,
``CAPTURE_GIT_FAILED``) leaves the receipt ``reserved``: nothing was written, and the same message may be captured
once the repository is repaired. A branch that moves under the capture is read again (at most ``HEAD_ATTEMPTS``).

The record (``build_proposal``): Q1 is the whole message, its ``source`` the message's span anchor
(``lineage.span_reference``, sha256 of the stored bytes); O1, each ACn and each Mn are exact byte spans of the message,
``attributed_to: owner``, ``source: Q1``; a suggestion is a Proposed Method with ``claim_type: hypothesis`` and its
Hypothesis item, never the objective. ``normalized_by`` is ``agent:owner-host-capture@<VERSION>``, and the only items
attributed to it are the Hypotheses, whose statement is the one sentence the capture writes. ``.openspec.yaml`` names
the ``intent-driven`` schema and the message's creation date.

What it never does: it opens no client socket, starts no process, and calls no model (the structural and audit tests
of tests/test_capture.py); it reads no configuration file (service.py reads ``config.yml``); it reads no credential.
"""
from __future__ import annotations

import dataclasses
import hashlib
import importlib.util
import json
import os
import re
import sys
import unicodedata
from pathlib import Path, PureWindowsPath, PurePosixPath

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


conversation = _load('aieh_conversation_store', REPO / 'integrations' / 'conversation' / 'conversation_store.py')
integration_store = _load('integration_store', REPO / 'integrations' / 'store' / 'integration_store.py')
lineage = _load('lineage', REPO / 'integrations' / 'lineage' / 'lineage.py')
intent = _load('aieh_check_intent_record', REPO / 'tools' / 'check_intent_record.py')
ra = lineage.planning.repository_access

VERSION = '1.0.0'
COMPONENT = f'owner-host-capture@{VERSION}'
NORMALIZED_BY = f'agent:{COMPONENT}'
RECEIPT_PREFIX = 'owner-ui/intent-capture/v1/'
RECEIPT_FORMAT = 'aieh-owner-ui-intent-capture/1'
ACTOR = 'owner-host-capture'
TRAILER = 'Intent-Capture'
CHANGES_DIR = 'openspec/changes'
CONFIG_POLICY = 'repository'           # the project's own git configuration only (decision 0014 section 5)
HEAD_ATTEMPTS = 3                      # a branch that moves under the capture is read again, at most this often
HISTORY_CEILING = 100_000              # first-parent commits read to settle a receipt; bounds a pathological walk

CONFIG_KEYS = ('project_repository', 'project_repository_id', 'backlog_command')
IDENTITIES_KEY = 'git_identities'      # optional: {principal: "Name <email>"}; absent, every capture is refused
# The principal of an authenticated Owner UI session: in I1 every enrolled session is the Owner's (decision 0025
# point 3), and the conversation store records his statements with this author.
OWNER_PRINCIPAL = 'owner'
GIT_IDENTITY = re.compile(r'(?P<name>[^<>\n\r\x00]+) <(?P<email>[^<>\s\x00@]+@(?P<domain>[^<>\s\x00@]+))>')
PLACEHOLDER_TLDS = ('invalid', 'localhost', 'example', 'test')
REPOSITORY_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,99}')
CHANGE_ID = re.compile(r'[a-z0-9]+(?:-[a-z0-9]+)*')
MAX_CHANGE_CHARS = 128
SHA256 = re.compile(r'[0-9a-f]{64}')

CHANGE_LABEL, OBJECTIVE_LABEL, CRITERIA_LINE = b'Change: ', b'Objective: ', b'Acceptance criteria:'
CRITERION_LABEL, SUGGESTION_LABEL = b'- ', b'Suggestion: '

STATUS = {'REQUEST_INVALID': 400, 'CAPTURE_PROJECT_UNCONFIGURED': 503, 'CAPTURE_CONFIG_INVALID': 503,
          'CAPTURE_STORE_UNAVAILABLE': 503, 'CAPTURE_NOT_A_STATEMENT': 409, 'CAPTURE_MESSAGE_MISMATCH': 409,
          'CAPTURE_LAYOUT_INVALID': 422, 'COMMIT_IDENTITY_UNAVAILABLE': 503,
          'COMMIT_IDENTITY_INVALID': 503, 'COMMIT_IDENTITY_PLACEHOLDER': 503, 'CAPTURE_PROJECT_UNAVAILABLE': 503,
          'CAPTURE_CHANGE_EXISTS': 409, 'CAPTURE_RECEIPT_CONFLICT': 409, 'CAPTURE_COMMIT_REFUSED': 409,
          'CAPTURE_GIT_FAILED': 500, 'CAPTURE_OUTCOME_UNKNOWN': 500}
REMEDIES = {
    'REQUEST_INVALID': 'send {sha256}: the sha256 of the message text\'s UTF-8 bytes, 64 lower-case hex digits',
    'CAPTURE_PROJECT_UNCONFIGURED': 'set components.owner_host (project_repository, project_repository_id, '
                                    'backlog_command, git_identities) in config.yml and restart the Integration '
                                    'process',
    'CAPTURE_CONFIG_INVALID': 'correct components.owner_host as example_config.yml describes it, then restart',
    'CAPTURE_STORE_UNAVAILABLE': 'start the Integration process through service.py up, which names the integration '
                                 'store',
    'CAPTURE_NOT_A_STATEMENT': 'capture an Owner message (a user message of the thread), not a reply',
    'CAPTURE_MESSAGE_MISMATCH': 'the message stored under this id is not the text sent; reload the thread and '
                                'capture the stored message',
    'CAPTURE_LAYOUT_INVALID': 'send the request through the request form: Change, Objective, Acceptance criteria '
                              '(one or more "- " lines) and optional Suggestion lines, one line each',
    'COMMIT_IDENTITY_UNAVAILABLE': 'set your git identity under components.owner_host.git_identities (your '
                                   'principal: "Name <email>"), restart the Integration process, then capture the '
                                   'same message again',
    'COMMIT_IDENTITY_INVALID': 'give components.owner_host.git_identities.<principal> as "Name <email>": one line, '
                               'no < or > in the name',
    'COMMIT_IDENTITY_PLACEHOLDER': 'configure a real address you publish under (a GitHub no-reply address is one), '
                                   'not a placeholder domain (localhost, .invalid, .localhost, .example, .test)',
    'CAPTURE_PROJECT_UNAVAILABLE': 'make project_repository the root of a git work tree with a commit on a branch',
    'CAPTURE_CHANGE_EXISTS': 'choose another change name: the project repository already has this change',
    'CAPTURE_RECEIPT_CONFLICT': 'this message was captured under another configuration; capture it with that one '
                                'or send the request again as a new message',
    'CAPTURE_COMMIT_REFUSED': 'repair the project repository as the detail says (nothing was written), then capture '
                              'the same message again',
    'CAPTURE_GIT_FAILED': 'repair the project repository (git fsck), then capture the same message again',
    'CAPTURE_OUTCOME_UNKNOWN': 'the receipt names a commit the branch does not hold; read the project repository '
                               'before anything else',
}


class CaptureRefused(Exception):
    """A refusal with a stable code; nothing was written unless the detail says otherwise."""

    def __init__(self, code: str, detail: str):
        self.code, self.detail, self.status, self.remedy = code, detail, STATUS[code], REMEDIES[code]
        super().__init__(f'{code}: {detail}')


# ---------------------------------------------------------------------------- configuration


@dataclasses.dataclass(frozen=True)
class ProjectConfig:
    """``components.owner_host``: the project repository's work tree and id, the Backlog.md command (for the
    projection, U-04.1; the capture does not run it), and each principal's git identity, as configured (checked when
    it is used, ``capture_identities``)."""
    project_repository: Path
    project_repository_id: str
    backlog_command: str
    git_identities: dict


def _absolute(text: str) -> bool:
    return PureWindowsPath(text).is_absolute() if os.name == 'nt' else PurePosixPath(text).is_absolute()


def project_config(raw) -> ProjectConfig:
    """Check RAW, the ``components.owner_host`` mapping as config.yml holds it (None when absent)."""
    if raw is None:
        raise CaptureRefused('CAPTURE_PROJECT_UNCONFIGURED', 'components.owner_host is not set')
    if not isinstance(raw, dict):
        raise CaptureRefused('CAPTURE_CONFIG_INVALID', 'components.owner_host is not a mapping')
    unknown = sorted(str(key) for key in raw if key not in CONFIG_KEYS + (IDENTITIES_KEY,))
    if unknown:
        raise CaptureRefused('CAPTURE_CONFIG_INVALID', f'unknown key components.owner_host.{unknown[0]}')
    for key in CONFIG_KEYS:
        value = raw.get(key)
        if not isinstance(value, str) or not value.strip() or value != value.strip() or '\x00' in value:
            raise CaptureRefused('CAPTURE_CONFIG_INVALID', f'components.owner_host.{key} must be a non-empty string')
    if not _absolute(raw['project_repository']):
        raise CaptureRefused('CAPTURE_CONFIG_INVALID', 'components.owner_host.project_repository must be absolute')
    if not REPOSITORY_ID.fullmatch(raw['project_repository_id']):
        raise CaptureRefused('CAPTURE_CONFIG_INVALID', 'components.owner_host.project_repository_id must be 1 to '
                                                       '100 of A-Z a-z 0-9 . _ - (starting with a letter or digit)')
    identities = raw.get(IDENTITIES_KEY, {})
    if identities is None:
        identities = {}
    if not isinstance(identities, dict) or not all(isinstance(k, str) and k for k in identities):
        raise CaptureRefused('CAPTURE_CONFIG_INVALID', f'components.owner_host.{IDENTITIES_KEY} must map principals '
                                                       'to "Name <email>"')
    return ProjectConfig(Path(raw['project_repository']), raw['project_repository_id'], raw['backlog_command'],
                         dict(identities))


def check_git_identity(value) -> str:
    """VALUE as a capture commit's identity: ``Name <email>`` (COMMIT_IDENTITY_INVALID) whose domain is not an
    invented placeholder (COMMIT_IDENTITY_PLACEHOLDER)."""
    match = GIT_IDENTITY.fullmatch(value) if isinstance(value, str) else None
    if match is None or match['name'] != match['name'].strip() or not ra.IDENTITY.fullmatch(value):
        raise CaptureRefused('COMMIT_IDENTITY_INVALID', 'the configured git identity is not "Name <email>"')
    labels = match['domain'].lower().rstrip('.').split('.')
    if not all(labels):
        raise CaptureRefused('COMMIT_IDENTITY_INVALID', 'the configured git identity\'s domain is malformed')
    if labels[-1] in PLACEHOLDER_TLDS:
        raise CaptureRefused('COMMIT_IDENTITY_PLACEHOLDER', 'the configured git identity\'s domain is a placeholder '
                                                            f'(.{labels[-1]})')
    return value


def capture_identities(config: ProjectConfig, principal: str) -> tuple[str, str]:
    """The (author, committer) of a capture commit: both the commissioning user's configured git identity, looked up
    by PRINCIPAL (never another principal's, never a default)."""
    if principal not in config.git_identities:
        raise CaptureRefused('COMMIT_IDENTITY_UNAVAILABLE', f'components.owner_host.{IDENTITIES_KEY} has no identity '
                                                            f'for the principal {principal}; nothing was written')
    identity = check_git_identity(config.git_identities[principal])
    return identity, identity


# ---------------------------------------------------------------------------- the request layout


@dataclasses.dataclass(frozen=True)
class Span:
    """Bytes [start, end) of the message, and their text."""
    start: int
    end: int
    text: str


@dataclasses.dataclass(frozen=True)
class Request:
    change: str
    objective: Span
    criteria: tuple
    suggestions: tuple


def _layout(line_number: int, why: str):
    raise CaptureRefused('CAPTURE_LAYOUT_INVALID', f'line {line_number}: {why}')


def _value(content: bytes, start: int, end: int, line_number: int, label: str) -> Span:
    text = content[start:end].decode('utf-8')
    if not text:
        _layout(line_number, f'{label} is empty')
    if text != text.strip():
        _layout(line_number, f'{label} has leading or trailing whitespace')
    for char in text:
        category = unicodedata.category(char)
        if (category == 'Cc' and char != '\t') or category in ('Zl', 'Zp'):
            _layout(line_number, f'{label} holds a control or separator character (U+{ord(char):04X})')
    return Span(start, end, text)


def parse_request(content: bytes) -> Request:
    """The request in the fixed layout (the module's docstring), parsed from the message's stored bytes; every
    other text is CAPTURE_LAYOUT_INVALID."""
    if b'\r' in content:
        _layout(1, 'the layout separates lines with LF only')
    lines, offset = [], 0
    for raw in content.split(b'\n'):
        lines.append((offset, raw))
        offset += len(raw) + 1
    if lines[-1][1] == b'':
        _layout(len(lines), 'the request ends with a line break')

    def take(index, label):
        start, raw = lines[index]
        if not raw.startswith(label):
            _layout(index + 1, f'expected "{label.decode().strip()}"')
        return start + len(label), start + len(raw)

    if len(lines) < 4:
        _layout(len(lines), 'a request has a Change, an Objective and at least one acceptance criterion')
    start, end = take(0, CHANGE_LABEL)
    change = content[start:end].decode('utf-8')
    if not CHANGE_ID.fullmatch(change) or len(change) > MAX_CHANGE_CHARS or change == 'archive':
        _layout(1, f'the change name must be kebab-case (a-z, 0-9, single hyphens), at most {MAX_CHANGE_CHARS} '
                   'characters, and not "archive"')
    objective = _value(content, *take(1, OBJECTIVE_LABEL), 2, 'the objective')
    if lines[2][1] != CRITERIA_LINE:
        _layout(3, f'expected "{CRITERIA_LINE.decode()}" alone on its line')
    criteria, suggestions, index = [], [], 3
    while index < len(lines) and lines[index][1].startswith(CRITERION_LABEL):
        criteria.append(_value(content, *take(index, CRITERION_LABEL), index + 1, 'a criterion'))
        index += 1
    if not criteria:
        _layout(4, 'at least one acceptance criterion ("- " line) is required')
    while index < len(lines) and lines[index][1].startswith(SUGGESTION_LABEL):
        suggestions.append(_value(content, *take(index, SUGGESTION_LABEL), index + 1, 'a suggestion'))
        index += 1
    if index < len(lines):
        _layout(index + 1, 'expected a "- " criterion, a "Suggestion: " line, or the end of the request')
    return Request(change, objective, tuple(criteria), tuple(suggestions))


# ---------------------------------------------------------------------------- the change


def receipt_key(thread_id: str, message_id: str) -> str:
    return f'{RECEIPT_PREFIX}{thread_id}/{message_id}'


def _fence(content: bytes) -> str:
    longest = max((len(run) for run in re.findall(rb'`+', content)), default=0)
    return '`' * max(3, longest + 1)


def build_proposal(thread_id: str, message_id: str, content: bytes, request: Request) -> tuple[str, bytes]:
    """(Q1's source reference, the proposal's bytes): the intent record of REQUEST, whose Original Quote is the whole
    message CONTENT under its span anchor."""
    q1 = lineage.span_reference(thread_id, message_id, content, 0, len(content)).text
    fence = _fence(content)
    out = ['# Proposal', '', '## Intent Record', '', f'- record_format: {intent.RECORD_FORMAT}',
           f'- normalized_by: {NORMALIZED_BY}', '',
           '<!-- Captured by the Owner host from one Owner message in the request layout, without a model (plan leaf',
           '     P-01.3). Q1 is the whole message; every item attributed to owner is an exact span of it; the',
           '     Hypotheses are the only statements the capture wrote. -->', '',
           '### Original Quote', '', '#### Q1', f'- source: {q1}', '- attributed_to: owner',
           '- claim_type: observation', '', f'{fence}text']
    head = '\n'.join(out) + '\n'
    tail = ['', fence, '', '### Objective', '', '#### O1', f'- statement: {request.objective.text}',
            '- claim_type: requirement', '- attributed_to: owner', '- source: Q1', '- authority: proposed', '',
            '### Binding Constraints', '', 'None.', '', '### Proposed Methods', '']
    if not request.suggestions:
        tail += ['None.', '']
    for n, suggestion in enumerate(request.suggestions, 1):
        tail += [f'#### M{n}', f'- statement: {suggestion.text}', '- claim_type: hypothesis', '- attributed_to: owner',
                 '- source: Q1', '- authority: proposed', f'- hypothesis: H{n}', '']
    tail += ['### Hypotheses', '']
    if not request.suggestions:
        tail += ['None.', '']
    for n in range(1, len(request.suggestions) + 1):
        tail += [f'#### H{n}', f'- statement: Applying M{n} achieves O1.', '- claim_type: hypothesis',
                 f'- attributed_to: {NORMALIZED_BY}', f'- source: M{n}', '- authority: proposed', '']
    tail += ['### Acceptance Criteria', '']
    for n, criterion in enumerate(request.criteria, 1):
        tail += [f'#### AC{n}', f'- statement: {criterion.text}', '- claim_type: requirement',
                 '- attributed_to: owner', '- source: Q1', '- authority: proposed', '']
    last = f'AC{len(request.criteria)}'
    criteria = 'AC1' if last == 'AC1' else f'AC1 to {last}'
    tail += ['### Open Clarifications', '', 'None.', '', '## Why', '',
             f'The Owner requested this change in the Owner host: Q1 is the message, O1 its objective and {criteria} '
             'its acceptance criteria, each in the Owner\'s own words. The Owner host captured it without a model; '
             'nothing in it is accepted until the Owner accepts O1.', '',
             '## What Changes', '',
             '- The objective O1 and its acceptance criteria, as the Owner stated them. The Owner\'s suggestions, if '
             'any, are Proposed Methods that stay hypotheses, never the objective.', '',
             '## Capabilities', '', 'Named by the design; none yet.', '',
             '## Impact', '', 'Assessed by the design; none yet.', '']
    return q1, head.encode('utf-8') + content + '\n'.join(tail).encode('utf-8')


def openspec_metadata(created_at: str | None) -> bytes:
    """The change's .openspec.yaml: the intent-driven schema and the message's creation date."""
    day = (created_at or '')[:10]
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', day):
        raise ValueError('an Owner message has its createdAt')
    return f'schema: intent-driven\ncreated: {day}\n'.encode('ascii')


def build_files(thread_id: str, message_id: str, stored, request: Request) -> tuple[str, dict]:
    """(Q1's source, {path: bytes}) of the change, its record checked against the stored bytes first."""
    q1, proposal = build_proposal(thread_id, message_id, stored.content, request)
    problems = intent.check(proposal, {q1: stored.content})
    if problems:   # the capture's own invariant: never written
        raise ValueError(f'the captured record does not pass check_intent_record: {problems[0]}')
    base = f'{CHANGES_DIR}/{request.change}'
    return q1, {f'{base}/proposal.md': proposal, f'{base}/.openspec.yaml': openspec_metadata(stored.created_at)}


def commit_message(change: str, key: str, thread_id: str, message_id: str, digest: str) -> str:
    return (f'openspec: capture the Owner\'s request {change}\n\n'
            'Captured by the Owner host (plan leaf P-01.3) from one Owner message in the request layout, without a '
            'model.\n\n'
            f'{TRAILER}: {key}\n'
            f'Owner-Message: conversation:{thread_id}/{message_id}#sha256:{digest}\n')


# ---------------------------------------------------------------------------- the repository


def open_project(config: ProjectConfig):
    """The project repository: CONFIG's path must be its work tree's root (no search above it)."""
    path = config.project_repository
    try:
        repo = ra.open_repository(path, config=CONFIG_POLICY, ceilings=[str(path.parent)])
    except (ra.CannotRun, ra.RepositoryError) as exc:
        raise CaptureRefused('CAPTURE_PROJECT_UNAVAILABLE', f'{exc}') from None
    try:
        if os.path.normcase(os.path.realpath(repo.root)) != os.path.normcase(os.path.realpath(path)):
            raise CaptureRefused('CAPTURE_PROJECT_UNAVAILABLE', 'project_repository is not its work tree\'s root')
        head = repo.head()
        if head.ref is None or not head.ref.startswith('refs/heads/') or head.commit is None:
            raise CaptureRefused('CAPTURE_PROJECT_UNAVAILABLE', 'HEAD does not name a branch with a commit')
    except BaseException:
        repo.close()
        raise
    return repo


def _parse_commit(data: bytes) -> tuple[list, bytes]:
    headers, _, message = data.partition(b'\n\n')
    parents = [line[7:].decode('ascii') for line in headers.split(b'\n') if line.startswith(b'parent ')]
    return parents, message


def find_capture(repo, key: str) -> str | None:
    """The commit on HEAD's first-parent history whose message carries ``Intent-Capture: KEY``, or None."""
    wanted = f'{TRAILER}: {key}'.encode('utf-8')
    oid = repo.head().commit
    for _ in range(HISTORY_CEILING):
        if oid is None:
            return None
        found = repo.read(oid)
        if found is None or found[1] != 'commit':
            raise CaptureRefused('CAPTURE_GIT_FAILED', f'commit {oid} cannot be read')
        parents, message = _parse_commit(found[2])
        if wanted in message.split(b'\n'):
            return oid
        oid = parents[0] if parents else None
    raise CaptureRefused('CAPTURE_OUTCOME_UNKNOWN', f'the history is longer than {HISTORY_CEILING} commits')


def change_present(repo, commit: str, change: str) -> bool:
    return repo.object_kind(f'{commit}:{CHANGES_DIR}/{change}') is not None


# ---------------------------------------------------------------------------- the capture


class Capture:
    """The capture of the Integration process: its project configuration (RAW, ``components.owner_host``), the
    integration store's path."""

    def __init__(self, raw_config, integration_store_path):
        self.raw_config, self.integration_store_path = raw_config, integration_store_path

    def capture(self, store, thread_id: str, message_id: str, sha256, session: dict) -> dict:
        config = project_config(self.raw_config)
        if not isinstance(sha256, str) or not SHA256.fullmatch(sha256):
            raise CaptureRefused('REQUEST_INVALID', 'sha256 must be 64 lower-case hex digits')
        stored = store.message(thread_id, message_id)
        if stored.role != 'user' or stored.author != 'owner':
            raise CaptureRefused('CAPTURE_NOT_A_STATEMENT', 'the message is not an Owner statement')
        digest = hashlib.sha256(stored.content).hexdigest()
        if digest != sha256:
            raise CaptureRefused('CAPTURE_MESSAGE_MISMATCH', 'the request\'s sha256 is not the stored message\'s')
        request = parse_request(stored.content)
        q1, files = build_files(thread_id, message_id, stored, request)
        author, committer = capture_identities(config, OWNER_PRINCIPAL)
        if self.integration_store_path is None:
            raise CaptureRefused('CAPTURE_STORE_UNAVAILABLE', 'no integration store is named')
        key = receipt_key(thread_id, message_id)
        intent_record = {
            'format': RECEIPT_FORMAT, 'component': COMPONENT, 'thread': thread_id, 'message': message_id,
            'messageSha256': digest, 'messageSession': stored.session_id, 'quote': q1, 'change': request.change,
            'project': {'id': config.project_repository_id, 'path': str(config.project_repository)},
            'files': {path: hashlib.sha256(data).hexdigest() for path, data in sorted(files.items())}}
        repo = open_project(config)
        try:
            path = Path(self.integration_store_path)
            if not path.exists():     # no receipt can exist: refuse a taken name before the store is created
                if change_present(repo, repo.head().commit, request.change):
                    raise CaptureRefused('CAPTURE_CHANGE_EXISTS', f'{CHANGES_DIR}/{request.change} exists at HEAD')
                path.parent.mkdir(exist_ok=True)
            with integration_store.open_store(path) as receipts:
                return self._capture(repo, receipts, key, intent_record, files, request,
                                     commit_message(request.change, key, thread_id, message_id, digest),
                                     author, committer, (session or {}).get('sessionId'))
        finally:
            repo.close()

    def _capture(self, repo, receipts, key, intent_record, files, request, message, author, committer,
                 session_id):
        existing = receipts.get(key)
        if existing is not None and existing.state == 'confirmed':
            return self._answer(receipts, key, intent_record, created=False)
        if existing is None and change_present(repo, repo.head().commit, request.change):
            raise CaptureRefused('CAPTURE_CHANGE_EXISTS', f'{CHANGES_DIR}/{request.change} exists at HEAD')
        try:
            reserved = receipts.reserve(key, intent_record, actor=ACTOR)
        except integration_store.ConflictingReservation:
            raise CaptureRefused('CAPTURE_RECEIPT_CONFLICT', f'{key} holds another intent') from None
        state = reserved.reservation.state
        if state not in ('reserved', 'dispatched', 'confirmed'):
            raise CaptureRefused('CAPTURE_RECEIPT_CONFLICT', f'{key} is {state}')
        if state == 'confirmed':
            return self._answer(receipts, key, intent_record, created=False)
        if not reserved.created:    # an earlier request reserved it: read before writing anything again
            found = find_capture(repo, key)
            if found is not None:
                self._confirm(receipts, key, found, 'settled by reading the project repository', session_id)
                return self._answer(receipts, key, intent_record, created=False)
            if state == 'dispatched':
                raise CaptureRefused('CAPTURE_OUTCOME_UNKNOWN', f'{key} is dispatched, and the branch does not hold '
                                                                'its commit')
        for attempt in range(HEAD_ATTEMPTS):
            head = repo.head()
            if change_present(repo, head.commit, request.change):
                raise CaptureRefused('CAPTURE_CHANGE_EXISTS', f'{CHANGES_DIR}/{request.change} exists at HEAD')
            try:
                commit = repo.write_commit(files, message, identity=committer, author=author,
                                           expected_head=head.commit)
            except ra.RepositoryError as exc:
                if exc.code == 'COMMIT_REFUSED' and exc.details.get('reason') == 'head-moved' \
                        and attempt + 1 < HEAD_ATTEMPTS:
                    continue
                committed = exc.details.get('committed')
                if exc.code == 'GIT_FAILED' and committed:
                    self._confirm(receipts, key, committed, 'committed; the work tree was not brought to it',
                                  session_id)
                    return self._answer(receipts, key, intent_record, created=True, work_tree=False)
                code = 'CAPTURE_COMMIT_REFUSED' if exc.code in ('COMMIT_REFUSED', 'HOOKS_UNSUPPORTED',
                                                                'OBJECT_NAME_INVALID') else 'CAPTURE_GIT_FAILED'
                raise CaptureRefused(code, f'{exc.code} {exc.details.get("reason") or ""}: {exc.message}'.strip()) \
                    from None
            except ra.CannotRun as exc:
                raise CaptureRefused('CAPTURE_PROJECT_UNAVAILABLE', str(exc)) from None
            self._confirm(receipts, key, commit, 'committed', session_id)
            return self._answer(receipts, key, intent_record, created=True)
        raise AssertionError('unreachable')   # the last attempt returns or raises

    @staticmethod
    def _confirm(receipts, key, commit, reason, session_id):
        detail = {'commit': commit, 'capturedBySession': session_id}
        if receipts.get(key).state == 'reserved':
            receipts.transition(key, 'dispatched', actor=ACTOR, reason=reason, detail=detail,
                                expected_from='reserved')
        receipts.transition(key, 'confirmed', actor=ACTOR, reason=reason, detail=detail, expected_from='dispatched')

    @staticmethod
    def _answer(receipts, key, intent_record, *, created, work_tree=True):
        events = receipts.events(key)
        confirmed = [e for e in events if e.to_state == 'confirmed']
        commit = json.loads(confirmed[-1].detail_json)['commit']
        answer = {'change': intent_record['change'], 'commit': commit, 'created': created, 'receipt': key,
                  'state': 'confirmed', 'quote': intent_record['quote'], 'files': intent_record['files'],
                  'project': intent_record['project']['id']}
        if not work_tree:
            answer['workTree'] = 'not brought to the commit'
        return answer
