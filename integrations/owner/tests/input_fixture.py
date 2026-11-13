"""Fixtures of the dispatch-input commands (plan leaf P-04.3): throwaway repositories, a per-test context
and synthetic statements, bases and candidate manifests.

``start()`` (setUpModule) builds, once per test module and with git and a fixed identity and date, in one
temporary directory outside the checkout:

- a **project repository** holding the OpenSpec change ``fixture-change`` at two commits (``FIRST`` and
  ``SECOND``: ``design.md`` changes) and a commit that holds no change folder;
- **fixture harness repositories**, each holding a decision 0018 and a log
  (``evidence/bootstrap-log.md``): ``accepted`` (``Status: Accepted (Owner) -``; the log's Decisions hold
  anchored entries: a ``Commitment:``, an ``Owner standing authorization:`` with its verbatim block, an
  ``Owner direction:`` and a per-act ``Owner authorization:``, and its Owner actions a row prepared and not
  granted), ``proposed`` (the same record ``Proposed``), ``worktree`` (accepted, but the log's entries are
  only in its work tree, never committed) and ``status-worktree`` (``Proposed`` committed, ``Accepted
  (Owner)`` only in the work tree).

``Fixture`` gives each test its own state root, live manifest path, candidate directory and integration
store (a copy of one migrated store per module), a fixed clock and the context over them. Nothing here
reads or writes the managed data root, its integration store, the real log or the real decision 0018 (a
test that reads the real decision 0018 does so itself, read-only, at ``HEAD``). Every statement, basis
and quote is **SYNTHETIC**: it stands in for an Owner statement, a commitment or a standing authorization
and is none of them.
"""
from __future__ import annotations

import datetime
import json
import shutil
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
OWNER = HERE.parent
REPO = OWNER.parents[1]


def _load(name, path):
    import importlib.util
    if (module := sys.modules.get(name)) is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = sys.modules[name] = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


IR = _load('input_recorder', OWNER / 'input_recorder.py')
I, G, D, DI, IS = IR.I, IR.G, IR.D, IR.DI, IR.store_module
sys.path.insert(0, str(REPO / 'integrations' / 'planning' / 'tests'))
import two_task_fixture as fx  # noqa: E402

NOW = datetime.datetime(2026, 11, 13, 12, 0, 0, tzinfo=datetime.timezone.utc)
LATER = NOW + datetime.timedelta(minutes=5)
RECORDED_BY = 'agent:fixture-transcriber'
PM, EM = 'agent:product-manager', 'agent:engineering-manager'
REPOSITORY = 'fixture-app'
CHANGE = 'fixture-change'
OTHER_CHANGE = 'fixture-other'
COMMITMENT = 'Commitment: FIXTURE-D (SYNTHETIC FIXTURE, not a commitment).'
ENVELOPE = ('SYNTHETIC FIXTURE, not an Owner authorization: a standing authorization to promote manifests of '
            'fixture-app until 2026-12-01.')
