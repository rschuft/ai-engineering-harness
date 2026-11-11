"""The live authorization exercise's two phases (test_live_authorization.py; Owner decision OA-14), offline.

Run from the repository root, under the tools interpreter:

    <tools python> -I -B -m unittest discover -s integrations/owner/tests -v

The phase functions run against the in-memory fake Gitea (fake_gitea.FakeGitea, gitea_host.http_get's
signature: no socket) with a fixture credential provider holding the fake aieh-owner's password and the
fake bots' tokens; the run directory is a fixture directory; the custody inspection is not run. Covered:
the presentation's content; phase record refusing a statement that is missing, empty, not JSON,
model-authored, not the Owner's or naming none of the challenged operations, before any Gitea call or
credential read; the expected outcome without a protection verifier (PROTECTION_UNVERIFIED, nothing
merged); with a fake verified verifier, one merge and the stale-head control refused with nothing merged
and main unmoved, its refusal recorded as observed (409, or 405 or 500: finding F14); the command line's
protection check (Owner decision OA-16) end to end against the fake's protection auditor, verified and
drifted; and the SECURITY FAILURE stop when a fake bot merge, or the stale-head control's, succeeds. Every statement here is SYNTHETIC and no Owner decision: it
stands in, in a fixture, for the Owner's reply the live phase reads from a file.
"""
import hashlib
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

CATEGORY = 'unit'

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import authz_support as su  # noqa: E402
import test_live_authorization as L  # noqa: E402

AR, fg, R = su.AR, su.fg, su.AR.roles


def setUpModule():
    su.start()


def tearDownModule():
    su.stop()


class Phases(su.Fixture):
    def gitea_for_test(self):
        gitea = fg.FakeGitea()
        return gitea, 3000, gitea

    def setUp(self):
        super().setUp()
        for role, spec in R.ROLES.items():
            self.provider.entries[R.target(role)] = (spec['user'], fg.BOT_TOKENS[spec['user']])
        self.run_dir = self.dir / 'run'
        self.run_dir.mkdir()

    def live(self, verifier=None):
        return L.Live(self.port, self.provider, self.run_dir, http=self.http, now=lambda: self.now,
                      verifier=verifier, verifier_note='fake verifier' if verifier else AR.NO_VERIFIER)

    def prepared(self, verifier=None):
        observed = {}
        return L.prepare_phase(self.live(verifier), observed), observed

    def statement_file(self, said, name='statement.json'):
        path = self.dir / name
        path.write_text(said if isinstance(said, str) else json.dumps(said), encoding='utf-8')
        return path

    def synthetic(self, *operations):
        """A SYNTHETIC statement naming OPERATIONS (no Owner decision)."""
        return su.statement(text='SYNTHETIC FIXTURE, not an Owner decision: I authorize operations '
                                 + ' and '.join(operations) + '.')

    def operations(self, presentation):
        return [c['operation'] for c in presentation['challenges']]


