"""The acceptance recorder's owner-ui channel (plan leaf P-04.4; decision 0025 point 9; the I1 integration design, R6).

Channel ``owner-ui`` is admitted only with a session-binding verifier passed to ``record`` in process (the Integration
process's, integrations/ownerhost/acceptance.py): without one it is ``SESSION_BINDING_REQUIRED``, so the command line
cannot declare it, and ``record_from_log`` refuses it too; a verifier that answers a reason is
``SESSION_BINDING_REFUSED``; a verifier is for that channel only. Each refusal leaves the branch, the work tree and the
index as they were. Every statement here is SYNTHETIC: it stands in for an Owner statement and is no Owner decision.
"""
import datetime
import io
import json
import sys
import unittest
from pathlib import Path

CATEGORY = 'integration'

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import owner_fixture as of  # noqa: E402
import test_acceptance_recorder as TAR  # noqa: E402  (its Fixture only: no test class is bound here)

A, R, L = of.A, of.A.R, of.A.L
NOW = of.NOW
LATER = NOW + datetime.timedelta(minutes=5)
PROPOSED = of.PROPOSED
OWNER_UI_REF = 'conversation:0f1e2d3c-4b5a-4968-8776-655443322110/Msg0002#sha256:' + 'ab' * 32


def owner_ui(**changes):
    return of.statement(**{'channel': 'owner-ui', 'reference': OWNER_UI_REF, **changes})


class OwnerUiChannel(TAR.Fixture):
    def bound(self, calls=None):
        def verify(statement, challenge):
            if calls is not None:
                calls.append((statement, challenge))
            return None
        return verify

    def test_owner_ui_without_a_session_binding_is_refused(self):
        challenge = self.prepare()
        error = self.refused('SESSION_BINDING_REQUIRED', self.record, challenge, owner_ui(), recorded_by='owner')
        self.assertIn('owner-ui', error.detail)

    def test_a_refusing_binding_is_refused_with_its_reason(self):
        challenge = self.prepare()
        error = self.refused('SESSION_BINDING_REFUSED', self.record, challenge, owner_ui(), recorded_by='owner',
                             session_binding=lambda statement, chall: 'not this session')
        self.assertEqual(error.detail, 'not this session')

    def test_a_bound_statement_is_recorded_and_resolves(self):
        challenge = self.prepare()
        calls = []
        result = self.record(challenge, owner_ui(), recorded_by='owner', session_binding=self.bound(calls))
        self.assertEqual(calls, [(owner_ui(), challenge)])
        self.assertTrue(result['minted'])
        self.assertEqual((result['decision']['statement']['channel'], result['decision']['recordedBy']),
                         ('owner-ui', 'owner'))
        self.assertEqual(result['decision']['statement']['reference'], OWNER_UI_REF)
        answer = self.resolve(result['reference'])
        self.assertTrue(answer.resolved)
        self.assertEqual(answer.facts['acceptance'], OWNER_UI_REF)

    def test_a_binding_is_for_the_owner_ui_channel_only(self):
        challenge = self.prepare()
        with self.unchanged(), self.assertRaises(ValueError):
            self.record(challenge, of.statement(), session_binding=self.bound())

    def test_the_owner_s_checks_come_first_and_the_binding_is_not_asked(self):
        challenge = self.prepare()
        calls = []
        self.refused('ACCEPTANCE_MODEL_AUTHORED', self.record, challenge, owner_ui(attributedTo='agent:x'),
                     recorded_by='owner', session_binding=self.bound(calls))
        self.refused('STATEMENT_NOT_OWNER', self.record, challenge, owner_ui(attributedTo='person:x'),
                     recorded_by='owner', session_binding=self.bound(calls))
        self.assertEqual(calls, [])

    def test_the_challenge_checks_still_apply_to_a_bound_statement(self):
        challenge = self.prepare()
        self.refused('CHALLENGE_EXPIRED', self.record, challenge, owner_ui(), recorded_by='owner',
                     session_binding=self.bound(), now=NOW + datetime.timedelta(hours=2))

    def test_record_from_log_refuses_owner_ui(self):
        statement = owner_ui(reference='harness:evidence/bootstrap-log.md#owner-direction-x')
        self.refused('SESSION_BINDING_REQUIRED', A.record_from_log, self.repo, PROPOSED, 'O1', statement,
                     recorded_by='owner', identity=of.IDENTITY, harness=self.root / 'no-harness-is-read')


class OwnerUiFromTheCommandLine(TAR.Fixture):
    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        code = A.main(list(argv), out=out, err=err)
        return code, out.getvalue(), err.getvalue()

    def test_owner_ui_from_the_command_line_is_session_binding_required(self):
        challenge = self.root / 'challenge.json'
        self.run_main('prepare', '--project', str(self.repo), '--change', PROPOSED, '--item', 'O1',
                      '--out', str(challenge))
        statement = self.root / 'statement.json'
        statement.write_text(json.dumps(owner_ui()), encoding='utf-8')
        for argv in (('record', '--project', str(self.repo), '--challenge', str(challenge)),
                     ('record-from-log', '--project', str(self.repo), '--change', PROPOSED, '--item', 'O1')):
            with self.subTest(command=argv[0]), self.unchanged():
                code, out, err = self.run_main(*argv, '--statement', str(statement), '--recorded-by', 'owner',
                                               '--identity', of.IDENTITY)
                self.assertEqual((code, out), (2, ''))
                self.assertTrue(err.startswith('acceptance-recorder: SESSION_BINDING_REQUIRED: '), err)
                self.assertIn(f'Remedy: {A.REMEDIES["SESSION_BINDING_REQUIRED"]}', err)


if __name__ == '__main__':
    unittest.main()