COMMITMENT_ANCHOR = 'commitment-fixture-d'
ENVELOPE_ANCHOR = 'owner-standing-authorization-fixture'
DIRECTION_ANCHOR = 'owner-direction-fixture'
AUTHORIZATION_ANCHOR = 'owner-authorization-fixture'
# Texts of the fixture log that are no authority of a basis type (each in the log, outside any verbatim block of
# an "Owner standing authorization:" entry, or in an entry of another kind).
DIRECTION_QUOTE = 'SYNTHETIC FIXTURE direction, not a standing authorization: promote fixture-app manifests.'
AUTHORIZATION_QUOTE = 'SYNTHETIC FIXTURE per-act authorization, not standing: promote this one manifest.'
ENVELOPE_PROSE = 'Given in the main session (SYNTHETIC FIXTURE), transcribed verbatim below'
OA_ROW = 'Prepared, not granted (SYNTHETIC FIXTURE): (j) the manifest envelope of fixture-app'
# An entry whose title contains "Commitment:" without beginning with it (slice 3, N-A), with a quote of its own that
# names a commitment; and undated entries of both kinds (their titles have no "<date>: ").
FINDINGS_ANCHOR = 'findings-on-a-commitment-fixture'
FINDINGS_QUOTE = 'Commitment: FIXTURE-D is in scope (SYNTHETIC FIXTURE findings, not a commitment).'
UNDATED_COMMITMENT_ANCHOR = 'commitment-undated-fixture'
UNDATED_COMMITMENT = 'Commitment: FIXTURE-U (SYNTHETIC FIXTURE, undated).'
UNDATED_ENVELOPE_ANCHOR = 'owner-standing-authorization-undated-fixture'
UNDATED_ENVELOPE = 'SYNTHETIC FIXTURE, undated: a standing authorization to promote fixture-app manifests.'
ACCEPTED_STATUS = ('Status: Accepted (Owner) - 2026-11-12, revision 4 (SYNTHETIC FIXTURE of decision 0018, not '
                   'the record)')
PROPOSED_STATUS = 'Status: Proposed - 2026-11-12, revision 4 (SYNTHETIC FIXTURE of decision 0018, not the record)'


def statement(token, **changes):
    """A SYNTHETIC statement standing in for the Owner's decision (no Owner decision), naming TOKEN."""
    return {'text': f'SYNTHETIC FIXTURE, not an Owner decision: I accept {token}.', 'attributedTo': 'owner',
            'channel': 'main-session', 'reference': 'conversation:fixture-owner/message-3', **changes}


def commitment(**changes):
    return {'type': 'commitment', 'link': f'{G.LOG}#{COMMITMENT_ANCHOR}', 'quote': COMMITMENT, **changes}


def envelope(**changes):
    return {'type': 'envelope', 'link': f'{G.LOG}#{ENVELOPE_ANCHOR}', 'quote': ENVELOPE, **changes}


def decision_record(status):
    return (f'# 0018 - Planning and execution roles (SYNTHETIC FIXTURE)\n\n{status}\n\n'
            '3. Delegated. 3.2 design acceptance; 3.3 manifest promotion.\n').encode('utf-8')


def _block(text, width=60):
    """TEXT as an indented verbatim block, wrapped, as the log records an Owner's words."""
    lines, line = [], ''
    for word in text.split():
        if line and len(line) + 1 + len(word) > width:
            lines.append(line)
            line = word
        else:
            line = f'{line} {word}' if line else word
    return [f'  > {each}' for each in lines + [line]]


def log(entries=True):
    """The fixture log: an Owner-actions row prepared and not granted, then the Decisions entries (a commitment,
    an Owner standing authorization with its verbatim block, an Owner direction and a per-act Owner
    authorization, each anchored), or none."""
    lines = ['# Bootstrap log (SYNTHETIC FIXTURE)', '', '## Owner actions', '', f'| OA-99 | {OA_ROW} | prepared |',
             '', '## Decisions', '']
    if entries:
        lines += [f'- <a id="{COMMITMENT_ANCHOR}"></a>**2026-11-12: {COMMITMENT}** Terminal leaf FIXTURE-1.',
                  f'- <a id="{ENVELOPE_ANCHOR}"></a>**2026-11-12: Owner standing authorization: the fixture-app '
                  f'envelope.** {ENVELOPE_PROSE}:', '', *_block(ENVELOPE), '',
                  f'- <a id="{DIRECTION_ANCHOR}"></a>**2026-11-12: Owner direction: fixture manifests.** Verbatim:',
                  '', *_block(DIRECTION_QUOTE), '',
                  f'- <a id="{AUTHORIZATION_ANCHOR}"></a>**2026-11-12: Owner authorization: one fixture manifest.** '
                  'Verbatim:', '', *_block(AUTHORIZATION_QUOTE), '',
                  f'- <a id="{FINDINGS_ANCHOR}"></a>**2026-11-12: Findings on the Commitment: FIXTURE-D scope.** '
                  f'{FINDINGS_QUOTE}',
                  f'- <a id="{UNDATED_COMMITMENT_ANCHOR}"></a>**{UNDATED_COMMITMENT}** Terminal leaf FIXTURE-2.',
                  f'- <a id="{UNDATED_ENVELOPE_ANCHOR}"></a>**Owner standing authorization: undated.** Verbatim:', '',
                  *_block(UNDATED_ENVELOPE), '',
                  '- **2026-11-12: An entry without an anchor (SYNTHETIC FIXTURE).**', '', '## Later section']
    return ''.join(f'{line}\n' for line in lines).encode('utf-8')


