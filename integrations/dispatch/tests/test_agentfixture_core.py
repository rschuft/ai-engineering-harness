"""Tests for the Agent Server fixture's cited core and its catalog (plan leaf E-01.4.2, slice 5c:
``integrations/agentfixture/``), offline.

Run from the repository root:

    python -I -B -m unittest discover -s integrations/dispatch/tests -p test_agentfixture_core.py -v

Shown here:

* the catalog's provenance rows are, cell for cell, the README's provenance table (``TableBinding``);
* the table's rules: every field of one of E-01.7's four classes, the one source-derived entry, or not served; nothing
  read is clock-valued or not served; every observation cited to a committed record (F-04.2, F-04.1c, the D1 run
  record), and each observed value found in the section it cites (``Rules``, ``Citations``);
* the core answers by route and state from the catalog only, labels every answer, refuses everything else with its
  label, and records in its call log what it received (``ByState``);
* SEED is answered by running the harness's own ``SEED_SCRIPT`` over the request's payload, once per conversation,
  and served only for the script's exit 0 (``Seed``);
* the read record notes each key read, by catalog answer and path, with its reader, and fails closed: every other
  read of a whole answer, or change of it, is an opaque read and raises (``Recording``).
"""
from pathlib import Path
import copy
import gzip
import hashlib
import importlib.util
import io
import json
import re
import sys
import tarfile
import unittest

CATEGORY = 'integration'

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]


def _load(name, path):
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module


AC = _load('agentfixture_core', REPO / 'integrations' / 'agentfixture' / 'core.py')
README = REPO / 'integrations' / 'agentfixture' / 'README.md'
CATALOG = AC.load_catalog()
ROWS = CATALOG['provenance']
CLASSES = {'observation', 'echo', 'pinned-rule', 'label', 'source-derived', 'none'}
CID = '055b27f3-903e-5eb9-8758-197c1029ade7'          # D1's conversation id (D1 run record section 2)
F042_CID = '929f0d8a-f3d8-4da3-8ac3-9d0017709d71'
MESSAGE = {'role': 'user', 'content': [{'type': 'text', 'text': 'Implement the change as designed.'}], 'run': True}
SCENARIO = "scenario: the core's transition (by call count)"
RANGE = '90816fa..9684d9c'
QUOTES = "'" * 3
UPSTREAM = r'`(sdk|as):openhands/[a-z_/]+\.py:\d+(-\d+)?`'


def row(answer, field):
    (found,) = [r for r in ROWS if (r['answer'], r['field']) == (answer, field)]
    return found


def table_rows(text):
    start = text.index('## The provenance table')
    end = text.index('\n## ', start + 5)
    rows = []
    for line in text[start:end].splitlines():
        if line.startswith('| `'):
            answer, field, klass, citation, determined, read, served, marks = [c.strip() for c in line[1:-1].split('|')]
            read, _, by = read.partition(': ')
            rows.append({'answer': answer.strip('`'), 'field': field, 'class': klass, 'citation': citation,
                         'determinedBy': determined, 'read': read == 'yes',
                         'readBy': [b.strip().strip('`') for b in by.split(',')] if by else [],
                         'served': served == 'yes', 'marks': marks})
    return rows


def section(record, heading):
    """The text of RECORD from the line starting with HEADING to the next heading of any level."""
    text = (REPO / record).read_text(encoding='utf-8')
    start = text.index(heading)
    following = re.search(r'\n#{2,4} ', text[start + len(heading):])
    return text[start:start + len(heading) + (following.start() if following else len(text))]


def json_block(text):
    return json.loads(re.search(r'```json\n(.*?)\n```', text, re.S).group(1))


class TableBinding(unittest.TestCase):
    category = 'unit'

    def test_the_catalog_rows_are_the_readme_table_cell_for_cell(self):
        self.assertEqual(ROWS, table_rows(README.read_text(encoding='utf-8')))
        self.assertGreater(len(ROWS), 60)

    def test_every_answer_has_rows_and_every_answer_with_rows_has_values(self):
        self.assertEqual({r['answer'] for r in ROWS}, set(CATALOG['answers']))


