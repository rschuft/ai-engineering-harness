"""The served fixture's catalog (plan leaf E-01.7, gates G3 and G4): its provenance table bound to the catalog, the
proof's rules on every row, every served route in the pinned route inventory, each answer validated, and each
observed value found in the record it cites.

The validation that needs the locked release openapi.json (never committed: decision 0005) runs when
``AIEH_LOCKED_OPENAPI`` names it, its sha256 checked; the catalog's own schemas are checked in every run.
"""
import hashlib
import io
import json
import re
import tarfile
import unittest

import fixture_support as S

CATEGORY = 'unit'

AC, SERVER, RESULT = S.AC, S.SERVER, S.RESULT
SERVED = S.SERVED
ROWS = SERVED['provenance']
README = S.PACKAGE / 'README.md'
CLASSES = {'observation', 'echo', 'pinned-rule', 'label', 'source-derived', 'none'}
UPSTREAM = r'`(sdk|as):openhands/[a-z_/]+\.py:\d+(-\d+)?`'
RECORDS = r'(S-01\.3\.1 §\d|E-01\.3\.3 §\d|D1 §\d|F-04\.1c §\d|F-04\.2 §\d)'
CHECK_PROFILE = S.load('aieh_check_profile', S.REPO / 'tools' / 'check_profile.py')
OPENAPI = S.locked_openapi_path()
LOCKED = None if OPENAPI is None else SERVER.locked_document(OPENAPI)
CONVERSATION = f'/api/conversations/{S.CID}'


def table(text):
    start = text.index('## The served fixture\'s provenance table')
    end = text.index('\n## ', start + 5)
    rows = []
    for line in text[start:end].splitlines():
        if line.startswith('| ') and not line.startswith('| Face') and not line.startswith('|---'):
            face, answer, field, klass, citation, determined, read, served, marks = \
                [c.strip() for c in line[1:-1].split(' | ')]
            read, _, by = read.partition(': ')
            rows.append({'face': face, 'answer': answer.strip('`'), 'field': field, 'class': klass,
                         'citation': citation, 'determinedBy': determined, 'read': read == 'yes',
                         'readBy': [b.strip().strip('`') for b in by.split(',')] if by else [],
                         'served': served == 'yes', 'marks': marks})
    return rows


def section(record, heading):
    text = (S.REPO / record).read_text(encoding='utf-8')
    start = text.index(heading)
    following = re.search(r'\n#{2,4} ', text[start + len(heading):])
    return ' '.join(text[start:start + len(heading) + (following.start() if following else len(text))].split())


def seed_body(files):
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode='w:gz', format=tarfile.PAX_FORMAT) as tar:
        for name, content in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
    payload = data.getvalue()
    digest = hashlib.sha256(payload).hexdigest()
    script = RESULT.pinned_script('SEED_SCRIPT')
    return {'command': f"printf %s '{payload.hex()}' | python -c '{script}' '/workspace/aieh-d1-demo' '{digest}'",
            'cwd': '/workspace', 'timeout': 120}


class Table(unittest.TestCase):
    def test_the_readme_table_is_the_catalog_row_for_row(self):
        self.assertEqual(table(README.read_text(encoding='utf-8')), ROWS)

    def test_every_served_answer_has_rows_and_every_row_an_answer(self):
        self.assertEqual({r['answer'] for r in ROWS}, set(SERVED['answers']))
        self.assertFalse(set(SERVED['answers']) & set(S.CATALOG['answers']), 'one name per answer')


