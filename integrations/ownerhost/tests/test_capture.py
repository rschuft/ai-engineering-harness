"""Intent capture (plan leaf P-01.3; decision 0025 point 8; I1 work design R6, slice 8): one Owner message in the
request layout becomes one intent-record/v1 OpenSpec change in a throwaway project repository, through the capture
route of the Integration process (ASGI, in process) and capture.py.

Each proof clause of P-01.3, and slice 8's additions, with its falsifier:

- **one message yields exactly one intent change**: one commit, whose tree differs from its parent's by exactly the
  change's proposal.md and .openspec.yaml; **idempotent by message id**: a repeat, a new Integration process (a
  restart) and a new session (a reconnect after a new enrollment) answer the same commit and write nothing;
- **the Original Quote's span verifies against the stored message**: Q1's source is the message's span anchor, which
  ``lineage.check_message_content`` resolves against the store's bytes, and the quote is those bytes;
- **the change passes tools/check_intent_record.py**, run as its command line with the store's bytes as the source;
- **the statement-to-objective originates edge resolves to the message**: after the acceptance recorder accepts O1 (a
  SYNTHETIC statement, in the throwaway repository), the lineage traversal's originates edge leaves the message node,
  resolved authoritatively from the conversation store, its quote verified;
- **a request whose bytes differ from the stored message** is ``CAPTURE_MESSAGE_MISMATCH``: the project repository,
  the conversation store and the integration store are unchanged;
- **no model is called**: an audited capture opens no socket and starts no process, and capture.py imports no model,
  inference or network client module;
- **a suggestion is a hypothesis, never the objective**;
- slice 8: the same message captured twice, and after a crash between the receipt and the commit (and after the
  branch moved but before the receipt was confirmed), yields one change; the layout is parsed strictly
  (``CAPTURE_LAYOUT_INVALID``, nothing written); an existing change name is ``CAPTURE_CHANGE_EXISTS``;
- the commit's author and committer are the commissioning user's configured git identity, both, read back by git;
  absent, another principal's, a placeholder domain or a malformed identity is refused with nothing written, and the
  same message is captured once the identity is configured.

Every identity here is synthetic in a reserved form (a GitHub no-reply address with a made-up id and login).
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

import ownerhost_support as T

sys.path.insert(0, str(T.REPO / 'integrations' / 'planning' / 'tests'))
import two_task_fixture as fx  # noqa: E402

CATEGORY = 'integration'
A, S, C = T.A, T.S, T.A.capture
CS = T.CS
NOW = T.utc(2026, 11, 16, 12, 0, 0)
LOCAL = '__LOCALID_capture1'
IDENTITY = 'Test Owner <12345+test-owner@users.noreply.github.com>'
OTHER_IDENTITY = 'Test Other <67890+test-other@users.noreply.github.com>'
OBJECTIVE = 'Titles become URL slugs — café stays readable, `code` too.'
CRITERIA = ('slugify("Hello World") returns "hello-world"', 'An empty title gives an empty slug')
SUGGESTION = 'Use the python-slugify package'
REQUEST = '\n'.join(['Change: add-slugify', f'Objective: {OBJECTIVE}', 'Acceptance criteria:',
                     *(f'- {c}' for c in CRITERIA), f'Suggestion: {SUGGESTION}'])
CHANGE_DIR = 'openspec/changes/add-slugify'
JSON = ('content-type', 'application/json')
CHECKER = T.REPO / 'tools' / 'check_intent_record.py'


def user_item(message_id, text, parent=None):
    return {'parentId': parent, 'message': {'id': message_id, 'createdAt': '2026-11-16T12:00:00.123Z', 'role': 'user',
                                            'content': [{'type': 'text', 'text': text}], 'attachments': [],
                                            'metadata': {'custom': {}}}}


def sha(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


class Crash(BaseException):
    """A process that ends here: nothing after it runs (not an Exception, so no handler of the capture catches it)."""


class Rig(unittest.TestCase):
    """A conversation store with one enrolled session and a thread holding the request message, a throwaway project
    repository with one commit, an integration store path, and the application with a configured capture."""

    def setUp(self):
        self.scratch = T.Scratch(prefix='aieh-capture-')
        self.addCleanup(self.scratch.close)
        self.work = self.scratch.dir
        self.credential, self.record = self.scratch.enroll(at=NOW)
        self.store = self.scratch.store
        self.thread, _ = self.store.initialize_thread(session_id=self.record.session_id, local_id=LOCAL,
                                                      at=T.stamp(NOW))
        self.thread_id = self.thread.thread_id
        self.append('Req0001', REQUEST)
        self.project = self.work / 'project'
        self.project.mkdir()
        fx.git(self.project, 'init', '--quiet', '-b', 'main')
        fx.write(self.project, {'README.md': b'A throwaway project repository of the capture tests.\n'})
        self.base = fx.commit_all(self.project, 'base')
        self.receipts = self.work / 'integration' / 'integration.sqlite'
        self.config = {'project_repository': str(self.project), 'project_repository_id': 'aieh-d1-demo',
                       'backlog_command': 'backlog', 'git_identities': {'owner': IDENTITY}}
        self.ceiling = fx.ceiling(self.work)
        self.ceiling.start()
        self.addCleanup(self.ceiling.stop)
        self.build()

    def build(self, config=None):
        self.capturer = C.Capture(self.config if config is None else config, self.receipts)
        self.app = A.create_app(lambda: self.store, clock=lambda: T.stamp(NOW), capturer=self.capturer)

    def append(self, message_id, text, parent=None):
        self.store.append_message(self.thread_id, user_item(message_id, text, parent),
                                  session_id=self.record.session_id, at=T.stamp(NOW))

    def capture(self, message_id='Req0001', digest=None, credential=None, body=None):
        payload = body if body is not None else {'sha256': digest or self.store.message(self.thread_id,
                                                                                        message_id).sha256}
        status, _, answer = T.call(self.app, 'POST', f'/threads/{self.thread_id}/messages/{message_id}/capture',
                                   (T.HOST, (S.HEADER, credential or self.credential), JSON),
                                   body=json.dumps(payload).encode('utf-8'))
        return status, json.loads(answer)

    def captured(self, message_id='Req0001'):
        status, answer = self.capture(message_id)
        self.assertEqual(status, 200, answer)
        return answer

    def refused(self, code, status=None, **kwargs):
        before = self.state()
        got, answer = self.capture(**kwargs)
        self.assertEqual(answer.get('code'), code, answer)
        if status is not None:
            self.assertEqual(got, status)
        self.assertEqual(self.state(), before, 'a refusal changed something')
        return answer

    def head(self):
        return fx.git(self.project, 'rev-parse', 'HEAD')

    def receipts_dump(self):
        if not self.receipts.exists():
            return None
        with C.integration_store.open_store(self.receipts) as store:
            return store.canonical_dump()

    def state(self):
        """What a refusal must leave as it was: the project's history and work tree, the conversation store, and
        the integration store."""
        return (self.head(), fx.git(self.project, 'status', '--porcelain', '--untracked-files=all'),
                self.store.canonical_dump(), self.receipts_dump())

    def receipt(self, message_id='Req0001'):
        with C.integration_store.open_store(self.receipts) as store:
            key = C.receipt_key(self.thread_id, message_id)
            return store.get(key), store.events(key)

    def commits(self):
        return fx.git(self.project, 'rev-list', 'HEAD').split()

    def changed_paths(self, commit):
        return fx.git(self.project, 'diff-tree', '--no-commit-id', '--name-status', '-r', f'{commit}~1',
                      commit).splitlines()

    def proposal(self):
        """The committed proposal: the work tree's file, which the commit wrote as its blob's bytes (no end-of-line
        conversion), checked equal to the blob's size and digest git reports."""
        data = (self.project / CHANGE_DIR / 'proposal.md').read_bytes()
        blob = fx.git(self.project, 'rev-parse', f'HEAD:{CHANGE_DIR}/proposal.md')
        self.assertEqual(int(fx.git(self.project, 'cat-file', '-s', blob)), len(data))
        self.assertEqual(fx.git(self.project, 'status', '--porcelain', '--', CHANGE_DIR), '')
        record, problems = C.intent._Parser(data).parse()
        self.assertEqual(problems, [])
        return data, record


