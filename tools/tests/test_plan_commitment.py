"""Tests for tools/plan_commitment.py: closure, status sources, readiness, the Backlog.md checks and
refusals (plan leaf P-05.1)."""

import importlib.util
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

CATEGORY = 'unit'

ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location('plan_commitment', ROOT / 'tools' / 'plan_commitment.py')
pc = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(pc)


def leaf(ident, deps=(), title=None, phase=1):
    return {'id': ident, 'title': title or f'Leaf {ident}', 'deps': list(deps), 'phase': phase,
            'proof': f'Proof of {ident}: the first sentence. (1) The second; with a quote\'s mark.'}


PLAN = {
    'milestones': [{'id': 1, 'code': 'I1'}, {'id': 2, 'code': 'I2'}],
    'work_packages': [
        leaf('A-01.1'),
        leaf('A-01.2', ['A-01.1']),
        leaf('B-01.1', ['A-01.1']),
        leaf('B-01.2', ['A-01.2', 'B-01.1']),
        leaf('C-01.1', ['B-01.2']),
        leaf('D-01.1'),
        leaf('W-01.1', ['A-01.1']),
        leaf('W-01.2', ['W-01.1']),
        leaf('W-01.3', ['W-01.2', 'A-01.2']),
    ],
    'decomposition': {'medium_parent_aliases': {'B-01': 'B-01.2'}, 'legacy_parent_aliases': {}},
}

LOG = """# Log

## Owner actions

| Id | Status |
|---|---|
| OA-1 | **PASS** |
| OA-7 | Open; needed by W-01.3's run |
| OA-8 | Open; needed by W-01.2 |

## Leaves

Intro text.

<a id="leaves-table-closed-2026-11-16"></a>**Closed on 2026-11-16 at 5 rows** (P-05.1).

| Task | Verdict | Revision | Evidence | Parent gates |
|---|---|---|---|---|
| A-01.1 First | **PASS (2026-11-06)** for the profile | `abc` | e | g |
| A-01.2 Second | PASS (2026-11-06); pushed | `def` | e | g |
| B-01.1 Third | **IN PROGRESS (2026-11-11)**: slice 1 | x | e | g |
| B-01 headroom (a group row, not a leaf) | **PASS (2026-11-10)** | x | e | g |
| D-01.1 Other | **BLOCKED on one clause (review)** | x | e | g |

## Decisions

| B-01.2 Not a leaves row | **PASS** | x | e | g |

- <a id="commitment-w-2026-11-16"></a>**2026-11-16: Commitment: W.** Terminal leaf W-01.3.
- <a id="owner-act-oa-7-2026-11-20"></a>**2026-11-20: the Owner's act OA-7**, verbatim.
- <a id="owner-decision-oa-1-2026-11-10"></a>**2026-11-10: the Owner's decision OA-1**, verbatim.
- An example, not an anchor: `<a id="owner-span-oa-7"></a>`.
<!-- <a id="owner-comment-oa-7"></a> -->

```
<a id="owner-fenced-oa-7"></a>
```
"""

# The fixture's Leaves table as closed: what LEAVES_CLOSED pins for the committed log.
FIXTURE_CLOSED = {'date': '2026-11-16', 'ids': ('A-01.1', 'A-01.2', 'B-01.1', 'B-01', 'D-01.1')}

CONFIG = '''project_name: "fixture"
default_status: "To Do"
statuses: ["To Do", "In Progress", "Done"]
labels: []
date_format: yyyy-mm-dd
max_column_width: 20
auto_open_browser: true
default_port: 6420
remote_operations: false
auto_commit: false
filesystem_only: false
bypass_git_hooks: false
check_active_branches: false
active_branch_days: 30
task_prefix: "task"
'''

MILESTONES = {'m-0 - i1.md': ('m-0', 'I1'), 'm-1 - i2.md': ('m-1', 'I2')}

ACT_REF = 'evidence/bootstrap-log.md#commitment-w-2026-11-16'
RECORDED = 'evidence/bootstrap-log.md#owner-act-oa-7-2026-11-20'


def yaml_list(key, items):
    """A list as Backlog.md 1.55.3 writes it: ``[]``, plain items, or ``>-`` for a long one."""
    if not items:
        return f'{key}: []\n'
    out = f'{key}:\n'
    for item in items:
        out += f'  - >-\n    {item}\n' if len(item) > 76 else f'  - {item}\n'
    return out


def task_text(ident, title, status='To Do', milestone='m-0', deps=(), refs=(), criteria=(), labels=()):
    quoted = "'" + title.replace("'", "''") + "'"
    text = (f'---\nid: {ident}\ntitle: {quoted}\nstatus: {status}\nassignee: []\n'
            f"created_date: '2026-11-16T03:39:00Z'\n" + yaml_list('labels', list(labels)))
    if milestone:
        text += f'milestone: {milestone}\n'
    text += yaml_list('dependencies', list(deps)) + (yaml_list('references', list(refs)) if refs else '')
    text += 'ordinal: 1000\n---\n\n## Description\n\n<!-- SECTION:DESCRIPTION:BEGIN -->\nA task.\n' \
            '<!-- SECTION:DESCRIPTION:END -->\n'
    if criteria:
        text += '\n## Acceptance Criteria\n<!-- AC:BEGIN -->\n'
        text += ''.join(f'- [ ] #{n} {item}\n' for n, item in enumerate(criteria, 1))
        text += '<!-- AC:END -->\n'
    return text


def leaf_task(ident, tid, deps=(), **kw):
    (spec,) = [w for w in PLAN['work_packages'] if w['id'] == ident]
    proof = spec['proof']
    first, second = proof.split(' (1) ')
    kw.setdefault('criteria', [first, '(1) ' + second])
    kw.setdefault('refs', [f'{pc.PLAN}#{ident}'])
    return tid, dict(title=f'{ident}: {spec["title"]}', deps=deps, **kw)


def act_task(act, tid, **kw):
    kw.setdefault('refs', [ACT_REF])
    kw.setdefault('labels', ['gates:W-01.3'])
    kw.setdefault('criteria', [f"Done only by reference to the Owner's recorded act {act}."])
    return tid, dict(title=f'{act}: an Owner act', **kw)


