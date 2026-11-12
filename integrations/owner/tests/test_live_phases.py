"""The live authorization exercise's two phases (test_live_authorization.py; Owner decision OA-14), offline.

Run from the repository root, under the tools interpreter:

    <tools python> -I -B -m unittest discover -s integrations/owner/tests -v

The phase functions run against the in-memory fake Gitea (fake_gitea.FakeGitea, gitea_host.http_get's
signature: no socket) with a fixture credential provider holding the fake aieh-owner's password and the
fake bots' tokens; the run directory is a fixture directory; the custody inspection is not run. Covered:
prepare's precondition before any write (the protection baseline variable absent or malformed, refused
before anything is read; the protection verifier answering anything but verified with exactly the
baseline digest; every role's identity and scopes by GET /token, each mismatch, 401 or unreadable answer;
an open pull request or an existing branch name; each refused with zero Gitea writes); the protection
auditor's control (only the merge of a nonexistent pull request confirmed absent first, passing only on
403 with the scope refusal; never addressing A or B); the stopping rule after every single control
attempt (a 2xx, main moving or a proposal merged: SECURITY FAILURE with no later control sent); the
presentation's content; phase record refusing a statement that is missing, empty, not JSON,
model-authored, not the Owner's or naming none of the challenged operations, before any Gitea call or
credential read; the expected outcome without a protection verifier (PROTECTION_UNVERIFIED, nothing
merged); with a fake verified verifier, one merge and the stale-head control refused with nothing merged
and main unmoved, its refusal recorded as observed (409, or 405 or 500: finding F14); the command line's
protection check (Owner decision OA-16) end to end against the fake's protection auditor, verified and
drifted; and the SECURITY FAILURE stop when a fake bot merge, or the stale-head control's, succeeds. Every
statement here is SYNTHETIC and no Owner decision: it stands in, in a fixture, for the Owner's reply the
live phase reads from a file.
"""
import ast
import hashlib
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
import test_live_authorization as L  # noqa: E402

AR, fg, R = su.AR, su.fg, su.AR.roles
BASELINE = su.VERIFIED.digest  # the fake verifier's verified digest
STAMP = su.NOW.strftime('%Y%m%dt%H%M%Sz')
BOTS = [role for role in R.ROLES if role != L.AUDITOR_ROLE]  # the four bots, in gitea_roles' order
ACT_C = HERE.parents[1] / 'gitea' / 'tests' / 'test_protection_audit_live.py'


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

    def live(self, verifier=None, baseline=BASELINE, http=None):
        return L.Live(self.port, self.provider, self.run_dir, http=http or self.http, now=lambda: self.now,
                      verifier=verifier, verifier_note='fake verifier' if verifier else AR.NO_VERIFIER,
                      baseline=baseline)

    def prepared(self, verifier='fake', baseline=BASELINE, http=None):
        """Phase prepare with VERIFIER (by default a fake one answering verified with BASELINE)."""
        observed = {}
        verifier = su.FakeVerifier() if verifier == 'fake' else verifier
        return L.prepare_phase(self.live(verifier, baseline, http), observed), observed

    def without_verifier(self, presentation):
        """The saved presentation, rewritten as if no protection verifier had been available at prepare (prepare
        now refuses without one; phase record's fail-closed path without a verifier stays tested)."""
        presentation = {**presentation, 'verifier': {'available': False, 'note': AR.NO_VERIFIER}}
        (self.run_dir / L.PRESENTATION).write_text(json.dumps(presentation), encoding='utf-8')
        return presentation

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

    def writes(self):
        """Every request to the fake Gitea but a GET (the auditor's included: the fake logs them first)."""
        return [r for r in self.gitea.requests if r['method'] != 'GET']

    def merges(self):
        return [r for r in self.gitea.requests if r['method'] == 'POST' and r['path'].endswith('/merge')]

    def scripted(self, rule):
        """An http callable over the fake Gitea: RULE(method, path, headers, answer) may return another answer
        (the fake has handled and logged the request first)."""
        def http(port, path, *, method='GET', body=None, headers=None, timeout=5.0):
            answer = self.gitea(port, path, method=method, body=body, headers=headers, timeout=timeout)
            return rule(method, path, headers or {}, answer) or answer
        return http

    def assertNothingPrepared(self):
        self.assertFalse((self.run_dir / L.PRESENTATION).exists())
        self.assertFalse((self.run_dir / L.RECORDER_DIR).exists())
        self.assertNotIn(AR.OWNER_ENTRY, self.provider.reads)

    def assertRefusedBeforeAnyWrite(self, code, **kw):
        observed = {}
        with self.assertRaises(L.PhaseRefused) as caught:
            L.prepare_phase(self.live(**kw), observed)
        self.assertEqual(caught.exception.code, code, str(caught.exception))
        self.assertEqual(self.writes(), [])
        self.assertNothingPrepared()
        self.assertLessEqual(set(self.provider.reads), {R.target(role) for role in R.ROLES})
        return observed, caught.exception