class OneMessageOneChange(Rig):
    def test_one_message_yields_exactly_one_intent_change(self):
        answer = self.captured()
        commits = self.commits()
        self.assertEqual(len(commits), 2)
        self.assertEqual(commits[1], self.base)
        self.assertEqual(answer['commit'], commits[0])
        self.assertTrue(answer['created'])
        self.assertEqual((answer['change'], answer['receipt'], answer['project']),
                         ('add-slugify', f'owner-ui/intent-capture/v1/{self.thread_id}/Req0001', 'aieh-d1-demo'))
        self.assertEqual(self.changed_paths(answer['commit']),
                         [f'A\t{CHANGE_DIR}/.openspec.yaml', f'A\t{CHANGE_DIR}/proposal.md'])
        self.assertEqual(fx.git(self.project, 'status', '--porcelain', '--untracked-files=all'), '')
        self.assertEqual((self.project / CHANGE_DIR / '.openspec.yaml').read_bytes(),
                         b'schema: intent-driven\ncreated: 2026-11-16\n')
        message = fx.git(self.project, 'log', '-1', '--format=%B', answer['commit'])
        self.assertTrue(f'Intent-Capture: {answer["receipt"]}' in message.splitlines())
        reservation, events = self.receipt()
        self.assertEqual(reservation.state, 'confirmed')
        self.assertEqual([e.to_state for e in events], ['reserved', 'dispatched', 'confirmed'])
        self.assertEqual(json.loads(events[-1].detail_json),
                         {'commit': answer['commit'], 'capturedBySession': self.record.session_id})
        intent = json.loads(reservation.intent_json)
        self.assertEqual((intent['messageSha256'], intent['messageSession'], intent['component']),
                         (sha(REQUEST), self.record.session_id, 'owner-host-capture@1.0.0'))

    def test_author_and_committer_are_the_commissioning_user_s_identity(self):
        commit = self.captured()['commit']
        self.assertEqual(fx.git(self.project, 'log', '-1', '--format=%an <%ae>%n%cn <%ce>', commit).splitlines(),
                         [IDENTITY, IDENTITY])
        self.assertTrue('localhost.invalid' not in fx.git(self.project, 'cat-file', '-p', commit))

    def test_a_retry_a_restart_or_a_reconnect_creates_no_second_change(self):
        first = self.captured()
        after = self.state()
        self.assertEqual(self.captured(), {**first, 'created': False})            # a retry
        self.build()                                                               # a restart of the process
        self.assertEqual(self.captured(), {**first, 'created': False})
        credential, _ = self.scratch.enroll(at=NOW)                                # a reconnect, a new session
        after = self.state()
        status, answer = self.capture(credential=credential)
        self.assertEqual((status, answer), (200, {**first, 'created': False}))
        self.assertEqual(self.state(), after)
        self.assertEqual(len(self.commits()), 2)