def tasks():
    return dict([
        leaf_task('W-01.1', 'TASK-1'),
        leaf_task('W-01.2', 'TASK-2', deps=['TASK-1']),
        act_task('OA-7', 'TASK-3'),
        leaf_task('W-01.3', 'TASK-4', deps=['TASK-2', 'TASK-3']),
    ])


class Fixture(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(pc, 'LEAVES_CLOSED', FIXTURE_CLOSED)
        patcher.start()
        self.addCleanup(patcher.stop)
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.plan = self.write('plan.json', json.dumps(PLAN))
        self.log = self.write('log.md', LOG)
        self.backlog = str(self.dir / 'backlog')
        self.tasks = tasks()
        self.write_backlog()

    def write(self, name, text):
        path = self.dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8', newline='\n')
        return str(path)

    def write_backlog(self, config=CONFIG):
        shutil.rmtree(self.backlog, ignore_errors=True)
        self.write('backlog/config.yml', config)
        for name, (ident, title) in MILESTONES.items():
            self.write(f'backlog/milestones/{name}', f'---\nid: {ident}\ntitle: "{title}"\n---\n\n## Description\n\n'
                                                     f'Milestone: {title}\n')
        for tid, spec in self.tasks.items():
            self.write(f'backlog/tasks/{tid.lower()} - {spec["title"].split(":")[0]}.md', task_text(tid, **spec))

    def report(self, terminal):
        return pc.report(terminal, self.plan, self.log, self.backlog)

    def rows(self, terminal):
        return {r['id']: r for r in self.report(terminal)['leaves']}

    def run_main(self, *argv, plan=None, log=None, backlog=None):
        out, err = io.StringIO(), io.StringIO()
        args = list(argv) + ['--plan', plan or self.plan, '--log', log or self.log,
                             '--backlog-dir', backlog or self.backlog]
        code = pc.main(args, stdout=out, stderr=err)
        return code, out.getvalue(), err.getvalue()

    def assert_refused(self, code_name, *argv, **paths):
        code, out, err = self.run_main(*(argv or ('W-01.3',)), '--json', **paths)
        self.assertEqual(code, 2, err)
        self.assertIn(f'REFUSED {code_name}:', err)
        self.assertEqual(json.loads(out)['error']['code'], code_name)
        return err


class StatusParsingTests(unittest.TestCase):
    def test_first_bold_token_reduced_to_leading_upper_case_words(self):
        cases = {
            '**PASS (2026-11-12)**: accepted': 'PASS',
            '**IN PROGRESS (2026-11-11)**: slice 2': 'IN PROGRESS',
            '**BLOCKED on one clause (acceptance review 2026-11-12; OA-21)**': 'BLOCKED',
            '**STOPPED (2026-11-11)** at the boundary': 'STOPPED',
            '**PASS:** done, then **FAIL** later': 'PASS',
            'PASS (2026-11-06), specification only; pushed': 'PASS',
            'Not started': 'not started',
        }
        for cell, expected in cases.items():
            with self.subTest(cell=cell):
                self.assertEqual(pc.status_of(cell), expected)

    @mock.patch.object(pc, 'LEAVES_CLOSED', FIXTURE_CLOSED)
    def test_leaves_table_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'log.md'
            path.write_text(LOG, encoding='utf-8')
            statuses = pc.load_statuses(path)
        self.assertEqual(statuses['A-01.1'], 'PASS')
        self.assertEqual(statuses['A-01.2'], 'PASS')
        self.assertEqual(statuses['B-01.1'], 'IN PROGRESS')
        self.assertEqual(statuses['D-01.1'], 'BLOCKED')
        self.assertNotIn('B-01.2', statuses)  # a row under Decisions is not a Leaves row
        self.assertNotIn('OA-1', statuses)


class ClosureAndReadinessTests(Fixture):
    def test_closure_is_the_transitive_dependencies_in_dependency_order(self):
        result = self.report('B-01.2')
        ids = [r['id'] for r in result['leaves']]
        self.assertEqual(ids, ['A-01.1', 'A-01.2', 'B-01.1', 'B-01.2'])
        self.assertNotIn('C-01.1', ids)  # a dependant is not in the closure
        self.assertNotIn('D-01.1', ids)  # an unrelated leaf is not either

    def test_readiness_and_summary(self):
        result = self.report('C-01.1')
        rows = {r['id']: r for r in result['leaves']}
        self.assertTrue(rows['A-01.1']['passed'])
        self.assertFalse(rows['A-01.1']['ready'])  # passed is never ready
        self.assertTrue(rows['B-01.1']['ready'])  # in progress, its dependency passed
        self.assertEqual(rows['B-01.2']['status'], 'not started')  # no row, no task
        self.assertEqual(rows['B-01.2']['source'], 'none')
        self.assertFalse(rows['B-01.2']['ready'])  # B-01.1 has not passed
        self.assertFalse(rows['C-01.1']['ready'])
        self.assertEqual(rows['B-01.2']['deps'], ['A-01.2', 'B-01.1'])
        self.assertEqual(result['summary'], {'total': 5, 'passed': 2, 'open': 3, 'ready': 1, 'blocked': 2})
        self.assertEqual(result['ready'], ['B-01.1'])

    def test_own_status_does_not_change_readiness(self):
        (row,) = self.report('D-01.1')['leaves']
        self.assertEqual((row['status'], row['ready'], row['source']), ('BLOCKED', True, 'leaves-table'))

    def test_text_and_json_output(self):
        code, out, err = self.run_main('C-01.1')
        self.assertEqual((code, err), (0, ''))
        self.assertIn('Summary: total 5, passed 2, open 3, ready 1, blocked 2', out)
        self.assertIn('Ready: B-01.1', out)
        self.assertIn('closed on 2026-11-16 at 5 rows', out)
        code, out, _ = self.run_main('C-01.1', '--json')
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data['schema'], 'ai-engineering-harness/plan-commitment/v2')
        self.assertEqual(data['terminal'], 'C-01.1')
        self.assertEqual(data['summary']['total'], 5)
        self.assertEqual(data['leaves_table'], {'date': '2026-11-16', 'rows': 5})


