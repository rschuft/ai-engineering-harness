"""The proof of plan leaf P-04.3: an approved-input manifest loads only through a recorded decision.

Run from the repository root, under the tools interpreter (Dulwich is required):

    <tools python> -I -B -m unittest discover -s integrations/dispatch/tests -v

Every row of the work design's proof table (answer.md section 3, stated before it was run) is shown through
``load_manifest`` with the REAL decision verifier (``integrations/owner/input_decisions.verifier``) over a
throwaway integration store, and the manifests are promoted by the REAL recorder
(``integrations/owner/input_recorder.py``), by the Owner (a challenge and a synthetic statement) or under
decision 0018 point 3.3 (on a fixture harness repository holding a decision 0018 and a log). Nothing here
uses the resolution tests' test-only verifier (``test_dispatch_inputs.fixture_verifier``). The fixtures are
the dispatch-input commands' own (``integrations/owner/tests/input_fixture.py``); every statement, basis
and quote is synthetic.
"""
import json
import sys
import unittest
from pathlib import Path

CATEGORY = 'integration'

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / 'integrations' / 'owner' / 'tests'))
import input_fixture as fi  # noqa: E402

IR, I, D, G, DI = fi.IR, fi.I, fi.D, fi.G, fi.DI
REPOSITORY, CHANGE = fi.REPOSITORY, fi.CHANGE


def setUpModule():
    fi.start()


def tearDownModule():
    fi.stop()


class Proof(fi.Fixture):
    def load(self, path=None, decisions=True):
        """load_manifest of PATH (the live manifest by default) with the real verifier over this test's store."""
        return DI.load_manifest(path or self.live, decisions=I.verifier(self.store) if decisions else None)

    def refused(self, path=None, decisions=True):
        with self.assertRaises(DI.DispatchRefused) as caught:
            self.load(path, decisions)
        return caught.exception.code

    def hand(self, text, name):
        """A manifest written by hand (outside the recorder), outside the checkout."""
        path = self.dir / 'candidates' / name
        path.write_text(text, encoding='utf-8', newline='\n')
        return path

    def promoted_v1(self):
        self.accept()
        self.promote(self.candidate())
        return self.live.read_text(encoding='utf-8')


class EntryWithoutARecordedDecision(Proof):
    """Proof clause: an entry written without a recorded decision."""

    def test_a_manifest_written_by_hand_with_an_empty_store(self):
        self.assertEqual(self.refused(self.hand(fi.manifest(), 'by-hand.json')), 'MANIFEST_NOT_PROMOTED')

    def test_an_entry_added_and_the_version_raised_by_hand(self):
        self.promoted_v1()
        data = json.loads(self.live.read_text(encoding='utf-8'))
        data['version'] = 2
        data['repositories'].append({'id': 'added-by-hand'})
        self.live.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8', newline='\n')
        self.assertEqual(self.refused(), 'MANIFEST_NOT_PROMOTED')

    def test_no_decision_source(self):
        self.promoted_v1()
        self.assertEqual(self.refused(decisions=False), 'MANIFEST_NOT_PROMOTED')
        self.assertIsNotNone(self.load().approval)  # with its source, the same file loads


class DigestOtherThanTheDecidedOne(Proof):
    """Proof clause: an entry with a digest that differs from the decided one."""

    def test_one_byte_of_whitespace(self):
        text = self.promoted_v1()
        self.live.write_text(text + ' ', encoding='utf-8', newline='\n')
        self.assertEqual(self.refused(), 'MANIFEST_DIGEST_MISMATCH')

    def test_a_profile_sha256_and_separately_a_pin_manifest_sha256(self):
        text = self.promoted_v1()
        for changed in (text.replace('2' * 64, '7' * 64), text.replace('4' * 64, '8' * 64)):
            with self.subTest(changed=changed != text):
                self.assertNotEqual(changed, text)
                self.live.write_text(changed, encoding='utf-8', newline='\n')
                self.assertEqual(self.refused(), 'MANIFEST_DIGEST_MISMATCH')