class Prepare(Phases):
    def test_the_presentation(self):
        presentation, observed = self.prepared()
        saved = json.loads((self.run_dir / L.PRESENTATION).read_text(encoding='utf-8'))
        self.assertEqual(saved, presentation)
        self.assertEqual(presentation['format'], L.PRESENTATION_FORMAT)
        self.assertEqual(presentation['verifier'], {'available': False, 'note': AR.NO_VERIFIER})
        self.assertEqual([c['role'] for c in presentation['challenges']], [L.AUTHORIZE, L.STALE])
        self.assertEqual(presentation['staleHeadControl'], presentation['challenges'][1]['pull'])
        self.assertEqual(presentation['mainHead'], self.gitea.branches['main'])
        for c in presentation['challenges']:
            with self.subTest(pull=c['pull']):
                self.assertEqual(tuple(c), L.CHALLENGE_KEYS)
                blob = self.gitea.commits[self.gitea.head(c['pull'])]['tree'][c['manifest']]
                self.assertEqual(c['manifestDigest'], 'sha256:' + hashlib.sha256(blob).hexdigest())
                self.assertEqual(c['approvedHead'], self.gitea.head(c['pull']))
                self.assertEqual((c['kind'], c['manifest']), (L.KIND, f'operations/{c["operation"]}.json'))
                self.assertEqual((c['base'], c['repository']), ('main', fg.REPOSITORY))
                self.assertEqual(c['operationExpiresAt'], '2026-11-11T12:00:00Z')
                self.assertEqual(c['challengeExpiresAt'], '2026-11-10T15:00:00Z')
                # the challenge the recorder issued, in this run's recorder state
                state = self.run_dir / L.RECORDER_DIR / 'state' / 'challenges' / f'{c["nonce"]}.json'
                issued = json.loads(state.read_text(encoding='utf-8'))
                self.assertEqual((issued['subject']['head'], issued['subject']['digest']),
                                 (c['approvedHead'], c['manifestDigest']))
                self.assertEqual(c['summary'], issued['shown']['summary'])
                self.assertEqual(c['protectionAtPrepare']['code'], 'PROTECTION_UNVERIFIED')
                self.assertIn('PROTECTION_UNVERIFIED', c['expectedOutcome'])
                self.assertTrue(any('merge commit on main' in e for e in c['effects']))
                self.assertTrue(any(c['manifestDigest'] in e for e in c['effects']))
                self.assertEqual(self.gitea.pulls[c['pull']]['reviews'], [(R.ROLES['reviewer']['user'], 'APPROVED',
                                                                           c['approvedHead'])])
        self.assertIn('nothing is merged and main does not move', presentation['challenges'][1]['expectedOutcome'])
        self.assertTrue(any('409 expected' in e and 'F14' in e for e in presentation['challenges'][1]['effects']))
        # the bot controls: each bot token on each proposal, refused (the auditor's by its scope); nothing merged
        self.assertEqual(len(presentation['botMerges']['statuses']), 2 * len(R.ROLES))
        for control, status in presentation['botMerges']['statuses'].items():
            self.assertEqual(status, 403 if control.startswith('protection-audit ') else 405, control)
        self.assertEqual(self.gitea.merge_count(), 0)
        self.assertEqual({r['doer'] for r in self.gitea.requests_by('POST') if r['path'].endswith('/merge')},
                         {spec['user'] for spec in R.ROLES.values()})
        text = (self.run_dir / L.PRESENTATION_TEXT).read_text(encoding='utf-8')
        for c in presentation['challenges']:
            for value in (c['operation'], c['nonce'], c['manifestDigest'], c['approvedHead'], c['challengeExpiresAt']):
                self.assertIn(value, text)
        self.assertIn('THE STALE-HEAD CONTROL (expected: refused; nothing merges and main does not move)', text)
        self.assertIn('Protection verifier: NONE', text)
        # the exercise wrote no statement, and no secret reached the run directory
        self.assertNotIn('attributedTo"', json.dumps(presentation))
        files = sorted(p.relative_to(self.run_dir).as_posix() for p in self.run_dir.rglob('*') if p.is_file())
        self.assertEqual([f for f in files if not f.startswith('recorder/')], [L.PRESENTATION, L.PRESENTATION_TEXT])
        self.secrets_absent(*(p.read_bytes().decode('utf-8', 'replace') for p in self.run_dir.rglob('*')
                              if p.is_file() and p.suffix != '.sqlite'), json.dumps(observed))

    def test_with_a_verifier_the_presentation_says_so(self):
        presentation, _ = self.prepared(su.FakeVerifier())
        self.assertEqual(presentation['verifier'], {'available': True, 'note': 'fake verifier'})
        authorize, stale = presentation['challenges']
        self.assertIn('one merge commit', authorize['expectedOutcome'])
        self.assertIn('nothing is merged and main does not move', stale['expectedOutcome'])
        self.assertIn('F14', stale['expectedOutcome'])
        self.assertEqual(authorize['protectionAtPrepare']['verdict'], 'verified')

    def test_a_verifier_that_does_not_verify_at_prepare_sets_the_expected_outcome(self):
        presentation, _ = self.prepared(su.FakeVerifier(default=su.DRIFT))
        for c in presentation['challenges']:
            self.assertTrue(c['expectedOutcome'].startswith('refused PROTECTION_DRIFT before anything is sent'),
                            c['expectedOutcome'])

    def test_the_available_verifier_is_the_command_line_s_protection_check(self):
        verifier, note = L.available_verifier(self.port, self.provider)
        self.assertEqual(verifier.__qualname__, 'protection_verifier.<locals>.verifier')
        self.assertIn('OA-16', note)
        self.assertIn(AR.protection.AUDITOR, note)

    def test_an_approval_of_another_commit_fails_the_phase(self):
        def http(port, path, **kw):
            status, headers, data = self.gitea(port, path, **kw)
            if path.endswith('/reviews'):
                data = json.dumps({**json.loads(data), 'commit_id': '0' * 40}).encode()
            return status, headers, data

        with self.assertRaisesRegex(AssertionError, 'the approval is of 0{40}, not the head'):
            L.prepare_phase(self.live()._replace(http=http), {})
        self.assertFalse((self.run_dir / L.PRESENTATION).exists())

    def test_a_used_run_directory_is_refused_before_anything(self):
        (self.run_dir / 'left-over.txt').write_text('x', encoding='utf-8')
        with self.assertRaises(L.PhaseRefused) as caught:
            self.prepared()
        self.assertEqual(caught.exception.code, 'RUN_DIR_NOT_EMPTY')
        self.assertEqual(self.gitea.requests, [])


