"""The Owner decision record (``owner-decision/v1``): the shape shared by the Owner's recorders
(plan group P-04).

One record is written for each Owner decision a deterministic, non-model recorder records:

- ``accept-objective``: the acceptance recorder (plan leaf P-04.1, ``acceptance_recorder.py``),
  the Owner's acceptance of an Objective item of an intent-driven OpenSpec change (decision 0008);
- ``authorize-operation``: the Owner authorization recorder (plan leaf P-04.2,
  ``authorization_recorder.py``), the Owner's authorization of one exact operation manifest on a
  pull request into a protected authorization branch (decision 0012);
- ``accept-design`` and ``promote-manifest``: the dispatch-input commands of the authorization
  recorder (plan leaf P-04.3, ``input_recorder.py``), the Owner's acceptance of an OpenSpec change's
  design at an exact revision (decision 0008 point 5) and the Owner's promotion of an approved-input
  manifest (``ai-engineering-harness/dispatch/approved-inputs/v1``). The same two kinds decided under
  decision 0018 point 3.2 or 3.3 are never Owner decisions: they are ``delegated-decision/v1``
  records (``delegated_decision.py``), whose subject is the subject defined here
  (``subject_problems``).

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

**A decision resting on a recorded statement** (plan leaf E-05.12): an ``accept-objective`` record
may rest on the Owner's statement already recorded verbatim in the harness log's Decisions (decision
0018 points 4.3 and 7) instead of on a challenge. Such a record has ``recorded`` where the others have
``shown`` (``RECORDED_FIELDS``), and never ``shown``: no challenge was shown. ``recorded`` is, in
this order (``RECORDED_BLOCK_FIELDS``): ``restsOn`` (``recorded-statement``), ``entry`` (the entry,
``evidence/bootstrap-log.md#<anchor>``), ``date`` (the entry's date, ``YYYY-MM-DD``), ``revision``
(the full commit of the harness repository at which the log was read, on its ``main``), ``origin``
(the harness's ``origin`` URL without userinfo; absent when it has none), ``digest`` (``sha256:`` of the
log's blob there), ``about`` (``{name, as}``: the name the statement names, ``as`` ``change`` (then the
subject's change) or ``repository``) and ``challengeShown`` (``false``). The statement's ``reference``
is then ``harness:<entry>``. Only the kinds in ``RECORDED_KINDS`` may rest on a recorded statement.

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
# A decision resting on the Owner's statement recorded in the harness log (plan leaf E-05.12): `recorded`
# in place of `shown`.
RECORDED_FIELDS = ('format', 'decisionId', 'kind', 'subject', 'recorded', 'statement', 'recordedBy', 'recordedAt')
RECORDED_BLOCK_FIELDS = ('restsOn', 'entry', 'date', 'revision', 'origin', 'digest', 'about', 'challengeShown')
RECORDED_OPTIONAL = ('origin',)  # absent when the harness has no origin remote
ABOUT_FIELDS = ('name', 'as')
ABOUT_KINDS = ('change', 'repository')
USERINFO = re.compile(r'^[a-z][a-z0-9+.-]*://[^/]*@', re.IGNORECASE)
RECORDED_KINDS = ('accept-objective',)
RESTS_ON = 'recorded-statement'
LOG_ENTRY = re.compile(r'^evidence/bootstrap-log\.md#[a-z0-9][a-z0-9-]{0,127}$')
ENTRY_DATE = re.compile(r'^[0-9]{4}-[0-9]{2}-[0-9]{2}$')
# The subject of each kind this module validates.
SUBJECT_FIELDS = {
    'accept-objective': ('change', 'item', 'outcome', 'revision', 'proposal'),
    # The operation manifest operations/<operation>.json on pull request <pull> of <repository> into
    # <base>, at head <head>, with the sha256 of its blob (<digest>), and what the manifest declares:
    # its kind, its target and its expiry.
    'authorize-operation': ('repository', 'pull', 'base', 'head', 'manifest', 'digest', 'operation',
                            'operationKind', 'target', 'expiresAt'),
    # The design of OpenSpec change <change> of the manifest repository <repository> at the exact revision
    # <commit>, with the digest of the change's folder there (<content>) and the decisionId of the
    # acceptance of that change it supersedes (null for the first).
    'accept-design': ('repository', 'change', 'commit', 'content', 'supersedes'),
    # The approved-input manifest <schema> at position <version> of the promotion series, the sha256 of its
    # bytes (<digest>), the promotion it replaces ({version, digest}, null for the first) and, for each of
    # its designs entries in manifest order, the design acceptance it rests on.
    'promote-manifest': ('schema', 'version', 'digest', 'previous', 'designs'),
}
KINDS = ('accept-objective', 'authorize-operation', 'accept-design', 'promote-manifest')

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
# authorize-operation: a Gitea repository (owner/name), a branch name, an operation id (the file name of
# its manifest, operations/<id>.json), the manifest blob's digest and a declared kind.
REPOSITORY = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,99}/[A-Za-z0-9][A-Za-z0-9._-]{0,99}$')
BRANCH = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$')
OPERATION = re.compile(r'^[a-z0-9][a-z0-9-]{0,127}$')
DIGEST = re.compile(r'^sha256:[0-9a-f]{64}$')
OPERATION_KIND = re.compile(r'^[a-z][a-z0-9.-]{0,63}$')
# accept-design and promote-manifest: the approved-input manifest's grammars (dispatch_inputs.ID_RE and
# MAX_ID; the planning adapter's CHANGE_ID and COMMIT; integration_store.MAX_CHANGE_ID), repeated here
# because this module imports nothing (a test asserts that they are equal).
MANIFEST_SCHEMA = 'ai-engineering-harness/dispatch/approved-inputs/v1'
MANIFEST_ID = re.compile(r'^[a-z0-9]+(?:-[a-z0-9]+)*$')
MANIFEST_ID_MAX = 64
DESIGN_CHANGE = re.compile(r'^[a-z0-9]+(?:-[a-z0-9]+)*$')
DESIGN_CHANGE_MAX = 128
FULL_COMMIT = re.compile(r'^(?:[0-9a-f]{40}|[0-9a-f]{64})$')
DESIGN_BINDING_FIELDS = ('repository', 'change', 'commit', 'acceptance', 'sequence')
PREVIOUS_FIELDS = ('version', 'digest')
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
    rests_on_log = 'recorded' in record and 'shown' not in record
    fields = RECORDED_FIELDS if rests_on_log else FIELDS
    if list(record) != list(fields):
        problems.append(f'the fields must be exactly {", ".join(fields)}, in that order')
    if record.get('format') != FORMAT:
        problems.append(f'format must be {FORMAT}')
    if not isinstance(record.get('decisionId'), str) or not UUID4.match(record['decisionId']):
        problems.append('decisionId must be a lower-case version 4 UUID')
    kind = record.get('kind')
    if kind not in KINDS:
        problems.append(f'kind must be one of {", ".join(KINDS)}')
    else:
        problems.extend(_subject_problems(kind, record.get('subject')))
    shown = record.get('shown')
    if rests_on_log:
        if kind in KINDS and kind not in RECORDED_KINDS:
            problems.append(f'only {", ".join(RECORDED_KINDS)} may rest on a recorded statement (recorded in place '
                            'of shown)')
        problems.extend(recorded_problems(record.get('recorded'), record.get('statement'), record.get('subject')))
    elif not isinstance(shown, dict) or list(shown) != list(SHOWN_FIELDS):
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


def recorded_problems(recorded, statement, subject=None):
    """The problems of RECORDED, the ``recorded`` block of a decision resting on the Owner's statement recorded
    in the harness log, with the record's STATEMENT (whose reference must name the same entry)."""
    fields = [name for name in RECORDED_BLOCK_FIELDS
              if name not in RECORDED_OPTIONAL or (isinstance(recorded, dict) and name in recorded)]
    if not isinstance(recorded, dict) or list(recorded) != fields:
        return [f'recorded must have exactly {", ".join(RECORDED_BLOCK_FIELDS)} (origin only when the harness has '
                'one), in that order']
    problems = []
    if recorded['restsOn'] != RESTS_ON:
        problems.append(f'recorded.restsOn must be {RESTS_ON}')
    entry = recorded['entry']
    if not isinstance(entry, str) or not LOG_ENTRY.match(entry):
        problems.append('recorded.entry must be evidence/bootstrap-log.md#<anchor>')
    elif isinstance(statement, dict) and statement.get('reference') != f'harness:{entry}':
        problems.append(f'statement.reference must be harness:{entry}, the entry the decision rests on')
    if not isinstance(recorded['date'], str) or not ENTRY_DATE.match(recorded['date']):
        problems.append('recorded.date must be the entry\'s date, YYYY-MM-DD')
    if not isinstance(recorded['revision'], str) or not FULL_COMMIT.match(recorded['revision']):
        problems.append('recorded.revision must be a full commit id of the harness repository')
    if not isinstance(recorded['digest'], str) or not DIGEST.match(recorded['digest']):
        problems.append('recorded.digest must be sha256:<64 hex digits>, the log\'s blob at that revision')
    if 'origin' in recorded:
        origin = recorded['origin']
        if not isinstance(origin, str) or not origin.strip() or origin.split() != [origin] \
                or USERINFO.match(origin):
            problems.append('recorded.origin must be the harness\'s origin URL, one word, without userinfo')
    about = recorded['about']
    if not isinstance(about, dict) or list(about) != list(ABOUT_FIELDS) or about['as'] not in ABOUT_KINDS \
            or not isinstance(about['name'], str) or not about['name'].strip():
        problems.append('recorded.about must be {name, as}, as change or repository')
    elif about['as'] == 'change' and isinstance(subject, dict) and about['name'] != subject.get('change'):
        problems.append('recorded.about names a change that is not the subject\'s')
    if recorded['challengeShown'] is not False:
        problems.append('recorded.challengeShown must be false: no challenge was shown')
    return problems