class DesignEntryWithoutAnAcceptance(Proof):
    """Proof clause: a design entry without a design-acceptance record."""

    def test_the_recorder_refuses_a_candidate_whose_design_has_no_acceptance(self):
        before = self.snapshot()
        for call in (lambda path: IR.manifest_prepare(self.ctx, path), self.delegate_promotion):
            with self.assertRaises(IR.RecorderError) as caught:
                call(self.candidate())
            self.assertEqual(caught.exception.code, 'DESIGN_ACCEPTANCE_MISSING')
        self.assertEqual(self.snapshot(), before)  # no receipt, live file unchanged (absent)
        self.assertEqual(self.receipts(), {})
        self.assertIsNone(self.live_bytes())

    def test_a_promotion_receipt_written_by_hand_for_a_design_without_an_acceptance_receipt(self):
        self.promoted_v1()
        text = fi.manifest(version=2, designs=((REPOSITORY, fi.OTHER_CHANGE, self.repos.second),))
        digest = f'sha256:{DI.parse_manifest(text.encode("utf-8")).sha256}'
        intent = json.loads(self.store.get(I.promotion_key(1)).intent_json)
        decision = intent['decision']
        decision['subject'].update(version=2, digest=digest, previous={'version': 1, 'digest': intent['digest']},
                                   designs=[{'repository': REPOSITORY, 'change': fi.OTHER_CHANGE,
                                             'commit': self.repos.second, 'acceptance': D.new_decision_id(),
                                             'sequence': 1}])
        key = I.promotion_key(2)
        self.store.reserve(key, {**intent, 'decision': decision, 'version': 2, 'digest': digest,
                                 'previous': decision['subject']['previous'], 'text': text}, actor='by-hand')
        self.store.transition(key, 'dispatched', actor='by-hand')
        self.store.transition(key, 'confirmed', actor='by-hand')
        self.live.write_text(text, encoding='utf-8', newline='\n')
        self.assertEqual(self.refused(), 'DESIGN_ACCEPTANCE_MISSING')


class ReplayedDecision(Proof):
    """Proof clause: a replayed decision."""

    def test_version_one_put_back_after_version_two(self):
        v1 = self.promoted_v1()
        self.promote(self.candidate(name='v2.json', version=2))
        self.assertEqual(self.load().version, 2)
        self.live.write_text(v1, encoding='utf-8', newline='\n')
        self.assertEqual(self.refused(), 'DECISION_REPLAYED')

    def test_record_twice_on_one_owner_challenge(self):
        self.accept()
        challenge = IR.manifest_prepare(self.ctx, self.candidate())
        said = fi.statement('approved-inputs-v1')
        IR.manifest_record(self.ctx, challenge['shown']['nonce'], said, recorded_by=fi.RECORDED_BY)
        with self.assertRaises(IR.RecorderError) as caught:
            IR.manifest_record(self.ctx, challenge['shown']['nonce'], said, recorded_by=fi.RECORDED_BY)
        self.assertEqual(caught.exception.code, 'CHALLENGE_CONSUMED')
        self.assertEqual([k for k in self.receipts() if k.startswith(I.PROMOTION_PREFIX)], [I.promotion_key(1)])

    def test_a_candidate_naming_a_superseded_design_revision(self):
        self.accept()
        self.accept(self.repos.second)
        with self.assertRaises(IR.RecorderError) as caught:
            IR.manifest_prepare(self.ctx, self.candidate())
        self.assertEqual(caught.exception.code, 'DECISION_REPLAYED')


class PromotedManifestLoads(Proof):
    """Proof clause: a promoted manifest loads, and each of its entries names its approving record."""

    def assertEveryEntryNamesItsRecord(self, manifest, authority):
        for section, entries in manifest._index().items():
            for key, entry in entries.items():
                with self.subTest(section=section, key=key):
                    named = manifest.approving_record(section, key)
                    reservation = self.store.get(named['receipt'])
                    self.assertEqual(reservation.state, 'confirmed')
                    decision = I.stored_record(json.loads(reservation.intent_json)['decision'])
                    self.assertEqual(named['decisionId'], decision['decisionId'])
                    self.assertEqual(named['authority']['authority'], authority)
                    if section == 'designs':
                        self.assertEqual(named['kind'], 'accept-design')
                        self.assertEqual({k: decision['subject'][k] for k in ('repository', 'change', 'commit')},
                                         {k: entry[k] for k in ('repository', 'change', 'commit')})
                    else:
                        self.assertEqual(named['kind'], 'promote-manifest')
                        self.assertEqual(decision['subject']['digest'], f'sha256:{manifest.sha256}')
                        self.assertEqual(decision['subject']['version'], manifest.version)

    def test_owner_kind_one_design(self):
        self.promoted_v1()
        manifest = self.load()
        written = self.live.read_bytes()
        self.assertEqual((manifest.version, manifest.sha256),
                         (1, __import__('hashlib').sha256(written).hexdigest()))
        self.assertEveryEntryNamesItsRecord(manifest, 'owner')
        self.assertEqual(manifest.approval['promotion']['format'], D.FORMAT)

    def test_delegated_kind_on_the_fixture_harness_repository(self):
        self.delegate_design()
        self.delegate_promotion(self.candidate())
        manifest = self.load()
        self.assertEveryEntryNamesItsRecord(manifest, 'delegated')
        promotion = manifest.approval['promotion']
        self.assertEqual(promotion['format'], G.FORMAT)
        self.assertEqual((promotion['authority']['record'], promotion['authority']['point'],
                          promotion['authority']['basis']), ('decision:0018', '3.3', fi.envelope()))
        design = manifest.approving_record('designs', (REPOSITORY, CHANGE))
        self.assertEqual((design['authority']['point'], design['authority']['basis']), ('3.2', fi.commitment()))