class SecurityFailureStops(Phases):
    """Any successful bot merge, or main moving, stops the exercise as a SECURITY FAILURE."""

    def test_a_successful_bot_merge_stops_the_exercise(self):
        self.gitea.protection['main']['merge_whitelist'].append(R.ROLES['builder']['user'])
        with self.assertRaises(L.SecurityFailure) as caught:
            self.prepared()
        self.assertTrue(str(caught.exception).startswith('SECURITY FAILURE: the builder bot\'s merge'))
        self.assertEqual(self.gitea.merge_count(), 1)
        last = self.gitea.requests[-1]
        self.assertEqual((last['method'], last['doer']), ('POST', R.ROLES['builder']['user']))
        self.assertTrue(last['path'].endswith('/merge'))
        self.assertFalse((self.run_dir / L.PRESENTATION).exists())
        self.assertFalse((self.run_dir / L.RECORDER_DIR).exists())
        self.assertNotIn(AR.OWNER_ENTRY, self.provider.reads)

    def test_a_merge_behind_a_refused_answer_stops_the_exercise(self):
        self.gitea.protection['main']['merge_whitelist'].append(R.ROLES['planner']['user'])
        self.gitea.on_merge = 'error-after'  # merged, then answered 500
        with self.assertRaises(L.SecurityFailure) as caught:
            self.prepared()
        self.assertIn('SECURITY FAILURE: after the bot controls main is at', str(caught.exception))
        self.assertFalse((self.run_dir / L.PRESENTATION).exists())
        self.assertNotIn(AR.OWNER_ENTRY, self.provider.reads)