class Rules(unittest.TestCase):
    def test_every_field_has_a_class_and_only_a_classed_field_is_served(self):
        for row in ROWS:
            with self.subTest(answer=row['answer'], field=row['field']):
                self.assertIn(row['class'], CLASSES)
                self.assertEqual(row['served'], row['class'] != 'none')
                if row['class'] == 'none':
                    self.assertTrue(row['citation'].startswith('not served:'))
                    self.assertFalse(row['read'])

    def test_source_derived_only_on_the_ui_face_cited_to_the_locked_wheels_and_marked(self):
        for row in ROWS:
            if row['class'] == 'source-derived':
                with self.subTest(answer=row['answer'], field=row['field']):
                    self.assertEqual(row['face'], 'ui')
                    self.assertTrue(row['answer'].startswith('ui-'))
                    self.assertIn('source-derived', row['marks'])
                    if row['field'] != '`body.event`':
                        self.assertRegex(row['citation'], UPSTREAM)
        core = [r for r in S.CATALOG['provenance'] if r['class'] == 'source-derived']
        self.assertEqual({r['answer'] for r in core}, {'message-event'}, 'the dispatcher face\'s one entry')

    def test_every_observation_cites_a_record_the_proof_names(self):
        for row in ROWS:
            if row['class'] == 'observation':
                with self.subTest(answer=row['answer'], field=row['field']):
                    self.assertRegex(row['citation'], RECORDS)

    def test_clock_valued_is_an_unread_observation_of_the_clock(self):
        clocked = [r for r in ROWS if 'clock-valued' in r['marks']]
        self.assertEqual([(r['answer'], r['field']) for r in clocked],
                         [('ui-server-info', '`body.uptime`, `body.idle_time`')])
        for row in clocked:
            self.assertEqual((row['class'], row['determinedBy'], row['read']), ('observation', 'the clock', False))
        body = SERVED['answers']['ui-server-info']['body']
        recorded = S.CATALOG['answers']['server-info']['recorded']
        self.assertEqual(body, {'uptime': recorded['uptime'], 'idle_time': recorded['idle_time']},
                         'replayed unchanged')

    def test_a_row_read_is_served_on_the_dispatchers_face_and_never_clock_valued(self):
        for row in ROWS:
            if row['read']:
                with self.subTest(answer=row['answer'], field=row['field']):
                    self.assertEqual((row['face'], row['served']), ('dispatcher', True))
                    self.assertNotIn('clock-valued', row['marks'])
                    for by in row['readBy']:
                        self.assertTrue((S.REPO / 'integrations' / 'dispatch' / f'{by.split(".")[0]}.py').is_file())

    def test_the_pinned_rule_is_harness_code_the_production_path_runs(self):
        for row in ROWS:
            if row['class'] == 'pinned-rule':
                with self.subTest(field=row['field']):
                    self.assertIn('`integrations/dispatch/attempt_run.py` `RESULT_SCRIPT`', row['citation'])
        self.assertIn("| python -c '{RESULT_SCRIPT}' ", (S.REPO / 'integrations' / 'dispatch' / 'attempt_run.py')
                      .read_text(encoding='utf-8'))

    def test_each_ui_label_names_exactly_its_source_derived_fields(self):
        core = AC.AgentServerCore(ui_running_reads=1)
        self.addCleanup(core.close)
        core('POST', '/api/conversations', S.d1_create())
        answers = [core.ui_answer('GET', '/server_info'), core.ui_answer('GET', CONVERSATION),
                   core.ui_answer('GET', CONVERSATION + '/events/search')]
        core('POST', CONVERSATION + '/events', S.MESSAGE)
        frames, _ = core.ui_session(S.CID, -1)
        for answer in answers + frames:
            name = answer['fixture']['answer']
            with self.subTest(answer=name):
                derived = sorted(p for r in ROWS if r['answer'] == name and r['class'] == 'source-derived'
                                 for p in AC.field_paths(r['field']))
                self.assertEqual(sorted(answer['fixture']['sourceDerived']), derived)