def _auditor(headers):
    return headers.get('Authorization') == 'token ' + fg.BOT_TOKENS[fg.AUDITOR]


def _absent_pull(path):
    match = re.search(r'/pulls/([0-9]+)(/merge)?$', path)
    return match is not None and int(match.group(1)) > L.ABSENT_PULL_OFFSET


class Prepare(Phases):
    def test_the_presentation(self):
        presentation, observed = self.prepared()
        saved = json.loads((self.run_dir / L.PRESENTATION).read_text(encoding='utf-8'))
        self.assertEqual(saved, presentation)
        self.assertEqual(presentation['format'], L.PRESENTATION_FORMAT)
        self.assertEqual(presentation['verifier'], {'available': True, 'note': 'fake verifier'})
        self.assertEqual([c['role'] for c in presentation['challenges']], [L.AUTHORIZE, L.STALE])
        authorize, stale = presentation['challenges']
        self.assertEqual(presentation['staleHeadControl'], stale['pull'])
        self.assertEqual(presentation['labels'], {
            'A': {'role': L.AUTHORIZE, 'pull': authorize['pull'], 'operation': authorize['operation']},
            'B': {'role': L.STALE, 'pull': stale['pull'], 'operation': stale['operation']}})
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
                self.assertEqual((c['protectionAtPrepare']['verdict'], c['protectionAtPrepare']['digest']),
                                 ('verified', BASELINE))
                self.assertTrue(any('merge commit on main' in e for e in c['effects']))
                self.assertTrue(any(c['manifestDigest'] in e for e in c['effects']))
                self.assertEqual(self.gitea.pulls[c['pull']]['reviews'], [(R.ROLES['reviewer']['user'], 'APPROVED',
                                                                           c['approvedHead'])])
        self.assertIn('one merge commit', authorize['expectedOutcome'])
        self.assertIn('nothing is merged and main does not move', stale['expectedOutcome'])
        self.assertTrue(any('409 expected' in e and 'F14' in e for e in stale['effects']))
        # the bot controls: each of the four bots on each proposal, refused; nothing merged
        self.assertEqual(presentation['botMerges']['statuses'],
                         {f'{role} on #{c["pull"]}': 405 for c in presentation['challenges'] for role in BOTS})
        self.assertEqual(self.gitea.merge_count(), 0)
        self.assertEqual({r['doer'] for r in self.merges()}, {spec['user'] for spec in R.ROLES.values()})
        # the stopping rule's reads after each of the nine control attempts: nothing moved
        self.assertEqual([(c['mainHead'], c['merged']) for c in observed['controlChecks']],
                         [(presentation['mainHead'], [])] * (2 * len(BOTS) + 1))
        text = (self.run_dir / L.PRESENTATION_TEXT).read_text(encoding='utf-8')
        for c in presentation['challenges']:
            for value in (c['operation'], c['nonce'], c['manifestDigest'], c['approvedHead'], c['challengeExpiresAt']):
                self.assertIn(value, text)
        self.assertIn(f'== A: pull request #{authorize["pull"]}, to authorize', text)
        self.assertIn(f'== B: pull request #{stale["pull"]}, THE STALE-HEAD CONTROL (expected: refused; nothing '
                      'merges and main does not move)', text)
        self.assertIn('Protection verifier: available', text)
        self.assertIn(f'Bot merge controls on A and B (each must be refused; main and both proposals read after '
                      f'each): {presentation["botMerges"]["statuses"]}.', text)
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
        """The precondition's answer verified with the baseline; the recorder's own prepare then gets drift."""
        verifier = su.FakeVerifier(su.VERIFIED, default=su.DRIFT)
        presentation, _ = self.prepared(verifier)
        for c in presentation['challenges']:
            self.assertTrue(c['expectedOutcome'].startswith('refused PROTECTION_DRIFT before anything is sent'),
                            c['expectedOutcome'])
        self.assertEqual(verifier.phases(), ['prepare'] * 3)

    def test_the_available_verifier_is_the_command_line_s_protection_check(self):
        verifier, note = L.available_verifier(self.port, self.provider)
        self.assertEqual(verifier.__qualname__, 'protection_verifier.<locals>.verifier')
        self.assertIn('OA-16', note)
        self.assertIn(AR.protection.AUDITOR, note)

    def test_an_approval_of_another_commit_fails_the_phase(self):
        def review(method, path, headers, answer):
            if path.endswith('/reviews'):
                status, sent, data = answer
                return status, sent, json.dumps({**json.loads(data), 'commit_id': '0' * 40}).encode()
            return None

        with self.assertRaisesRegex(AssertionError, 'the approval is of 0{40}, not the head'):
            self.prepared(http=self.scripted(review))
        self.assertFalse((self.run_dir / L.PRESENTATION).exists())

    def test_a_used_run_directory_is_refused_before_anything(self):
        (self.run_dir / 'left-over.txt').write_text('x', encoding='utf-8')
        with self.assertRaises(L.PhaseRefused) as caught:
            self.prepared()
        self.assertEqual(caught.exception.code, 'RUN_DIR_NOT_EMPTY')
        self.assertEqual(self.gitea.requests, [])