class Rules(unittest.TestCase):
    category = 'unit'

    def test_every_field_has_a_class_and_only_a_classed_field_is_served(self):
        for row in ROWS:
            with self.subTest(answer=row['answer'], field=row['field']):
                self.assertIn(row['class'], CLASSES)
                self.assertEqual(row['served'], row['class'] != 'none')
                if row['class'] == 'none':
                    self.assertFalse(row['read'])
                    self.assertTrue(row['citation'].startswith('not served:'))

    def test_nothing_read_is_clock_valued_or_not_served(self):
        for row in ROWS:
            with self.subTest(answer=row['answer'], field=row['field']):
                if 'clock-valued' in row['marks']:
                    self.assertEqual((row['class'], row['determinedBy'], row['read']), ('observation', 'the clock',
                                                                                         False))
                if row['read']:
                    self.assertTrue(row['served'])
                    self.assertNotIn('clock-valued', row['marks'])

    def test_at_most_one_source_derived_entry_cited_to_the_locked_wheels(self):
        derived = [r for r in ROWS if r['class'] == 'source-derived' or 'source-derived' in r['marks']]
        self.assertEqual({r['answer'] for r in derived}, {'message-event'})
        for row in derived:
            with self.subTest(field=row['field']):
                if row['class'] == 'source-derived':
                    self.assertRegex(row['citation'], r'`(sdk|as):openhands/[a-z_/]+\.py:\d+(-\d+)?`')
                    self.assertEqual(row['marks'], 'source-derived')
        self.assertEqual(sorted(CATALOG['upstream']), ['as', 'sdk'])
        locked = json.loads((REPO / 'composition' / 'lock' / 'components.lock.json').read_text(encoding='utf-8'))
        text = json.dumps(locked)
        for wheel in CATALOG['upstream'].values():
            self.assertIn(wheel['sha256'], text)
        self.assertEqual(AC.SOURCE_DERIVED, ('source', 'llm_message', 'llm_message.content'))

    def test_the_pinned_rule_is_harness_code_the_production_path_runs(self):
        (row,) = [r for r in ROWS if r['class'] == 'pinned-rule' and r['field'] == '`body.stdout`']
        self.assertIn('integrations/dispatch/attempt_run.py', row['citation'])
        # the production path's SEED builder sends exactly this script (attempt_run.build_seed)
        self.assertIn("| python -c '{SEED_SCRIPT}' ", AC.ATTEMPT_RUN.read_text(encoding='utf-8'))

    def test_every_observation_cites_a_committed_record(self):
        for row in ROWS:
            if row['class'] == 'observation':
                with self.subTest(answer=row['answer'], field=row['field']):
                    self.assertRegex(row['citation'], r'(F-04\.2 §4\.\d|F-04\.1c §3|D1 §5)')

    def test_every_row_read_names_the_dispatch_functions_that_read_it(self):
        """Dispatch 14, N4: the Read column's "where" (bound to the recorded readers by test_read_binding)."""
        for r in ROWS:
            with self.subTest(answer=r['answer'], field=r['field']):
                self.assertEqual(bool(r['readBy']), r['read'])
                for by in r['readBy']:
                    module, _, function = by.partition('.')
                    self.assertTrue((REPO / 'integrations' / 'dispatch' / f'{module}.py').is_file(), by)
                    self.assertRegex(function, r'^[A-Za-z_][A-Za-z0-9_.]*$')

    def test_the_server_timeouts_are_not_served(self):
        """Dispatch 14 (follow-up): the two timeouts come from openhands-tools, not among the extracted wheels, and the
        profile's environment changed since F-04.1c; unread, so not served."""
        fields = ('runtime_idle_timeout_seconds', 'max_foreground_terminal_timeout_seconds')
        for name in fields:
            with self.subTest(field=name):
                r = row('server-info', f'`body.{name}`')
                self.assertEqual((r['class'], r['read'], r['served'], r['readBy']), ('none', False, False, []))
                for text in ('openhands-tools', 'not among the extracted wheels', 'LITELLM_LOCAL_MODEL_COST_MAP',
                             '574d8db', RANGE):
                    self.assertIn(text, r['citation'])
        entry = CATALOG['answers']['server-info']
        self.assertTrue(set(fields) <= set(entry['recorded']))
        self.assertFalse(set(fields) & set(entry['body']))
        core = AC.AgentServerCore()
        self.addCleanup(core.close)
        self.assertFalse(set(fields) & set(core('GET', '/server_info')['body']))

    def test_the_runtime_stops_body_is_the_production_paths_rule_for_no_content(self):
        """Dispatch 14, S1: built on the observed 204, cited to the probe's and the transport's own code by line."""
        stop = row('runtime-stop', '`body`')
        self.assertEqual((stop['class'], stop['marks'], stop['read'], stop['served']), ('pinned-rule', '', True, True))
        self.assertIn('the observed `204`', stop['citation'])
        self.assertIsNone(CATALOG['answers']['runtime-stop']['body'])
        cited = {'tools/guest.py': (9128, 'json.loads(text) if text else None'),
                 'integrations/dispatch/guest_transport.py': (192, "response.get('body')")}
        for path, (line, code) in cited.items():
            with self.subTest(path=path):
                self.assertIn(f'`{path}:{line}`', stop['citation'])
                self.assertIn(f'`{code}`', stop['citation'])
                lines = (REPO / path).read_text(encoding='utf-8').splitlines()
                self.assertIn(code, lines[line - 1])
        lines = (REPO / 'tools' / 'guest.py').read_text(encoding='utf-8').splitlines()
        start = lines.index('API_PROBE = r' + QUOTES + 'import base64, errno, hashlib, http.client, json, os, re, sys, '
                            'time')
        end = next(i for i in range(start + 1, len(lines)) if lines[i].startswith(QUOTES))
        self.assertLess(start, 9128 - 1)
        self.assertLess(9128 - 1, end, 'the cited line is API_PROBE\'s')
        self.assertNotIn('see the note', README.read_text(encoding='utf-8'))

    def test_the_creates_status_is_determined_by_what_the_core_checks(self):
        """Dispatch 14, S3: the determining inputs are those the core checks; the inputs in which the matrix's create
        differs from D1's are shown, by the pinned source, not to determine the status."""
        status = row('create-new', '`status`')
        self.assertEqual(status['determinedBy'], 'a `conversation_id` that is a UUID the server does not hold')
        self.assertIn('the `acp_model` value and the secret values', status['citation'])
        self.assertGreaterEqual(len(re.findall(UPSTREAM, status['citation'])), 4)
        self.assertIn('slice 9', README.read_text(encoding='utf-8').split('**What determines the create')[1][:3000])

    def test_the_cores_own_transitions_are_marked_as_its_scenario(self):
        """Dispatch 14, S4: finished and the non-empty events page are the fixture's transition, no turn run."""
        marked = {(r['answer'], r['field']) for r in ROWS if SCENARIO in r['marks']}
        self.assertEqual(marked, {('conversation', '`body.execution_status`'), ('events', '`body.items`')})
        for answer, field in marked:
            with self.subTest(answer=answer):
                r = row(answer, field)
                self.assertEqual(r['class'], 'observation', 'the cited value stays the observation')
                self.assertIn("the fixture's transition on the message", r['determinedBy'])
                self.assertIn('no turn runs', r['determinedBy'])

    def test_each_inferred_input_cites_the_source_that_shows_it(self):
        """Dispatch 14, N2: an observation served for inputs other than its observed run's cites why they agree."""
        cases = {('conversation-absent', '`status`'): 'a conversation never created answers alike',
                 ('events', '`body.items`'): "an ACP agent's log is as empty before its message, SEED included",
                 ('server-info', '`body.usable_tools`'): RANGE}
        for (answer, field), text in cases.items():
            with self.subTest(answer=answer, field=field):
                r = row(answer, field)
                self.assertIn(text, r['citation'] + ' ' + r['determinedBy'])
                self.assertGreaterEqual(len(re.findall(UPSTREAM + '|`:\\d+(-\\d+)?`', r['citation'] + ' '
                                                       + r['determinedBy'])), 2)
        config = [r for r in ROWS if r['answer'] == 'server-info' and r['field'] in (
            '`body.conversation_runtime`', '`body.available_conversation_runtimes`', '`body.app_backend_ingress_url`',
            '`body.capabilities`', '`body.usable_tools`')]
        self.assertEqual(len(config), 5)
        for r in config:
            with self.subTest(field=r['field']):
                self.assertIn(RANGE, r['determinedBy'])
        self.assertIn('the browser', row('server-info', '`body.usable_tools`')['determinedBy'])