class Repositories:
    """The module's repositories (built by ``start``)."""
    project: Path
    first: str
    second: str
    empty: str
    harness: dict


def _init(repo, files, message):
    Path(repo).mkdir(parents=True)
    fx.git(repo, 'init', '--quiet', '-b', 'main')
    fx.write(repo, files)
    return fx.commit_all(repo, message)


def _build(root):
    repos = Repositories()
    repos.project = root / 'project'
    base = f'openspec/changes/{CHANGE}'
    repos.empty = _init(repos.project, {'README.md': b'Throwaway project repository (P-04.3 fixture).\n'},
                        'A commit without the change')
    fx.write(repos.project, {f'{base}/proposal.md': b'# Proposal (SYNTHETIC FIXTURE)\n',
                             f'{base}/design.md': b'# Design (SYNTHETIC FIXTURE), first revision\n',
                             f'{base}/specs/fixture/spec.md': b'# Spec (SYNTHETIC FIXTURE)\n'})
    repos.first = fx.commit_all(repos.project, 'The change, first revision')
    fx.write(repos.project, {f'{base}/design.md': b'# Design (SYNTHETIC FIXTURE), second revision\n',
                             f'openspec/changes/{OTHER_CHANGE}/proposal.md': b'# Another change\n'})
    repos.second = fx.commit_all(repos.project, 'The change, second revision')
    repos.harness = {}
    record = 'decisions/0018-fixture-delegation.md'
    for name, status, entries in (('accepted', ACCEPTED_STATUS, True), ('proposed', PROPOSED_STATUS, True),
                                  ('worktree', ACCEPTED_STATUS, False),
                                  ('status-worktree', PROPOSED_STATUS, True)):
        path = root / f'harness-{name}'
        _init(path, {record: decision_record(status), G.LOG: log(entries),
                     'decisions/0017-another.md': decision_record(ACCEPTED_STATUS)}, 'The fixture harness')
        repos.harness[name] = path
    # only in the work tree, never committed: the log's entries; and an Accepted (Owner) status over a Proposed one
    fx.write(repos.harness['worktree'], {G.LOG: log(True)})
    fx.write(repos.harness['status-worktree'], {record: decision_record(ACCEPTED_STATUS)})
    return repos


_SHARED = []


def start():
    """setUpModule: one temporary directory, the repositories and one migrated integration store."""
    root = Path(tempfile.mkdtemp(prefix='aieh-inputs-'))
    repos = _build(root)
    golden = root / 'golden.sqlite'
    IS.open_store(golden).close()
    _SHARED.append((root, root, repos, golden))


def stop():
    """tearDownModule."""
    fx.rmtree(_SHARED.pop()[0])