class Precondition(Phases):
    """Before any write: the protection baseline, every role's identity and scopes, and the repository's state;
    each failure refuses the phase with zero Gitea writes and no Owner or site administrator credential read."""

    def test_the_baseline_variable_is_required_before_anything_is_read(self):
        cases = {None: 'BASELINE_MISSING', '': 'BASELINE_MISSING', 'sha256:' + 'C' * 64: 'BASELINE_INVALID',
                 'sha256:' + 'c' * 63: 'BASELINE_INVALID', 'sha256:' + 'c' * 65: 'BASELINE_INVALID',
                 'sha1:' + 'c' * 64: 'BASELINE_INVALID', ' ' + BASELINE: 'BASELINE_INVALID',
                 BASELINE + '\n': 'BASELINE_INVALID', 'c' * 64: 'BASELINE_INVALID', 7: 'BASELINE_INVALID'}
        verifier = su.FakeVerifier()
        for baseline, code in cases.items():
            with self.subTest(baseline=baseline):
                self.assertRefusedBeforeAnyWrite(code, verifier=verifier, baseline=baseline)
                self.assertEqual(self.gitea.requests, [])
                self.assertEqual(self.provider.reads, [])
                self.assertEqual(verifier.calls, [])
        self.assertEqual(L.BASELINE_VARIABLE, 'AIEH_AUTHZ_RECORDER_PROTECTION_BASELINE')

    def test_the_protection_check_must_answer_verified_with_the_baseline(self):
        other = 'sha256:' + 'e' * 64
        cases = {
            'no verifier': (None, 'PROTECTION_UNVERIFIED'),
            'drift': (su.FakeVerifier(default=su.DRIFT), 'PROTECTION_DRIFT'),
            'unverified': (su.FakeVerifier(default=su.UNVERIFIED), 'PROTECTION_UNVERIFIED'),
            'verified with another digest': (su.FakeVerifier(default=AR.ProtectionVerdict('verified', 'x', other)),
                                             'PROTECTION_BASELINE_DIFFERS'),
            'verified with no digest': (su.FakeVerifier(default=AR.ProtectionVerdict('verified', 'x')),
                                        'PROTECTION_BASELINE_DIFFERS'),
            'drift with the baseline digest': (su.FakeVerifier(default=AR.ProtectionVerdict('drift', 'x', BASELINE)),
                                               'PROTECTION_DRIFT'),
            'raising': (su.FakeVerifier(RuntimeError('boom')), 'PROTECTION_UNVERIFIED'),
            'malformed': (su.FakeVerifier(default=('verified', 'x', BASELINE)), 'PROTECTION_UNVERIFIED'),
        }
        for name, (verifier, code) in cases.items():
            with self.subTest(case=name):
                observed, refused = self.assertRefusedBeforeAnyWrite(code, verifier=verifier)
                self.assertEqual(self.gitea.requests, [])
                self.assertEqual(self.provider.reads, [])
                if verifier is not None:
                    self.assertEqual(verifier.calls, [(fg.REPOSITORY, 'main', 'prepare')])
                    self.assertEqual(observed['precondition']['protection']['expected'], BASELINE)

    def test_each_identity_or_scope_mismatch_is_refused(self):
        auditor_view = self.gitea.audit.tokens[fg.protection_fake.AUDIT_TOKEN]

        scripted = {  # answers of GET /token given instead of the fake's
            'not an object': lambda user, scopes: (200, ['a list']),
            'scopes not a list': lambda user, scopes: (200, {'user': {'login': user}, 'scopes': ','.join(scopes)}),
            'no login': lambda user, scopes: (200, {'user': {}, 'scopes': scopes}),
            'not 200': lambda user, scopes: (203, {'user': {'login': user}, 'scopes': scopes}),
        }

        def damage(role, how):
            """Damage ROLE's identity HOW; returns the http callable to use, or None."""
            user = R.ROLES[role]['user']
            view = auditor_view if role == L.AUDITOR_ROLE else self.gitea.token_views[user]
            other = 'write:repository' if R.ROLES[role]['scopes'] == ('read:repository',) else 'read:repository'
            if how == 'login':
                view['login'] = 'aieh-bot-other'
            elif how == 'scopes':
                view['scopes'] = [other]
            elif how == 'extra scope':
                view['scopes'] = [*view['scopes'], 'write:issue']
            elif how in scripted:
                status, payload = scripted[how](user, list(R.ROLES[role]['scopes']))

                def unreadable(method, path, headers, answer):
                    if path == '/api/v1/token' and headers.get('Authorization') == 'token ' + fg.BOT_TOKENS[user]:
                        return status, {'content-type': 'application/json'}, json.dumps(payload).encode()
                    return None
                return self.scripted(unreadable)
            elif how == '401':
                self.provider.entries[R.target(role)] = (user, 'f' * 40)
            elif how == '500':
                if role == L.AUDITOR_ROLE:
                    self.gitea.audit.faults['token'] = 500
                else:
                    self.gitea.token_views[user] = 500
            elif how == 'entry':
                self.provider.entries[R.target(role)] = ('aieh-bot-other', fg.BOT_TOKENS[user])

        codes = {'login': 'IDENTITY_MISMATCH', 'scopes': 'IDENTITY_MISMATCH', 'extra scope': 'IDENTITY_MISMATCH',
                 'not an object': 'IDENTITY_UNREADABLE', 'scopes not a list': 'IDENTITY_UNREADABLE',
                 'no login': 'IDENTITY_UNREADABLE', 'not 200': 'IDENTITY_UNREADABLE',
                 '401': 'IDENTITY_UNREADABLE', '500': 'IDENTITY_UNREADABLE', 'entry': 'CREDENTIAL_MISMATCH'}
        for role in R.ROLES:
            for how, code in codes.items():
                with self.subTest(role=role, how=how):
                    self.setUp()
                    auditor_view = self.gitea.audit.tokens[fg.protection_fake.AUDIT_TOKEN]
                    http = damage(role, how)
                    observed, refused = self.assertRefusedBeforeAnyWrite(code, verifier=su.FakeVerifier(), http=http)
                    self.assertIn(role if how != 'entry' else R.ROLES[role]['user'], str(refused))
                    if how != 'entry':
                        self.assertEqual(self.gitea.requests[-1]['path'], '/api/v1/token')
                        self.assertEqual(list(observed['precondition']['identities'])[-1], role)

    def test_an_open_pull_request_is_refused(self):
        self.gitea.propose({'operations/x.json': su.manifest('x')}, branch='work/x')
        observed, refused = self.assertRefusedBeforeAnyWrite('PULL_REQUEST_OPEN', verifier=su.FakeVerifier())
        self.assertEqual(observed['precondition']['openPulls'], [1])
        self.assertEqual(self.gitea.requests[-1]['path'], '/api/v1' + L.OPEN_PULLS)

    def test_a_closed_pull_request_does_not_block(self):
        number = self.gitea.propose({'operations/x.json': su.manifest('x')}, branch='work/x', state='closed')
        presentation, observed = self.prepared()
        self.assertEqual(observed['precondition']['openPulls'], [])
        self.assertEqual(L.ABSENT_PULL_OFFSET + number + 2, observed['auditorControl']['pull'])

    def test_a_branch_the_run_would_create_is_refused(self):
        for suffix in ('a', 'b'):
            with self.subTest(branch=suffix):
                self.setUp()
                self.gitea.branches[f'work/authz-recorder-{STAMP}-{suffix}'] = self.gitea.branches['main']
                observed, refused = self.assertRefusedBeforeAnyWrite('BRANCH_EXISTS', verifier=su.FakeVerifier())
                self.assertIn(f'work/authz-recorder-{STAMP}-{suffix}', str(refused))

    def test_an_unreadable_repository_state_is_refused(self):
        for fragment in ('/pulls?state=open', f'/branches/work/authz-recorder-{STAMP}-b'):
            with self.subTest(route=fragment):
                self.setUp()
                self.gitea.fail_routes[fragment] = 500
                self.assertRefusedBeforeAnyWrite('REPOSITORY_UNREADABLE', verifier=su.FakeVerifier())

        for status, data in ((200, b'{"not": "a list"}'), (500, b'[]'), (203, b'[]')):
            with self.subTest(status=status, data=data):
                def answer(method, path, headers, answer):
                    return (status, {}, data) if '/pulls?state=open' in path else None
                self.setUp()
                self.assertRefusedBeforeAnyWrite('REPOSITORY_UNREADABLE', verifier=su.FakeVerifier(),
                                                 http=self.scripted(answer))

    def test_an_open_pull_request_listed_in_another_form_is_refused(self):
        def answer(method, path, headers, answer):
            return (200, {}, b'[7]') if '/pulls?state=open' in path else None
        observed, _ = self.assertRefusedBeforeAnyWrite('PULL_REQUEST_OPEN', verifier=su.FakeVerifier(),
                                                       http=self.scripted(answer))
        self.assertEqual(observed['precondition']['openPulls'], [7])

    def test_the_precondition_is_recorded_and_runs_before_any_write(self):
        presentation, observed = self.prepared()
        pre = observed['precondition']
        self.assertEqual(pre['protection'], {'verdict': 'verified', 'digest': BASELINE, 'expected': BASELINE,
                                             'detail': su.VERIFIED.detail})
        declared = {role: {'status': 200, 'login': spec['user'], 'scopes': list(spec['scopes'])}
                    for role, spec in R.ROLES.items()}
        self.assertEqual(pre['identities'], declared)
        self.assertEqual((pre['mainHead'], pre['openPulls']), (presentation['mainHead'], []))
        self.assertEqual(pre['branchesAbsent'], [f'work/authz-recorder-{STAMP}-a', f'work/authz-recorder-{STAMP}-b'])
        self.assertEqual(observed['mainBefore'], pre['mainHead'])
        self.assertEqual(presentation['precondition'], {
            'checked': 'before any write', 'baselineVariable': L.BASELINE_VARIABLE,
            'protection': {'verdict': 'verified', 'digest': BASELINE, 'expected': BASELINE},
            'identities': pre['identities'], 'mainHead': pre['mainHead'], 'openPulls': [],
            'openPullsRead': L.OPEN_PULLS, 'branchesAbsent': pre['branchesAbsent']})
        # every precondition read comes before the first write
        first_write = self.gitea.requests.index(self.writes()[0])
        reads = [r['path'] for r in self.gitea.requests[:first_write]]
        self.assertEqual(reads.count('/api/v1/token'), len(R.ROLES))
        self.assertIn('/api/v1' + L.OPEN_PULLS, reads)
        for branch in pre['branchesAbsent']:
            self.assertIn(f'/api/v1/repos/{fg.REPOSITORY}/branches/{branch}', reads)
        text = (self.run_dir / L.PRESENTATION_TEXT).read_text(encoding='utf-8')
        self.assertIn(f'protection: verified with the expected baseline {BASELINE} ({L.BASELINE_VARIABLE})', text)
        for role, spec in R.ROLES.items():
            self.assertIn(f'{role} {spec["user"]} [{", ".join(spec["scopes"])}]', text)
        self.assertIn(f'main at {pre["mainHead"]}; open pull requests: none; branches absent: '
                      f'{", ".join(pre["branchesAbsent"])}', text)


