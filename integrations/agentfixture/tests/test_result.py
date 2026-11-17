"""RESULT's answer (plan leaf E-01.7; ``result.py``) and gate G7: the built commit is decision 0024 point 4.4's commit,
and the real RESULT script's through a real shell on the same base, edits, identity, message and time.

The base is a D1-shaped project repository built in process with Dulwich in a throwaway directory: D1's demo
repository's committed template (``integrations/gitea/demo/aieh-d1-demo``), the accepted design D1 ran
(``evidence/D1-demo-design``) and a task file. Nothing is committed anywhere but there.
"""
import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import fixture_support as S

CATEGORY = 'integration'

TAR = S.load('test_attempt_run', S.DISPATCH_TESTS / 'test_attempt_run.py')
AR = TAR.AR
RESULT = S.RESULT
DEMO = S.REPO / 'integrations' / 'gitea' / 'demo' / 'aieh-d1-demo'
DESIGN = S.REPO / 'evidence' / 'D1-demo-design'
ATTEMPT = '3c39e307-8648-588f-8fd7-0a957e74933c'           # D1's attempt id (the D1 run record, section 2)
WHEN = 1763254632                                           # a fixed commit time
TITLE = 'Implement slugify(text) in aieh_d1_demo (add-slugify)'


def d1_trees(readme: bytes | None = None):
    """C0 the demo template, C1 the accepted design, C2 the task file: each a full tree ({path: bytes})."""
    c0 = {p.relative_to(DEMO).as_posix(): p.read_bytes() for p in sorted(DEMO.rglob('*')) if p.is_file()}
    if readme is not None:
        c0['README.md'] = readme
    c1 = dict(c0, **{p.relative_to(DESIGN).as_posix(): p.read_bytes() for p in sorted(DESIGN.rglob('*'))
                     if p.is_file()})
    task = (f'---\nid: TASK-1\ntitle: \'{TITLE}\'\nstatus: To Do\n---\n\n## Description\n\nslugify\n').encode()
    c2 = dict(c1, **{f'backlog/tasks/task-1 - Implement-slugify.md': task})
    return [('C0', c0), ('C1', c1), ('C2', c2)]


def message():
    return f'TASK-1: {TITLE}\n\nTask: TASK-1\nAttempt: {ATTEMPT}\nOutcome: outcome:x@y\nDesign: openspec:x@y\n'


def result_command(base, *, identity=None, **changes):
    """The production RESULT command (attempt_run.build_result); with IDENTITY or CHANGES, its parameters edited."""
    command = AR.build_result(base, attempt_id=ATTEMPT, message=message(), when=WHEN)
    body = {'command': command.command, 'cwd': '/workspace', 'timeout': command.timeout}
    if identity is None and not changes:
        return body
    payload = body['command'].split("'")[1]
    params = json.loads(bytes.fromhex(payload).decode('utf-8'))
    if identity is not None:
        params['name'], params['email'] = identity
    params.update(changes)
    edited = json.dumps(params, sort_keys=True, separators=(',', ':')).encode('utf-8').hex()
    return dict(body, command=body['command'].replace(payload, edited))


def seed_body(base):
    command = AR.build_seed(base)
    return {'command': command.command, 'cwd': '/workspace', 'timeout': command.timeout}


class D1Shaped(unittest.TestCase):
    """A core holding one conversation seeded with a D1-shaped base, its turn finished."""
    category = 'integration'

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='aieh-fx-result-'))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.base = self.make_base()
        self.core = S.AC.AgentServerCore(scratch=self.tmp / 'core')
        self.path = f'/api/conversations/{S.CID}/bash/execute_bash_command'
        self.core('POST', '/api/conversations', S.d1_create())

    def make_base(self, readme=None, name='demo'):
        commits = TAR.make_repository(self.tmp / name, d1_trees(readme))
        return AR.read_base(self.tmp / name, repository='aieh-d1-demo', design_commit=commits['C1'])

    def seeded(self, finished=True):
        answer = self.core('POST', self.path, seed_body(self.base))
        self.assertEqual(answer['status'], 200, answer['fixture'])
        if finished:
            self.assertEqual(self.core('POST', f'/api/conversations/{S.CID}/events', S.MESSAGE)['status'], 200)

    def refused(self, answer, text):
        self.assertEqual((answer['status'], answer['fixture']['answer']), (501, 'refusal'))
        self.assertIn(text, answer['fixture']['refused'])


