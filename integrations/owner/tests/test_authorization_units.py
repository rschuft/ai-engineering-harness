"""The Owner authorization recorder's parts (plan leaf P-04.2), in the test process only.

Run from the repository root, under the tools interpreter:

    <tools python> -I -B -m unittest discover -s integrations/owner/tests -v

The fake Gitea (fake_gitea.FakeGitea) is called in memory here, with gitea_host.http_get's signature: no
socket is opened. These tests cover the shared record's ``authorize-operation`` subject, the trailers and
the merge message, the policy comparison, the session's fixed calls, the credential checks that refuse
before anything is sent, the codes and remedies, that a fixture context never reaches the managed data
root or the platform's credential store, and the command line. Every statement is synthetic.
"""
import contextlib
import io
import json
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

CATEGORY = 'unit'

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import authz_support as su  # noqa: E402

AR, D, fg = su.AR, su.D, su.fg
SUBJECT = {'repository': fg.REPOSITORY, 'pull': 3, 'base': 'main', 'head': 'a' * 40,
           'manifest': 'operations/op-0001.json', 'digest': 'sha256:' + 'b' * 64, 'operation': 'op-0001',
           'operationKind': 'example-effect', 'target': 'example-target', 'expiresAt': su.EXPIRES}


def decision(**subject):
    return {'format': D.FORMAT, 'decisionId': '1f0e2d3c-4b5a-4968-8776-0123456789ab', 'kind': AR.KIND,
            'subject': {**SUBJECT, **subject},
            'shown': {'summary': 'shown', 'nonce': 'ab' * 16, 'expiresAt': su.EXPIRES},
            'statement': su.statement(), 'recordedBy': su.RECORDED_BY, 'recordedAt': '2026-11-10T12:05:00Z'}


class InMemory(su.Fixture):
    def gitea_for_test(self):
        gitea = fg.FakeGitea()
        return gitea, 3000, gitea


class Record(unittest.TestCase):
    """The shared Owner decision record's authorize-operation subject (owner_decision.py)."""

    def test_an_authorize_operation_record_has_the_shared_shape(self):
        self.assertEqual(D.check_record(decision()), [])

    def test_each_subject_problem(self):
        cases = {
            'repository': decision(repository='no-slash'),
            'pull': decision(pull=True),
            'pull number': decision(pull=0),
            'base': decision(base='../main'),
            'head': decision(head='HEAD'),
            'operation': decision(operation='Op_1'),
            'manifest': decision(manifest='operations/other.json'),
            'digest': decision(digest='b' * 64),
            'operationKind': decision(operationKind='Kind'),
            'target': decision(target='two\nlines'),
            'expiresAt': decision(expiresAt='tomorrow'),
        }
        for name, record in cases.items():
            with self.subTest(name=name):
                self.assertNotEqual(D.check_record(record), [])
        missing = decision()
        del missing['subject']['target']
        self.assertTrue(any('subject must have exactly' in p for p in D.check_record(missing)))


class Message(unittest.TestCase):
    def test_trailers_round_trip_through_the_message(self):
        record = decision()
        values = AR.trailers(record, SUBJECT['head'], SUBJECT['digest'])
        self.assertEqual(tuple(values), AR.TRAILERS)
        title, body = AR.merge_message(record, values)
        self.assertEqual(AR.parse_trailers(title + '\n\n' + body.strip() + '\n'), values)
        self.assertIn(f'Merged under Owner authority by the recorder on decision {record["decisionId"]}.', body)
        self.assertNotIn('merged by the owner', (title + body).lower())

    def test_parse_trailers_reads_the_last_paragraph_only(self):
        self.assertEqual(AR.parse_trailers('t\n\nAIEH-Recorder: x\n\nbody'), {})
        self.assertEqual(AR.parse_trailers('t\r\n\r\nAIEH-Recorder: x\r\n'), {'AIEH-Recorder': 'x'})
        self.assertEqual(AR.parse_trailers('t\n\nAIEH-Recorder: x\nAIEH-Recorder: y\n'), {'AIEH-Recorder': None})