class BacklogStatusTests(Fixture):
    """A leaf without a row takes its Backlog.md task's status: Done is passed, any other is open."""

    def set_status(self, tid, status, refs=None):
        self.tasks[tid]['status'] = status
        if refs is not None:
            self.tasks[tid]['refs'] = refs
        self.write_backlog()

    def test_task_status_is_the_leaf_status(self):
        rows = self.rows('W-01.3')
        self.assertEqual((rows['W-01.1']['status'], rows['W-01.1']['source'], rows['W-01.1']['task']),
                         ('To Do', 'backlog', 'TASK-1'))
        self.assertTrue(rows['W-01.1']['ready'])
        self.assertFalse(rows['W-01.2']['ready'])
        self.assertEqual(rows['A-01.1']['source'], 'leaves-table')

    def test_a_task_status_change_changes_readiness(self):
        before = self.rows('W-01.3')
        self.assertEqual((before['W-01.1']['passed'], before['W-01.2']['ready']), (False, False))
        self.set_status('TASK-1', 'In Progress')
        rows = self.rows('W-01.3')
        self.assertEqual((rows['W-01.1']['status'], rows['W-01.1']['passed'], rows['W-01.2']['ready']),
                         ('In Progress', False, False))
        self.set_status('TASK-1', 'Done')
        rows = self.rows('W-01.3')
        self.assertEqual((rows['W-01.1']['status'], rows['W-01.1']['passed']), ('Done', True))
        self.assertTrue(rows['W-01.2']['ready'])

    def test_an_open_owner_act_blocks_and_is_named(self):
        self.tasks['TASK-1']['status'] = 'Done'
        self.set_status('TASK-2', 'Done')
        rows = self.rows('W-01.3')
        self.assertEqual((rows['W-01.3']['ready'], rows['W-01.3']['waits_on']), (False, ['OA-7']))
        code, out, _ = self.run_main('W-01.3')
        self.assertEqual(code, 0)
        self.assertIn('blocked', [line for line in out.splitlines() if line.startswith('W-01.3')][0])
        self.assertIn('[waits on Owner act: OA-7]', out)
        self.set_status('TASK-3', 'Done', refs=[ACT_REF, RECORDED])
        rows = self.rows('W-01.3')
        self.assertEqual((rows['W-01.3']['ready'], rows['W-01.3']['waits_on']), (True, []))

    def test_owner_act_done_only_by_reference_to_a_recorded_act(self):
        log = 'evidence/bootstrap-log.md#'
        cases = {
            'no log reference': [],
            'a Decisions anchor that is not an Owner record': [ACT_REF],
            'an owner- anchor that the Decisions do not hold': [log + 'owner-act-oa-7-1999-01-01'],
            'another file': ['other.md#owner-act-oa-7-2026-11-20'],
            'another act\'s record': [log + 'owner-decision-oa-1-2026-11-10'],
            'an anchor in a code span': [log + 'owner-span-oa-7'],
            'an anchor in an HTML comment': [log + 'owner-comment-oa-7'],
            'an anchor in a fenced block': [log + 'owner-fenced-oa-7'],
            'a relative path': ['./' + RECORDED],
        }
        for name, refs in cases.items():
            with self.subTest(name):
                self.set_status('TASK-3', 'Done', refs=refs)
                err = self.assert_refused('OWNER_ACT_UNRECORDED')
                self.assertIn('TASK-3 (OA-7)', err)

    def test_the_recorded_act_names_the_act_as_a_token(self):
        self.assertTrue(pc.re.search(r'(^|-)oa-7(-|$)', 'owner-act-oa-7-2026-11-20'))
        for anchor in ('owner-act-oa-70-2026-11-20', 'owner-act-xoa-7', 'owner-act-oa-7x'):
            with self.subTest(anchor):
                log = LOG.replace('</a>**2026-11-10', f'</a><a id="{anchor}"></a>**2026-11-10')
                self.set_status('TASK-3', 'Done', refs=[f'evidence/bootstrap-log.md#{anchor}'])
                self.assert_refused('OWNER_ACT_UNRECORDED', log=self.write('anchors.md', log))

    def test_a_done_leaf_needs_its_dependencies_passed(self):
        self.set_status('TASK-2', 'Done')  # W-01.1 is To Do
        self.assertIn('TASK-2 for W-01.2 is Done while W-01.1 has not passed', self.assert_refused('TASK_DONE_EARLY'))
        self.tasks['TASK-1']['status'] = 'Done'
        self.tasks['TASK-2']['status'] = 'Done'
        self.set_status('TASK-4', 'Done')  # its act OA-7 is open
        self.assertIn('while OA-7 has not passed', self.assert_refused('TASK_DONE_EARLY'))
        self.set_status('TASK-3', 'Done', refs=[ACT_REF, RECORDED])
        self.assertTrue(self.rows('W-01.3')['W-01.3']['passed'])
        log = LOG.replace('| A-01.2 Second | PASS (2026-11-06); pushed |', '| A-01.2 Second | **IN PROGRESS** |')
        self.assertIn('while A-01.2 has not passed',  # a Leaves-table dependency that has not passed
                      self.assert_refused('TASK_DONE_EARLY', log=self.write('open.md', log)))

    def test_crlf_files_read_the_same(self):
        expected = self.report('W-01.3')
        for path in Path(self.backlog).rglob('*'):
            if path.is_file():
                path.write_bytes(path.read_bytes().replace(b'\n', b'\r\n'))
        self.assertEqual(self.report('W-01.3'), expected)