class Answer(D1Shaped):
    def test_result_is_the_harness_script_over_d1s_changes_with_d1s_test_output(self):
        self.seeded()
        answer = self.core('POST', self.path, result_command(self.base))
        self.assertEqual((answer['status'], answer['fixture']['answer'], answer['body']['exit_code']),
                         (200, 'result', 0), answer['fixture'])
        printed = AR.parse_result(answer, delivered_expected=False)
        self.assertEqual(printed['base'], self.base.commit)
        self.assertEqual((printed['tests']['status'], printed['excluded_digest']['count']), ('0', 0))
        output = bytes.fromhex(next(line for line in answer['body']['stdout'].split('\n')
                                    if line.startswith('AIEH-RESULT test-output ')).split()[-1])
        self.assertEqual((len(output), hashlib.sha256(output).hexdigest()),
                         (114, '432e764160c5b06b41e1864e05386aaf72bcdcdfe2465d19c35fe57144567754'))
        # the frame the command asked for (the delivery's input; the delivery itself is E-01.8's)
        self.assertIn(f'AIEH-EXCHANGE-PART bundle {printed["bundle"]["sha256"]} {printed["bundle"]["size"]}',
                      answer['body']['stdout'])

    def test_g7_the_commit_is_decision_0024_point_4_4s_rule(self):
        self.seeded()
        printed = AR.parse_result(self.core('POST', self.path, result_command(self.base)), delivered_expected=False)
        raw = AR.expected_commit(printed['tree'], self.base.commit, message(), WHEN)
        self.assertEqual(printed['commit'], AR.object_id('commit', raw))

    def test_the_identity_is_an_input(self):
        self.seeded()
        identity = ('Throwaway Person', 'throwaway@example.invalid')
        printed = AR.parse_result(self.core('POST', self.path, result_command(self.base, identity=identity)),
                                  delivered_expected=False)
        who = f'{identity[0]} <{identity[1]}> {WHEN} +0000'
        raw = (f'tree {printed["tree"]}\nparent {self.base.commit}\nauthor {who}\ncommitter {who}\n\n'
               f'{message()}').encode('utf-8')
        self.assertEqual(printed['commit'], AR.object_id('commit', raw))
        self.assertNotEqual(printed['commit'], AR.object_id('commit', AR.expected_commit(
            printed['tree'], self.base.commit, message(), WHEN)))

    def test_d1s_recorded_changes_are_the_report_d1_committed(self):
        report = RESULT.report_text()
        self.assertEqual(hashlib.sha256(report.encode('utf-8')).hexdigest(), RESULT.REPORT_SHA256)
        changes = RESULT.d1_changes(report)
        self.assertEqual([(c['path'], c['status']) for c in changes],
                         [('aieh_d1_demo/__init__.py', 'modified'), ('aieh_d1_demo/slugify.py', 'added'),
                          ('tests/test_slugify.py', 'added')])
        added = sum(len(new) - len(old) for c in changes for _, old, new in c['hunks'])
        self.assertEqual(added, 116, 'the report\'s Diff (3 file(s), +116 -0)')
        self.assertEqual(RESULT.d1_test_output(report), ('.' * 15 + '\n' + '-' * 70 + '\nRan 15 tests in 0.001s\n\nOK\n')
                         .encode('ascii'))

    def test_the_demo_blobs_are_the_committed_template_and_the_constants_the_builders(self):
        found = {p.relative_to(DEMO).as_posix(): RESULT.blob_id(p.read_bytes()) for p in DEMO.rglob('*')
                 if p.is_file() and p.relative_to(DEMO).parts[0] not in RESULT.PROTECTED}
        self.assertEqual(found, RESULT.DEMO_BLOBS)
        command = AR.build_result(self.base, attempt_id=ATTEMPT, message=message(), when=WHEN)
        params = json.loads(bytes.fromhex(command.command.split("'")[1]).decode('utf-8'))
        self.assertEqual(set(params), RESULT.PARAMETERS)
        self.assertEqual({k: params[k] for k in RESULT.CONSTANTS}, RESULT.CONSTANTS)
        self.assertEqual((RESULT.pinned_script('RESULT_SCRIPT'), RESULT.pinned_script('SEED_SCRIPT')),
                         (AR.RESULT_SCRIPT, AR.SEED_SCRIPT))
        self.assertEqual(RESULT.RESULT_TIMEOUT_MAX_S, AR.RESULT_TIMEOUT_S)