class TheRecord(Rig):
    def setUp(self):
        super().setUp()
        self.commit = self.captured()['commit']
        self.data, self.record_ = self.proposal()
        self.content = self.store.message_content(self.thread_id, 'Req0001')

    def item(self, item_id):
        return self.record_.items[item_id]

    def test_the_original_quote_s_span_verifies_against_the_stored_message(self):
        q1 = self.item('Q1')
        self.assertEqual(q1.quote, self.content)
        reference = C.lineage.parse(q1.fields['source'])
        self.assertIsInstance(reference, C.lineage.MessageRef)
        self.assertEqual((reference.thread, reference.message, reference.span),
                         (self.thread_id, 'Req0001', (0, len(self.content))))
        self.assertTrue(C.lineage.check_message_content(reference, self.content).resolved)
        self.assertEqual(C.lineage.span_bytes(reference, self.content), self.content)
        altered = self.content.replace(b'slugify', b'slugifY', 1)
        self.assertEqual(C.lineage.check_message_content(reference, altered).code, 'SPAN_DIGEST_MISMATCH')

    def test_each_owner_stated_item_is_an_exact_span_of_the_message_attributed_to_owner(self):
        expected = {'O1': OBJECTIVE, 'AC1': CRITERIA[0], 'AC2': CRITERIA[1], 'M1': SUGGESTION}
        for item_id, text in expected.items():
            with self.subTest(item=item_id):
                fields = self.item(item_id).fields
                self.assertEqual(fields['statement'], text)
                self.assertEqual(self.content.count(text.encode('utf-8')), 1)
                self.assertEqual((fields['attributed_to'], fields['source']), ('owner', 'Q1'))
        owner_items = [i for i in self.record_.items.values() if i.fields.get('attributed_to') == 'owner']
        self.assertEqual(sorted(i.id for i in owner_items), ['AC1', 'AC2', 'M1', 'O1', 'Q1'])
        self.assertEqual(self.record_.header['normalized_by'], 'agent:owner-host-capture@1.0.0')

    def test_a_suggestion_is_a_hypothesis_never_the_objective(self):
        m1, h1 = self.item('M1').fields, self.item('H1').fields
        self.assertEqual((m1['claim_type'], m1['authority'], m1['hypothesis']), ('hypothesis', 'proposed', 'H1'))
        self.assertEqual(h1, {'statement': 'Applying M1 achieves O1.', 'claim_type': 'hypothesis',
                              'attributed_to': 'agent:owner-host-capture@1.0.0', 'source': 'M1',
                              'authority': 'proposed'})
        self.assertEqual([i.id for i in self.record_.sections['Objective']], ['O1'])
        for item in self.record_.sections['Objective'] + self.record_.sections['Acceptance Criteria']:
            self.assertTrue(SUGGESTION not in item.fields['statement'], item.id)
        self.assertEqual(self.record_.sections['Binding Constraints'], [])
        # the only statements the capture wrote are the Hypotheses
        agent = [i.id for i in self.record_.items.values() if i.fields.get('attributed_to', '').startswith('agent:')]
        self.assertEqual(agent, ['H1'])

    def test_the_change_passes_check_intent_record_with_the_store_s_bytes_as_the_source(self):
        source = self.work / 'message.bin'
        source.write_bytes(self.store.message_content(self.thread_id, 'Req0001'))
        proposal = self.work / 'proposal.md'
        proposal.write_bytes(self.data)
        reference = self.item('Q1').fields['source']
        result = subprocess.run([sys.executable, '-I', '-B', str(CHECKER), str(proposal), '--source',
                                 f'{reference}={source}'], capture_output=True, text=True, encoding='utf-8',
                                timeout=T.WAIT_CEILING_S, stdin=subprocess.DEVNULL)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(result.stdout.startswith('PASS '), result.stdout)
        # the falsifier: the same record against bytes that are not the stored message's
        source.write_bytes(self.store.message_content(self.thread_id, 'Req0001').replace(b'slug', b'slog'))
        result = subprocess.run([sys.executable, '-I', '-B', str(CHECKER), str(proposal), '--source',
                                 f'{reference}={source}'], capture_output=True, text=True, encoding='utf-8',
                                timeout=T.WAIT_CEILING_S, stdin=subprocess.DEVNULL)
        self.assertEqual(result.returncode, 1)
        self.assertTrue('quote-not-in-source' in result.stdout, result.stdout)

    def test_the_openspec_headings_are_present_and_why_is_within_openspec_s_bounds(self):
        text = self.data.decode('utf-8')
        for heading in ('## Intent Record', '## Why', '## What Changes', '## Capabilities', '## Impact'):
            self.assertEqual(text.count(f'\n{heading}\n'), 1, heading)
        why = text.split('\n## Why\n', 1)[1].split('\n## ', 1)[0].strip()
        self.assertTrue(50 <= len(why) <= 1000, len(why))