class BacklogCheckTests(Fixture):
    """Every mismatch between the tasks, the plan and the log refuses the report."""

    def rewrite(self, tid, **changes):
        self.tasks[tid].update(changes)
        self.write_backlog()

    def test_the_fixture_passes(self):
        self.assertEqual(self.run_main('W-01.3')[0], 0)

    def test_criteria_split_freely_and_whitespace_normalized(self):
        proof = [w for w in PLAN['work_packages'] if w['id'] == 'W-01.1'][0]['proof']
        words = proof.split(' ')
        self.rewrite('TASK-1', criteria=[' '.join(words[:3]), '  '.join(words[3:7]) + ' ', ' '.join(words[7:])])
        self.assertEqual(self.run_main('W-01.3')[0], 0)

    def test_criteria_differing_from_the_proof(self):
        proof = [w for w in PLAN['work_packages'] if w['id'] == 'W-01.2'][0]['proof']
        for name, criteria in {'one word': [proof.replace('first', 'only')],
                               'a dropped sentence': [proof.split(' (1) ')[0]],
                               'none': []}.items():
            with self.subTest(name):
                self.rewrite('TASK-2', criteria=criteria)
                err = self.assert_refused('TASK_CRITERIA_MISMATCH')
                self.assertIn('TASK-2 for W-01.2', err)

    def test_two_status_sources(self):
        self.tasks.update([leaf_task('A-01.2', 'TASK-9')])
        self.write_backlog()
        err = self.assert_refused('STATUS_TWO_SOURCES')
        self.assertIn('A-01.2 has both a Leaves-table row and the task TASK-9', err)

    def test_unmapped_and_duplicate_tasks(self):
        self.tasks['TASK-9'] = dict(title='A task about nothing')
        self.write_backlog()
        self.assert_refused('TASK_UNMAPPED')
        self.tasks['TASK-9'] = dict(title='Z-09.9: Not a plan leaf')
        self.write_backlog()
        self.assert_refused('TASK_UNMAPPED')
        del self.tasks['TASK-9']
        self.tasks.update([leaf_task('W-01.1', 'TASK-9')])
        self.write_backlog()
        self.assertIn('W-01.1 has two tasks', self.assert_refused('TASK_DUPLICATE'))
        del self.tasks['TASK-9']
        self.tasks.update([act_task('OA-7', 'TASK-9')])
        self.write_backlog()
        self.assertIn('OA-7 has two tasks', self.assert_refused('TASK_DUPLICATE'))

    def test_unknown_owner_act(self):
        self.tasks.update([act_task('OA-99', 'TASK-9')])
        self.write_backlog()
        self.assertIn('OA-99', self.assert_refused('OWNER_ACT_UNKNOWN'))

    def test_link_to_the_plan_contract(self):
        self.rewrite('TASK-1', title='W-01.1: Another title')
        self.assert_refused('TASK_LINK_MISMATCH')
        self.rewrite('TASK-1', title='W-01.1: Leaf W-01.1', refs=[f'{pc.PLAN}#W-01.2'])
        self.assert_refused('TASK_LINK_MISMATCH')
        self.rewrite('TASK-1', refs=[])
        self.assert_refused('TASK_LINK_MISMATCH')

    def test_title_is_a_word_boundary_prefix_of_the_plan_title(self):
        self.rewrite('TASK-1', title='W-01.1: Leaf')  # the plan title is "Leaf W-01.1"
        self.assertEqual(self.run_main('W-01.3')[0], 0)
        for name, title in {'a cut inside a word': 'W-01.1: Lea', 'a cut inside the last word': 'W-01.1: Leaf W-01',
                            'not a prefix': 'W-01.1: W-01.1', 'a trailing space': 'W-01.1: Leaf ',
                            'another leaf id': 'W-01.2: Leaf'}.items():
            with self.subTest(name):
                self.rewrite('TASK-1', title=title)
                code = 'TASK_DUPLICATE' if title.startswith('W-01.2') else 'TASK_LINK_MISMATCH'
                self.assert_refused(code)

    def test_path_length(self):
        name = 'tasks/task-1 - ' + 'x' * (100 - len('backlog/tasks/task-1 - .md')) + '.md'
        source = Path(self.backlog) / 'tasks' / 'task-1 - W-01.1.md'
        text = source.read_text(encoding='utf-8')
        source.unlink()
        self.write(f'backlog/{name}', text)
        self.assertEqual(len(f'backlog/{name}'), 100)
        self.assertEqual(self.run_main('W-01.3')[0], 0)  # 100 characters is within the limit
        (Path(self.backlog) / name).rename(Path(self.backlog) / name.replace('.md', 'y.md'))
        err = self.assert_refused('BACKLOG_PATH_TOO_LONG')
        self.assertIn('is 101 characters long', err)
        self.write_backlog()
        self.write('backlog/milestones/' + 'm' * 90 + '.md', '---\nid: m-5\ntitle: "I5"\n---\n')
        self.assert_refused('BACKLOG_PATH_TOO_LONG')

    def test_milestone(self):
        self.rewrite('TASK-1', milestone='m-1')
        self.assertIn("milestone 'I2', the plan milestone is 'I1'", self.assert_refused('TASK_MILESTONE_MISMATCH'))
        self.rewrite('TASK-1', milestone=None)
        self.assert_refused('TASK_MILESTONE_MISMATCH')

    def test_dependencies(self):
        for name, deps in {'a missing plan dependency': [],
                           'an extra leaf task': ['TASK-2'],
                           'a task that does not exist': ['TASK-77'],
                           'a repeated dependency': ['TASK-1', 'TASK-1']}.items():
            with self.subTest(name):
                self.rewrite('TASK-2', deps=deps)
                self.assert_refused('TASK_DEPENDENCIES_MISMATCH')
        self.rewrite('TASK-3', labels=['gates:W-01.3', 'gates:W-01.2'])
        self.rewrite('TASK-2', deps=['TASK-1', 'TASK-3'])  # an Owner-act task that gates it may be added
        self.assertEqual(self.run_main('W-01.3', log=self.write('two.md', LOG.replace(
            "W-01.3's run", "W-01.3's run and W-01.2")))[0], 0)

    def test_owner_act_gates(self):
        cases = {
            'OWNER_ACT_GATES_NOTHING': dict(labels=[]),
            'OWNER_ACT_GATE_UNLISTED': dict(labels=['gates:W-01.1']),  # OA-7's row names W-01.3 only
        }
        for code, changes in cases.items():
            with self.subTest(code):
                self.tasks = tasks()
                self.rewrite('TASK-3', **changes)
                self.assert_refused(code)
        self.tasks = tasks()
        self.rewrite('TASK-3', labels=['gates:Z-09.9'])
        self.assert_refused('OWNER_ACT_GATE_UNLISTED')

    def test_a_gated_leaf_keeps_its_act_dependency(self):
        self.rewrite('TASK-4', deps=['TASK-2'])  # the act dependency dropped
        self.assertIn('OA-7 gates W-01.3, but its task TASK-4 does not depend on TASK-3',
                      self.assert_refused('OWNER_ACT_GATE_DROPPED'))
        del self.tasks['TASK-4']  # the gated leaf's task deleted
        self.write_backlog()
        self.assertIn('OA-7 gates W-01.3, which has no task', self.assert_refused('OWNER_ACT_GATE_UNTASKED'))

    def test_a_leaf_depends_only_on_acts_that_gate_it(self):
        self.rewrite('TASK-2', deps=['TASK-1', 'TASK-3'])  # OA-7 does not declare W-01.2
        self.assertIn('does not declare gates:W-01.2', self.assert_refused('OWNER_ACT_GATE_UNDECLARED'))
        self.rewrite('TASK-3', labels=['gates:W-01.3', 'gates:W-01.2'])  # OA-7's row does not name W-01.2
        self.assert_refused('OWNER_ACT_GATE_UNLISTED')
        self.tasks.update([act_task('OA-8', 'TASK-9', labels=['gates:W-01.2'])])
        self.rewrite('TASK-3', labels=['gates:W-01.3'])
        self.rewrite('TASK-2', deps=['TASK-1', 'TASK-9'])
        self.assertEqual(self.rows('W-01.3')['W-01.2']['waits_on'], ['OA-8'])

    def test_a_plan_dependency_without_row_or_task(self):
        del self.tasks['TASK-1']
        self.rewrite('TASK-2', deps=[])
        self.assertIn('W-01.2 (TASK-2) depends on W-01.1', self.assert_refused('TASK_MISSING'))

    def test_checks_run_whatever_the_terminal(self):
        self.rewrite('TASK-2', criteria=['Something else.'])
        self.assert_refused('TASK_CRITERIA_MISMATCH', 'D-01.1')