class Routes(unittest.TestCase):
    def test_every_served_route_is_in_the_pinned_inventory_with_its_recorded_source(self):
        pin = SERVED['inventory']
        data = (S.REPO / pin['path']).read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(), pin['sha256'])
        profile = (S.REPO / 'profiles' / 'strong-windows-qemu-whpx' / 'profile.json').read_bytes()
        self.assertEqual(hashlib.sha256(profile).hexdigest(), pin['profile'])
        inventory = {(r['method'], r['path']): r for r in json.loads(data)['routes']}
        for route in SERVED['routes']:
            with self.subTest(face=route['face'], method=route['method'], path=route['path']):
                found = inventory[(route['method'], route['inventory'])]
                self.assertEqual(found['source'], route['source'])
                if route['inventory'] != route['path']:
                    tail = route['path'].split('/{conversation_id}/', 1)[1]
                    self.assertIn(tail, found['tails'])
                else:
                    self.assertNotIn('tails', found)

    def test_every_route_the_listener_answers_is_a_catalog_route(self):
        routes = SERVED['routes']
        for face, method, path in (('dispatcher', 'GET', '/server_info'), ('dispatcher', 'POST', CONVERSATION + '/events'),
                                   ('ui', 'GET', CONVERSATION + '/events/search')):
            self.assertTrue(SERVER.in_catalog(routes, face, method, path))
        for face, method, path in (('dispatcher', 'GET', '/alive'), ('ui', 'POST', CONVERSATION),
                                   ('dispatcher', 'POST', CONVERSATION + '/runtime/credentials'),
                                   ('dispatcher', 'GET', CONVERSATION + '/events/search/x')):
            self.assertFalse(SERVER.in_catalog(routes, face, method, path))

    @unittest.skipIf(LOCKED is None, 'AIEH_LOCKED_OPENAPI is not given (the locked document is never committed)')
    def test_g4_each_routes_presence_in_the_locked_document_is_as_recorded(self):
        templates = {(m.upper(), re.sub(r'\{[^}]+\}', '{}', p)) for p, item in LOCKED['paths'].items() for m in item}
        for route in SERVED['routes']:
            with self.subTest(face=route['face'], method=route['method'], path=route['path']):
                key = (route['method'], re.sub(r'\{[^}]+\}', '{}', route['path']))
                self.assertEqual(key in templates and route['inventory'] == route['path'], route['locked'])
        self.assertFalse([p for p in LOCKED['paths'] if not p.startswith('/api/')])


class Answers(unittest.TestCase):
    """Every answer kind the listener serves, made by the core and the listener's own rules, validated."""
    category = 'integration'          # SEED runs the harness's script in a process

    @classmethod
    def setUpClass(cls):
        fixture = SERVER.Fixture('running')
        cls.addClassCleanup(fixture.core.close)
        core = fixture.core
        made = cls.made = {}

        def keep(answer):
            made.setdefault(answer['fixture']['answer'], []).append(answer)
            return answer
        keep(core('GET', '/server_info'))
        keep(core.ui_answer('GET', '/server_info'))
        keep(core('POST', '/api/conversations', S.d1_create()))
        keep(core('GET', '/api/conversations/count'))
        keep(core('GET', CONVERSATION))
        keep(core('GET', '/api/conversations/11111111-2222-4333-8444-555555555555'))
        keep(core('GET', CONVERSATION + '/runtime'))
        keep(core('GET', CONVERSATION + '/events/search'))
        keep(core.ui_answer('GET', CONVERSATION))
        keep(core.ui_answer('GET', CONVERSATION + '/events/search'))
        keep(core('POST', CONVERSATION + '/bash/execute_bash_command', seed_body({'README.md': b'x'})))
        keep(core('POST', CONVERSATION + '/events', S.MESSAGE))
        for _ in range(SERVER.RUNNING_READS + 1):
            keep(core.ui_answer('GET', CONVERSATION))
        keep(core.ui_answer('GET', CONVERSATION + '/events/search'))
        keep(core('GET', CONVERSATION))
        frames, _ = core.ui_session(S.CID, -1)
        for frame in frames:
            keep(frame)
        keep(core('DELETE', CONVERSATION + '/runtime'))
        keep(core('GET', CONVERSATION + '/runtime'))
        keep(core.unauthorized('dispatcher'))
        keep(core.unauthorized('ui'))

    def schema(self, name):
        return {'$ref': f'#/schemas/{name}'}, {'schemas': SERVED['schemas']}

    def test_the_ui_statuses_are_only_those_a_live_run_reaches(self):
        statuses = {a['body']['execution_status'] for a in self.made['ui-conversation']}
        self.assertEqual(statuses, {'idle', 'running', 'finished'})

    def test_each_answer_validates_against_the_catalogs_model_schemas(self):
        for name, model in (('server-info', 'ServerInfo'), ('ui-server-info', 'ServerInfo'),
                            ('events', 'EventPage'), ('ui-events', 'EventPage'), ('ui-sync', 'SyncFrame'),
                            ('ui-durable', 'DurableFrame')):
            for answer in self.made[name]:
                with self.subTest(answer=name):
                    schema, document = self.schema(model)
                    self.assertEqual(CHECK_PROFILE.schema_errors(answer['body'], schema, document), [])
        for answer in self.made['count']:
            self.assertIs(type(answer['body']), int)
        self.assertNotIn('body', self.made['message'][0])
        self.assertIsNone(self.made['runtime-stop'][0]['body'])

    @unittest.skipIf(LOCKED is None, 'AIEH_LOCKED_OPENAPI is not given (the locked document is never committed)')
    def test_each_answer_validates_against_the_locked_schema_save_the_listed_not_served(self):
        unserved = {}
        for row in S.CATALOG['provenance']:
            if not row['served']:
                unserved.setdefault(row['answer'], set()).update(
                    p[len('body.'):] for p in AC.field_paths(row['field']) if p.startswith('body.'))
        cases = [('create-new', 'ConversationInfo'), ('conversation', 'ConversationInfo'),
                 ('runtime', 'ConversationRuntimeInfo'), ('seed', 'BashOutput'), ('ui-conversation', 'ConversationInfo')]
        for name, model in cases:
            for answer in self.made[name]:
                with self.subTest(answer=name):
                    errors = CHECK_PROFILE.schema_errors(answer['body'], {'$ref': f'#/components/schemas/{model}'},
                                                         LOCKED)
                    allowed = [e for e in errors if name in unserved and re.fullmatch(
                        r"\$: missing required '([a-z_]+)'", e) and (e.split("'")[1] in unserved[name]
                                                                     or '<the other top-level fields of the 36>'
                                                                     in unserved[name]
                                                                     or '<every other ConversationInfo field>'
                                                                     in unserved[name])]
                    self.assertEqual([e for e in errors if e not in allowed], [])
                    if name.startswith('ui-'):
                        self.assertEqual(errors, [], 'the UI face lists nothing not served')
        for name in ('events', 'ui-events'):
            for answer in self.made[name]:
                for item in answer['body']['items']:
                    self.assertEqual(CHECK_PROFILE.schema_errors(item, {'$ref': '#/components/schemas/Event'},
                                                                 LOCKED), [])
        for answer in self.made['ui-durable']:
            self.assertEqual(CHECK_PROFILE.schema_errors(answer['body']['event'],
                                                         {'$ref': '#/components/schemas/Event'}, LOCKED), [])