class OriginatesEdge(Rig):
    """The lineage traversal from the accepted objective: its originates edge leaves the captured message."""

    OUTCOME = '6a1f0c2e-3b4d-4e5f-8a9b-0c1d2e3f4a5b'

    def test_the_statement_to_objective_originates_edge_resolves_to_the_message(self):
        commit = self.captured()['commit']
        owner = T._load('acceptance_recorder', T.REPO / 'integrations' / 'owner' / 'acceptance_recorder.py')
        challenge = owner.prepare(self.project, 'add-slugify', 'O1', now=NOW, nonce='c1' * 16)
        statement = {'text': 'SYNTHETIC FIXTURE, not an Owner decision: I accept O1 of add-slugify as written.',
                     'attributedTo': 'owner', 'channel': 'main-session',
                     'reference': 'conversation:fixture-owner/message-2'}
        owner.record(self.project, challenge, statement, recorded_by='agent:fixture-transcriber',
                     identity='Synthetic Recorder <recorder@example.invalid>', now=NOW,
                     new_outcome=lambda: self.OUTCOME, new_decision_id=lambda: '1b2c3d4e-5f60-4718-9a2b-3c4d5e6f7a8b')
        self.assertEqual(self.commits()[1], commit)
        trace = T._load('lineage_trace', T.REPO / 'integrations' / 'lineage' / 'lineage_trace.py')
        registry = trace.resolve_mod.build_registry(project=self.project, conversations=self.scratch.dir / CS.DB_NAME)
        projection = trace.trace(f'outcome:{self.OUTCOME}', trace.Authorities(registry), project=self.project)
        q1 = self.proposal()[1].items['Q1'].fields['source']
        edges = [e for e in projection['edges'] if e['relation'] == 'originates']
        self.assertEqual([(e['from'], e['to']) for e in edges], [(q1, f'outcome:{self.OUTCOME}')])
        self.assertEqual([p.get('via') for p in edges[0]['provenance']], ['Q1'])
        (node,) = [n for n in projection['nodes'] if n['reference'] == q1]
        self.assertEqual((node['kind'], node['resolution']['outcome'], node['authority_mode']),
                         ('message', 'resolved', 'authoritative'))
        self.assertEqual([q['outcome'] for q in node['quotes']], ['resolved'])
        self.assertFalse([u for u in projection['uncertainties'] if u['reference'] == q1])