class LeavesClosureTests(Fixture):
    def test_closure_record_required(self):
        log = LOG.replace('**Closed on 2026-11-16 at 5 rows**', 'Closed')
        self.assert_refused('LEAVES_CLOSURE_MISSING', log=self.write('noclosure.md', log))
        log = LOG.replace('Intro text.', 'Intro text. **Closed on 2026-11-17 at 5 rows**')
        self.assert_refused('LEAVES_CLOSURE_MISSING', log=self.write('twoclosures.md', log))

    def test_table_gains_no_rows(self):
        row = '| D-01.1 Other | **BLOCKED on one clause (review)** | x | e | g |\n'
        new = '| W-01.1 A new row | **PASS (2026-11-20)** | x | e | g |\n'
        log = LOG.replace(row, row + new)
        err = self.assert_refused('LEAVES_TABLE_REOPENED', log=self.write('grown.md', log))
        self.assertIn('the Leaves table has 6 rows and row 6 is W-01.1; it was closed on 2026-11-16 at 5 rows', err)
        self.assert_refused('LEAVES_TABLE_REOPENED', log=self.write('shrunk.md', LOG.replace(row, '')))
        log = LOG.replace(row, row + new).replace('at 5 rows**', 'at 6 rows**')  # the record edited too
        err = self.assert_refused('LEAVES_TABLE_REOPENED', log=self.write('recount.md', log))
        self.assertIn('the closure record reads closed on 2026-11-16 at 6 rows', err)

    def test_the_rows_ids_are_pinned(self):
        row = '| D-01.1 Other | **BLOCKED on one clause (review)** | x | e | g |\n'
        cases = {
            'a row replaced': LOG.replace(row, '| W-01.1 Swapped in | **PASS (2026-11-20)** | x | e | g |\n'),
            'a first cell relabelled': LOG.replace('| B-01.1 Third |', '| W-01.2 Third |'),
            'rows reordered': LOG.replace('| A-01.1 First', '| A-01.X').replace('| A-01.2 Second', '| A-01.1 First')
                                 .replace('| A-01.X', '| A-01.2 Second'),
        }
        for name, log in cases.items():
            with self.subTest(name):
                self.assert_refused('LEAVES_TABLE_REOPENED', log=self.write('swapped.md', log))

    def test_no_rows_after_the_closed_table(self):
        row = '| D-01.1 Other | **BLOCKED on one clause (review)** | x | e | g |\n'
        cases = {
            'a second table': LOG.replace(row, row + '\n| Task | Verdict |\n|---|---|\n| W-01.1 x | **PASS** |\n'),
            'a table split by a blank line': LOG.replace('| B-01.1 Third', '\n| B-01.1 Third'),
            'an indented row': LOG.replace(row, row + '\nText.\n\n  | W-01.1 x | **PASS** |\n'),
        }
        for name, log in cases.items():
            with self.subTest(name):
                self.assert_refused('LEAVES_TABLE_REOPENED', log=self.write('after.md', log))

    def test_a_verdict_edited_in_place_is_accepted(self):
        log = LOG.replace('**IN PROGRESS (2026-11-11)**: slice 1', '**PASS (2026-11-20)**')
        code, out, _ = self.run_main('C-01.1', '--json', log=self.write('edited.md', log))
        self.assertEqual(code, 0)
        self.assertEqual({r['id']: r['status'] for r in json.loads(out)['leaves']}['B-01.1'], 'PASS')