class NeverAnOwnerDecision(Proof):
    """Proof clause: never an Owner decision (decision 0018 point 3.2; the P-04 gate)."""

    def test_an_agent_attributed_statement_is_refused_for_either_kind(self):
        design = IR.design_prepare(self.ctx, self.repos.project, REPOSITORY, CHANGE, self.repos.first)
        for attributed in (fi.PM, fi.EM):
            with self.assertRaises(IR.RecorderError) as caught:
                IR.design_record(self.ctx, design['shown']['nonce'], fi.statement(CHANGE, attributedTo=attributed),
                                 recorded_by=fi.RECORDED_BY)
            self.assertEqual(caught.exception.code, 'STATEMENT_MODEL_AUTHORED')
        self.accept()
        manifest = IR.manifest_prepare(self.ctx, self.candidate())
        with self.assertRaises(IR.RecorderError) as caught:
            IR.manifest_record(self.ctx, manifest['shown']['nonce'],
                               fi.statement('approved-inputs-v1', attributedTo=fi.PM), recorded_by=fi.PM)
        self.assertEqual(caught.exception.code, 'STATEMENT_MODEL_AUTHORED')
        self.assertIsNone(self.live_bytes())

    def test_a_delegated_record_fails_the_owner_records_check(self):
        delegated = self.delegate_design()['decision']
        self.assertEqual(G.check_record(delegated), [])
        self.assertIn('format must be owner-decision/v1', D.check_record(delegated))
        promotion = self.delegate_promotion(self.candidate())['decision']
        self.assertIn('format must be owner-decision/v1', D.check_record(promotion))


class EnforcementCannotBeSkipped(Proof):
    """Proof clause: the enforcement cannot be skipped. ``resolve`` and ``admit`` given ``parse_manifest``'s
    output refuse MANIFEST_NOT_PROMOTED, with nothing reserved and nothing read."""

    def forbidden(self, what):
        def call(*args, **kw):
            self.reads.append(what)
            raise AssertionError(f'{what} was called')
        return call

    def setUp(self):
        super().setUp()
        self.reads = []
        self.promoted_v1()
        self.parsed = DI.parse_manifest(self.live.read_bytes())
        self.assertIsNone(self.parsed.approval)

    def request(self):
        return {'format': DI.REQUEST_FORMAT, 'work_id': 'TASK-1', 'repository': REPOSITORY, 'stage': 'implement',
                'profile': 'fixture-profile', 'catalog_pin': 'fixture-pin'}

    def test_resolve(self):
        before = self.store.attempts()
        with self.assertRaises(DI.DispatchRefused) as caught:
            DI.resolve(self.request(), manifest=self.parsed, work_sources=self.forbidden('work_sources'),
                       next_ordinal=self.forbidden('next_ordinal'), read_profile=self.forbidden('read_profile'))
        self.assertEqual(caught.exception.code, 'MANIFEST_NOT_PROMOTED')
        self.assertEqual((self.reads, self.store.attempts()), ([], before))

    def test_admit(self):
        resolved = DI.ResolvedInputs(
            work_id='TASK-1', repository=REPOSITORY, stage='implement', ordinal=1,
            design_revision=f'openspec:changes/{CHANGE}@{self.repos.first}', profile='fixture-profile',
            profile_digest='2' * 64, catalog_pin='fixture-pin', agent_manifest_digest='4' * 64,
            planned_workspace=f'{REPOSITORY}/TASK-1/x', policy_digest='0' * 64, policy_inputs_json='{}',
            manifest_version=1, manifest_sha256=self.parsed.sha256, outcome_ref='outcome:x')
        with self.assertRaises(DI.DispatchRefused) as caught:
            DI.admit(resolved, manifest=self.parsed, workspaces=None, read_profile=self.forbidden('read_profile'),
                     read_artifact=self.forbidden('read_artifact'))
        self.assertEqual(caught.exception.code, 'MANIFEST_NOT_PROMOTED')
        self.assertEqual(self.reads, [])

    def test_dispatch_reserves_nothing(self):
        before = self.store.attempts()
        with self.assertRaises(DI.DispatchRefused) as caught:
            DI.dispatch(self.request(), manifest=self.parsed, work_sources=self.forbidden('work_sources'),
                        integration_store=self.store, workspaces=None, transport=self.forbidden('transport'),
                        actor='test', read_profile=self.forbidden('read_profile'),
                        read_artifact=self.forbidden('read_artifact'))
        self.assertEqual(caught.exception.code, 'MANIFEST_NOT_PROMOTED')
        self.assertEqual((self.reads, self.store.attempts()), ([], before))

    def test_an_approval_of_another_manifest_is_refused(self):
        """A manifest object carrying a view that does not match its own version and digest."""
        loaded = self.load()
        forged = DI.dataclasses.replace(self.parsed, approval_json=loaded.approval_json.replace(
            loaded.sha256, '0' * 64))
        with self.assertRaises(DI.DispatchRefused) as caught:
            DI.resolve(self.request(), manifest=forged, work_sources=self.forbidden('work_sources'),
                       next_ordinal=self.forbidden('next_ordinal'), read_profile=self.forbidden('read_profile'))
        self.assertEqual(caught.exception.code, 'MANIFEST_NOT_PROMOTED')
        with self.assertRaises(DI.DispatchRefused) as caught:
            self.parsed.approving_record('profiles', 'fixture-profile')
        self.assertEqual(caught.exception.code, 'MANIFEST_NOT_PROMOTED')