class Refusals(Rig):
    def test_a_request_whose_bytes_differ_from_the_stored_message_is_refused_and_changes_nothing(self):
        for digest in (sha(REQUEST + ' '), sha(REQUEST.replace('slugify', 'slugifY')), '0' * 64):
            with self.subTest(digest=digest):
                answer = self.refused('CAPTURE_MESSAGE_MISMATCH', 409, digest=digest)
                self.assertTrue(answer['remedy'])
        self.assertFalse(self.receipts.exists())
        self.assertEqual(self.commits(), [self.base])

    def test_a_malformed_request_body_is_refused(self):
        for body in ({'sha256': sha(REQUEST).upper()}, {'sha256': sha(REQUEST), 'change': 'x'}, {}):
            with self.subTest(body=body):
                self.refused('REQUEST_INVALID', 400, body=body)

    def test_a_reply_is_not_a_statement(self):
        self.store.append_message(self.thread_id, {'parentId': 'Req0001', 'message': {
            'id': 'Rep0001', 'role': 'assistant', 'status': {'type': 'complete'},
            'content': [{'type': 'text', 'text': REQUEST}]}}, session_id=self.record.session_id, at=T.stamp(NOW))
        digest = self.store.message(self.thread_id, 'Rep0001').sha256
        self.refused('CAPTURE_NOT_A_STATEMENT', 409, message_id='Rep0001', digest=digest)

    def test_an_unknown_thread_or_message_answers_the_store_s_code(self):
        self.refused('MESSAGE_NOT_FOUND', 404, message_id='Nope000', digest=sha(REQUEST))
        status, answer = T.call(self.app, 'POST', '/threads/00000000-0000-4000-8000-000000000000/messages/Req0001'
                                '/capture', (T.HOST, (S.HEADER, self.credential), JSON),
                                body=json.dumps({'sha256': sha(REQUEST)}).encode())[0::2]
        self.assertEqual((status, T.code_of(answer)), (404, 'THREAD_NOT_FOUND'))

    def test_the_layout_is_parsed_strictly_and_a_request_it_cannot_express_is_refused(self):
        cases = {
            'plain chat': 'Please add a slugify function.',
            'carriage return': REQUEST.replace('\n', '\r\n'),
            'trailing line break': REQUEST + '\n',
            'blank line': REQUEST.replace('\nAcceptance', '\n\nAcceptance'),
            'no criterion': 'Change: add-slugify\nObjective: x\nAcceptance criteria:',
            'criterion after suggestion': REQUEST + '\n- late criterion',
            'unknown line': REQUEST + '\nNote: something else',
            'change not kebab': REQUEST.replace('add-slugify', 'Add_Slugify'),
            'change archive': REQUEST.replace('add-slugify', 'archive'),
            'empty objective': REQUEST.replace(f'Objective: {OBJECTIVE}', 'Objective: '),
            'padded criterion': REQUEST.replace(f'- {CRITERIA[0]}', f'-  {CRITERIA[0]}'),
            'trailing space': REQUEST.replace(OBJECTIVE, OBJECTIVE + ' '),
            'line separator': REQUEST.replace('café', 'café '),
            'control character': REQUEST.replace('café', 'café\x07'),
            'label case': REQUEST.replace('Objective:', 'objective:'),
        }
        for n, (name, text) in enumerate(cases.items(), 2):
            with self.subTest(case=name):
                message_id = f'Bad{n:04d}'
                self.append(message_id, text)
                self.refused('CAPTURE_LAYOUT_INVALID', 422, message_id=message_id)
        self.assertEqual(self.commits(), [self.base])

    def test_every_line_of_a_valid_layout_is_accepted_without_suggestions_or_with_several(self):
        request = C.parse_request(b'Change: a\nObjective: o\nAcceptance criteria:\n- c\tc')
        self.assertEqual((request.change, request.objective.text, [c.text for c in request.criteria],
                          request.suggestions), ('a', 'o', ['c\tc'], ()))
        request = C.parse_request(REQUEST.encode() + b'\nSuggestion: second')
        self.assertEqual([s.text for s in request.suggestions], [SUGGESTION, 'second'])

    def test_an_existing_change_name_is_refused_and_nothing_is_reserved(self):
        fx.write(self.project, {f'{CHANGE_DIR}/proposal.md': b'# Proposal\n'})
        self.base = fx.commit_all(self.project, 'someone else\'s change')
        self.refused('CAPTURE_CHANGE_EXISTS', 409)
        self.assertFalse(self.receipts.exists())

    def test_an_absent_or_invalid_project_configuration_is_refused(self):
        self.build(config=None)
        self.capturer.raw_config = None
        self.refused('CAPTURE_PROJECT_UNCONFIGURED', 503)
        bad = [[], {**self.config, 'extra': 1}, {**self.config, 'project_repository': 'relative/path'},
               {**self.config, 'project_repository_id': 'has space'}, {**self.config, 'backlog_command': ''},
               {k: v for k, v in self.config.items() if k != 'backlog_command'},
               {**self.config, 'git_identities': ['owner']}, '{not json']
        for raw in bad:
            with self.subTest(raw=raw):
                self.capturer.raw_config = raw
                self.refused('CAPTURE_CONFIG_INVALID', 503)

    def test_a_project_path_that_is_not_the_work_tree_root_is_refused(self):
        inner = self.project / 'inner'
        inner.mkdir()
        self.build({**self.config, 'project_repository': str(inner)})
        self.refused('CAPTURE_PROJECT_UNAVAILABLE', 503)
        self.build({**self.config, 'project_repository': str(self.work / 'absent')})
        self.refused('CAPTURE_PROJECT_UNAVAILABLE', 503)

    def test_without_a_capture_the_route_answers_unconfigured(self):
        app = A.create_app(lambda: self.store, clock=lambda: T.stamp(NOW))
        status, _, answer = T.call(app, 'POST', f'/threads/{self.thread_id}/messages/Req0001/capture',
                                   (T.HOST, (S.HEADER, self.credential), JSON),
                                   body=json.dumps({'sha256': sha(REQUEST)}).encode())
        self.assertEqual((status, T.code_of(answer)), (503, 'CAPTURE_PROJECT_UNCONFIGURED'))


