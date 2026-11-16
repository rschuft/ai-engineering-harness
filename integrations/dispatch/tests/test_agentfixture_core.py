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
* SEED is answered by running the harness's own ``SEED_SCRIPT`` over the request's payload, once per conversation
  (``Seed``);
* the read record notes each key read, by catalog answer and path (``Recording``).
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


def table_rows(text):
    start = text.index('## The provenance table')
    end = text.index('\n## ', start + 5)
    rows = []
    for line in text[start:end].splitlines():
        if line.startswith('| `'):
            answer, field, klass, citation, determined, read, served, marks = [c.strip() for c in line[1:-1].split('|')]
            rows.append({'answer': answer.strip('`'), 'field': field, 'class': klass, 'citation': citation,
                         'determinedBy': determined, 'read': read == 'yes', 'served': served == 'yes', 'marks': marks})
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


class Citations(unittest.TestCase):
    """Each observed value is found in the committed section it cites."""
    category = 'unit'

    def test_server_info_is_f_04_1c_section_3_complete(self):
        recorded = json_block(section('evidence/F-04.1c-agent-server.md', '## 3. Run 1'))
        self.assertEqual(CATALOG['answers']['server-info']['body'], recorded)

    def test_the_create_answer_is_f_04_2_section_4_2_and_its_request_the_profiles_fixture(self):
        recorded = json_block(section('evidence/F-04.2-conversation-lifecycle.md', '### 4.2 (b) Create'))
        entry = CATALOG['answers']['create-new']
        self.assertEqual({'id': F042_CID, **entry['clock'], **entry['equalRequest'], **entry['ownRequest']}, recorded)
        fixture = json.loads((REPO / 'profiles' / 'strong-windows-qemu-whpx' / 'agent-server' /
                              'conversation-create.json').read_text(encoding='utf-8'))
        self.assertEqual(entry['observedRequest'], fixture)

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


if __name__ == '__main__':
    unittest.main()