class Citations(unittest.TestCase):
    """Each observed value is found in the committed section it cites."""
    category = 'unit'

    def test_server_info_is_f_04_1c_section_3_complete(self):
        recorded = json_block(section('evidence/F-04.1c-agent-server.md', '## 3. Run 1'))
        entry = CATALOG['answers']['server-info']
        self.assertEqual(entry['recorded'], recorded)
        # the served body is the recorded block less exactly the rows not served
        unserved = {path[len('body.'):] for r in ROWS if r['answer'] == 'server-info' and not r['served']
                    for path in AC.field_paths(r['field'])}
        self.assertEqual(entry['body'], {k: v for k, v in recorded.items() if k not in unserved})

    def test_the_create_answer_is_f_04_2_section_4_2_and_its_request_the_profiles_fixture(self):
        recorded = json_block(section('evidence/F-04.2-conversation-lifecycle.md', '### 4.2 (b) Create'))
        entry = CATALOG['answers']['create-new']
        self.assertEqual({'id': F042_CID, **entry['clock'], **entry['equalRequest'], **entry['ownRequest']}, recorded)
        fixture = json.loads((REPO / 'profiles' / 'strong-windows-qemu-whpx' / 'agent-server' /
                              'conversation-create.json').read_text(encoding='utf-8'))
        self.assertEqual(entry['observedRequest'], fixture)

    def test_the_server_configuration_over_the_range_differs_only_by_the_browser(self):
        """Dispatch 14, N2: F-04.1c's configuration as written and the profile's now differ only by enable_browser
        false, and F-04.1c's image had no browser (a tag not the stock repository's, its browser flag unset)."""
        then = json_block(section('evidence/F-04.1c-agent-server.md', '### Configuration as written'))
        profile = json.loads((REPO / 'profiles' / 'strong-windows-qemu-whpx' / 'profile.json').read_text(
            encoding='utf-8'))
        now = profile['provisioning']['agent_server']['config']['content']
        self.assertEqual({k for k in set(then) | set(now) if then.get(k) != now.get(k)}, {'enable_browser'})
        self.assertIs(now['enable_browser'], False)
        self.assertNotIn('conversation_image_has_browser', then)
        self.assertFalse(then['conversation_image'].startswith('ghcr.io/openhands/agent-server'))
        self.assertEqual((then['conversation_runtime'], then['conversation_runtime_selectable']), ('docker', False))
        self.assertNotIn('app_backend_public_url', then)
        self.assertIn('## 3. Run 1 (`f041c-a`, commit `90816fa`)', (REPO / 'evidence' / 'F-04.1c-agent-server.md')
                      .read_text(encoding='utf-8'))

    def test_each_state_value_is_in_its_cited_section(self):
        f042 = 'evidence/F-04.2-conversation-lifecycle.md'
        d1 = 'evidence/D1-run-2026-11-16.md'
        cases = [
            (f042, '### 4.3', ['`execution_status` idle', '{"runtime_status": "available", "can_resume": true}']),
            (f042, '### 4.4', ['{"items": [], "next_page_id": null}']),
            (f042, '### 4.6', ['returned **204**', '{"runtime_status": "missing", "can_resume": true}']),
            (f042, '### 4.9', ['`GET` returns 404']),
            (d1, '## 5. The steps', ['`execution_status` `finished`', 'count 1', 'the outer count 0',
                                     '5 `MessageEvent`', 'runtime `available`', '`POST .../events` 200',
                                     '`POST .../bash/execute_bash_command` 200 (SEED)', '`DELETE .../runtime` 204']),
            ('evidence/F-04.1c-agent-server.md', '## 3. Run 1', ['`/api/conversations/count`: 200 with the key (body '
                                                                 '`0`)']),
        ]
        for record, heading, texts in cases:
            found = ' '.join(section(record, heading).split())
            for text in texts:
                with self.subTest(record=record, text=text):
                    self.assertIn(text, found)
        answers = CATALOG['answers']
        self.assertEqual((answers['conversation']['execution_status'], answers['runtime']['runtime_status'],
                          answers['count']['body']), (['idle', 'finished'], ['available', 'missing'], [0, 1]))
        self.assertEqual((answers['message-event']['kind'], answers['events']['next_page_id']), ('MessageEvent', None))


