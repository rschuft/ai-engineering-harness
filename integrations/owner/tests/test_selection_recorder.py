"""The model-selection recorder (plan leaf S-03.5, slice 2; ``selection_recorder.py``) and the ``select-models``
row of the delegation table with its ``envelope-receipt`` basis type (``delegated_decision.py``).

Run from the repository root, under the tools interpreter (Dulwich is required):

    <tools python> -I -B -m unittest discover -s integrations/owner/tests -v

The fixture harness repositories (a decision 0018 ``Accepted (Owner)`` and the same ``Proposed``) are the
dispatch-input commands' (``input_fixture.py``); the provider-envelope receipts the basis names are made by the
REAL authorization recorder against the fake Gitea, called in memory, into each test's throwaway store. A
hand-written receipt appears only where a test says so. Every statement, basis and selection is SYNTHETIC.
"""
import io
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

CATEGORY = 'integration'

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import input_fixture as fi  # noqa: E402
import authz_support as su  # noqa: E402

G, D, fx = fi.G, fi.D, fi.fx
AR, fg = su.AR, su.fg
SR = fi._load('selection_recorder', fi.OWNER / 'selection_recorder.py')
ED = SR.ED
EM, PM = fi.EM, fi.PM
ENVELOPE_EXPIRES = '2026-12-01T00:00:00Z'


def setUpModule():
    fi.start()


def tearDownModule():
    fi.stop()


def selection(**changes):
    return {'leaf': 'S-03.3',
            'models': {'anthropic-messages': [{'id': 'syn-model-a', 'use': 'the coding turn (SYNTHETIC)',
                                               'cost': 'about 1 USD per attempt (SYNTHETIC)'}]},
            'verified': {'source': 'https://provider.example.test/models (SYNTHETIC)', 'at': '2026-11-13T11:00:00Z'},
            **changes}


def envelope_manifest(operation, *, kind='provider-envelope', expires=ENVELOPE_EXPIRES):
    data = {'operation': operation, 'kind': kind, 'target': 'sha256:' + '1' * 64, 'expiresAt': expires,
            'envelope': {'format': 'aieh-provider-envelope/1', 'stand-in': 'SYNTHETIC'}}
    return (json.dumps(data, indent=2) + '\n').encode('utf-8')


class Selections(fi.Fixture):
    def setUp(self):
        super().setUp()
        self.gitea = fg.FakeGitea()

    def sctx(self, **changes):
        fields = dict(state_root=self.dir / 'state', store=self.store, harness=self.repos.harness['accepted'],
                      now=lambda: self.now)
        fields.update(changes)
        return SR.Context(**fields)

    def envelope(self, operation='op-envelope-1', *, on_merge=None, **kw):
        """A provider-envelope authorization by the real recorder (a SYNTHETIC statement): its receipt key."""
        number = self.gitea.propose({f'operations/{operation}.json': envelope_manifest(operation, **kw)},
                                    branch=f'work/{operation}')
        actx = AR.Context(self.dir / 'authz', self.store, fg.FixtureProvider(su.owner_entry()), 3000, http=self.gitea,
                          now=lambda: su.NOW, verifier=su.FakeVerifier())
        nonce = AR.prepare(actx, fg.REPOSITORY, number)['shown']['nonce']
        self.gitea.on_merge = on_merge
        try:
            AR.record(actx, nonce, su.statement(operation), recorded_by=su.RECORDED_BY)
        except AR.RecorderError:
            pass
        finally:
            self.gitea.on_merge = None
        return AR.RECEIPT_PREFIX + nonce

    def basis(self, receipt):
        return {'type': 'envelope-receipt', 'receipt': receipt}

    def delegate(self, receipt, chosen=None, decided_by=EM, ctx=None, **kw):
        return SR.delegate(ctx or self.sctx(), selection() if chosen is None else chosen, decided_by=decided_by,
                           basis=self.basis(receipt) if isinstance(receipt, str) else receipt, **kw)

    def selection_state(self):
        """What a refusal must leave as it was: the series' receipts and the record copies."""
        keys = sorted((r.operation_key, r.state) for r in self.store.attempts()
                      if r.operation_key.startswith(ED.SELECTION_PREFIX))
        copies = self.dir / 'state' / 'delegated-decisions' / 'model-selections'
        return keys, sorted(p.name for p in copies.glob('*.json')) if copies.is_dir() else []

    def assertRefusedLeavingNothing(self, code, *args, **kw):
        before = self.selection_state()
        with self.assertRaises(SR.RecorderError) as caught:
            self.delegate(*args, **kw)
        self.assertEqual((caught.exception.code, caught.exception.refusal), (code, True), caught.exception.detail)
        self.assertIn(code, SR.REMEDIES)
        self.assertEqual(self.selection_state(), before)
        return caught.exception