class Identity(Rig):
    """Author and committer: the commissioning user's explicitly configured git identity, by principal."""

    def configure(self, identities):
        config = dict(self.config)
        if identities is None:
            config.pop('git_identities')
        else:
            config['git_identities'] = identities
        self.build(config)

    def test_an_absent_identity_is_refused_with_nothing_written_and_a_retry_succeeds_once_configured(self):
        for identities in (None, {}):
            with self.subTest(identities=identities):
                self.configure(identities)
                self.refused('COMMIT_IDENTITY_UNAVAILABLE', 503)
                self.assertFalse(self.receipts.exists())
        self.configure({'owner': IDENTITY})
        answer = self.captured()
        self.assertTrue(answer['created'])
        self.assertEqual(fx.git(self.project, 'log', '-1', '--format=%an <%ae>|%cn <%ce>').split('|'),
                         [IDENTITY, IDENTITY])

    def test_another_principal_s_identity_is_not_used(self):
        self.configure({'someone-else': OTHER_IDENTITY})
        self.refused('COMMIT_IDENTITY_UNAVAILABLE', 503)

    def test_a_placeholder_domain_is_refused(self):
        for identity in ('Test Owner <test-owner@owner.invalid>', 'Test Owner <test-owner@host.localhost>',
                         'Test Owner <test-owner@localhost>', 'Test Owner <test-owner@mail.example>',
                         'Test Owner <test-owner@lab.test>', 'Test Owner <test-owner@LOCALHOST.INVALID>'):
            with self.subTest(identity=identity):
                self.configure({'owner': identity})
                self.refused('COMMIT_IDENTITY_PLACEHOLDER', 503)

    def test_a_malformed_identity_is_refused(self):
        for identity in ('Test Owner', 'Test Owner <>', 'Test <Owner> <12345+test-owner@users.noreply.github.com>',
                         'Test Owner <12345+test-owner@users.noreply.github.com>\n',
                         ' Test Owner <12345+test-owner@users.noreply.github.com>',
                         'Test Owner <a@b@users.noreply.github.com>', 'Test Owner <test owner@x.com>',
                         'Test Owner<12345+test-owner@users.noreply.github.com>', 'Test Owner <owner@.com>', 7):
            with self.subTest(identity=identity):
                self.configure({'owner': identity})
                self.refused('COMMIT_IDENTITY_INVALID', 503)

    def test_a_noreply_identity_and_another_real_address_are_accepted(self):
        self.assertEqual(C.check_git_identity(IDENTITY), IDENTITY)
        configured = 'Test Owner <test-owner@mail.company.org>'
        self.assertEqual(C.check_git_identity(configured), configured)