class Refused(D1Shaped):
    def test_a_base_that_is_not_d1s_outside_openspec_and_backlog_is_refused(self):
        self.base = self.make_base(readme=b'# not the demo\n', name='other')
        self.seeded()
        self.refused(self.core('POST', self.path, result_command(self.base)), 'base is not D1\'s')

    def test_result_before_seed_before_the_turn_or_twice_is_refused(self):
        self.refused(self.core('POST', self.path, result_command(self.base)), 'before SEED')
        self.seeded(finished=False)
        self.refused(self.core('POST', self.path, result_command(self.base)), 'before the turn finished')
        self.assertEqual(self.core('POST', f'/api/conversations/{S.CID}/events', S.MESSAGE)['status'], 200)
        self.assertEqual(self.core('POST', self.path, result_command(self.base))['status'], 200)
        self.refused(self.core('POST', self.path, result_command(self.base)), 'a second RESULT')

    def test_a_script_or_a_constant_not_the_builders_is_refused_without_running(self):
        self.seeded()
        altered = result_command(self.base)
        altered['command'] = altered['command'].replace('import hashlib, json', 'import hashlib,  json')
        self.refused(self.core('POST', self.path, altered), 'not the harness\'s SEED or RESULT command')
        self.refused(self.core('POST', self.path, result_command(self.base, test_timeout=5)),
                     'not the production builder\'s')
        self.assertFalse((self.tmp / 'core' / S.CID / 'result').exists(), 'nothing ran')

    def test_a_result_with_an_exchange_delivery_is_refused_as_before(self):
        self.seeded()
        answer = self.core('POST', self.path, result_command(self.base), deliver={'part': 'bundle', 'name': 'x'})
        self.refused(answer, 'exchange delivery')


@unittest.skipIf(TAR.BASH is None, 'no Git Bash (Windows) or bash: G7 needs a real shell')
class G7RealShell(D1Shaped):
    """G7: the real RESULT script, through a real shell, on the same base, edits, identity, message and time."""

    def test_the_built_commit_equals_the_real_scripts_through_a_real_shell(self):
        self.seeded()
        built = AR.parse_result(self.core('POST', self.path, result_command(self.base)), delivered_expected=False)
        workspace = self.tmp / 'shell' / self.base.repository
        workspace.parent.mkdir()
        code, out, err = TAR.run_command(seed_body(self.base)['command'], workspace)
        self.assertEqual(code, 0, err)
        RESULT.apply_changes(workspace, RESULT.d1_changes())
        code, out, err = TAR.run_command(result_command(self.base)['command'], workspace)
        self.assertEqual(code, 0, err)
        real = AR.parse_result({'status': 200, 'body': {'stdout': out, 'exit_code': 0}}, delivered_expected=False)
        for key in ('base', 'tree', 'commit', 'bundle'):
            with self.subTest(key=key):
                self.assertEqual(built[key], real[key])
        raw = AR.expected_commit(real['tree'], self.base.commit, message(), WHEN)
        self.assertEqual(real['commit'], AR.object_id('commit', raw))


if __name__ == '__main__':
    unittest.main()
