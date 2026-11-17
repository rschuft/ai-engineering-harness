"""Objective acceptance from the Owner UI (plan leaf P-04.4; decision 0025 points 8 and 9; I1 work design R6, slice 10):
the acceptance recorder's challenge shown as a card, and the Owner's acceptance recorded on his own message, bound to
his authenticated Owner UI session, through the acceptance routes of the Integration process (ASGI, in process) and
acceptance.py, in a throwaway project repository whose intent change the capture (P-01.3) made.

P-04.4's proof, clause by clause, each with its falsifier:

- **an acceptance made in the Owner's authenticated session mints the outcome once**: one commit (the decision record,
  the item's acceptance, the outcome declared), ``minted``; a repeat answers the same commit and changes nothing;
- **the outcome resolves through the lineage objective resolver**, its acceptance the statement's reference, and
  **the statement resolves to the Owner's message** through the lineage message resolver over the conversation store;
- **re-recording keeps the outcome id** (a new review and acceptance of the accepted item);
- **refused with a stable code, changing nothing** (the project repository's head and work tree, the conversation
  store and the integration store, compared before and after): an expired, a consumed and a stale challenge; a
  missing and a foreign session (and a revoked one); an acceptance not made in the Owner's session (a message of
  another session; a challenge issued to another session); a statement authored by a model or an agent (an
  assistant message);
- the commit's author and committer are the session principal's configured identity (decision 0028), read back by git;
- the race window: a refusal of the recorder's backstop after the reservation leaves the receipt reserved and nothing
  in the project repository; once repaired the same message records exactly one acceptance; a process that ended
  after the commit is settled by reading the repository first, never by recording again;
- no model is called: an audited acceptance opens no socket and starts no process.

Every identity, credential, statement and repository here is SYNTHETIC and throwaway.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

import ownerhost_support as T

sys.path.insert(0, str(T.REPO / 'integrations' / 'planning' / 'tests'))
import two_task_fixture as fx  # noqa: E402

CATEGORY = 'integration'
A, S, C, CS = T.A, T.S, T.A.capture, T.CS
AC = T.A.acceptance
REC = AC.recorder
NOW = T.utc(2026, 11, 17, 12, 0, 0)
LOCAL = '__LOCALID_accept1'
IDENTITY = 'Test Owner <12345+test-owner@users.noreply.github.com>'
REQUEST = '\n'.join(['Change: add-slugify', 'Objective: Titles become URL slugs.', 'Acceptance criteria:',
                     '- slugify("Hello World") returns "hello-world"'])
REVIEW = 'Review acceptance: O1 of add-slugify'
ACCEPT = 'Accept O1 of add-slugify\nSYNTHETIC FIXTURE: I accept this objective as stated.'
CHANGE_DIR = 'openspec/changes/add-slugify'
JSON = ('content-type', 'application/json')


def item(message_id, text, parent=None, role='user'):
    if role == 'user':
        message = {'id': message_id, 'createdAt': '2026-11-17T12:00:00.123Z', 'role': 'user',
                   'content': [{'type': 'text', 'text': text}], 'attachments': [], 'metadata': {'custom': {}}}
    else:
        message = {'id': message_id, 'role': 'assistant', 'status': {'type': 'complete', 'reason': 'stop'},
                   'content': [{'type': 'text', 'text': text}]}
    return {'parentId': parent, 'message': message}


def sha(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


class Crash(BaseException):
    """A process that ends here (not an Exception: no handler of the acceptance catches it)."""


class Rig(unittest.TestCase):
    """A conversation store with one enrolled session; a thread with the captured request, its capture card and a
    review message; a throwaway project repository holding the captured change; the application with a configured
    capture and acceptance."""

    def setUp(self):
        self.scratch = T.Scratch(prefix='aieh-accept-')
        self.addCleanup(self.scratch.close)
        self.work = self.scratch.dir
        self.credential, self.record = self.scratch.enroll(at=NOW)
        self.store = self.scratch.store
        self.thread_id = self.store.initialize_thread(session_id=self.record.session_id, local_id=LOCAL,
                                                      at=T.stamp(NOW))[0].thread_id
        self.project = self.work / 'project'
        self.project.mkdir()
        fx.git(self.project, 'init', '--quiet', '-b', 'main')
        fx.write(self.project, {'README.md': b'A throwaway project repository of the acceptance tests.\n'})
        fx.commit_all(self.project, 'base')
        self.receipts = self.work / 'integration' / 'integration.sqlite'
        self.config = {'project_repository': str(self.project), 'project_repository_id': 'aieh-d1-demo',
                       'backlog_command': 'backlog', 'git_identities': {'owner': IDENTITY}}
        self.ceiling = fx.ceiling(self.work)
        self.ceiling.start()
        self.addCleanup(self.ceiling.stop)
        self.clock = NOW
        self.build()
        self.append('Req0001', REQUEST)
        status, answer = self.post('Req0001', 'capture', {'sha256': sha(REQUEST)})
        self.assertEqual(status, 200, answer)
        self.captured = answer['commit']
        self.append('Cap0001', 'Captured.', 'Req0001', role='assistant')
        self.append('Rev0001', REVIEW, 'Cap0001')

    def build(self, config=None):
        config = self.config if config is None else config
        self.capturer = C.Capture(config, self.receipts)
        self.accepter = AC.Acceptance(config, self.receipts, now=lambda: self.clock)
        self.app = A.create_app(lambda: self.store, clock=lambda: T.stamp(self.clock), capturer=self.capturer,
                                accepter=self.accepter)

    def append(self, message_id, text, parent=None, role='user', record=None):
        self.store.append_message(self.thread_id, item(message_id, text, parent, role),
                                  session_id=(record or self.record).session_id, at=T.stamp(NOW))

    def post(self, message_id, route, body, credential=None, headers=None):
        hdrs = (T.HOST, JSON) + ((S.HEADER, credential or self.credential),) if headers is None else headers
        status, _, answer = T.call(self.app, 'POST', f'/threads/{self.thread_id}/messages/{message_id}/{route}',
                                   hdrs, body=json.dumps(body).encode('utf-8'))
        return status, json.loads(answer)

    def challenge(self, request='Rev0001', card='Crd0001', credential=None, store_card=True, record=None):
        status, answer = self.post(request, 'acceptance-challenge',
                                   {'sha256': self.store.message(self.thread_id, request).sha256, 'card': card},
                                   credential=credential)
        self.assertEqual(status, 200, answer)
        if store_card:
            self.append(card, 'The acceptance card.', request, role='assistant', record=record)
        return answer

    def accept(self, message_id, nonce, credential=None, digest=None):
        return self.post(message_id, 'acceptance',
                         {'nonce': nonce, 'sha256': digest or self.store.message(self.thread_id, message_id).sha256},
                         credential=credential)

    def accepted(self, message_id, nonce):
        status, answer = self.accept(message_id, nonce)
        self.assertEqual(status, 200, answer)
        return answer

    def head(self):
        return fx.git(self.project, 'rev-parse', 'HEAD')

    def receipts_dump(self):
        if not self.receipts.exists():
            return None
        with C.integration_store.open_store(self.receipts) as store:
            return store.canonical_dump()

    def state(self):
        """What a refusal must leave as it was: the project's history and work tree, the conversation store and the
        integration store."""
        return (self.head(), fx.git(self.project, 'status', '--porcelain', '--untracked-files=all'),
                self.store.canonical_dump(), self.receipts_dump())

    def refused(self, code, call, *args, status=None, **kwargs):
        before = self.state()
        got, answer = call(*args, **kwargs)
        self.assertEqual(answer.get('code'), code, answer)
        self.assertTrue(answer.get('remedy'), answer)
        if status is not None:
            self.assertEqual(got, status)
        self.assertEqual(self.state(), before, 'a refusal changed something')
        return answer

    def receipt(self, message_id):
        with C.integration_store.open_store(self.receipts) as store:
            key = AC.receipt_key(self.thread_id, message_id)
            return store.get(key), store.events(key)

    def acceptance_commits(self):
        """The commits of HEAD's history that carry the recorder's owner-ui statement line."""
        out = []
        for commit in fx.git(self.project, 'rev-list', 'HEAD').split():
            body = fx.git(self.project, 'log', '-1', '--format=%B', commit)
            if any(line.startswith('acceptance recorder. Statement: conversation:') for line in body.splitlines()):
                out.append(commit)
        return out

    def resolver(self):
        return REC.R.ObjectiveResolver(self.project)


class MintOnce(Rig):
    def test_an_acceptance_in_the_owner_s_session_mints_the_outcome_once(self):
        card = self.challenge()
        self.assertEqual((card['change'], card['item'], card['card'], card['request']),
                         ('add-slugify', 'O1', 'Crd0001', 'Rev0001'))
        self.assertIn('Outcome: none yet; recording this acceptance mints its id.', card['summary'])
        self.append('Acc0001', ACCEPT, 'Crd0001')
        answer = self.accepted('Acc0001', card['nonce'])
        self.assertEqual((answer['minted'], answer['created'], answer['state']), (True, True, 'confirmed'))
        self.assertEqual(fx.git(self.project, 'rev-list', 'HEAD').split()[1], self.captured)
        self.assertEqual(self.acceptance_commits(), [answer['commit']])
        changed = fx.git(self.project, 'diff-tree', '--no-commit-id', '--name-status', '-r', f'{answer["commit"]}~1',
                         answer['commit']).splitlines()
        self.assertEqual(changed, [f'M\t{CHANGE_DIR}/.openspec.yaml',
                                   f'A\t{CHANGE_DIR}/owner-decisions/{answer["decision"]}.json',
                                   f'M\t{CHANGE_DIR}/proposal.md'])
        self.assertEqual(fx.git(self.project, 'status', '--porcelain', '--untracked-files=all'), '')
        reservation, events = self.receipt('Acc0001')
        self.assertEqual([e.to_state for e in events], ['reserved', 'dispatched', 'confirmed'])
        self.assertEqual(json.loads(events[-1].detail_json)['acceptedBySession'], self.record.session_id)

    def test_the_outcome_resolves_and_the_statement_resolves_to_the_owner_s_message(self):
        card = self.challenge()
        self.append('Acc0001', ACCEPT, 'Crd0001')
        answer = self.accepted('Acc0001', card['nonce'])
        stored = self.store.message(self.thread_id, 'Acc0001')
        reference = f'conversation:{self.thread_id}/Acc0001#sha256:{stored.sha256}'
        self.assertEqual(answer['statement'], reference)
        resolved = self.resolver().resolve(REC.L.parse(answer['reference']))
        self.assertTrue(resolved.resolved, resolved)
        self.assertEqual((resolved.facts['item'], resolved.facts['acceptance']), ('O1', reference))
        message = REC.R.MessageResolver(self.work / CS.DB_NAME).resolve(REC.L.parse(reference))
        self.assertEqual((message.outcome, message.code), ('resolved', None), message)
        record = json.loads(fx.git(self.project, 'show',
                                   f'{answer["commit"]}:{CHANGE_DIR}/owner-decisions/{answer["decision"]}.json'))
        self.assertEqual(record['statement'], {'text': ACCEPT, 'attributedTo': 'owner', 'channel': 'owner-ui',
                                               'reference': reference})
        self.assertEqual((record['recordedBy'], record['shown']['nonce']), ('owner', card['nonce']))
        self.assertEqual(record['shown']['summary'], card['summary'])

    def test_author_and_committer_are_the_session_principal_s_configured_identity(self):
        card = self.challenge()
        self.append('Acc0001', ACCEPT, 'Crd0001')
        commit = self.accepted('Acc0001', card['nonce'])['commit']
        self.assertEqual(fx.git(self.project, 'log', '-1', '--format=%an <%ae>|%cn <%ce>', commit),
                         f'{IDENTITY}|{IDENTITY}')

    def test_a_repeat_answers_the_same_commit_and_changes_nothing(self):
        card = self.challenge()
        self.append('Acc0001', ACCEPT, 'Crd0001')
        first = self.accepted('Acc0001', card['nonce'])
        before = self.state()
        again = self.accepted('Acc0001', card['nonce'])
        self.assertEqual(self.state(), before)
        self.assertEqual({**again, 'created': True}, first)
        self.assertFalse(again['created'])
        self.build()                                       # a restart: no challenge is held, the receipt answers
        self.assertEqual(self.accepted('Acc0001', card['nonce']), again)
        self.assertEqual(self.state(), before)

    def test_re_recording_keeps_the_outcome_id(self):
        card = self.challenge()
        self.append('Acc0001', ACCEPT, 'Crd0001')
        first = self.accepted('Acc0001', card['nonce'])
        self.append('Rev0002', REVIEW, 'Acc0001')
        second_card = self.challenge('Rev0002', 'Crd0002')
        self.assertIn(f'Outcome: {first["outcome"]}; recording a new acceptance keeps this id.', second_card['summary'])
        self.append('Acc0002', 'Accept O1 of add-slugify\nSYNTHETIC FIXTURE: accepted again.', 'Crd0002')
        second = self.accepted('Acc0002', second_card['nonce'])
        self.assertEqual((second['outcome'], second['minted'], second['created']), (first['outcome'], False, True))
        self.assertEqual(self.acceptance_commits(), [second['commit'], first['commit']])
        resolved = self.resolver().resolve(REC.L.parse(second['reference']))
        self.assertTrue(resolved.resolved)
        self.assertEqual(resolved.facts['acceptance'], second['statement'])
        meta = (self.project / CHANGE_DIR / '.openspec.yaml').read_text(encoding='utf-8')
        self.assertEqual(meta.count(first['outcome']), 1)


class ChallengeRefusals(Rig):
    def setUp(self):
        super().setUp()
        self.card = self.challenge()
        self.append('Acc0001', ACCEPT, 'Crd0001')

    def test_an_expired_challenge_is_refused_and_changes_nothing(self):
        self.clock = NOW + datetime.timedelta(minutes=AC.EXPIRY_MINUTES)
        self.refused('CHALLENGE_EXPIRED', self.accept, 'Acc0001', self.card['nonce'], status=409)

    def test_a_consumed_challenge_is_refused_and_changes_nothing(self):
        self.accepted('Acc0001', self.card['nonce'])
        self.append('Acc0002', 'Accept O1 of add-slugify\nSYNTHETIC FIXTURE: a second acceptance.', 'Crd0001')
        self.refused('CHALLENGE_CONSUMED', self.accept, 'Acc0002', self.card['nonce'], status=409)
        self.build()                                       # after a restart the challenge is not held at all
        self.refused('ACCEPTANCE_CHALLENGE_UNKNOWN', self.accept, 'Acc0002', self.card['nonce'], status=409)

    def test_a_stale_challenge_is_refused_and_changes_nothing(self):
        proposal = self.project / CHANGE_DIR / 'proposal.md'
        proposal.write_bytes(proposal.read_bytes().replace(b'## Why\n', b'## Why\n\nEdited after the card.\n'))
        fx.commit_all(self.project, 'edit the proposal')
        self.refused('CHALLENGE_STALE', self.accept, 'Acc0001', self.card['nonce'], status=409)

    def test_a_challenge_lost_on_restart_is_unknown(self):
        self.build()
        self.refused('ACCEPTANCE_CHALLENGE_UNKNOWN', self.accept, 'Acc0001', self.card['nonce'], status=409)
        self.refused('ACCEPTANCE_CHALLENGE_UNKNOWN', self.accept, 'Acc0001', 'ab' * 16, status=409)

    def test_an_acceptance_not_after_the_card_is_refused(self):
        self.append('Acc0002', 'Accept O1 of add-slugify', 'Rev0001')       # a sibling of the card, not after it
        self.refused('ACCEPTANCE_NOT_AFTER_CARD', self.accept, 'Acc0002', self.card['nonce'], status=409)
        self.append('Rev0002', REVIEW, 'Acc0001')
        other = self.challenge('Rev0002', 'Crd0002', store_card=False)       # the card was never stored
        self.append('Acc0003', 'Accept O1 of add-slugify', 'Rev0002')
        self.refused('ACCEPTANCE_NOT_AFTER_CARD', self.accept, 'Acc0003', other['nonce'], status=409)

    def test_the_layout_and_the_message_s_bytes_are_checked(self):
        for message_id, text in (('Acc0002', 'I accept O1 of add-slugify'), ('Acc0003', 'Accept O1 of add-slugify\n'),
                                 ('Acc0004', 'Accept O1 of add-slugify\r\nyes')):
            with self.subTest(text=text):
                self.append(message_id, text, 'Crd0001')
                self.refused('ACCEPTANCE_LAYOUT_INVALID', self.accept, message_id, self.card['nonce'], status=422)
        self.refused('ACCEPTANCE_MESSAGE_MISMATCH', self.accept, 'Acc0001', self.card['nonce'],
                     digest=sha(ACCEPT + ' '), status=409)
        self.append('Acc0005', 'Accept O2 of add-slugify', 'Crd0001')
        self.refused('ACCEPTANCE_CHALLENGE_MISMATCH', self.accept, 'Acc0005', self.card['nonce'], status=409)

    def test_malformed_bodies_are_refused(self):
        digest = self.store.message(self.thread_id, 'Acc0001').sha256
        for body in ({'nonce': self.card['nonce']}, {'nonce': self.card['nonce'].upper(), 'sha256': digest},
                     {'nonce': self.card['nonce'], 'sha256': digest, 'extra': 1}):
            with self.subTest(body=body):
                self.refused('REQUEST_INVALID', self.post, 'Acc0001', 'acceptance', body, status=400)
        for body in ({'sha256': sha(REVIEW)}, {'sha256': sha(REVIEW), 'card': 'Rev0001'},
                     {'sha256': sha(REVIEW), 'card': 'bad id'}):
            with self.subTest(body=body):
                self.refused('REQUEST_INVALID', self.post, 'Rev0001', 'acceptance-challenge', body, status=400)


class SessionRefusals(Rig):
    def setUp(self):
        super().setUp()
        self.card = self.challenge()
        self.append('Acc0001', ACCEPT, 'Crd0001')

    def test_a_missing_or_foreign_session_is_refused_and_changes_nothing(self):
        digest = self.store.message(self.thread_id, 'Acc0001').sha256
        body = {'nonce': self.card['nonce'], 'sha256': digest}
        foreign = S.PREFIX + 'a' * 52
        for route, message_id, payload in (('acceptance', 'Acc0001', body),
                                           ('acceptance-challenge', 'Rev0001', {'sha256': sha(REVIEW),
                                                                                'card': 'Crd0009'})):
            with self.subTest(route=route):
                self.refused('SESSION_CREDENTIAL_MISSING', self.post, message_id, route, payload,
                             headers=(T.HOST, JSON), status=401)
                self.refused('SESSION_CREDENTIAL_FOREIGN', self.post, message_id, route, payload, credential=foreign,
                             status=401)

    def test_an_acceptance_not_made_in_the_owner_s_session_is_refused(self):
        """A new enrollment supersedes the session the card and the acceptance were made in: a request from the new
        session naming that message is refused, the old session's credential is revoked, and a message of the new
        session on the old session's challenge is refused too."""
        credential, record = self.scratch.enroll(at=NOW)
        self.refused('ACCEPTANCE_SESSION_MISMATCH', self.accept, 'Acc0001', self.card['nonce'], credential=credential,
                     status=403)
        self.refused('SESSION_CREDENTIAL_REVOKED', self.accept, 'Acc0001', self.card['nonce'], status=401)
        self.append('Acc0002', 'Accept O1 of add-slugify', 'Crd0001', record=record)
        self.refused('ACCEPTANCE_SESSION_MISMATCH', self.accept, 'Acc0002', self.card['nonce'], credential=credential,
                     status=403)
        self.refused('ACCEPTANCE_SESSION_MISMATCH', self.post, 'Rev0001', 'acceptance-challenge',
                     {'sha256': sha(REVIEW), 'card': 'Crd0009'}, credential=credential, status=403)

    def test_a_statement_authored_by_a_model_or_an_agent_is_refused(self):
        """An assistant message is display state the shell wrote, or a model's or an agent's text: never the Owner's
        statement, whatever it says."""
        self.append('Agt0001', 'Accept O1 of add-slugify', 'Crd0001', role='assistant')
        for message_id in ('Agt0001', 'Crd0001'):
            with self.subTest(message=message_id):
                self.refused('ACCEPTANCE_MODEL_AUTHORED', self.accept, message_id, self.card['nonce'], status=409)
        self.refused('ACCEPTANCE_NOT_A_STATEMENT', self.post, 'Cap0001', 'acceptance-challenge',
                     {'sha256': self.store.message(self.thread_id, 'Cap0001').sha256, 'card': 'Crd0009'}, status=409)