class AuditorControl(Phases):
    """The protection auditor's negative control: the merge of a nonexistent pull request, confirmed absent
    first; it passes only on 403 with Gitea's scope refusal; it never addresses A or B."""

    def test_the_auditor_never_addresses_a_real_pull_request(self):
        presentation, observed = self.prepared()
        real = [c['pull'] for c in presentation['challenges']]
        absent = max(real) + L.ABSENT_PULL_OFFSET
        mine = [r for r in self.gitea.requests if r['doer'] == fg.AUDITOR]
        for pull in real:
            self.assertEqual([r for r in mine if re.search(rf'/pulls/{pull}(/|$)', r['path'])], [])
        self.assertEqual([(r['method'], r['path']) for r in mine if r['method'] != 'GET'],
                         [('POST', f'/api/v1/repos/{fg.REPOSITORY}/pulls/{absent}/merge')])
        at = self.gitea.requests.index(next(r for r in mine if r['method'] == 'POST'))
        self.assertEqual((self.gitea.requests[at - 1]['method'], self.gitea.requests[at - 1]['path'],
                          self.gitea.requests[at - 1]['doer']),
                         ('GET', f'/api/v1/repos/{fg.REPOSITORY}/pulls/{absent}', R.ROLES['verifier']['user']))
        control = presentation['auditorControl']
        self.assertEqual({k: v for k, v in control.items() if k != 'message'},
                         {'pull': absent, 'absence': 404, 'status': 403, 'refusedByScope': True,
                          'shown': f'nonexistent pull request #{absent}, refused by scope'})
        self.assertIn(L.SCOPE_REFUSAL, control['message'])
        self.assertEqual(observed['auditorControl'], {k: v for k, v in control.items() if k != 'shown'})
        self.assertNotIn('protection-audit on', json.dumps(presentation['botMerges']))
        text = (self.run_dir / L.PRESENTATION_TEXT).read_text(encoding='utf-8')
        self.assertIn(f'Protection auditor control: nonexistent pull request #{absent}, refused by scope (403; '
                      'confirmed absent first: 404). It never addresses A or B.', text)

    def answering(self, status, payload):
        def rule(method, path, headers, answer):
            if method == 'POST' and _auditor(headers) and _absent_pull(path):
                return status, {'content-type': 'application/json'}, (
                    b'' if payload is None else payload if isinstance(payload, bytes) else json.dumps(payload).encode())
            return None
        return self.scripted(rule)

    def test_the_control_passes_only_on_403_with_the_scope_refusal(self):
        failing = {'404 (absence, not the scope)': (404, {'message': 'pull request not found'}),
                   '403 without the scope text': (403, {'message': 'forbidden'}),
                   '403 with no body': (403, None),
                   '403 with the text in another field': (403, {'errors': [L.SCOPE_REFUSAL], 'message': 'x'}),
                   '405': (405, {'message': 'User not allowed to merge PR'}),
                   '409': (409, {'message': L.SCOPE_REFUSAL}),
                   '500': (500, {'message': 'internal'}),
                   '401': (401, {'message': 'unauthorized'}),
                   '403 with the text as a plain body': (403, L.SCOPE_REFUSAL.encode()),
                   '403 with a message that is no string': (403, {'message': [L.SCOPE_REFUSAL]})}
        for name, (status, payload) in failing.items():
            with self.subTest(answer=name):
                self.setUp()
                observed = {}
                with self.assertRaises(L.ControlFailed) as caught:
                    L.prepare_phase(self.live(su.FakeVerifier(), http=self.answering(status, payload)), observed)
                self.assertEqual(caught.exception.code, 'AUDITOR_CONTROL_FAILED')
                self.assertNothingPrepared()
                self.assertEqual(self.writes()[-1]['doer'], fg.AUDITOR)  # nothing written after the control
                said = payload.get('message') if isinstance(payload, dict) else None
                self.assertEqual((observed['auditorControl']['status'], observed['auditorControl']['refusedByScope'],
                                  observed['auditorControl']['message']),
                                 (status, False, said if isinstance(said, str) else ''))
        # Gitea's own text, as the scope check gives it, passes
        self.setUp()
        presentation, _ = self.prepared(http=self.answering(403, {'message': L.SCOPE_REFUSAL + ', required=[x]'}))
        self.assertTrue(presentation['auditorControl']['refusedByScope'])

    def test_a_2xx_answer_to_the_auditor_is_a_security_failure(self):
        for status in (200, 201, 204):
            with self.subTest(status=status):
                self.setUp()
                observed = {}
                with self.assertRaisesRegex(L.SecurityFailure, '^SECURITY FAILURE: the protection auditor\'s merge of '
                                            'the nonexistent pull request'):
                    L.prepare_phase(self.live(su.FakeVerifier(), http=self.answering(status, None)), observed)
                self.assertEqual(self.gitea.requests[-1]['doer'], fg.AUDITOR)  # nothing sent after it
                self.assertNothingPrepared()
                self.assertEqual(observed['controlChecks'][-1]['status'], status)

    def test_absence_not_confirmed_sends_no_merge(self):
        for status in (200, 403, 500):
            with self.subTest(status=status):
                self.setUp()

                def present(method, path, headers, answer):
                    if method == 'GET' and _absent_pull(path):
                        return status, {'content-type': 'application/json'}, b'{"number": 1}'
                    return None

                observed = {}
                with self.assertRaises(L.ControlFailed) as caught:
                    L.prepare_phase(self.live(su.FakeVerifier(), http=self.scripted(present)), observed)
                self.assertEqual(caught.exception.code, 'AUDITOR_CONTROL_NOT_EXERCISABLE')
                self.assertEqual([r for r in self.gitea.requests if r['doer'] == fg.AUDITOR and r['method'] != 'GET'],
                                 [])
                self.assertEqual(observed['auditorControl'], {'pull': 2 + L.ABSENT_PULL_OFFSET, 'absence': status})
                self.assertNothingPrepared()

    def test_the_scope_refusal_is_act_c_s(self):
        tree = ast.parse(ACT_C.read_text(encoding='utf-8'))
        values = [node.value.value for node in tree.body if isinstance(node, ast.Assign)
                  and [getattr(t, 'id', None) for t in node.targets] == ['SCOPE_REFUSAL']]
        self.assertEqual(values, [L.SCOPE_REFUSAL])
        self.assertTrue(fg.protection_fake.SCOPE_TEXT.startswith(L.SCOPE_REFUSAL))
        self.assertEqual(L.AUDITOR_ROLE, 'protection-audit')