def manifest(version=1, designs=((REPOSITORY, CHANGE, None),), **changes):
    """A candidate manifest (approved-inputs/v1) as its text: DESIGNS are (repository, change, commit);
    a commit of None is the fixture's FIRST commit."""
    repos = _SHARED[-1][2]
    data = {'schema': DI.MANIFEST_SCHEMA, 'version': version,
            'repositories': [{'id': REPOSITORY}],
            'designs': [{'repository': r, 'change': c, 'commit': commit or repos.first} for r, c, commit in designs],
            'profiles': [{'id': 'fixture-profile', 'sha256': '2' * 64}],
            'catalog_pins': [{'id': 'fixture-pin', 'repository': 'fixture-catalog', 'commit': '3' * 40,
                              'manifest_sha256': '4' * 64}],
            'bindings': [{'repository': REPOSITORY, 'stage': 'implement', 'profiles': ['fixture-profile'],
                          'catalog_pins': ['fixture-pin']}]}
    data.update(changes)
    return json.dumps(data, indent=2) + '\n'


class Fixture(unittest.TestCase):
    """A directory per test in the module's temporary directory: a copy of the migrated store, the state
    root, the live manifest's directory and a candidate directory; a fixed clock; the context."""

    HARNESS = 'accepted'

    @classmethod
    def setUpClass(cls):
        _tmp, root, cls.repos, cls.golden = _SHARED[-1]
        cls.root = root / cls.__name__
        cls.root.mkdir()
        cls.serial = 0

    def setUp(self):
        type(self).serial += 1
        self.dir = self.root / f't{self.serial}'
        (self.dir / 'state' / 'dispatch').mkdir(parents=True)
        (self.dir / 'candidates').mkdir()
        shutil.copyfile(self.golden, self.dir / 'integration.sqlite')
        self.store = IS.open_store(self.dir / 'integration.sqlite')
        self.addCleanup(self.store.close)
        self.live = self.dir / 'state' / 'dispatch' / 'approved-inputs.json'
        self.now = NOW
        self.replace = None
        self.ctx = self.context()
        ceiling = fx.ceiling(self.root)
        ceiling.start()
        self.addCleanup(ceiling.stop)

    def context(self, **changes):
        fields = dict(state_root=self.dir / 'state', store=self.store, manifest_path=self.live,
                      harness=self.repos.harness[self.HARNESS], checkout=REPO, now=lambda: self.now,
                      replace=lambda source, target: (self.replace or IR.os.replace)(source, target))
        fields.update(changes)
        return IR.Context(**fields)

    # -- acts

    def candidate(self, text=None, name='candidate.json', **kw):
        path = self.dir / 'candidates' / name
        path.write_bytes((manifest(**kw) if text is None else text).encode('utf-8'))
        return path

    def accept(self, commit=None, change=CHANGE, **kw):
        """An Owner acceptance of CHANGE at COMMIT (FIRST by default): prepare, then record."""
        challenge = IR.design_prepare(self.ctx, self.repos.project, REPOSITORY, change, commit or self.repos.first)
        return IR.design_record(self.ctx, challenge['shown']['nonce'], statement(change), recorded_by=RECORDED_BY,
                                **kw)

    def delegate_design(self, commit=None, change=CHANGE, **kw):
        return IR.design_delegate(self.ctx, self.repos.project, REPOSITORY, change, commit or self.repos.first,
                                  decided_by=kw.pop('decided_by', PM), basis=kw.pop('basis', commitment()), **kw)

    def promote(self, path, **kw):
        """An Owner promotion of the candidate at PATH: prepare, then record."""
        challenge = IR.manifest_prepare(self.ctx, path)
        version = challenge['subject']['version']
        return IR.manifest_record(self.ctx, challenge['shown']['nonce'], statement(f'approved-inputs-v{version}'),
                                  recorded_by=RECORDED_BY, **kw)

    def delegate_promotion(self, path, **kw):
        return IR.manifest_delegate(self.ctx, path, decided_by=kw.pop('decided_by', PM),
                                    basis=kw.pop('basis', envelope()), **kw)

    # -- observations

    def assertRefused(self, code, call, *args, refusal=True, **kw):
        with self.assertRaises(IR.RecorderError) as caught:
            call(*args, **kw)
        self.assertEqual(caught.exception.code, code, caught.exception.detail)
        self.assertEqual(caught.exception.refusal, refusal, caught.exception.detail)
        self.assertIn(code, IR.REMEDIES)
        return caught.exception

    def receipts(self):
        """{key: (state, [events])} of the dispatch-input receipts."""
        return {r.operation_key: (r.state, [e.to_state for e in self.store.events(r.operation_key)])
                for r in self.store.attempts() if r.operation_key.startswith(I.KEY_PREFIX)}

    def live_bytes(self):
        return self.live.read_bytes() if self.live.exists() else None

    def snapshot(self):
        """What a refusal must leave as it was: the receipts, the live manifest and the decision copies."""
        state = self.dir / 'state'
        copies = sorted(p.relative_to(state).as_posix() for p in state.rglob('*.json')
                        if 'challenges' not in p.parts and p != self.live)
        return self.receipts(), self.live_bytes(), copies

    def verify(self, path=None):
        """The verifier's answer for the manifest at PATH (the live one by default)."""
        approved = DI.parse_manifest(Path(path or self.live).read_bytes())
        designs = [{k: e[k] for k in ('repository', 'change', 'commit')} for e in approved.data['designs']]
        return I.verifier(self.store)(approved.version, approved.sha256, designs)

    # -- receipts written by hand (what decision 0010 point 1 leaves possible: a same-account store write)

    def hand_receipt(self, key, intent, state='confirmed', actor=None):
        """Reserve KEY with INTENT by hand, as ACTOR (the recorder's own name by default, as a careful forger
        would write it), and move it to STATE."""
        self.store.reserve(key, intent, actor=actor or IR.RECORDER)
        path = {'reserved': [], 'dispatched': ['dispatched'], 'confirmed': ['dispatched', 'confirmed'],
                'failed': ['failed'], 'unknown': ['dispatched', 'unknown']}[state]
        for to_state in path:
            self.store.transition(key, to_state, actor=actor or IR.RECORDER)
        return key

    def hand_promotion(self, version, text, *, state='confirmed', actor=None, intent_changes=None, decision_id=None,
                       nonce=None, **subject):
        """A promotion receipt written by hand at VERSION for the manifest TEXT: a copy of version 1's Owner
        decision with a fresh decisionId and challenge (or DECISION_ID, NONCE), its subject rebound (version,
        digest, previous: the last confirmed promotion, SUBJECT's other changes)."""
        intent = json.loads(self.store.get(I.promotion_key(1)).intent_json)
        decision = I.stored_record(intent['decision'])
        decision['decisionId'] = decision_id or D.new_decision_id()
        decision['shown']['nonce'] = nonce or uuid.uuid4().hex
        head = I.last_confirmed(I.promotions(self.store))
        digest = f'sha256:{DI.parse_manifest(text.encode("utf-8")).sha256}'
        decision['subject'].update({'version': version, 'digest': digest,
                                    'previous': {'version': head.position, 'digest': head.intent['digest']},
                                    **subject})
        hand = {**intent, 'decision': decision, 'version': version, 'digest': digest,
                'previous': decision['subject']['previous'], 'text': text, **(intent_changes or {})}
        return self.hand_receipt(I.promotion_key(version), hand, state, actor)

    def hand_design(self, sequence, commit, *, state='confirmed', actor=None, intent_changes=None):
        """A design-acceptance receipt of CHANGE written by hand at SEQUENCE for COMMIT: a copy of sequence 1's
        decision with a fresh decisionId and challenge. Returns the decision id."""
        intent = json.loads(self.store.get(I.design_key(REPOSITORY, CHANGE, 1)).intent_json)
        decision = I.stored_record(intent['decision'])
        decision['decisionId'] = D.new_decision_id()
        decision['shown']['nonce'] = uuid.uuid4().hex
        decision['subject']['commit'] = commit
        hand = {**intent, 'decision': decision, 'sequence': sequence, **(intent_changes or {})}
        self.hand_receipt(I.design_key(REPOSITORY, CHANGE, sequence), hand, state, actor)
        return decision['decisionId']