class ConfigurationRefusals(Rig):
    def setUp(self):
        super().setUp()
        self.card = self.challenge()
        self.append('Acc0001', ACCEPT, 'Crd0001')

    def test_an_absent_or_placeholder_identity_is_refused_and_changes_nothing(self):
        for identities, code in (({}, 'COMMIT_IDENTITY_UNAVAILABLE'),
                                 ({'owner': 'Someone <someone@example.invalid>'}, 'COMMIT_IDENTITY_PLACEHOLDER'),
                                 ({'other': IDENTITY}, 'COMMIT_IDENTITY_UNAVAILABLE')):
            with self.subTest(identities=identities):
                held = self.accepter.held
                self.build({**self.config, 'git_identities': identities})
                self.accepter.held = held
                self.refused(code, self.accept, 'Acc0001', self.card['nonce'], status=503)
        self.build()
        self.accepter.held = held
        self.assertTrue(self.accepted('Acc0001', self.card['nonce'])['minted'])

    def test_the_harness_checkout_is_never_the_project(self):
        held = self.accepter.held
        self.build({**self.config, 'project_repository': str(T.REPO)})
        self.accepter.held = held
        self.refused('CAPTURE_PROJECT_IS_HARNESS', self.accept, 'Acc0001', self.card['nonce'], status=503)
        self.refused('CAPTURE_PROJECT_IS_HARNESS', self.post, 'Rev0001', 'acceptance-challenge',
                     {'sha256': sha(REVIEW), 'card': 'Crd0009'}, status=503)

    def test_an_unconfigured_project_is_refused(self):
        self.build(None)
        self.accepter = AC.Acceptance(None, self.receipts, now=lambda: self.clock)
        self.app = A.create_app(lambda: self.store, clock=lambda: T.stamp(self.clock), accepter=self.accepter)
        self.refused('CAPTURE_PROJECT_UNCONFIGURED', self.accept, 'Acc0001', self.card['nonce'], status=503)