class RecordRefusals(Phases):
    """Phase record refuses a statement that is not the Owner's authorization of a challenged operation
    before any Gitea call or credential read."""

    def test_each_statement_refusal(self):
        presentation, _ = self.prepared()
        before, reads = len(self.gitea.requests), len(self.provider.reads)
        cases = {
            'no file named': ('STATEMENT_MISSING', None),
            'a missing file': ('STATEMENT_MISSING', self.dir / 'absent.json'),
            'an empty file': ('STATEMENT_MISSING', self.statement_file('  \n', 'empty.json')),
            'not JSON': ('STATEMENT_INVALID', self.statement_file('yes, go ahead', 'text.json')),
            'model-authored': ('STATEMENT_MODEL_AUTHORED', self.statement_file(
                {**self.synthetic(*self.operations(presentation)), 'attributedTo': 'agent:overseer'}, 'model.json')),
            'not the Owner\'s': ('STATEMENT_NOT_OWNER', self.statement_file(
                {**self.synthetic(*self.operations(presentation)), 'attributedTo': 'person:someone'}, 'other.json')),
            'naming no challenged operation': ('STATEMENT_OPERATION_MISSING', self.statement_file(
                self.synthetic('live-other-a'), 'other-op.json')),
            'a vague yes': ('STATEMENT_OPERATION_MISSING', self.statement_file(su.statement(text='Yes.'), 'yes.json')),
        }
        for name, (code, path) in cases.items():
            with self.subTest(case=name), self.assertRaises(L.PhaseRefused) as caught:
                L.record_phase(self.live(), path, {})
            self.assertEqual(caught.exception.code, code)
        self.assertEqual(len(self.gitea.requests), before)
        self.assertEqual(len(self.provider.reads), reads)

    def test_a_missing_presentation_or_a_changed_verifier_is_refused(self):
        said = self.statement_file(self.synthetic('live-x'))
        with self.assertRaises(L.PhaseRefused) as caught:
            L.record_phase(self.live(), said, {})
        self.assertEqual(caught.exception.code, 'PRESENTATION_MISSING')
        for damaged in ('{"format": "other"}', '[]', '{'):
            with self.subTest(presentation=damaged), self.assertRaises(L.PhaseRefused) as caught:
                (self.run_dir / L.PRESENTATION).write_text(damaged, encoding='utf-8')
                L.record_phase(self.live(), said, {})
            self.assertEqual(caught.exception.code, 'PRESENTATION_INVALID')
        (self.run_dir / L.PRESENTATION).unlink()
        presentation, _ = self.prepared()
        said = self.statement_file(self.synthetic(*self.operations(presentation)))
        before = len(self.gitea.requests)
        with self.assertRaises(L.PhaseRefused) as caught:
            L.record_phase(self.live(su.FakeVerifier()), said, {})
        self.assertEqual(caught.exception.code, 'VERIFIER_CHANGED')
        self.assertIn('was not available, and one is available now', str(caught.exception))
        self.assertEqual(len(self.gitea.requests), before)
        # a presentation saying a verifier was available, recorded without one
        (self.run_dir / L.PRESENTATION).write_text(json.dumps({**presentation, 'verifier': {'available': True}}),
                                                   encoding='utf-8')
        with self.assertRaises(L.PhaseRefused) as caught:
            L.record_phase(self.live(), said, {})
        self.assertIn('was available, and one is not available now', str(caught.exception))