class Records(unittest.TestCase):
    """The documented placeholder identity is one the capture refuses, and the shell knows every capture code."""

    def test_the_example_configuration_s_identity_is_a_placeholder_the_capture_refuses(self):
        import re
        text = (T.REPO / 'example_config.yml').read_text(encoding='utf-8')
        (value,) = re.findall(r'^ *#owner: "(.*)"$', text, re.M)
        with self.assertRaises(C.CaptureRefused) as caught:
            C.check_git_identity(value)
        self.assertEqual(caught.exception.code, 'COMMIT_IDENTITY_INVALID')
        readme = (T.PACKAGE / 'README.md').read_text(encoding='utf-8')
        self.assertTrue(f'owner: "{value}"' in readme, 'the README shows another placeholder')

    def test_the_shell_knows_every_capture_refusal(self):
        import re
        text = (T.REPO / 'apps' / 'owner-host' / 'src' / 'identity' / 'owner-session.ts').read_text(encoding='utf-8')
        block = text.split('export const CAPTURE_CODES = [', 1)[1].split('] as const;', 1)[0]
        self.assertEqual(sorted(re.findall(r'"([A-Z_]+)"', block)), sorted(set(C.STATUS) - {'REQUEST_INVALID'}))
        self.assertEqual(set(C.STATUS), set(C.REMEDIES))


class CrashWindows(Rig):
    """Slice 8: the same message after a crash between the receipt and the commit yields one change."""

    def crash_once(self, target, attribute):
        original = getattr(target, attribute)
        state = {'armed': True}

        def wrapper(*args, **kwargs):
            if state['armed']:
                state['armed'] = False
                raise Crash()
            return original(*args, **kwargs)
        return mock.patch.object(target, attribute, wrapper)

    def test_a_crash_between_the_receipt_and_the_commit_yields_one_change(self):
        with self.crash_once(C.ra.Repository, 'write_commit'), self.assertRaises(Crash):
            self.capturer.capture(self.store, self.thread_id, 'Req0001', sha(REQUEST), {'sessionId': 's'})
        reservation, _ = self.receipt()
        self.assertEqual(reservation.state, 'reserved')
        self.assertEqual(self.commits(), [self.base])
        answer = self.captured()
        self.assertTrue(answer['created'])
        self.assertEqual(len(self.commits()), 2)
        self.assertEqual(self.captured(), {**answer, 'created': False})

    def test_a_crash_after_the_branch_moved_before_the_receipt_is_confirmed_yields_one_change(self):
        with self.crash_once(C.Capture, '_confirm'), self.assertRaises(Crash):
            self.capturer.capture(self.store, self.thread_id, 'Req0001', sha(REQUEST), {'sessionId': 's'})
        reservation, _ = self.receipt()
        self.assertEqual(reservation.state, 'reserved')
        commits = self.commits()
        self.assertEqual(len(commits), 2)
        answer = self.captured()      # settled by reading the project repository, never written again
        self.assertEqual((answer['commit'], answer['created']), (commits[0], False))
        self.assertEqual(self.commits(), commits)
        _, events = self.receipt()
        self.assertEqual([(e.to_state, e.reason) for e in events][1:],
                         [('dispatched', 'settled by reading the project repository'),
                          ('confirmed', 'settled by reading the project repository')])

    def test_a_receipt_left_reserved_is_settled_from_history_below_later_commits(self):
        with self.crash_once(C.Capture, '_confirm'), self.assertRaises(Crash):
            self.capturer.capture(self.store, self.thread_id, 'Req0001', sha(REQUEST), {'sessionId': 's'})
        captured = self.commits()[0]
        fx.write(self.project, {'later.txt': b'later\n'})
        later = fx.commit_all(self.project, 'a later commit on top of the capture')
        answer = self.captured()
        self.assertEqual((answer['commit'], answer['created']), (captured, False))
        self.assertEqual(self.commits()[:2], [later, captured])

    def test_a_crash_between_dispatched_and_confirmed_yields_one_change(self):
        store_class = C.integration_store.IntegrationStore
        original = store_class.transition

        def transition(store, key, to_state, **kwargs):
            if to_state == 'confirmed' and not getattr(self, 'crashed', False):
                self.crashed = True
                raise Crash()
            return original(store, key, to_state, **kwargs)
        with mock.patch.object(store_class, 'transition', transition), self.assertRaises(Crash):
            self.capturer.capture(self.store, self.thread_id, 'Req0001', sha(REQUEST), {'sessionId': 's'})
        self.assertEqual(self.receipt()[0].state, 'dispatched')
        commits = self.commits()
        answer = self.captured()
        self.assertEqual((answer['commit'], answer['created']), (commits[0], False))
        self.assertEqual(self.commits(), commits)
        self.assertEqual(self.receipt()[0].state, 'confirmed')

    def test_a_refused_commit_leaves_the_receipt_reserved_and_the_same_message_is_captured_after_repair(self):
        fx.write(self.project, {f'{CHANGE_DIR}/proposal.md': b'untracked\n'})
        answer = self.capture()[1]
        self.assertEqual(answer['code'], 'CAPTURE_COMMIT_REFUSED')
        self.assertTrue('local-changes' in answer['detail'], answer['detail'])
        self.assertEqual(self.receipt()[0].state, 'reserved')
        self.assertEqual(self.commits(), [self.base])
        (self.project / CHANGE_DIR / 'proposal.md').unlink()
        self.assertTrue(self.captured()['created'])
        self.assertEqual(len(self.commits()), 2)

    def test_a_branch_that_moves_under_the_capture_is_read_again(self):
        original = C.ra.Repository.write_commit
        moved = []

        def write_commit(repo, files, message, **kwargs):
            if not moved:
                fx.write(self.project, {'other.txt': b'other\n'})
                moved.append(fx.commit_all(self.project, 'a concurrent commit'))
            return original(repo, files, message, **kwargs)
        with mock.patch.object(C.ra.Repository, 'write_commit', write_commit):
            answer = self.captured()
        commits = self.commits()
        self.assertEqual(commits[1:], [moved[0], self.base])
        self.assertEqual(answer['commit'], commits[0])