class LoadOrder(Proof):
    """Ruling R8: the path rules stay load_manifest's first refusals (the recorder relies on them), then the
    read and the schema; the verifier is asked last, and only a well-formed answer approves."""

    def counting(self, answer=None):
        calls = []

        def verifier(*args):
            calls.append(args)
            if isinstance(answer, BaseException):
                raise answer
            return I.verifier(self.store)(*args) if answer is None else answer
        return verifier, calls

    def test_the_path_refusals_come_first_and_ask_no_verifier(self):
        verifier, calls = self.counting()
        cases = (('relative.json', 'MANIFEST_PATH_INVALID'), (None, 'MANIFEST_PATH_INVALID'),
                 (str(self.dir / 'a' / '..' / 'm.json'), 'MANIFEST_PATH_INVALID'),
                 (REPO / 'never-written-p043.json', 'MANIFEST_INSIDE_CHECKOUT'),
                 (REPO.parent, 'MANIFEST_INSIDE_CHECKOUT'),
                 (self.dir / 'absent.json', 'MANIFEST_MISSING'), (self.dir, 'MANIFEST_UNREADABLE'),
                 (self.hand('{', 'broken.json'), 'MANIFEST_INVALID'))
        for path, code in cases:
            with self.subTest(path=path):
                with self.assertRaises(DI.DispatchRefused) as caught:
                    DI.load_manifest(path, decisions=verifier)
                self.assertEqual(caught.exception.code, code)
        self.assertEqual(calls, [])
        self.assertEqual(list(DI.REFUSALS)[4:10], ['MANIFEST_PATH_INVALID', 'MANIFEST_INSIDE_CHECKOUT',
                                                    'MANIFEST_MISSING', 'MANIFEST_UNREADABLE', 'MANIFEST_INVALID',
                                                    'MANIFEST_NOT_PROMOTED'])
        self.assertEqual(DI.DECISION_REFUSALS, tuple(I.REFUSALS))
        self.assertEqual(DI.APPROVAL_FORMAT, I.APPROVAL_FORMAT)

    def test_a_verifier_that_raises_or_answers_badly_approves_nothing(self):
        self.promoted_v1()
        good = I.verifier(self.store)(*self.args())
        approval = good.approval
        for answer in (RuntimeError('store locked'), 'yes', (None, ''), (None, '', None),
                       ('SOMETHING_ELSE', 'x', None), (None, '', {**approval, 'digest': 'sha256:' + '0' * 64}),
                       (None, '', {**approval, 'version': 2}), (None, '', {**approval, 'designs': []}),
                       (None, '', {**approval, 'format': 'other'}),
                       (None, '', {**approval, 'promotion': {'decisionId': 'x'}})):
            with self.subTest(answer=answer):
                verifier, calls = self.counting(answer)
                with self.assertRaises(DI.DispatchRefused) as caught:
                    DI.load_manifest(self.live, decisions=verifier)
                self.assertEqual(caught.exception.code, 'DECISION_RECORD_INVALID')
                self.assertEqual(len(calls), 1)
        verifier, calls = self.counting()
        self.assertEqual(DI.load_manifest(self.live, decisions=verifier).approval, approval)
        self.assertEqual(calls, [self.args()])

    def args(self):
        approved = DI.parse_manifest(self.live.read_bytes())
        return (approved.version, approved.sha256,
                [{k: e[k] for k in ('repository', 'change', 'commit')} for e in approved.data['designs']])

    def test_the_verifiers_own_refusals_pass_through(self):
        self.promoted_v1()
        self.store.reserve(I.promotion_key(2), {'format': 'by-hand'}, actor='test')
        self.live.write_text(fi.manifest(version=2), encoding='utf-8', newline='\n')
        self.assertEqual(self.refused(), 'DECISION_RECORD_INVALID')


if __name__ == '__main__':
    unittest.main()