class ByState(unittest.TestCase):
    category = 'unit'

    def setUp(self):
        self.core = AC.AgentServerCore()
        self.addCleanup(self.core.close)

    def body(self, cid=CID, **extra):
        return {'conversation_id': cid, 'conversation_runtime': 'docker', **extra}

    def refused(self, answer):
        self.assertEqual((answer['status'], answer['fixture']['answer']), (501, 'refusal'))
        self.assertNotIn('body', answer)
        return answer['fixture']['refused']

    def test_every_answer_is_labelled_and_serves_only_listed_fields(self):
        answer = self.core('GET', '/server_info')
        self.assertEqual((answer['status'], answer['body']['version']), (200, '1.60.1'))
        self.assertEqual(answer['fixture'], {'fixture': 'ai-engineering-harness/agentfixture', 'authority': 'fixture',
                                             'answer': 'server-info'})
        self.assertEqual(answer['body'], CATALOG['answers']['server-info']['body'])

    def test_a_create_serves_the_id_and_the_clock_valued_time_and_more_only_for_an_equal_request(self):
        answer = self.core('POST', '/api/conversations', self.body(secrets={'X': {'kind': 'StaticSecret'}}))
        self.assertEqual((answer['status'], answer['body']), (201, {'id': CID,
                                                                    'created_at': '2026-11-07T07:25:46.090747Z'}))
        f042 = copy.deepcopy(CATALOG['answers']['create-new']['observedRequest'])
        other = dict(f042, conversation_id='11111111-2222-4333-8444-555555555555')
        answer = self.core('POST', '/api/conversations', other)
        self.assertEqual(answer['body']['execution_status'], 'idle')
        self.assertEqual(answer['body']['id'], other['conversation_id'])
        self.assertNotIn('persistence_dir', answer['body'], 'determined by the id: F-04.2\'s own request only')
        answer = self.core('POST', '/api/conversations', f042)
        self.assertEqual(answer['body']['persistence_dir'], '/var/openhands/conversations/' + F042_CID.replace('-', ''))
        self.assertIn('a create of a conversation the server holds', self.refused(
            self.core('POST', '/api/conversations', f042)))

    def test_the_conversation_its_count_runtime_message_and_events_by_state(self):
        self.assertEqual(self.core('GET', '/api/conversations/count')['body'], 0)
        absent = self.core('GET', f'/api/conversations/{CID}')
        self.assertEqual((absent['status'], 'body' in absent, absent['fixture']['answer']),
                         (404, False, 'conversation-absent'))
        self.core('POST', '/api/conversations', self.body())
        self.assertEqual(self.core('GET', '/api/conversations/count')['body'], 1)
        self.assertEqual(self.core('GET', f'/api/conversations/{CID}')['body'], {'id': CID, 'execution_status': 'idle'})
        events = self.core('GET', f'/api/conversations/{CID}/events/search')
        self.assertEqual((events['body'], 'sourceDerived' in events['fixture']), ({'items': [], 'next_page_id': None},
                                                                                  False))
        sent = self.core('POST', f'/api/conversations/{CID}/events', copy.deepcopy(MESSAGE))
        self.assertEqual((sent['status'], 'body' in sent), (200, False))
        self.assertEqual(self.core('GET', f'/api/conversations/{CID}')['body']['execution_status'], 'finished')
        events = self.core('GET', f'/api/conversations/{CID}/events/search')
        self.assertEqual(events['body'], {'items': [{'kind': 'MessageEvent', 'source': 'user', 'llm_message': {
            'content': [{'text': 'Implement the change as designed.'}]}}], 'next_page_id': None})
        self.assertEqual(events['fixture']['sourceDerived'], ['message-event.source', 'message-event.llm_message',
                                                              'message-event.llm_message.content'])
        self.assertIn('second message', self.refused(self.core('POST', f'/api/conversations/{CID}/events',
                                                               copy.deepcopy(MESSAGE))))
        self.assertEqual(self.core('GET', f'/api/conversations/{CID}/runtime')['body'],
                         {'runtime_status': 'available', 'can_resume': True})
        stop = self.core('DELETE', f'/api/conversations/{CID}/runtime')
        self.assertEqual((stop['status'], stop['body']), (204, None))
        self.assertEqual(self.core('GET', f'/api/conversations/{CID}/runtime')['body']['runtime_status'], 'missing')
        self.refused(self.core('DELETE', f'/api/conversations/{CID}/runtime'))
        self.core('POST', '/api/conversations', self.body('11111111-2222-4333-8444-555555555555'))
        self.assertIn('a count of 2', self.refused(self.core('GET', '/api/conversations/count')))

    def test_anything_else_is_refused_with_the_label(self):
        self.core('POST', '/api/conversations', self.body())
        cases = [('GET', '/api/conversations/search', None), ('DELETE', f'/api/conversations/{CID}', None),
                 ('GET', f'/api/conversations/{CID}/events/search?page_id=x', None),
                 ('GET', '/server_info?x=1', None), ('POST', f'/api/conversations/{CID}/events', {'role': 'user'}),
                 ('POST', f'/api/conversations/{CID}/bash/execute_bash_command', {'command': 'ls', 'cwd': '/workspace',
                                                                                  'timeout': 5}),
                 ('GET', '/alive', None), (None, None, None),
                 ('GET', '/api/conversations/not-a-uuid', None)]
        for method, path, body in cases:
            with self.subTest(method=method, path=path):
                self.refused(self.core(method, path, body))
        unknown = '11111111-2222-4333-8444-555555555555'
        for path in (f'/api/conversations/{unknown}/runtime', f'/api/conversations/{unknown}/events/search'):
            self.refused(self.core('GET', path))
        self.refused(self.core.answer('POST', f'/api/conversations/{CID}/bash/execute_bash_command',
                                      {'command': 'x', 'cwd': '/workspace', 'timeout': 5}, deliver={'part': 'bundle',
                                                                                                   'name': 'x'}))

    def test_a_create_is_answered_by_its_id_alone(self):
        """Dispatch 14, S3 (the review's probe_core): any body whose conversation_id is a UUID the core does not hold is
        answered 201, the D1 template with another model and other secret values included; the rest is unchecked."""
        template = json.loads((REPO / 'profiles' / 'strong-windows-qemu-whpx' / 'agent-server' / 'd1-create.json')
                              .read_text(encoding='utf-8'))
        ids = iter(f'11111111-2222-4333-8444-55555555555{n}' for n in range(6))
        secrets = {'CLAUDE_CODE_OAUTH_TOKEN': {'kind': 'StaticSecret', 'value': 'synthetic-a'}}
        for body in ({}, {'conversation_runtime': 'local', 'junk': [1]},
                     dict(template, secrets=secrets, secrets_encrypted=False),
                     dict(template, agent_settings=dict(template['agent_settings'], acp_model='syn-model-a'),
                          secrets={'CLAUDE_CODE_OAUTH_TOKEN': {'kind': 'StaticSecret', 'value': 'synthetic-b'}},
                          secrets_encrypted=False)):
            with self.subTest(keys=sorted(body)):
                cid = next(ids)
                answer = self.core('POST', '/api/conversations', dict(body, conversation_id=cid))
                self.assertEqual((answer['status'], answer['body']['id']), (201, cid))
        self.refused(self.core('POST', '/api/conversations', {'conversation_id': 'not-a-uuid'}))
        self.refused(self.core('POST', '/api/conversations', {'conversation_id': cid}))

    def test_the_message_finishes_the_conversation_at_that_call_with_no_turn(self):
        """Dispatch 14, S4: the fixture's transition happens on the message call itself (by call count)."""
        self.core('POST', '/api/conversations', self.body())
        before = len(self.core.calls)
        self.core('POST', f'/api/conversations/{CID}/events', copy.deepcopy(MESSAGE))
        self.assertEqual(len(self.core.calls), before + 1)
        held = self.core.conversations[CID]
        self.assertEqual((held['execution_status'], [e['kind'] for e in held['events']]), ('finished',
                                                                                          ['MessageEvent']))

    def test_the_call_log_records_what_the_core_received_and_only_that(self):
        self.core('GET', '/server_info')
        self.core.answer('POST', '/api/conversations', self.body())      # a dropped request: never received
        self.core('POST', '/api/conversations', self.body('11111111-2222-4333-8444-555555555555'))
        self.assertEqual([c[:2] for c in self.core.calls], [('GET', '/server_info'), ('POST', '/api/conversations')])
        self.assertEqual(len(self.core.creates), 1)


