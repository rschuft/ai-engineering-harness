"""Fixtures of the dispatch-input commands (plan leaf P-04.3): throwaway repositories, a per-test context
and synthetic statements, bases and candidate manifests.

``start()`` (setUpModule) builds, once per test module and with git and a fixed identity and date, in one
temporary directory outside the checkout:

- a **project repository** holding the OpenSpec change ``fixture-change`` at two commits (``FIRST`` and
  ``SECOND``: ``design.md`` changes) and a commit that holds no change folder;
- **fixture harness repositories**, each holding a decision 0018 and a log
  (``evidence/bootstrap-log.md``): ``accepted`` (``Status: Accepted (Owner)``, the log quoting a commitment
  and an envelope), ``proposed`` (the same record ``Proposed``) and ``worktree`` (accepted, but the quotes
  are only in the log's work tree, never committed).

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
COMMITMENT = '2026-11-12: Commitment: FIXTURE-D (SYNTHETIC FIXTURE, not a commitment). Terminal leaf FIXTURE-1.'
ENVELOPE = ('SYNTHETIC FIXTURE, not an Owner authorization: a standing authorization to promote manifests of '
            'fixture-app until 2026-12-01.')
ACCEPTED_STATUS = ('Status: Accepted (Owner) - 2026-11-12, revision 4 (SYNTHETIC FIXTURE of decision 0018, not '
                   'the record)')
PROPOSED_STATUS = 'Status: Proposed - 2026-11-12, revision 4 (SYNTHETIC FIXTURE of decision 0018, not the record)'


def statement(token, **changes):
    """A SYNTHETIC statement standing in for the Owner's decision (no Owner decision), naming TOKEN."""
    return {'text': f'SYNTHETIC FIXTURE, not an Owner decision: I accept {token}.', 'attributedTo': 'owner',
            'channel': 'main-session', 'reference': 'conversation:fixture-owner/message-3', **changes}


def commitment(**changes):
    return {'type': 'commitment', 'link': G.LOG, 'quote': COMMITMENT, **changes}


def envelope(**changes):
    return {'type': 'envelope', 'link': G.LOG, 'quote': ENVELOPE, **changes}


def decision_record(status):
    return (f'# 0018 - Planning and execution roles (SYNTHETIC FIXTURE)\n\n{status}\n\n'
            '3. Delegated. 3.2 design acceptance; 3.3 manifest promotion.\n').encode('utf-8')


def log(*quotes):
    return ('# Bootstrap log (SYNTHETIC FIXTURE)\n\n## Decisions\n\n'
            + ''.join(f'- {quote}\n' for quote in quotes)).encode('utf-8')


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
    for name, status, quotes in (('accepted', ACCEPTED_STATUS, (COMMITMENT, ENVELOPE)),
                                 ('proposed', PROPOSED_STATUS, (COMMITMENT, ENVELOPE)),
                                 ('worktree', ACCEPTED_STATUS, ())):
        path = root / f'harness-{name}'
        _init(path, {record: decision_record(status), G.LOG: log(*quotes),
                     'decisions/0017-another.md': decision_record(ACCEPTED_STATUS)}, 'The fixture harness')
        repos.harness[name] = path
    # the quotes only in the work tree: never committed
    fx.write(repos.harness['worktree'], {G.LOG: log(COMMITMENT, ENVELOPE)})
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