class Citations(unittest.TestCase):
    def test_each_observed_value_is_in_its_cited_section(self):
        s0131 = section('evidence/S-01.3.1-management-api-admission.md', '### 3.4 What a refused caller sees')
        for text in ('`401 {"detail": "Unauthorized"}`', 'handshake 101, then close 4001 "Authentication failed"',
                     'WebSocket, wrong key in the query or header | handshake 403'):
            self.assertIn(text, s0131)
        e0133 = section('evidence/E-01.3.3-dispatcher-custody.md', '### 8.3 The custody probe')
        self.assertIn('(4) a conversation runtime credential minted by the dispatcher answers 401 on every key-gated '
                      'route of the outer server', e0133)
        self.assertIn('its own conversation\'s inner server, which refuses a request without it', e0133)
        self.assertIn('steps (1), (2), (4) and (5) PASS', section('evidence/E-01.3.3-dispatcher-custody.md', '### 9.1'))
        d1 = section('evidence/D1-run-2026-11-16.md', '## 2. Identities')
        self.assertIn('status `0` (`PASSED`), output 114 bytes, sha256 '
                      '`432e764160c5b06b41e1864e05386aaf72bcdcdfe2465d19c35fe57144567754`', d1)
        self.assertIn('`report.md` sha256 `4c2e6826c41f81d5b4e20b9344f07d436beb14ec6b694a377498eb893726c338` (10096 '
                      'bytes)', d1)
        calls = section('evidence/D1-run-2026-11-16.md', '## 5. The steps')
        self.assertIn('`POST .../bash/execute_bash_command` 200 (RESULT', calls)
        self.assertIn('`GET /api/conversations/{id}` 200, seven times (the wait)', calls)
        answers = SERVED['answers']
        self.assertEqual((answers['unauthorized'], answers['ui-unauthorized']),
                         ({'status': 401, 'body': {'detail': 'Unauthorized'}},) * 2)
        self.assertEqual(answers['ui-socket-unauthorized'], {'code': 4001, 'reason': 'Authentication failed'})
        self.assertEqual((answers['ui-socket-denied']['status'], SERVER.RUNNING_READS), (403, 7))
        self.assertEqual(answers['result']['testOutput'], {'bytes': RESULT.TEST_OUTPUT_BYTES,
                                                           'sha256': RESULT.TEST_OUTPUT_SHA256})


if __name__ == '__main__':
    unittest.main()