class RaceWindow(Rig):
    """Only a race reaches the recorder's backstop after the reservation (decision of the engineering manager on
    P-04.4, ruling B): its refusal leaves the receipt reserved and nothing in the project repository; once repaired,
    the same message records exactly one acceptance; a process that ended after the commit is settled by reading the
    repository first."""

    def setUp(self):
        super().setUp()
        self.card = self.challenge()
        self.append('Acc0001', ACCEPT, 'Crd0001')
        self.proposal = self.project / CHANGE_DIR / 'proposal.md'
        self.original = self.proposal.read_bytes()

    def test_a_backstop_refusal_leaves_the_receipt_reserved_and_the_repository_unchanged(self):
        real = REC.record

        def racing(*args, **kwargs):          # another process edits the proposal between the checks and the commit
            self.proposal.write_bytes(self.original.replace(b'## Why\n', b'## Why\n\nA racing edit.\n'))
            self.raced = fx.commit_all(self.project, 'a racing edit')
            return real(*args, **kwargs)

        conversation = self.store.canonical_dump()
        with mock.patch.object(REC, 'record', racing):
            status, answer = self.accept('Acc0001', self.card['nonce'])
        self.assertEqual((status, answer['code']), (409, 'CHALLENGE_STALE'))
        self.assertIn('stays reserved', answer['detail'])
        self.assertEqual(self.head(), self.raced)                       # the race's commit, and nothing of ours
        self.assertEqual(self.acceptance_commits(), [])
        self.assertEqual(fx.git(self.project, 'status', '--porcelain', '--untracked-files=all'), '')
        self.assertEqual(self.store.canonical_dump(), conversation)
        reservation, events = self.receipt('Acc0001')
        self.assertEqual((reservation.state, [e.to_state for e in events]), ('reserved', ['reserved']))
        # Repaired: the proposal is the one the card showed again. The same message records exactly one acceptance.
        self.proposal.write_bytes(self.original)
        fx.commit_all(self.project, 'revert the racing edit')
        with mock.patch.object(AC, 'find_acceptance', wraps=AC.find_acceptance) as found:
            answer = self.accepted('Acc0001', self.card['nonce'])
        self.assertEqual(found.call_count, 1)                           # the repository was read first
        self.assertTrue(answer['minted'])
        self.assertEqual(self.acceptance_commits(), [answer['commit']])
        reservation, events = self.receipt('Acc0001')
        self.assertEqual([e.to_state for e in events], ['reserved', 'dispatched', 'confirmed'])

    def test_a_process_that_ended_after_the_commit_is_settled_by_reading_the_repository(self):
        def crash(store, *args, **kwargs):
            raise Crash()
        with mock.patch.object(C.integration_store.IntegrationStore, 'transition', crash), \
                self.assertRaises(Crash):
            self.accept('Acc0001', self.card['nonce'])
        (commit,) = self.acceptance_commits()
        self.assertEqual(self.receipt('Acc0001')[0].state, 'reserved')
        self.build()                                                  # the restarted process holds no challenge
        with mock.patch.object(REC, 'record', side_effect=AssertionError('recorded again')):
            answer = self.accepted('Acc0001', self.card['nonce'])
        self.assertEqual((answer['commit'], answer['created'], answer['minted']), (commit, False, True))
        self.assertEqual(self.acceptance_commits(), [commit])
        self.assertEqual(self.receipt('Acc0001')[0].state, 'confirmed')

    def test_the_settlement_line_is_the_recorder_s(self):
        decision = {'decisionId': 'd', 'recordedBy': 'owner', 'subject': {'item': 'O1', 'change': 'c', 'outcome': 'o'}}
        statement = {'reference': 'conversation:t/m#sha256:' + '0' * 64, 'channel': 'owner-ui'}
        message = REC.commit_message(decision, True, statement)
        self.assertIn(AC.statement_line(statement['reference']), message.split('\n'))
        self.assertIn(f'{AC.OUTCOME_TRAILER}o', message.split('\n'))
        self.assertIn(f'{AC.DECISION_TRAILER}d', message.split('\n'))