class SecurityFailureStops(Phases):
    """The stopping rule: after every single control attempt, main's head and both proposals' merged state are
    read; any 2xx merge answer, either proposal merged, or main moved is a SECURITY FAILURE at once, with no
    later control, no recorder prepare, no challenge and no presentation."""

    def test_a_successful_bot_merge_stops_the_exercise(self):
        for position, role in enumerate(BOTS, start=1):
            with self.subTest(role=role):
                self.setUp()
                self.gitea.protection['main']['merge_whitelist'].append(R.ROLES[role]['user'])
                observed = {}
                with self.assertRaises(L.SecurityFailure) as caught:
                    L.prepare_phase(self.live(su.FakeVerifier()), observed)
                self.assertTrue(str(caught.exception).startswith(f'SECURITY FAILURE: the {role} bot\'s merge'))
                self.assertEqual(self.gitea.merge_count(), 1)
                self.assertEqual(len(self.merges()), position)  # no later control was sent
                last = self.gitea.requests[-1]
                self.assertEqual((last['method'], last['doer']), ('POST', R.ROLES[role]['user']))
                self.assertTrue(last['path'].endswith('/merge'))
                self.assertNothingPrepared()
                self.assertEqual(observed['botMerges'][f'{role} on #1'], 200)

    def test_a_merge_behind_a_refused_answer_stops_the_exercise(self):
        self.gitea.protection['main']['merge_whitelist'].append(R.ROLES['planner']['user'])
        self.gitea.on_merge = 'error-after'  # merged, then answered 500
        with self.assertRaises(L.SecurityFailure) as caught:
            self.prepared()
        self.assertIn('SECURITY FAILURE: after the planner bot\'s merge of pull request #1 (500) main is at',
                      str(caught.exception))
        self.assertEqual(len(self.merges()), 1)
        self.assertNothingPrepared()

    def moving(self, after, change):
        """An http callable that runs CHANGE after the AFTER-th merge attempt (a refused one) is answered."""
        sent = []

        def rule(method, path, headers, answer):
            if method == 'POST' and path.endswith('/merge'):
                sent.append(path)
                if len(sent) == after:
                    change()
            return None
        return self.scripted(rule)

    def test_main_moving_after_any_refused_control_stops_at_once(self):
        controls = 2 * len(BOTS) + 1  # the auditor's is the last
        for after in range(1, controls + 1):
            with self.subTest(after=after):
                self.setUp()
                observed = {}
                http = self.moving(after, lambda: self.gitea.advance_main({'x.txt': b'moved\n'}))
                with self.assertRaisesRegex(L.SecurityFailure, r'^SECURITY FAILURE: after the .* main is at'):
                    L.prepare_phase(self.live(su.FakeVerifier(), http=http), observed)
                self.assertEqual(len(self.merges()), after)
                self.assertEqual(self.writes()[-1], self.merges()[-1])  # nothing written after it
                self.assertNothingPrepared()
                self.assertNotEqual(observed['controlChecks'][-1]['mainHead'], observed['mainBefore'])
                self.assertEqual(len(observed['controlChecks']), after)

    def test_a_proposal_merged_after_any_refused_control_stops_at_once(self):
        for after, pull in ((1, 2), (4, 1), (2 * len(BOTS) + 1, 2)):
            with self.subTest(after=after, pull=pull):
                self.setUp()
                observed = {}
                http = self.moving(after, lambda: self.gitea.pulls[pull].update(merged=True))
                with self.assertRaisesRegex(L.SecurityFailure, rf'pull request\(s\) \[{pull}\] are merged'):
                    L.prepare_phase(self.live(su.FakeVerifier(), http=http), observed)
                self.assertEqual(len(self.merges()), after)
                self.assertEqual(observed['controlChecks'][-1]['merged'], [pull])
                self.assertNothingPrepared()

    def test_an_unexpected_bot_refusal_stops_the_controls(self):
        self.gitea.fail_routes['/merge'] = 409  # the four bots' merges only: the auditor's goes to its fake
        observed = {}
        with self.assertRaises(L.ControlFailed) as caught:
            L.prepare_phase(self.live(su.FakeVerifier()), observed)
        self.assertTrue(str(caught.exception).startswith('BOT_CONTROL_UNEXPECTED: the planner bot\'s merge of pull '
                                                         'request #1 was refused with 409'), str(caught.exception))
        self.assertEqual(len(self.merges()), 1)
        self.assertEqual(observed['botMerges'], {'planner on #1': 409})
        self.assertNothingPrepared()

    def test_a_403_bot_refusal_is_expected(self):
        def forbid(method, path, headers, answer):
            if method == 'POST' and path.endswith('/merge') and not _auditor(headers):
                return 403, {'content-type': 'application/json'}, b'{"message": "forbidden"}'
            return None
        presentation, _ = self.prepared(http=self.scripted(forbid))
        self.assertEqual(set(presentation['botMerges']['statuses'].values()), {403})


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
        # a presentation saying a verifier was available, recorded without one
        with self.assertRaises(L.PhaseRefused) as caught:
            L.record_phase(self.live(), said, {})
        self.assertEqual(caught.exception.code, 'VERIFIER_CHANGED')
        self.assertIn('was available, and one is not available now', str(caught.exception))
        self.assertEqual(len(self.gitea.requests), before)
        # a presentation saying none was available, recorded with one
        self.without_verifier(presentation)
        with self.assertRaises(L.PhaseRefused) as caught:
            L.record_phase(self.live(su.FakeVerifier()), said, {})
        self.assertIn('was not available, and one is available now', str(caught.exception))
        self.assertEqual(len(self.gitea.requests), before)