class BacklogReaderTests(Fixture):
    """The strict reader: the subset Backlog.md writes is read; anything else is refused."""

    def test_folded_quoted_and_plain_scalars(self):
        lines = ['id: TASK-16', 'title: >-', '  U-06.1: Demonstrate I1: one Owner request through the Owner UI to an',
                 '  accepted objective', "status: 'In Progress'", 'milestone: "m-0"', 'labels: []',
                 'dependencies:', '  - TASK-15', '  - TASK-1', 'references:', '  - >-',
                 f'    {pc.PLAN}#U-06.1', '  - evidence/bootstrap-log.md#owner-act-oa-32']
        self.assertEqual(pc.parse_yaml(lines, 'fixture'), {
            'id': 'TASK-16', 'title': 'U-06.1: Demonstrate I1: one Owner request through the Owner UI to an '
                                      'accepted objective',
            'status': 'In Progress', 'milestone': 'm-0', 'labels': [], 'dependencies': ['TASK-15', 'TASK-1'],
            'references': [f'{pc.PLAN}#U-06.1', 'evidence/bootstrap-log.md#owner-act-oa-32']})
        self.assertEqual(pc.parse_yaml(["title: 'OA-32: The Owner''s act'"], 'f'), {'title': "OA-32: The Owner's act"})

    def test_unsupported_yaml_is_refused(self):
        cases = {
            'literal block': ['title: |', '  text'],
            'more-indented folded line': ['title: >-', '  a', '    b'],
            'blank line in folded': ['title: >-', '  a', '', '  b'],
            'keep folded': ['title: >', '  a'],
            'anchor': ['title: &a text'],
            'mapping in plain': ['title: a: b'],
            'comment': ['status: To Do # done'],
            'escape': ['title: "a\\tb"'],
            'open quote': ["title: 'a"],
            'flow mapping': ['title: {a: b}'],
            'nested mapping': ['title:', '  a: b'],
            'empty value': ['milestone:'],
            'duplicate key': ['status: Done', 'status: To Do'],
            'indented key': ['  status: Done'],
        }
        for name, lines in cases.items():
            with self.subTest(name):
                with self.assertRaises(pc.Refusal) as ctx:
                    pc.parse_yaml(lines, 'fixture')
                self.assertEqual(ctx.exception.code, 'BACKLOG_UNREADABLE')

    def put(self, name, text):
        self.write(f'backlog/{name}', text)

    def test_unreadable_task_files(self):
        good = (Path(self.backlog) / 'tasks' / 'task-1 - W-01.1.md').read_text(encoding='utf-8')
        cases = {
            'no front matter': good.replace('---\n', '', 1),
            'unknown status': good.replace('status: To Do', 'status: Finished'),
            'unknown milestone': good.replace('milestone: m-0', 'milestone: m-9'),
            'two criteria blocks': good + '<!-- AC:BEGIN -->\n- [ ] #1 x\n<!-- AC:END -->\n',
            'misnumbered criterion': good.replace('- [ ] #2 ', '- [ ] #3 '),
            'free text in criteria': good.replace('<!-- AC:END -->', 'text\n<!-- AC:END -->'),
            'a list where text is expected': good.replace("title: 'W-01.1: Leaf W-01.1'", 'title: []'),
        }
        for name, text in cases.items():
            with self.subTest(name):
                self.write_backlog()
                self.put('tasks/task-1 - W-01.1.md', text)
                self.assert_refused('BACKLOG_UNREADABLE')

    def test_duplicate_task_id_and_unsupported_files(self):
        self.put('tasks/task-1 - copy.md', (Path(self.backlog) / 'tasks' / 'task-1 - W-01.1.md')
                 .read_text(encoding='utf-8'))
        self.assertIn('duplicate task id TASK-1', self.assert_refused('BACKLOG_UNREADABLE'))
        for name in ('drafts/draft-1 - x.md', 'completed/task-1 - W-01.1.md', 'archive/tasks/task-5 - x.md',
                     'tasks/notes.txt', 'docs/doc-1.md'):
            with self.subTest(name):
                self.write_backlog()
                self.put(name, '---\nid: X\n---\n')
                self.assertIn('unsupported file', self.assert_refused('BACKLOG_UNREADABLE'))

    def test_config(self):
        for key in pc.CONFIG_OFF:
            with self.subTest(key):
                self.write_backlog(CONFIG.replace(f'{key}: false', f'{key}: true'))
                self.assertIn(key, self.assert_refused('BACKLOG_CONFIG_REFUSED'))
        self.write_backlog(CONFIG.replace('statuses: ["To Do", "In Progress", "Done"]\n', ''))
        self.assert_refused('BACKLOG_UNREADABLE')

    def test_no_backlog_directory(self):
        self.assert_refused('UNREADABLE_FILE', backlog=str(self.dir / 'absent'))


class RefusalTests(Fixture):
    def test_unknown_leaf(self):
        self.assert_refused('UNKNOWN_LEAF', 'Z-09.9')

    def test_group_id_names_its_terminal_leaf(self):
        err = self.assert_refused('UNKNOWN_LEAF', 'B-01')
        self.assertIn('its terminal leaf is B-01.2', err)

    def test_cycle(self):
        plan = {'work_packages': [leaf('X-01.1', ['X-01.2']), leaf('X-01.2', ['X-01.1']),
                                  leaf('X-01.3', ['X-01.2'])], 'milestones': PLAN['milestones']}
        empty = self.dir / 'empty-backlog'
        (empty / 'tasks').mkdir(parents=True)
        (empty / 'config.yml').write_text(CONFIG, encoding='utf-8')
        err = self.assert_refused('DEPENDENCY_CYCLE', 'X-01.3', plan=self.write('cycle.json', json.dumps(plan)),
                                  backlog=str(empty))
        self.assertIn('X-01.1, X-01.2', err)

    def test_unreadable_files(self):
        missing = str(self.dir / 'absent.json')
        self.assert_refused('UNREADABLE_FILE', 'A-01.1', plan=missing)
        self.assert_refused('UNREADABLE_FILE', 'A-01.1', plan=self.write('bad.json', '{not json'))
        self.assert_refused('UNREADABLE_FILE', 'A-01.1', plan=self.write('nowp.json', '{}'))
        self.assert_refused('UNREADABLE_FILE', 'A-01.1', log=self.write('noleaves.md', '# Log\n\n## Decisions\n'))
        self.assert_refused('UNREADABLE_FILE', 'A-01.1', log=str(self.dir / 'absent.md'))


I1_WAVE = {'U-01.3', 'E-01.4.1', 'E-01.7', 'U-02.1', 'U-01.2', 'E-01.4.2', 'U-02.2', 'P-01.3', 'E-01.5',
           'P-04.4', 'U-04.1', 'E-01.8', 'U-04.2', 'U-06.1'}