class Record(Phases):
    def test_without_a_verifier_every_record_is_refused_and_nothing_is_merged(self):
        presentation, _ = self.prepared()
        said = self.synthetic(*self.operations(presentation))
        path = self.statement_file(said)
        observed = L.record_phase(self.live(), path, {})
        for c in presentation['challenges']:
            self.assertEqual(observed['outcomes'][c['operation']],
                             {'code': 'PROTECTION_UNVERIFIED', 'refusal': True, 'receipt': None})
            self.assertEqual(self.gitea.pulls[c['pull']]['state'], 'closed')  # the cleanup
            self.assertFalse(self.gitea.pulls[c['pull']]['merged'])
        self.assertEqual(self.gitea.merge_count(), 0)
        self.assertEqual(self.gitea.branches['main'], presentation['mainHead'])
        self.assertEqual([r for r in self.gitea.requests_by('POST') if r['doer'] == AR.OWNER], [])
        self.assertEqual(json.loads(path.read_text(encoding='utf-8')), said)  # read, never rewritten

    def test_with_a_verifier_one_merge_and_the_stale_head_control(self):
        verifier = su.FakeVerifier()
        presentation, _ = self.prepared(verifier)
        authorize, stale = presentation['challenges']
        observed = L.record_phase(self.live(verifier), self.statement_file(
            self.synthetic(*self.operations(presentation))), {})
        merged = observed['outcomes'][authorize['operation']]
        self.assertEqual(merged['receipt']['state'], 'confirmed')
        self.assertEqual(self.gitea.branches['main'], merged['merge']['mergeCommit'])
        self.assertEqual(self.gitea.merge_count(), 1)
        refused = observed['outcomes'][stale['operation']]
        self.assertEqual((refused['code'], refused['moved'], refused['receipt'], refused['giteaStatus'],
                          refused['merged'], refused['mainMoved']), ('HEAD_STALE', [201], 'failed', 409, False, False))
        self.assertNotEqual(self.gitea.head(stale['pull']), stale['approvedHead'])
        # the stale-head control is sent first, so that A's merge does not leave it behind main
        self.assertEqual([b['head_commit_id'] for b in self.gitea.merge_bodies[-2:]],
                         [stale['approvedHead'], authorize['approvedHead']])
        self.assertEqual(observed['cleanup'], {stale['pull']: 201})
        self.assertEqual(self.gitea.pulls[stale['pull']]['state'], 'closed')

    def test_the_stale_head_control_records_the_refusal_it_observes(self):
        """Finding F14: after the push Gitea may answer 405 (try again later) or 500 (still checking) instead of
        409; the control's property is that nothing merges and main does not move."""
        for status, code, receipt in ((405, 'MERGE_REFUSED', 'failed'), (500, 'OUTCOME_UNKNOWN', 'unknown')):
            with self.subTest(status=status):
                self.setUp()
                verifier = su.FakeVerifier()
                presentation, _ = self.prepared(verifier)
                authorize, stale = presentation['challenges']
                self.gitea.fail_routes['/merge'] = status
                observed = L.record_phase(self.live(verifier), self.statement_file(
                    self.synthetic(stale['operation'])), {})
                refused = observed['outcomes'][stale['operation']]
                self.assertEqual((refused['code'], refused['receipt'], refused['giteaStatus'], refused['moved'],
                                  refused['merged'], refused['mainMoved']), (code, receipt, status, [201], False, False))
                self.assertEqual(self.gitea.merge_count(), 0)
                self.assertEqual(self.gitea.branches['main'], presentation['mainHead'])

    def test_a_refusal_other_than_the_protection_check_s_stops_the_phase(self):
        verifier = su.FakeVerifier()
        presentation, _ = self.prepared(verifier)
        authorize, stale = presentation['challenges']
        self.gitea.fail_routes['/merge'] = 405
        with self.assertRaises(AR.RecorderError) as caught:
            L.record_phase(self.live(verifier), self.statement_file(self.synthetic(authorize['operation'])), {})
        self.assertEqual(caught.exception.code, 'MERGE_REFUSED')
        self.assertEqual(self.gitea.merge_count(), 0)

    def test_a_stale_head_control_that_merges_is_a_security_failure(self):
        verifier = su.FakeVerifier()
        presentation, _ = self.prepared(verifier)
        authorize, stale = presentation['challenges']
        with mock.patch.object(L.AR, 'record', return_value={'merge': 'as if it had merged'}), \
                self.assertRaisesRegex(L.SecurityFailure, '^SECURITY FAILURE: the stale-head control merged'):
            L.record_phase(self.live(verifier), self.statement_file(self.synthetic(stale['operation'])), {})

    def test_a_stale_head_control_refused_by_the_protection_check_is_not_reached(self):
        verifier = su.FakeVerifier()
        presentation, _ = self.prepared(verifier)
        authorize, stale = presentation['challenges']
        verifier.default = su.UNVERIFIED
        observed = L.record_phase(self.live(verifier), self.statement_file(
            self.synthetic(*self.operations(presentation))), {})
        self.assertEqual({op: (o['code'], o.get('moved'), o['receipt']) for op, o in observed['outcomes'].items()},
                         {stale['operation']: ('PROTECTION_UNVERIFIED', [], None),
                          authorize['operation']: ('PROTECTION_UNVERIFIED', None, None)})
        self.assertEqual(self.gitea.merge_count(), 0)
        self.assertEqual(self.gitea.head(stale['pull']), stale['approvedHead'])

    def test_a_stale_head_control_that_cannot_move_the_head_sends_no_merge_and_stops(self):
        verifier = su.FakeVerifier()
        presentation, _ = self.prepared(verifier)
        authorize, stale = presentation['challenges']
        self.gitea.protection[stale['branch']] = {}  # the builder can no longer push to B's branch
        with self.assertRaisesRegex(AssertionError, 'the stale-head control'):
            L.record_phase(self.live(verifier), self.statement_file(self.synthetic(*self.operations(presentation))),
                           {})
        self.assertEqual(self.gitea.merge_count(), 0)  # B's merge was never sent; A was not reached
        self.assertEqual(self.gitea.head(stale['pull']), stale['approvedHead'])
        with su.IS.open_store(self.run_dir / L.RECORDER_DIR / 'integration.sqlite') as store:
            self.assertEqual(L._receipt(store, stale['nonce']), 'unknown')
            self.assertIsNone(L._receipt(store, authorize['nonce']))

    def test_a_merge_without_a_verifier_is_a_security_failure(self):
        presentation, _ = self.prepared()
        path = self.statement_file(self.synthetic(*self.operations(presentation)))
        with mock.patch.object(L.AR, 'record', return_value={'merge': 'as if it had merged'}), \
                self.assertRaisesRegex(L.SecurityFailure, '^SECURITY FAILURE: the recorder merged live-'):
            L.record_phase(self.live(), path, {})

    def test_only_the_named_operations_are_recorded(self):
        verifier = su.FakeVerifier()
        presentation, _ = self.prepared(verifier)
        authorize, stale = presentation['challenges']
        observed = L.record_phase(self.live(verifier), self.statement_file(self.synthetic(authorize['operation'])), {})
        self.assertEqual(observed['authorized'], [authorize['operation']])
        self.assertEqual(observed['outcomes'][stale['operation']]['code'], None)
        self.assertEqual(self.gitea.head(stale['pull']), stale['approvedHead'])
        self.assertEqual(self.gitea.merge_count(), 1)
        self.assertEqual(self.gitea.pulls[stale['pull']]['state'], 'closed')


