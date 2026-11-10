"""The Owner decision record (``owner-decision/v1``): the shape shared by the Owner's recorders
(plan group P-04).

One record is written for each Owner decision a deterministic, non-model recorder records:

- ``accept-objective``: the acceptance recorder (plan leaf P-04.1, ``acceptance_recorder.py``),
  the Owner's acceptance of an Objective item of an intent-driven OpenSpec change (decision 0008);
- ``authorize-operation``: reserved for the Owner authorization recorder (plan leaf P-04.2), which
  defines its own subject. It is not built here, so a record of that kind is refused until it is.

Fields, in this order (``FIELDS``):

``format``      ``owner-decision/v1``
``decisionId``  a random UUID (version 4), canonical lower-case text
``kind``        one of ``KINDS``
``subject``     what was decided on: an object whose fields the kind defines (``SUBJECT_FIELDS``)
``shown``       what the recorder presented before the decision: ``summary`` (the text shown),
                ``nonce`` (32 lower-case hex digits) and ``expiresAt`` (the challenge's expiry)
``statement``   the decision as stated: ``text`` (verbatim), ``attributedTo`` (``owner``),
                ``channel`` (how it reached the recorder) and ``reference`` (where it is kept)
``recordedBy``  who ran the recorder: ``owner``, ``agent:<id>`` or ``person:<id>``
``recordedAt``  when, as ``YYYY-MM-DDTHH:MM:SSZ`` (UTC)

Attribution and reference values use the intent-record/v1 grammar
(``catalog/skills/intent-normalization/references/intent-record.md``). The record is clerical: it
says what was shown and what was said, by whom it was recorded and when. It does not authenticate
the Owner: ``attributedTo`` and ``channel`` are declared by the party that transcribed the
statement, and the reference, not the record, is the proof (decision 0008, point 2).

Standard library only. It launches no process and opens no file.
"""
import json
import re
import uuid

FORMAT = 'owner-decision/v1'
FIELDS = ('format', 'decisionId', 'kind', 'subject', 'shown', 'statement', 'recordedBy', 'recordedAt')
SHOWN_FIELDS = ('summary', 'nonce', 'expiresAt')
STATEMENT_FIELDS = ('text', 'attributedTo', 'channel', 'reference')
# The subject of each kind this module validates. P-04.2 adds 'authorize-operation' with its own.
SUBJECT_FIELDS = {
    'accept-objective': ('change', 'item', 'outcome', 'revision', 'proposal'),
}
KINDS = ('accept-objective', 'authorize-operation')

UUID4 = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$')
OUTCOME = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')  # lineage UUID
NONCE = re.compile(r'^[0-9a-f]{32}$')
TIMESTAMP = re.compile(r'^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$')
CHANNEL = re.compile(r'^[a-z][a-z0-9-]*$')
# intent-record/v1 (tools/check_intent_record.py: ATTRIBUTION, REFERENCE).
ATTRIBUTION = re.compile(r'^(owner|(agent|person):[A-Za-z0-9._@/+-]+)$')
REFERENCE = re.compile(r'^[a-z][a-z0-9+.-]*:[^\s=,]+$')
COMMIT = re.compile(r'^[0-9a-f]{40}$')
SHA256 = re.compile(r'^[0-9a-f]{64}$')
CHANGE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]*$')
OBJECTIVE_ITEM = re.compile(r'^O[1-9][0-9]*$')
# Reference schemes whose records an agent writes: an engineering conversation of the OpenHands
# Agent Server (the lineage `attempt` kind) is a model's own transcript, never an Owner statement.
MODEL_SCHEMES = ('openhands',)

# The verdicts of statement_verdict.
MISSING, MODEL, NOT_OWNER, INVALID = 'missing', 'model', 'not-owner', 'invalid'


def new_decision_id():
    """A new decision id: a random UUID (version 4) in canonical lower-case text."""
    return str(uuid.uuid4())