class PolicyComparison(unittest.TestCase):
    def test_the_fixture_policy_and_its_drift(self):
        policy = AR.admitted_policies()[fg.REPOSITORY]
        self.assertEqual(policy.base, 'main')
        repo = {**policy.repository, 'permissions': {'admin': False, 'push': True, 'pull': True, 'extra': 1}}
        self.assertEqual(AR.policy_drift(policy, repo, dict(policy.branch)), [])
        self.assertEqual(AR.policy_drift(policy, repo, {**policy.branch, 'status_check_contexts': None}), [])
        self.assertNotEqual(AR.policy_drift(policy, repo, {**policy.branch, 'status_check_contexts': ['ci']}), [])
        drift = AR.policy_drift(policy, {**repo, 'allow_merge_commits': False}, {**policy.branch, 'protected': False})
        self.assertEqual([f for f, _, _ in drift], ['repository.allow_merge_commits', 'branch.protected'])
        self.assertIn('block_admin_merge_override', policy.unobservable)

    def test_the_expected_policy_is_the_fixture_s_declared_protection(self):
        rule = next(r for r in AR.roles.protection_rules() if r['rule_name'] == 'main')
        policy = AR.admitted_policies()[f'{AR.roles.FIXTURE_ORG}/{AR.roles.FIXTURE_REPO}']
        self.assertEqual(policy.branch['required_approvals'], rule['required_approvals'])
        self.assertEqual(rule['merge_whitelist_usernames'], [AR.OWNER])
        self.assertIs(rule['enable_push'], False)