class NoModelNoSocket(Rig):
    """No model is called: the capture opens no socket and starts no process (an audit hook), and capture.py imports
    no model, inference or network client module."""

    EVENTS = ('socket.', 'subprocess.Popen', 'os.system', 'os.exec', 'os.posix_spawn', 'os.spawn', 'os.startfile',
              'urllib.Request', 'http.client.connect', 'webbrowser.open')

    def test_an_audited_capture_opens_no_socket_and_starts_no_process(self):
        seen, armed = [], []

        def hook(event, _args):
            if armed and event.startswith(self.EVENTS):
                seen.append(event)
        sys.addaudithook(hook)
        armed.append(True)
        try:
            answer = self.capturer.capture(self.store, self.thread_id, 'Req0001', sha(REQUEST),
                                           {'sessionId': self.record.session_id})
        finally:
            armed.clear()
        self.assertTrue(answer['created'])
        self.assertEqual(seen, [])

    def test_capture_imports_no_model_inference_or_network_module(self):
        import ast
        tree = ast.parse((T.PACKAGE / 'capture.py').read_text(encoding='utf-8'))
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
        self.assertEqual({n for n in names if n.endswith('.py')},
                         {'conversation_store.py', 'integration_store.py', 'lineage.py', 'check_intent_record.py'})
        text = (T.PACKAGE / 'capture.py').read_text(encoding='utf-8')
        for word in ('inference', 'broker', 'credential_provider', 'dispatch_inputs'):
            self.assertTrue(f'{word}.py' not in text and f"'{word}'" not in text, word)

    def test_the_capture_uses_only_local_repository_reads_and_the_commit(self):
        import ast
        tree = ast.parse((T.PACKAGE / 'capture.py').read_text(encoding='utf-8'))
        called = {node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call)
                  and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
                  and node.func.value.id == 'repo'}
        self.assertEqual(called, {'head', 'read', 'object_kind', 'write_commit', 'close'})
        self.assertEqual({node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call)
                          and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
                          and node.func.value.id == 'ra'}, {'open_repository'})


if __name__ == '__main__':
    unittest.main()