class NoModelNoSocket(Rig):
    EVENTS = ('socket.', 'subprocess.Popen', 'os.system', 'os.exec', 'os.posix_spawn', 'os.spawn', 'os.startfile',
              'urllib.Request', 'http.client.connect', 'webbrowser.open')

    def test_an_audited_review_and_acceptance_open_no_socket_and_start_no_process(self):
        seen, armed = [], []

        def hook(event, _args):
            if armed and event.startswith(self.EVENTS):
                seen.append(event)
        sys.addaudithook(hook)
        session = self.record.public()
        armed.append(True)
        try:
            card = self.accepter.prepare(self.store, self.thread_id, 'Rev0001',
                                         {'sha256': sha(REVIEW), 'card': 'Crd0001'}, session)
            self.append('Crd0001', 'The acceptance card.', 'Rev0001', role='assistant')
            self.append('Acc0001', ACCEPT, 'Crd0001')
            answer = self.accepter.record(self.store, self.thread_id, 'Acc0001',
                                          {'nonce': card['nonce'], 'sha256': sha(ACCEPT)}, session)
        finally:
            armed.clear()
        self.assertTrue(answer['minted'])
        self.assertEqual(seen, [])

    def test_acceptance_imports_no_model_inference_network_or_authorization_module(self):
        import ast
        tree = ast.parse((T.PACKAGE / 'acceptance.py').read_text(encoding='utf-8'))
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name.split('.')[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                names.add((node.module or '').split('.')[0])
            elif isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.endswith('.py'):
                names.add(node.value)
        self.assertEqual(names & {'http', 'urllib', 'urllib3', 'requests', 'httpx', 'socket', 'ssl', 'anthropic',
                                  'openai', 'subprocess', 'dulwich'}, set())
        self.assertEqual({n for n in names if n.endswith('.py')}, {'capture.py', 'acceptance_recorder.py'})


if __name__ == '__main__':
    unittest.main()