def subject_problems(kind, subject):
    """The problems of SUBJECT as the subject of KIND (one of ``KINDS``): its fields, in order, and their
    values. ``delegated_decision.py`` validates a delegated decision's subject with it."""
    if kind not in KINDS:
        return [f'kind must be one of {", ".join(KINDS)}']
    return _subject_problems(kind, subject)


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
    if kind == 'authorize-operation':
        problems.extend(operation_subject_problems(subject))
    if kind == 'accept-design':
        problems.extend(design_subject_problems(subject))
    if kind == 'promote-manifest':
        problems.extend(promotion_subject_problems(subject))
    return problems


def _manifest_id(value):
    return isinstance(value, str) and len(value) <= MANIFEST_ID_MAX and MANIFEST_ID.match(value) is not None


def _design_change(value):
    return isinstance(value, str) and len(value) <= DESIGN_CHANGE_MAX and DESIGN_CHANGE.match(value) is not None


def _full_commit(value):
    return isinstance(value, str) and FULL_COMMIT.match(value) is not None


def _position(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def design_subject_problems(subject):
    """The problems of an ``accept-design`` subject's values (its fields are checked by the caller)."""
    problems = []
    if not _manifest_id(subject['repository']):
        problems.append(f'subject.repository must be a manifest repository id (at most {MANIFEST_ID_MAX})')
    if not _design_change(subject['change']):
        problems.append(f'subject.change must be an OpenSpec change id (at most {DESIGN_CHANGE_MAX})')
    if not _full_commit(subject['commit']):
        problems.append('subject.commit must be a full commit id (40 or 64 lower-case hex digits)')
    if not isinstance(subject['content'], str) or not DIGEST.match(subject['content']):
        problems.append('subject.content must be sha256:<64 hex digits>')
    supersedes = subject['supersedes']
    if supersedes is not None and (not isinstance(supersedes, str) or not UUID4.match(supersedes)):
        problems.append('subject.supersedes must be null or a decisionId (a lower-case version 4 UUID)')
    return problems


def promotion_subject_problems(subject):
    """The problems of a ``promote-manifest`` subject's values (its fields are checked by the caller)."""
    problems = []
    if subject['schema'] != MANIFEST_SCHEMA:
        problems.append(f'subject.schema must be {MANIFEST_SCHEMA}')
    version = subject['version']
    if not _position(version):
        problems.append('subject.version must be an integer of at least 1')
    if not isinstance(subject['digest'], str) or not DIGEST.match(subject['digest']):
        problems.append('subject.digest must be sha256:<64 hex digits>')
    previous = subject['previous']
    if previous is not None:
        if not isinstance(previous, dict) or list(previous) != list(PREVIOUS_FIELDS) \
                or not _position(previous['version']) \
                or not isinstance(previous['digest'], str) or not DIGEST.match(previous['digest']):
            problems.append('subject.previous must be null or {version, digest} of an earlier promotion')
        elif _position(version) and previous['version'] >= version:
            problems.append('subject.previous.version must be lower than subject.version')
    designs = subject['designs']
    if not isinstance(designs, list):
        return problems + ['subject.designs must be a list']
    seen = set()
    for index, binding in enumerate(designs):
        where = f'subject.designs[{index}]'
        if not isinstance(binding, dict) or list(binding) != list(DESIGN_BINDING_FIELDS):
            problems.append(f'{where} must have exactly {", ".join(DESIGN_BINDING_FIELDS)}')
            continue
        if not _manifest_id(binding['repository']) or not _design_change(binding['change']) \
                or not _full_commit(binding['commit']):
            problems.append(f'{where} must name a manifest repository id, an OpenSpec change id and a full commit')
        if not isinstance(binding['acceptance'], str) or not UUID4.match(binding['acceptance']):
            problems.append(f'{where}.acceptance must be a decisionId (a lower-case version 4 UUID)')
        if not _position(binding['sequence']):
            problems.append(f'{where}.sequence must be an integer of at least 1')
        key = (binding['repository'], binding['change'])
        if key in seen:
            problems.append(f'{where} binds {binding["repository"]}/{binding["change"]} twice')
        seen.add(key)
    return problems


def operation_subject_problems(subject):
    """The problems of an ``authorize-operation`` subject's values (its fields are checked by the
    caller)."""
    problems = []
    repository = subject['repository']
    if not isinstance(repository, str) or not REPOSITORY.match(repository) or '..' in repository:
        problems.append('subject.repository must be a Gitea repository, owner/name')
    pull = subject['pull']
    if isinstance(pull, bool) or not isinstance(pull, int) or pull < 1:
        problems.append('subject.pull must be a pull request number')
    if not isinstance(subject['base'], str) or not BRANCH.match(subject['base']) or '..' in subject['base']:
        problems.append('subject.base must be a branch name')
    if not isinstance(subject['head'], str) or not COMMIT.match(subject['head']):
        problems.append('subject.head must be a full commit id')
    operation = subject['operation']
    if not isinstance(operation, str) or not OPERATION.match(operation):
        problems.append('subject.operation must be an operation id (lower-case letters, digits and hyphens)')
    elif subject['manifest'] != f'operations/{operation}.json':
        problems.append('subject.manifest must be operations/<operation>.json')
    if not isinstance(subject['digest'], str) or not DIGEST.match(subject['digest']):
        problems.append('subject.digest must be sha256:<64 hex digits>')
    if not isinstance(subject['operationKind'], str) or not OPERATION_KIND.match(subject['operationKind']):
        problems.append('subject.operationKind must be a lower-case token')
    target = subject['target']
    if not isinstance(target, str) or not target.strip() or target.splitlines() != [target]:
        problems.append('subject.target must be one line of text')
    if not isinstance(subject['expiresAt'], str) or not TIMESTAMP.match(subject['expiresAt']):
        problems.append('subject.expiresAt must be YYYY-MM-DDTHH:MM:SSZ')
    return problems


def dumps(record):
    """The record's file text: JSON, two-space indent, its own field order, UTF-8 kept, LF."""
    return json.dumps(record, indent=2, ensure_ascii=False) + '\n'