class TheAct(Selections):
    def test_the_engineering_manager_records_a_selection_and_a_later_one_supersedes_it(self):
        receipt = self.envelope()
        first = self.delegate(receipt)
        record = first['decision']
        self.assertEqual(G.check_record(record), [])
        self.assertEqual((record['format'], record['kind'], record['decidedBy'], record['recordedBy']),
                         (G.FORMAT, 'select-models', EM, EM))
        delegation = record['delegation']
        self.assertEqual((delegation['record'], delegation['point'], delegation['basis']),
                         ('decision:0018', '3', self.basis(receipt)))
        self.assertTrue(D.FULL_COMMIT.match(delegation['revision']))
        self.assertEqual(record['subject'], {**selection(), 'supersedes': None})
        self.assertEqual((first['receipt']['operation_key'], first['receipt']['state'], first['receipt']['events']),
                         ('model-selection/v1/1', 'confirmed', ['reserved', 'dispatched', 'confirmed']))
        self.assertEqual(self.store.events('model-selection/v1/1')[0].actor, 'selection-recorder/1')
        copy = self.dir / 'state' / 'delegated-decisions' / 'model-selections' / f'{record["decisionId"]}.json'
        self.assertEqual(json.loads(copy.read_text(encoding='utf-8')), record)
        self.assertFalse((self.dir / 'state' / 'owner-authorization').exists())   # never among the Owner's records
        intent = json.loads(self.store.get('model-selection/v1/1').intent_json)
        self.assertEqual((intent['format'], intent['recorder'], intent['series'], intent['sequence'],
                          intent['receipt']), (ED.SELECTION_FORMAT, ED.SELECTION_RECORDER, 'selection', 1, receipt))
        second = self.delegate(receipt, selection(leaf='S-03.4'))
        self.assertEqual(second['receipt']['operation_key'], 'model-selection/v1/2')
        self.assertEqual(second['decision']['subject']['supersedes'], record['decisionId'])
        state = SR.status(self.sctx())
        self.assertEqual((state['head']['sequence'], state['head']['decisionId'], state['head']['basis'],
                          state['head']['models'], state['next'], state['envelope']),
                         (2, second['decision']['decisionId'], receipt, {'anthropic-messages': ['syn-model-a']}, 3,
                          {'receipt': receipt}))

    def test_c8_the_product_manager_is_refused(self):
        self.assertRefusedLeavingNothing('DECIDER_NOT_DELEGATED', self.envelope(), decided_by=PM)

    def test_c8_a_basis_of_another_shape_is_refused(self):
        receipt = self.envelope()
        for basis in (None, {'type': 'envelope', 'receipt': receipt}, {'type': 'envelope-receipt'},
                      {'type': 'envelope-receipt', 'receipt': 'owner-authorization/v1/short'},
                      {'type': 'envelope-receipt', 'receipt': receipt, 'extra': 1}, fi.envelope()):
            with self.subTest(basis=basis):
                self.assertRefusedLeavingNothing('DELEGATION_BASIS_INVALID', basis)

    def test_c8_an_unknown_receipt_is_not_recorded(self):
        self.envelope()
        self.assertRefusedLeavingNothing('DELEGATION_BASIS_NOT_RECORDED', AR.RECEIPT_PREFIX + 'ab' * 16)

    def test_c8_a_receipt_not_confirmed_is_no_authority(self):
        receipt = self.envelope(on_merge='drop')                      # the merge answer lost: unknown
        self.assertEqual(self.store.get(receipt).state, 'unknown')
        self.assertIn('not confirmed', self.assertRefusedLeavingNothing('DELEGATION_BASIS_NOT_AUTHORITY',
                                                                        receipt).detail)

    def test_c8_a_receipt_of_another_kind_is_no_authority(self):
        receipt = self.envelope(kind='example-effect')
        self.assertEqual(self.store.get(receipt).state, 'confirmed')
        self.assertIn('example-effect', self.assertRefusedLeavingNothing('DELEGATION_BASIS_NOT_AUTHORITY',
                                                                         receipt).detail)

    def test_c8_a_superseded_or_expired_envelope_is_no_authority(self):
        first = self.envelope('op-envelope-1')
        second = self.envelope('op-envelope-2')
        self.assertIn('supersedes', self.assertRefusedLeavingNothing('DELEGATION_BASIS_NOT_AUTHORITY', first).detail)
        self.now = su.datetime.datetime(2026, 12, 1, tzinfo=su.datetime.timezone.utc)
        self.assertIn('expired', self.assertRefusedLeavingNothing('DELEGATION_BASIS_NOT_AUTHORITY', second).detail)

    def test_c8_an_unsettled_later_envelope_leaves_no_authority(self):
        first = self.envelope('op-envelope-1')
        self.envelope('op-envelope-2', on_merge='drop')
        self.assertIn('ENVELOPE_AUTHORIZATION_UNRESOLVED',
                      self.assertRefusedLeavingNothing('DELEGATION_BASIS_NOT_AUTHORITY', first).detail)

    def test_c8_a_receipt_reserved_by_another_actor_is_no_authority(self):
        receipt = self.envelope()
        intent = json.loads(self.store.get(receipt).intent_json)
        forged = AR.RECEIPT_PREFIX + 'cd' * 16
        self.hand_receipt(forged, intent, actor='someone-else')
        self.assertRefusedLeavingNothing('DELEGATION_BASIS_NOT_AUTHORITY', forged)

    def test_c8_decision_0018_proposed_at_head(self):
        receipt = self.envelope()
        self.assertRefusedLeavingNothing('DELEGATION_NOT_ACCEPTED', receipt,
                                         ctx=self.sctx(harness=self.repos.harness['proposed']))

    def test_c8_no_store(self):
        receipt = self.envelope()
        self.assertRefusedLeavingNothing('AUTHORITY_UNAVAILABLE', receipt, ctx=self.sctx(store=None))
        with self.assertRaises(G.DelegationRefused) as caught:                  # the basis type itself
            G.read_authority(self.repos.harness['accepted'], 'select-models', EM, self.basis(receipt))
        self.assertEqual(caught.exception.code, 'AUTHORITY_UNAVAILABLE')

    def test_c8_a_malformed_selection(self):
        receipt = self.envelope()
        entry = selection()['models']['anthropic-messages'][0]
        for name, chosen in (
                ('a wildcard', selection(models={'anthropic-messages': [{**entry, 'id': 'syn-*'}]})),
                ('a duplicate', selection(models={'anthropic-messages': [entry, entry]})),
                ('an empty list', selection(models={'anthropic-messages': []})),
                ('no family', selection(models={})),
                ('a family that is no id', selection(models={'Anthropic Messages': [entry]})),
                ('a use of two lines', selection(models={'anthropic-messages': [{**entry, 'use': 'a\nb'}]})),
                ('an entry without cost', selection(models={'anthropic-messages': [{'id': 'm', 'use': 'u'}]})),
                ('a leaf that is no id', selection(leaf='the next one')),
                ('a verification without a time', selection(verified={'source': 'x', 'at': 'today'})),
                ('supersedes given', {**selection(), 'supersedes': None}),
                ('a missing field', {'leaf': 'S-03.3', 'models': selection()['models']})):
            with self.subTest(name):
                self.assertRefusedLeavingNothing('SELECTION_INVALID', receipt, chosen)

    def test_a_position_taken_meanwhile(self):
        receipt = self.envelope()
        store, sr_store = self.store, self

        class Racing:
            """The store, with another act reserving the position just before this one does."""
            def __getattr__(self, name):
                return getattr(store, name)

            def reserve(self, key, intent, *, actor):
                store.reserve(key, {'format': 'another act (SYNTHETIC)'}, actor=ED.SELECTION_RECORDER)
                return store.reserve(key, intent, actor=actor)
        with self.assertRaises(SR.RecorderError) as caught:
            self.delegate(receipt, ctx=self.sctx(store=Racing()))
        self.assertEqual((caught.exception.code, caught.exception.refusal), ('SELECTION_POSITION_TAKEN', True))
        self.assertEqual(sr_store.selection_state(), ([('model-selection/v1/1', 'reserved')], []))

    def test_a_write_that_stops_after_the_reservation_spends_the_position(self):
        receipt = self.envelope()
        blocked = self.dir / 'state-is-a-file'
        blocked.write_text('not a directory\n', encoding='utf-8')
        with self.assertRaises(SR.RecorderError) as caught:
            self.delegate(receipt, ctx=self.sctx(state_root=blocked))
        self.assertEqual((caught.exception.code, caught.exception.refusal), ('SELECTION_WRITE_FAILED', False))
        self.assertEqual(self.store.get('model-selection/v1/1').state, 'failed')
        self.assertEqual(self.delegate(receipt)['receipt']['operation_key'], 'model-selection/v1/2')
        self.assertEqual(SR.status(self.sctx())['failed'], [1])

    def test_the_read_side_answers_the_governing_selection(self):
        """envelope_decisions.verify_selection (and the source's selection): missing, the view of the last
        confirmed position, another receipt, and the order of a stored record restored."""
        receipt = self.envelope()
        self.assertEqual(ED.verify_selection(self.store, receipt).code, 'MODEL_SELECTION_MISSING')
        first = self.delegate(receipt)
        second = self.delegate(receipt, selection(leaf='S-03.4'))
        verdict = ED.verifier(self.store).selection(receipt)
        self.assertIsNone(verdict.code, verdict.detail)
        self.assertEqual(verdict.view, {'receipt': 'model-selection/v1/2',
                                        'decisionId': second['decision']['decisionId'], 'record': 'decision:0018',
                                        'point': '3', 'basis': receipt,
                                        'models': {'anthropic-messages': ['syn-model-a']}})
        self.assertNotEqual(verdict.view['decisionId'], first['decision']['decisionId'])
        other = AR.RECEIPT_PREFIX + 'ab' * 16
        self.assertEqual(ED.verify_selection(self.store, other).code, 'MODEL_SELECTION_RECEIPT_MISMATCH')
        stored = json.loads(self.store.get('model-selection/v1/2').intent_json)['decision']
        self.assertNotEqual(G.check_record(stored), [])                       # sorted keys: the order check fails
        self.assertEqual(ED.stored_selection(stored), second['decision'])
        self.assertEqual(list(ED.SELECTION_REFUSALS), ['MODEL_SELECTION_MISSING', 'MODEL_SELECTION_NOT_AUTHORIZED',
                                                       'MODEL_SELECTION_RECEIPT_MISMATCH'])

    def test_the_real_decision_0018_at_head_delegates_the_selection(self):
        """Read-only at this checkout's HEAD: decision 0018 is Accepted (Owner), so the row is in force."""
        receipt = self.envelope()
        authority = G.read_authority(fi.REPO, 'select-models', EM, self.basis(receipt), store=self.store)
        self.assertEqual((authority.row.record, authority.row.point, authority.row.decider),
                         ('decision:0018', '3', EM))