def seed_command(files, repository='aieh-d1-demo', script=None):
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode='w:gz', format=tarfile.PAX_FORMAT) as tar:
        for name, content in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
    payload = data.getvalue()
    gzip.decompress(payload)
    script = AC._attempt_run().SEED_SCRIPT if script is None else script
    digest = hashlib.sha256(payload).hexdigest()
    return {'command': f"printf %s '{payload.hex()}' | python -c '{script}' '/workspace/{repository}' '{digest}'",
            'cwd': '/workspace', 'timeout': 120}, digest


class Seed(unittest.TestCase):
    category = 'integration'

    def setUp(self):
        self.core = AC.AgentServerCore()
        self.addCleanup(self.core.close)
        self.core('POST', '/api/conversations', {'conversation_id': CID})
        self.path = f'/api/conversations/{CID}/bash/execute_bash_command'

    def test_seed_runs_the_harness_script_once_per_conversation(self):
        command, digest = seed_command({'a.txt': b'a', 'pkg/b.py': b'b'})
        answer = self.core('POST', self.path, command)
        self.assertEqual((answer['status'], answer['body']), (200, {'stdout': f'AIEH-SEED ok {digest} 2\n',
                                                                    'exit_code': 0}))
        self.assertEqual(sorted(p.name for p in (self.core.scratch() / CID / 'aieh-d1-demo').rglob('*')),
                         ['a.txt', 'b.py', 'pkg'])
        self.assertIn('a second SEED', self.core('POST', self.path, command)['fixture']['refused'])

    def test_a_command_that_is_not_the_harness_seed_is_refused_without_running(self):
        command, _ = seed_command({'a.txt': b'a'}, script=AC._attempt_run().SEED_SCRIPT + '#')
        self.assertEqual(self.core('POST', self.path, command)['fixture']['answer'], 'refusal')
        self.assertFalse((self.core.scratch() / CID).exists())

    def test_a_seed_whose_script_exits_other_than_0_is_refused(self):
        """Dispatch 14, N1 (the review's probe_seed): the script ran (exit 3, its digest refused), and no record
        observes a 200 with that exit, so the label refuses it."""
        command, digest = seed_command({'a.txt': b'a'})
        command['command'] = command['command'].replace(digest, '0' * 64)
        answer = self.core('POST', self.path, command)
        self.assertEqual((answer['status'], answer['fixture']['answer']), (501, 'refusal'))
        self.assertIn('exit is 3', answer['fixture']['refused'])
        self.assertNotIn('body', answer)
        self.assertTrue(self.core.conversations[CID]['seeded'])
        self.assertEqual(CATALOG['answers']['seed']['exit_code'], 0)
        self.assertIn('its exit `0`', row('seed', '`status`')['determinedBy'])