def statement_verdict(statement):
    """(verdict, detail) of a statement as an Owner's decision, or (None, '') when it is one.

    Decided from the statement alone, in this order:

    - ``missing``: no statement, an empty ``text``, or no ``reference`` (absent, empty or
      ``missing:<what>``);
    - ``model``: authored by a model: ``attributedTo`` is ``agent:<id>`` (an agent writes as a
      model), or the ``reference`` is an engineering conversation of the Agent Server
      (``MODEL_SCHEMES``);
    - ``not-owner``: ``attributedTo`` is anything but ``owner`` (``person:<id>``, another text,
      or absent);
    - ``invalid``: a field outside the shape (``STATEMENT_FIELDS``), a ``channel`` that is not a
      lower-case token, or a ``reference`` outside the intent-record/v1 grammar.

    The attribution is declared, not authenticated (see the module's docstring)."""
    if statement is None:
        return MISSING, 'no statement was given'
    if not isinstance(statement, dict):
        return INVALID, 'the statement must be an object'
    text = statement.get('text')
    reference = statement.get('reference')
    if not isinstance(text, str) or not text.strip():
        return MISSING, 'the statement has no text'
    if not isinstance(reference, str) or not reference.strip() or reference.startswith('missing:'):
        return MISSING, 'the statement names no reference where it is kept'
    attributed = statement.get('attributedTo')
    scheme = reference.split(':', 1)[0]
    if isinstance(attributed, str) and attributed.startswith('agent:'):
        return MODEL, f'the statement is attributed to {attributed}, a model'
    if scheme in MODEL_SCHEMES:
        return MODEL, f'{reference} is an agent conversation, written by a model'
    if attributed != 'owner':
        return NOT_OWNER, f'the statement is attributed to {attributed!r}, not to the Owner'
    unknown = sorted(set(statement) - set(STATEMENT_FIELDS))
    if unknown:
        return INVALID, f'the statement has fields outside its shape: {", ".join(unknown)}'
    channel = statement.get('channel')
    if not isinstance(channel, str) or not CHANNEL.match(channel):
        return INVALID, f'channel {channel!r} is not a lower-case token such as main-session'
    if not REFERENCE.match(reference):
        return INVALID, f'reference {reference!r} is not a scheme:reference'
    return None, ''


def check_record(record):
    """The problems of RECORD as an Owner decision record (an empty list when it has the shape)."""
    problems = []
    if not isinstance(record, dict):
        return ['the record must be an object']
    if list(record) != list(FIELDS):
        problems.append(f'the fields must be exactly {", ".join(FIELDS)}, in that order')
    if record.get('format') != FORMAT:
        problems.append(f'format must be {FORMAT}')
    if not isinstance(record.get('decisionId'), str) or not UUID4.match(record['decisionId']):
        problems.append('decisionId must be a lower-case version 4 UUID')
    kind = record.get('kind')
    if kind not in KINDS:
        problems.append(f'kind must be one of {", ".join(KINDS)}')
    elif kind not in SUBJECT_FIELDS:
        problems.append(f'kind {kind} has no subject defined yet (plan leaf P-04.2)')
    else:
        problems.extend(_subject_problems(kind, record.get('subject')))
    shown = record.get('shown')
    if not isinstance(shown, dict) or list(shown) != list(SHOWN_FIELDS):
        problems.append(f'shown must have exactly {", ".join(SHOWN_FIELDS)}')
    else:
        if not isinstance(shown['summary'], str) or not shown['summary'].strip():
            problems.append('shown.summary must be the text presented')
        if not isinstance(shown['nonce'], str) or not NONCE.match(shown['nonce']):
            problems.append('shown.nonce must be 32 lower-case hex digits')
        if not isinstance(shown['expiresAt'], str) or not TIMESTAMP.match(shown['expiresAt']):
            problems.append('shown.expiresAt must be YYYY-MM-DDTHH:MM:SSZ')
    statement = record.get('statement')
    if not isinstance(statement, dict) or list(statement) != list(STATEMENT_FIELDS):
        problems.append(f'statement must have exactly {", ".join(STATEMENT_FIELDS)}')
    else:
        verdict, detail = statement_verdict(statement)
        if verdict is not None:
            problems.append(f'statement: {detail}')
    if not isinstance(record.get('recordedBy'), str) or not ATTRIBUTION.match(record['recordedBy']):
        problems.append('recordedBy must be owner, agent:<id> or person:<id>')
    if not isinstance(record.get('recordedAt'), str) or not TIMESTAMP.match(record['recordedAt']):
        problems.append('recordedAt must be YYYY-MM-DDTHH:MM:SSZ')
    return problems


def _subject_problems(kind, subject):
    fields = SUBJECT_FIELDS[kind]
    if not isinstance(subject, dict) or list(subject) != list(fields):
        return [f'subject must have exactly {", ".join(fields)}']
    problems = []
    if kind == 'accept-objective':
        if not isinstance(subject['change'], str) or not CHANGE.match(subject['change']):
            problems.append('subject.change must be an OpenSpec change name')
        if not isinstance(subject['item'], str) or not OBJECTIVE_ITEM.match(subject['item']):
            problems.append('subject.item must be an Objective item id (O<n>)')
        # Any canonical UUID: the recorder mints version 4, and keeps an id recorded by hand before it.
        if not isinstance(subject['outcome'], str) or not OUTCOME.match(subject['outcome']):
            problems.append('subject.outcome must be an outcome id (a lower-case UUID)')
        if not isinstance(subject['revision'], str) or not COMMIT.match(subject['revision']):
            problems.append('subject.revision must be a full commit id')
        if not isinstance(subject['proposal'], str) or not SHA256.match(subject['proposal']):
            problems.append('subject.proposal must be a sha256')
    return problems


def dumps(record):
    """The record's file text: JSON, two-space indent, its own field order, UTF-8 kept, LF."""
    return json.dumps(record, indent=2, ensure_ascii=False) + '\n'