class Repeated(unittest.TestCase):
    def test_the_repeated_constants_equal_their_sources(self):
        self.assertEqual((G.ENVELOPE_RECEIPT_PREFIX, G.ENVELOPE_RECORDER, G.ENVELOPE_RECEIPT_FORMAT),
                         (AR.RECEIPT_PREFIX, AR.RECORDER, AR.RECEIPT_FORMAT))
        self.assertEqual(G.ENVELOPE_KIND, ED.OPERATION_KIND)
        row = G.DELEGATIONS['select-models']
        self.assertEqual((row.record, row.point, row.decider, row.basis_type),
                         ('decision:0018', '3', EM, 'envelope-receipt'))
        self.assertTrue(G.BASIS_TYPES['envelope-receipt'].needs_store)
        self.assertFalse(any(G.BASIS_TYPES[name].needs_store for name in ('commitment', 'envelope')))


class CommandLine(Selections):
    def write(self, name, data):
        path = self.dir / name
        path.write_text(json.dumps(data), encoding='utf-8')
        return str(path)

    def run_main(self, *argv, ctx=None):
        out, err = io.StringIO(), io.StringIO()

        class Opened:
            def __enter__(inner):
                return ctx or self.sctx()

            def __exit__(inner, *exc):
                return False
        code = SR.main(list(argv), out, err, context=Opened)
        return code, out.getvalue(), err.getvalue()

    def test_delegate_and_status(self):
        receipt = self.envelope()
        code, out, err = self.run_main('delegate', '--selection', self.write('s.json', selection()), '--decided-by', EM,
                                       '--basis', self.write('b.json', self.basis(receipt)))
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)['receipt']['state'], 'confirmed')
        code, out, err = self.run_main('status')
        self.assertEqual((code, json.loads(out)['head']['sequence']), (0, 1))
        code, out, err = self.run_main('delegate', '--selection', self.write('s2.json', selection()), '--decided-by', PM,
                                       '--basis', self.write('b2.json', self.basis(receipt)))
        self.assertEqual(code, 2)
        self.assertIn('DECIDER_NOT_DELEGATED', err)
        code, out, err = self.run_main('delegate', '--selection', str(self.dir / 'absent.json'), '--decided-by', EM,
                                       '--basis', self.write('b3.json', self.basis(receipt)))
        self.assertEqual(code, 2)
        self.assertIn('SELECTION_INVALID', err)

    def test_a_failed_write_exits_1(self):
        receipt = self.envelope()
        blocked = self.dir / 'state-is-a-file'
        blocked.write_text('x\n', encoding='utf-8')
        code, _out, err = self.run_main('delegate', '--selection', self.write('s.json', selection()), '--decided-by',
                                        EM, '--basis', self.write('b.json', self.basis(receipt)),
                                        ctx=self.sctx(state_root=blocked))
        self.assertEqual(code, 1)
        self.assertIn('SELECTION_WRITE_FAILED', err)

    def test_the_managed_context_opens_the_managed_store_and_this_checkout(self):
        res = object()
        made = []

        def ensure(category, resolved, *parts):
            made.append((category, *parts))
            return self.dir / 'managed' / category / Path(*parts) if parts else self.dir / 'managed' / category
        opened = mock.MagicMock()
        opened.__enter__.return_value = self.store
        with mock.patch.object(SR.paths, 'resolve', return_value=res), \
                mock.patch.object(SR.paths, 'ensure', side_effect=ensure), \
                mock.patch.object(SR.store_module, 'open_store', return_value=opened) as open_store:
            with SR.managed_context() as ctx:
                self.assertEqual((ctx.state_root, ctx.store, ctx.harness),
                                 (self.dir / 'managed' / 'state', self.store, fi.REPO))
        self.assertEqual(made, [('state',), ('state', 'integration')])
        open_store.assert_called_once_with(self.dir / 'managed' / 'state' / 'integration' / 'integration.sqlite')

    def test_importing_the_act_loads_no_gitea_and_no_credential_module(self):
        code = ('import importlib.util, json, sys\n'
                'spec = importlib.util.spec_from_file_location("selection_recorder", sys.argv[1])\n'
                'module = importlib.util.module_from_spec(spec); sys.modules["selection_recorder"] = module\n'
                'spec.loader.exec_module(module)\n'
                'print(json.dumps(sorted(getattr(m, "__file__", None) or "" for m in list(sys.modules.values()))))\n')
        result = subprocess.run([sys.executable, '-I', '-B', '-c', code, str(fi.OWNER / 'selection_recorder.py')],
                                capture_output=True, text=True, encoding='utf-8', timeout=fx.WAIT_CEILING_S,
                                stdin=subprocess.DEVNULL,
                                env={**os.environ, 'AIEH_DATA_ROOT': str(self.dir / 'no-data-root')})
        self.assertEqual(result.returncode, 0, result.stderr)
        files = [Path(f) for f in json.loads(result.stdout) if f]
        loaded = {f.resolve().relative_to(fi.REPO).as_posix() for f in files if f.resolve().is_relative_to(fi.REPO)}
        self.assertIn('integrations/owner/envelope_decisions.py', loaded)
        forbidden = sorted(f for f in loaded if f.startswith(('integrations/gitea/', 'integrations/credentials/',
                                                              'integrations/inference/'))
                           or f.endswith('authorization_recorder.py'))
        self.assertEqual(forbidden, [])
        self.assertFalse((self.dir / 'no-data-root').exists())


if __name__ == '__main__':
    unittest.main()