class Recording(unittest.TestCase):
    category = 'unit'

    def test_each_key_read_is_noted_by_answer_and_path(self):
        core = AC.AgentServerCore()
        plain = core('GET', '/server_info')
        self.assertIs(type(plain), dict)
        reads = AC.Reads()
        with AC.recording(reads):
            answer = core('GET', '/server_info')
            core('POST', '/api/conversations', {'conversation_id': CID})
            core('POST', f'/api/conversations/{CID}/events', copy.deepcopy(MESSAGE))
            events = core('GET', f'/api/conversations/{CID}/events/search')
        self.assertIs(AC.RECORDER, None)
        self.assertEqual(answer['body'].get('version'), '1.60.1')
        self.assertIsNone(answer.get('nothing'))
        copied = copy.deepcopy(events)
        [item] = copied['body']['items']
        self.assertEqual(item['llm_message']['content'][0]['text'], MESSAGE['content'][0]['text'])
        self.assertEqual(reads.to_json(), [
            {'answer': 'events', 'path': 'body', 'present': True, 'how': ['item']},
            {'answer': 'events', 'path': 'body.items', 'present': True, 'how': ['item']},
            {'answer': 'message-event', 'path': 'llm_message', 'present': True, 'how': ['item']},
            {'answer': 'message-event', 'path': 'llm_message.content', 'present': True, 'how': ['item']},
            {'answer': 'message-event', 'path': 'llm_message.content[].text', 'present': True, 'how': ['item']},
            {'answer': 'server-info', 'path': 'body', 'present': True, 'how': ['item']},
            {'answer': 'server-info', 'path': 'body.version', 'present': True, 'how': ['get']},
            {'answer': 'server-info', 'path': 'nothing', 'present': False, 'how': ['get']}])

    def recorded(self):
        core = AC.AgentServerCore()
        self.addCleanup(core.close)
        reads = AC.Reads()
        with AC.recording(reads):
            answer = core('GET', '/server_info')
        return answer, reads

    def test_the_recorded_reads_and_writes_keep_the_answer(self):
        answer, reads = self.recorded()
        body = answer['body']
        self.assertIsInstance(body, dict)
        self.assertEqual((len(body), bool(body)), (len(CATALOG['answers']['server-info']['body']), True))
        self.assertEqual(dict(body), CATALOG['answers']['server-info']['body'])
        self.assertEqual(json.loads(json.dumps(answer['body'])), CATALOG['answers']['server-info']['body'])
        self.assertEqual(list(reversed(body))[0], list(CATALOG['answers']['server-info']['body'])[-1])
        body['added'] = 1                      # a knob's write: not a read
        del body['added']
        self.assertEqual({**body}, CATALOG['answers']['server-info']['body'])
        self.assertEqual([r['how'] for r in reads.to_json() if r['path'] == 'body.version'],
                         [['keys', 'item', 'items', 'iter']])      # dict(), json.dumps, reversed
        self.assertFalse(any(h.startswith(AC.OPAQUE) for r in reads.to_json() for h in r['how']))

    def test_every_read_of_the_whole_answer_or_change_of_it_is_opaque_and_raises(self):
        """Dispatch 14, S2 (the review's probe_core): one negative control per operation class."""
        operations = {
            'equality': [('==', lambda b: b == {}), ('!=', lambda b: b != {}), ('==', lambda b: {} == b)],
            'text': [('repr', repr), ('str', str), ('format', lambda b: f'{b}'), ('format', lambda b: format(b, ''))],
            'union': [('|', lambda b: b | {}), ('|', lambda b: {} | b), ('|=', lambda b: b.__ior__({}))],
            'change': [('pop', lambda b: b.pop('uptime')), ('popitem', lambda b: b.popitem()),
                       ('setdefault', lambda b: b.setdefault('idle_time', 0)), ('update', lambda b: b.update(x=1)),
                       ('clear', lambda b: b.clear())],
            'copy': [('copy', lambda b: b.copy())],
            'unbound': [('dict-unbound', lambda b: dict.get(b, 'python_version')),
                        ('dict-unbound', lambda b: dict.__getitem__(b, 'python_version')),
                        ('dict-unbound', lambda b: dict.__contains__(b, 'python_version')),
                        ('dict-unbound', lambda b: dict.pop(b, 'python_version')),
                        ('dict-unbound', lambda b: str(next(iter(dict.keys(b))))),
                        ('dict-unbound', lambda b: bool(next(iter(dict.values(b))))),
                        ('dict-unbound', lambda b: list(dict.items(b))[0][1] == '1.60.1')],
        }
        for kind, cases in operations.items():
            for operation, act in cases:
                with self.subTest(kind=kind, operation=operation, act=act):
                    answer, reads = self.recorded()
                    with self.assertRaises(AC.OpaqueRead):
                        act(answer['body'])
                    opaque = [r for r in reads.to_json() if any(h.startswith(AC.OPAQUE) for h in r['how'])]
                    self.assertEqual([(r['answer'], r['how']) for r in opaque],
                                     [('server-info', [AC.OPAQUE + operation])])
                    self.assertTrue(opaque[0]['path'].startswith('body.'), opaque)
                    self.assertEqual(answer['body']['version'], '1.60.1', 'the answer is unchanged')

    def test_not_seen_an_unbound_dict_method_on_a_key_the_answer_does_not_hold(self):
        """The recorder's documented limit: dict's storage answers for an absent key without calling Python code."""
        answer, reads = self.recorded()
        self.assertIsNone(dict.get(answer['body'], 'absent'))
        self.assertNotIn('body.absent', [r['path'] for r in reads.to_json()])

    def test_each_read_notes_its_reader(self):
        answer, reads = self.recorded()
        answer['body'].get('version')
        self.assertEqual(reads.readers_json(), [
            {'answer': 'server-info', 'path': 'body', 'by': [
                'outside:test_agentfixture_core.Recording.test_each_read_notes_its_reader']},
            {'answer': 'server-info', 'path': 'body.version', 'by': [
                'outside:test_agentfixture_core.Recording.test_each_read_notes_its_reader']}])
        dispatch = REPO / 'integrations' / 'dispatch'
        self.assertEqual(AC._kind(str(dispatch / 'attempt_end.py')), ('dispatch', 'attempt_end'))
        self.assertEqual(AC._kind(str(dispatch / 'tests' / 'test_attempt_end.py'))[0], 'outside')
        self.assertEqual(AC._kind(AC.__file__)[0], 'skip')
        self.assertEqual(AC._kind(json.__file__)[0], 'skip')