class Session(InMemory):
    def test_the_session_makes_only_its_fixed_calls(self):
        session = AR.open_session(self.ctx)
        for path in ('/admin/users', '/users/aieh-owner/tokens/1', '/repos/a/b/branch_protections',
                     '/user?sudo=aieh-owner', f'/repos/{fg.REPOSITORY}/raw/README.md?ref={"a" * 40}'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                session.get(path)
        with self.assertRaises(ValueError):
            session.merge(f'/repos/{fg.REPOSITORY}/pulls/1/merge', {'Do': 'merge'})
        merging = AR.Gitea(self.ctx, fg.PASSWORD, may_merge=True)
        body = dict(zip(AR.MERGE_BODY_KEYS, ('merge', 't', 'm', 'a' * 40, False)))
        for bad in ({**body, 'force_merge': True}, {**body, 'Do': 'squash'}, {**body, 'delete_branch_after_merge': True},
                    {k: v for k, v in body.items() if k != 'head_commit_id'}):
            with self.subTest(body=bad), self.assertRaises(ValueError):
                merging.merge(f'/repos/{fg.REPOSITORY}/pulls/1/merge', bad)
        with self.assertRaises(ValueError):
            merging.merge('/users/aieh-owner/tokens', body)
        session.close()
        with self.assertRaises(ValueError):
            session.get('/user')
        self.assertEqual({r['method'] for r in self.gitea.requests}, {'GET'})

    def test_the_credential_is_read_by_name_and_held_only_by_the_session(self):
        session = AR.open_session(self.ctx)
        self.assertEqual(self.provider.reads, [AR.OWNER_ENTRY])
        self.assertEqual(AR.OWNER_ENTRY, 'AIEH Gitea owner')
        session.close()
        self.assertIsNone(session._password)


class CredentialInput(InMemory):
    """Every bot token and every foreign entry is refused before anything is sent."""

    def test_refused_inputs_send_nothing(self):
        cases = {'missing': None, 'empty': (fg.OWNER, ''), 'site admin': ('aieh-site-admin', 'x'),
                 **{f'{bot} and its token': (bot, token) for bot, token in fg.BOT_TOKENS.items()},
                 **{f'aieh-owner with the token of {bot}': (fg.OWNER, token) for bot, token in fg.BOT_TOKENS.items()},
                 'aieh-owner with an upper-case token': (fg.OWNER, 'A' * 40)}
        for name, entry in cases.items():
            with self.subTest(entry=name):
                self.provider.entries = {} if entry is None else {AR.OWNER_ENTRY: entry}
                code = 'CREDENTIAL_MISSING' if entry is None else 'CREDENTIAL_REFUSED'
                self.assertRefused(code, AR.open_session, self.ctx)
        self.assertEqual(self.gitea.requests, [])


class Codes(unittest.TestCase):
    SOURCE = (su.OWNER_DIR / 'authorization_recorder.py').read_text(encoding='utf-8')

    def test_every_code_has_a_remedy_and_every_remedy_a_code(self):
        raised = set(re.findall(r"RecorderError\(\s*'([A-Z_]+)'", self.SOURCE))
        raised |= set(re.findall(r"code = '([A-Z_]+)' if", self.SOURCE))
        raised |= set(re.findall(r"else '([A-Z_]+)'", self.SOURCE))
        raised |= set(re.findall(r"D\.[A-Z_]+: '([A-Z_]+)'", self.SOURCE))
        raised |= {'POLICY_DRIFT'}
        self.assertEqual(raised - set(AR.REMEDIES), set())
        self.assertEqual(set(AR.REMEDIES) - raised, set())

    def test_the_recorder_never_names_a_token_route_sudo_or_a_forced_merge(self):
        self.assertNotIn("'force_merge'", self.SOURCE)
        self.assertNotIn('merge_when_checks_succeed', self.SOURCE.split('MERGE_BODY_KEYS = ')[1])
        self.assertNotIn("'Sudo'", self.SOURCE)
        self.assertNotIn('generate-access-token', self.SOURCE)
        self.assertNotIn("'POST', '/users", self.SOURCE)


class ManagedRootNeverReached(InMemory):
    """A fixture context never reaches the managed data root, its integration store or the platform's
    credential store; a context without its own store or state is refused."""

    def test_a_fixture_context_never_reaches_the_managed_store(self):
        forbid = AssertionError('the managed data root or the platform credential store')
        with mock.patch.object(AR.host.paths, 'resolve', side_effect=forbid), \
                mock.patch.object(AR.host, 'credential_receipts', side_effect=forbid), \
                mock.patch.object(AR.host, 'credential_provider', side_effect=forbid), \
                mock.patch.object(AR, 'managed_context', side_effect=forbid):
            number = self.propose()
            challenge = self.prepare(number)
            result = self.record(challenge['shown']['nonce'])
            AR.resolve(self.ctx, challenge['shown']['nonce'])
            for missing in ({'store': None}, {'state_dir': None}, {'provider': None}, {'port': None}):
                with self.subTest(missing=missing), self.assertRaises(ValueError):
                    AR.prepare(self.context(**missing), fg.REPOSITORY, number)
        self.assertEqual(result['receipt']['state'], 'confirmed')
        self.assertTrue(self.store.path.is_relative_to(self.root))


class CommandLine(InMemory):
    def main(self, *argv):
        out, err = io.StringIO(), io.StringIO()

        @contextlib.contextmanager
        def context(port, guard):
            self.assertIsNone(port)
            yield self.context(provider=AR.contract.WatchedProvider(self.provider, guard))

        code = AR.main(list(argv), out=out, err=err, context=context)
        return code, out.getvalue(), err.getvalue()

    def test_prepare_record_and_resolve(self):
        number = self.propose()
        code, out, err = self.main('prepare', fg.REPOSITORY, str(number))
        self.assertEqual((code, err), (0, ''))
        nonce = json.loads(out)['shown']['nonce']
        said = self.dir / 'statement.json'
        said.write_text(json.dumps(su.statement()), encoding='utf-8')
        code, out, err = self.main('record', '--challenge', nonce, '--statement', str(said),
                                   '--recorded-by', su.RECORDED_BY)
        self.assertEqual((code, err), (0, ''))
        self.assertEqual(json.loads(out)['receipt']['state'], 'confirmed')
        code, out, err = self.main('resolve', '--challenge', nonce)
        self.assertEqual((code, json.loads(out)['changed']), (0, False))
        self.secrets_absent(out, err)

    def test_refusals_and_unknown_outcomes_exit_with_their_codes(self):
        code, out, err = self.main('record', '--recorded-by', su.RECORDED_BY)
        self.assertEqual((code, out), (2, ''))
        self.assertIn('CHALLENGE_MISSING', err)
        self.assertIn('Remedy:', err)
        number = self.propose()
        nonce = json.loads(self.main('prepare', fg.REPOSITORY, str(number))[1])['shown']['nonce']
        said = self.dir / 'statement.json'
        said.write_text(json.dumps(su.statement()), encoding='utf-8')
        self.gitea.on_merge = 'drop-before'
        code, out, err = self.main('record', '--challenge', nonce, '--statement', str(said),
                                   '--recorded-by', su.RECORDED_BY)
        self.assertEqual(code, 1)
        self.assertIn('OUTCOME_UNKNOWN', err)
        code, out, err = self.main('record', '--challenge', nonce, '--statement', str(self.dir / 'absent.json'),
                                   '--recorded-by', su.RECORDED_BY)
        self.assertEqual(code, 2)
        self.secrets_absent(out, err)

    def test_an_exposed_secret_fails_the_command(self):
        number = self.propose()
        self.gitea.pulls[number]['title'] = f'title holding {fg.PASSWORD}'
        code, out, err = self.main('prepare', fg.REPOSITORY, str(number))
        self.assertEqual((code, out), (1, ''))
        self.assertIn('EXPOSURE_FOUND', err)
        self.assertNotIn(fg.PASSWORD, err)


if __name__ == '__main__':
    unittest.main()