class ProtectionCheckEndToEnd(Phases):
    """The command line's protection check (Owner decision OA-16) in the exercise, against the fake's protection
    auditor (fake_gitea.FakeGitea.audit): it reads the auditor's entry, verifies, and the merge happens; with
    drift the record is refused and nothing is merged."""

    def check(self):
        return AR.protection_verifier(self.provider, self.port, http=self.http)

    def test_verified_one_merge_and_the_stale_head_control(self):
        verifier = self.check()
        presentation, _ = self.prepared(verifier)
        authorize, stale = presentation['challenges']
        self.assertEqual({c['protectionAtPrepare']['verdict'] for c in presentation['challenges']}, {'verified'})
        observed = L.record_phase(self.live(verifier), self.statement_file(
            self.synthetic(*self.operations(presentation))), {})
        merged = observed['outcomes'][authorize['operation']]
        self.assertEqual((merged['receipt']['state'], merged['protection']['equal']), ('confirmed', True))
        self.assertEqual(merged['protection']['before']['verdict'], 'verified')
        self.assertEqual(observed['outcomes'][stale['operation']]['code'], 'HEAD_STALE')
        self.assertEqual(self.gitea.merge_count(), 1)
        audit = self.gitea.audit.requests
        self.assertTrue(audit)
        self.assertEqual({(r['method'], r['auth'], r['doer']) for r in audit if not r['path'].endswith('/merge')},
                         {('GET', 'token', fg.AUDITOR)})
        merges = [r for r in self.gitea.requests if r['method'] == 'POST' and r['path'].endswith('/merge')
                  and r['doer'] == AR.OWNER]
        self.assertEqual({r['auth'] for r in merges}, {'basic'})

    def test_drift_refuses_the_record_and_nothing_is_merged(self):
        verifier = self.check()
        presentation, _ = self.prepared(verifier)
        self.gitea.audit.rule('main')['block_admin_merge_override'] = False
        observed = L.record_phase(self.live(verifier), self.statement_file(
            self.synthetic(*self.operations(presentation))), {})
        for c in presentation['challenges']:
            outcome = observed['outcomes'][c['operation']]
            self.assertEqual((outcome['code'], outcome['receipt']), ('PROTECTION_DRIFT', None))
            self.assertIn('main.block_admin_merge_override', outcome['detail'])
        self.assertEqual(self.gitea.merge_count(), 0)
        self.assertEqual(self.gitea.branches['main'], presentation['mainHead'])


if __name__ == '__main__':
    unittest.main()