class ContainerInspect(unittest.TestCase):
    """The container inspect E-01.5's launch gate reads (the ``container-inspect`` entry): each value found in the
    section it cites, its determining inputs the same at F-04.2's run and at D1's, and the core's answer by state."""
    category = 'unit'
    PROFILE = REPO / 'profiles' / 'strong-windows-qemu-whpx'

    def setUp(self):
        self.core = AC.AgentServerCore()
        self.addCleanup(self.core.close)

    def test_each_value_is_in_its_cited_section(self):
        entry = CATALOG['answers']['container-inspect']
        f042 = 'evidence/F-04.2-conversation-lifecycle.md'
        d1 = 'evidence/D1-run-2026-11-16.md'
        cases = [
            (f042, '### 4.3', [f'| `.Image` | `{entry["Image"]}` = the locked image ID |',
                               '`Memory` 4294967296, `NanoCpus` 2000000000, `PidsLimit` 512 (= config)',
                               '| `Mounts` | exactly the three declared binds (section 5), `RW` true',
                               '| Network | `bridge`', '`ExtraHosts` `host.docker.internal:host-gateway`']),
            (f042, '## 7. Containment deviations', ['`HostConfig.ExtraHosts` `["host.docker.internal:host-gateway"]`',
                                                    '`HostConfig.NetworkMode` `bridge`']),
            (d1, '## 5. The steps', ['| (3) | PASS | count 1; one container, of the conversation, no container problem',
                                     'workspace scope exactly the three declared binds',
                                     'limits `cpu.max` 200000 100000, `memory.max` 4294967296, `pids.max` 512',
                                     'the same caps in `HostConfig`']),
            (d1, '## 4. Before the dispatch', [f'Image `{entry["Image"]}`', '`b7c5d2fedb6495679d6d24eca7df652b4f55e88'
                                               '32f2c17987c26569861eed9c7`', 'lock `f02e430a3f3de69976e5eb632d757126c9d'
                                               '1a879ab68cf2c3681f9977a8168e0`']),
        ]
        for record, heading, texts in cases:
            found = ' '.join(section(record, heading).split())
            for text in texts:
                with self.subTest(record=record, text=text):
                    self.assertIn(' '.join(text.split()), found)
        self.assertEqual(entry['HostConfig'], {'Memory': 4294967296, 'NanoCpus': 2000000000, 'PidsLimit': 512,
                                               'NetworkMode': 'bridge',
                                               'ExtraHosts': ['host.docker.internal:host-gateway']})

    def test_the_determining_inputs_are_the_profile_d1_ran(self):
        """The image by the provision lock the profile pins, the caps by its configuration and a create with no
        container caps, the mounts by its declared binds: the checked-in profile is D1's (D1 section 4)."""
        raw = (self.PROFILE / 'profile.json').read_bytes()
        pin = CATALOG['answers']['container-inspect']['mounts']['profile']
        self.assertEqual(pin, {'path': 'profiles/strong-windows-qemu-whpx/profile.json',
                               'sha256': hashlib.sha256(raw).hexdigest()})
        declared = json.loads(raw)
        lock_pin = declared['provider']['provision_lock']
        lock_raw = (REPO / lock_pin['path']).read_bytes()
        self.assertEqual(hashlib.sha256(lock_raw).hexdigest(), lock_pin['sha256'])
        self.assertEqual(json.loads(lock_raw)['image']['image_id'], CATALOG['answers']['container-inspect']['Image'])
        config = declared['provisioning']['agent_server']['config']['content']
        self.assertEqual((config['conversation_container_memory'], config['conversation_container_cpus'],
                          config['conversation_container_pids_limit']), ('4g', 2.0, 512))
        for name in ('d1-create.json', 'conversation-create.json'):
            with self.subTest(template=name):
                template = json.loads((self.PROFILE / 'agent-server' / name).read_text(encoding='utf-8'))
                self.assertEqual(template['container'], {'browser': False})
        mounts = declared['provisioning']['agent_server']['conversations']['mounts']
        self.assertEqual([(m['type'], m['rw']) for m in mounts], [('bind', True)] * 3)

    def test_the_core_answers_the_inspect_of_a_held_conversation_with_a_container(self):
        cid = CID
        self.assertEqual(self.core.container_inspect(cid)['fixture']['answer'], 'refusal', 'no conversation held')
        self.core('POST', '/api/conversations', {'conversation_id': cid})
        answer = self.core.container_inspect(cid)
        self.assertEqual(set(answer), {'body', 'fixture'}, 'no HTTP status: it is not an Agent Server answer')
        self.assertEqual(answer['fixture'], {**CATALOG['label'], 'answer': 'container-inspect'})
        body = answer['body']
        entry = CATALOG['answers']['container-inspect']
        self.assertEqual((body['Image'], body['HostConfig']), (entry['Image'], entry['HostConfig']))
        declared = json.loads((self.PROFILE / 'profile.json').read_bytes())
        binds = AC._attempt_run().di._binds_for(declared['provisioning']['agent_server']['conversations']['mounts'],
                                                cid.replace('-', ''))
        self.assertEqual(body['Mounts'], [{'Type': b['type'], 'Source': b['source'], 'Destination': b['destination'],
                                           'RW': b['rw']} for b in binds])
        self.assertIn(f'/srv/scratch/openhands/conversations/{cid.replace("-", "")}',
                      [m['Source'] for m in body['Mounts']])
        self.assertEqual(self.core.calls[-1][:2], ('POST', '/api/conversations'), 'an inspect is no Agent Server call')
        self.assertEqual([c for _, c in self.core.inspected], [cid, cid])
        self.core('DELETE', f'/api/conversations/{cid}/runtime')
        self.assertEqual(self.core.container_inspect(cid)['fixture']['answer'], 'refusal',
                         'no container once the runtime is stopped (F-04.2 4.6)')

    def test_the_inspect_is_refused_when_the_profile_is_not_the_one_d1_ran(self):
        self.core('POST', '/api/conversations', {'conversation_id': CID})
        catalog = copy.deepcopy(CATALOG)
        catalog['answers']['container-inspect']['mounts']['profile']['sha256'] = '0' * 64
        other = AC.AgentServerCore(catalog)
        self.addCleanup(other.close)
        other('POST', '/api/conversations', {'conversation_id': CID})
        answer = other.container_inspect(CID)
        self.assertEqual(answer['fixture']['answer'], 'refusal')
        self.assertIn('not the profile D1 ran', answer['fixture']['refused'])


if __name__ == '__main__':
    unittest.main()