def committed_copy(test):
    """A throwaway copy of the committed backlog/ with every task's status reset to To Do and every
    reference to an Owner record (``evidence/bootstrap-log.md#owner-...``) removed, so that a test of
    a status change or of an Owner act stays true whatever the committed statuses and recorded acts
    are as I1 progresses."""
    tmp = tempfile.TemporaryDirectory()
    test.addCleanup(tmp.cleanup)
    copy = Path(tmp.name) / 'backlog'
    shutil.copytree(ROOT / pc.BACKLOG, copy)
    owner_ref = pc.LOG + '#' + pc.OWNER_ANCHOR_PREFIX
    for path in (copy / 'tasks').glob('*.md'):
        lines = path.read_text(encoding='utf-8').replace('\r\n', '\n').split('\n')
        end = lines.index('---', 1)
        head = []
        n = 0
        while n < end:
            line = lines[n]
            if line == '  - >-' and n + 1 < end and lines[n + 1].strip().startswith(owner_ref):
                n += 2  # a folded reference item
                continue
            if line.startswith('  - ' + owner_ref):
                n += 1
                continue
            head.append('status: To Do' if line.startswith('status: ') else line)
            n += 1
        head = ['references: []' if line == 'references:' and (i + 1 == len(head) or not head[i + 1].startswith('  - '))
                else line for i, line in enumerate(head)]
        path.write_text('\n'.join(head + lines[end:]), encoding='utf-8', newline='\n')
    return copy


def committed_log(test, extra=''):
    """A throwaway copy of the committed log, with ``extra`` added at the start of its Decisions."""
    tmp = tempfile.TemporaryDirectory()
    test.addCleanup(tmp.cleanup)
    text = (ROOT / pc.LOG).read_text(encoding='utf-8').replace('\r\n', '\n')
    assert text.count('\n## Decisions\n') == 1
    path = Path(tmp.name) / 'log.md'
    path.write_text(text.replace('\n## Decisions\n', '\n## Decisions\n\n' + extra), encoding='utf-8', newline='\n')
    return path


def committed_task(backlog, title_head):
    """The task whose title starts with ``<title_head>:``, and its text with LF line ends (a checkout
    may hold CRLF)."""
    (task,) = [t for t in pc.Backlog(backlog).tasks.values() if t['title'].startswith(title_head + ': ')]
    return task, task['path'].read_text(encoding='utf-8').replace('\r\n', '\n')


def rewrite(task, text):
    task['path'].write_text(text, encoding='utf-8', newline='\n')