class Record(Phases):
    def test_without_a_verifier_every_record_is_refused_and_nothing_is_merged(self):
        presentation = self.without_verifier(self.prepared()[0])
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
        presentation = self.without_verifier(self.prepared()[0])
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
    drift the record is refused and nothing is merged; drift before prepare refuses the precondition."""

    def check(self):
        return AR.protection_verifier(self.provider, self.port, http=self.http)

    def baseline(self):
        """The digest the protection check answers on the fake as declared (the run's expected baseline)."""
        verdict = self.check()(fg.REPOSITORY, 'main', 'prepare')
        self.assertEqual(verdict.status, 'verified')
        self.gitea.requests.clear()
        self.provider.reads.clear()
        return verdict.digest

    def test_verified_one_merge_and_the_stale_head_control(self):
        verifier = self.check()
        presentation, _ = self.prepared(verifier, self.baseline())
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
        presentation, _ = self.prepared(verifier, self.baseline())
        self.gitea.audit.rule('main')['block_admin_merge_override'] = False
        observed = L.record_phase(self.live(verifier), self.statement_file(
            self.synthetic(*self.operations(presentation))), {})
        for c in presentation['challenges']:
            outcome = observed['outcomes'][c['operation']]
            self.assertEqual((outcome['code'], outcome['receipt']), ('PROTECTION_DRIFT', None))
            self.assertIn('main.block_admin_merge_override', outcome['detail'])
        self.assertEqual(self.gitea.merge_count(), 0)
        self.assertEqual(self.gitea.branches['main'], presentation['mainHead'])

    def test_drift_before_prepare_refuses_the_precondition(self):
        baseline = self.baseline()
        self.gitea.audit.rule('main')['block_admin_merge_override'] = False
        observed, refused = self.assertRefusedBeforeAnyWrite('PROTECTION_DRIFT', verifier=self.check(),
                                                             baseline=baseline)
        self.assertIn('main.block_admin_merge_override', str(refused))
        self.assertEqual(self.provider.reads, [R.target(L.AUDITOR_ROLE)])


if __name__ == '__main__':
    unittest.main()