class CommittedPlanTests(unittest.TestCase):
    """The committed plan, log and backlog/: every leaf's closure computes, the D1 terminal leaf's
    included, and the next wave (I1) is in Backlog.md."""

    category = 'contract'

    def test_d1_closure(self):
        result = pc.report('E-05.5')
        ids = [r['id'] for r in result['leaves']]
        self.assertEqual(ids[-1], 'E-05.5')
        for ident in ('E-05.1', 'E-05.2', 'E-05.3', 'E-05.4', 'E-01.3.2', 'E-05.11', 'P-04.3'):
            self.assertIn(ident, ids)
        self.assertEqual(len(ids), len(set(ids)))
        position = {ident: n for n, ident in enumerate(ids)}
        for row in result['leaves']:
            for dep in row['deps']:
                self.assertLess(position[dep], position[row['id']])
        s = result['summary']
        self.assertEqual(s['total'], s['passed'] + s['ready'] + s['blocked'])

    def test_every_leaf_resolves(self):
        leaves, _, _ = pc.load_plan(pc.ROOT / pc.PLAN)
        for ident in leaves:
            pc.closure(leaves, ident)

    def test_next_wave_is_in_backlog(self):
        """Status-independent: true whatever the tasks' statuses are."""
        rows = {r['id']: r for r in pc.report('U-06.1')['leaves']}
        for ident, row in rows.items():
            with self.subTest(ident):
                self.assertEqual(row['source'], 'backlog' if ident in I1_WAVE else 'leaves-table')
        backlog = pc.Backlog(ROOT / pc.BACKLOG)
        by_head = {t['title'].split(': ', 1)[0]: t for t in backlog.tasks.values()}
        for act in ('OA-32', 'OA-33'):
            self.assertEqual(by_head[act]['labels'], ['gates:U-06.1'])
            self.assertIn(by_head[act]['id'], by_head['U-06.1']['dependencies'])
        for path in (ROOT / pc.BACKLOG).rglob('*'):
            self.assertLessEqual(len(path.relative_to(ROOT).as_posix()), pc.MAX_PATH, path.name)
        backlog = pc.Backlog(ROOT / pc.BACKLOG)
        leaves = pc.load_plan(ROOT / pc.PLAN)[0]
        heads = sorted(t['title'].split(': ', 1)[0] for t in backlog.tasks.values())
        self.assertEqual(heads, sorted(I1_WAVE | {'OA-32', 'OA-33'}))
        for task in backlog.tasks.values():
            head = task['title'].split(': ', 1)[0]
            self.assertEqual(task['milestone'], 'I1')
            if head in leaves:  # the check plan_commitment.py runs, stated here once more
                self.assertEqual(' '.join(' '.join(task['criteria']).split()), ' '.join(leaves[head]['proof'].split()))

    def test_p05_1_keeps_its_row(self):
        (row,) = [r for r in pc.report('P-05.1')['leaves'] if r['id'] == 'P-05.1']
        self.assertEqual(row['source'], 'leaves-table')

    def test_a_next_wave_task_status_change_changes_readiness(self):
        copy = committed_copy(self)
        before = {r['id']: r for r in pc.report('U-06.1', backlog_dir=copy)['leaves']}
        self.assertEqual((before['E-01.4.1']['ready'], before['E-01.4.2']['ready']), (True, False))
        self.assertEqual(before['U-06.1']['waits_on'], ['OA-32', 'OA-33'])
        task, text = committed_task(copy, 'E-01.4.1')
        self.assertEqual(text.count('\nstatus: To Do\n'), 1)
        rewrite(task, text.replace('\nstatus: To Do\n', '\nstatus: Done\n'))
        after = {r['id']: r for r in pc.report('U-06.1', backlog_dir=copy)['leaves']}
        self.assertEqual((after['E-01.4.1']['status'], after['E-01.4.1']['passed']), ('Done', True))
        self.assertTrue(after['E-01.4.2']['ready'])

    def test_a_next_wave_criteria_change_is_refused(self):
        copy = committed_copy(self)
        task, text = committed_task(copy, 'U-04.2')
        rewrite(task, text.replace('- [ ] #1 ', '- [ ] #1 Roughly: ', 1))
        with self.assertRaises(pc.Refusal) as ctx:
            pc.report('U-06.1', backlog_dir=copy)
        self.assertEqual(ctx.exception.code, 'TASK_CRITERIA_MISMATCH')
        self.assertIn('U-04.2', ctx.exception.detail)

    def test_owner_act_tasks_close_only_on_a_recorded_act(self):
        copy = committed_copy(self)
        task, text = committed_task(copy, 'OA-32')
        done = text.replace('\nstatus: To Do\n', '\nstatus: Done\n')
        rewrite(task, done)
        with self.assertRaises(pc.Refusal) as ctx:
            pc.report('U-06.1', backlog_dir=copy)
        self.assertEqual(ctx.exception.code, 'OWNER_ACT_UNRECORDED')
        anchor = 'owner-act-oa-32-2099-01-01'  # a stand-in for OA-32's record, in a copy of the log
        rewrite(task, done.replace('references:\n', f'references:\n  - evidence/bootstrap-log.md#{anchor}\n'))
        for name, ref in {'another Owner record': 'owner-direction-i1-2026-11-16',
                          'another act\'s record': 'owner-decision-oa-31-2026-11-14'}.items():
            with self.subTest(name):
                other = done.replace('references:\n', f'references:\n  - evidence/bootstrap-log.md#{ref}\n')
                rewrite(task, other)
                with self.assertRaises(pc.Refusal) as ctx:
                    pc.report('U-06.1', backlog_dir=copy, log_path=committed_log(self))
                self.assertEqual(ctx.exception.code, 'OWNER_ACT_UNRECORDED')
        rewrite(task, done.replace('references:\n', f'references:\n  - evidence/bootstrap-log.md#{anchor}\n'))
        log = committed_log(self, f'- <a id="{anchor}"></a>**A test record.**\n')
        rows = {r['id']: r for r in pc.report('U-06.1', backlog_dir=copy, log_path=log)['leaves']}
        self.assertEqual(rows['U-06.1']['waits_on'], ['OA-33'])

    def test_the_act_gate_cannot_be_dropped(self):
        copy = committed_copy(self)
        task, text = committed_task(copy, 'U-06.1')
        acts = [committed_task(copy, act)[0]['id'] for act in ('OA-32', 'OA-33')]
        dropped = text
        for act in acts:
            dropped = dropped.replace(f'  - {act}\n', '', 1)
        self.assertNotEqual(dropped, text)
        rewrite(task, dropped)
        with self.assertRaises(pc.Refusal) as ctx:
            pc.report('U-06.1', backlog_dir=copy)
        self.assertEqual(ctx.exception.code, 'OWNER_ACT_GATE_DROPPED')
        task['path'].unlink()
        with self.assertRaises(pc.Refusal) as ctx:
            pc.report('U-06.1', backlog_dir=copy)
        self.assertEqual(ctx.exception.code, 'OWNER_ACT_GATE_UNTASKED')

    def test_the_terminal_leaf_is_not_done_before_its_acts(self):
        copy = committed_copy(self)
        task, text = committed_task(copy, 'U-06.1')
        rewrite(task, text.replace('\nstatus: To Do\n', '\nstatus: Done\n'))
        with self.assertRaises(pc.Refusal) as ctx:
            pc.report('U-06.1', backlog_dir=copy)
        self.assertEqual(ctx.exception.code, 'TASK_DONE_EARLY')
        self.assertIn('OA-32, OA-33', ctx.exception.detail)


BACKLOG_CLI = os.environ.get('AIEH_BACKLOG')


@unittest.skipUnless(BACKLOG_CLI, 'set AIEH_BACKLOG to the pinned Backlog.md 1.55.3 entry point (cli.js)')
class PinnedBacklogTests(unittest.TestCase):
    """The pinned Backlog.md CLI reads the committed task files as the strict reader does, and a status
    it writes changes readiness."""

    category = 'e2e'

    def backlog(self, project, *args):
        argv = (['node', BACKLOG_CLI] if BACKLOG_CLI.endswith('.js') else [BACKLOG_CLI]) + list(args)
        result = subprocess.run(argv, cwd=project, capture_output=True, text=True, encoding='utf-8',
                                stdin=subprocess.DEVNULL, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_round_trip_and_status_change(self):
        copy = committed_copy(self)
        project = copy.parent
        self.assertEqual(self.backlog(project, '--version').strip(), '1.55.3')
        ours = pc.Backlog(copy)
        listed = json.loads(self.backlog(project, 'task', 'list', '--json'))['tasks']  # statuses reset
        self.assertEqual(sorted(t['id'] for t in listed), sorted(ours.tasks))
        for entry in listed:
            view = json.loads(self.backlog(project, 'task', 'view', entry['id'], '--json'))['task']
            mine = ours.tasks[entry['id']]
            with self.subTest(entry['id']):
                self.assertEqual((view['title'], view['status'], view['dependencies'], view['references']),
                                 (mine['title'], mine['status'], mine['dependencies'], mine['references']))
                self.assertEqual(ours.milestones[view['milestone']], mine['milestone'])
                self.assertEqual([c['text'] for c in view['acceptanceCriteria']], mine['criteria'])
        task, _ = committed_task(copy, 'E-01.4.1')
        self.backlog(project, 'task', 'edit', task['id'], '-s', 'Done')
        rows = {r['id']: r for r in pc.report('U-06.1', backlog_dir=copy)['leaves']}
        self.assertEqual((rows['E-01.4.1']['status'], rows['E-01.4.2']['ready']), ('Done', True))


if __name__ == '__main__':
    unittest.main()
