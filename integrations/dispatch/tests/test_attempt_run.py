"""Tests for the attempt run (D1 slice A2: ``attempt_run.py``), offline.

Run from the repository root, under the tools interpreter (Dulwich is required):

    <tools python> -I -B -m unittest discover -s integrations/dispatch/tests -p test_attempt_run.py -v

Shown here, against the design's A2 evidence list:

* the golden texts of SEED, RESULT and the message frame (their sha256 pinned), and that no slot takes a value from
  outside the reserved record, the approved repository at a base that contains the accepted design commit, and the
  store (``Goldens``, ``Base``, ``Message``);
* the turn journal is dispatched before the POST (asserted on the transport's order); a second send on a
  dispatched, confirmed or unknown journal makes zero calls; a lost answer is settled by reading the events, never
  by sending again (``Turn``);
* the oracle: the SEED and RESULT commands run by a real shell (Git Bash here) and git over temporary trees (add,
  modify, delete; an untouched tree; a tree holding a ``.git`` with hooks and an fsmonitor, a link, a nested
  repository, a forbidden name) yield a bundle the retained verifier (``tools/guest.py`` ``verify_pulled_bundle``,
  decision 0014 row R6) accepts and whose commit id equals the host-computed one, or the stated stable refusal
  (``Oracle``);
* the intake refuses another reference, a second one, a prerequisite, a commit id that differs, an attempt with an
  end record, an attempt not confirmed (``Intake``);
* with a fake Agent Server: the call sequence is exactly the declared one; a failed inspection sends no message; a
  turn that is not ``finished`` runs no RESULT; an observer stop calls ``end_interrupted_attempt`` with the mapped
  record and reserves no result journal (``Run``); the end refuses an attempt whose result journal is dispatched,
  and R2's two new kinds are security stops (``EndExclusion``).

The commands run on the host only in a temporary directory standing for ``/workspace/<repository>``; git is
launched by the commands' own text (Python in a string, as in the guest), never by this module.
"""
from pathlib import Path
import contextlib
import copy
import dataclasses
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

CATEGORY = 'integration'

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
BASE_PYTHON = getattr(sys, '_base_executable', sys.executable)
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def _load(name, path):
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module


te = _load('test_attempt_end', HERE / 'test_attempt_end.py')
di, AE, store_mod = te.di, te.AE, te.store_mod
AR = _load('attempt_run', HERE.parent / 'attempt_run.py')
guest = _load('aieh_guest_for_dispatch_tests', REPO / 'tools' / 'guest.py')
ra = di.planning.repository_access
PROFILE_DIR = REPO / 'profiles' / 'strong-windows-qemu-whpx'

# The golden texts' sha256 (a change to a builder or the frame is a change of what the agent's container runs or
# reads: review it, then update these).
SEED_SCRIPT_SHA256 = 'd103e6a4c0b32b1a2c1c419fb4400dcdff4bc3a90664292f79ecfdf54ca5fbe5'
RESULT_SCRIPT_SHA256 = 'c99306040351f33cab879ce0ce59a15d5fddb9758a5c6e72a7f6490bc58bc5c5'
FRAME_SHA256 = '3efb3ece1fafa73d10321782d5e08cd61e676c484e6b55f8503bda991732d723'
# The fixture's seeded tar, before gzip (deterministic: a fixed tree, sorted, times and owners 0; the gzip bytes
# themselves depend on the zlib build, so they are not pinned).
SEED_TAR_SHA256 = '9496e43d4350e1258576acbb771557f46c2c68454ba14653cb766b52f692f131'

TITLE = 'Implement slugify(text) in aieh_d1_demo (add-slugify)'
WHEN = 1763251200          # 2025-11-16T00:00:00Z, a fixed commit time for the oracle


def git_bash():
    """Git for Windows' bash (never WSL's), or a POSIX bash."""
    if os.name == 'nt':
        for root in (os.environ.get('ProgramFiles'), os.environ.get('ProgramW6432'), r'C:\Program Files'):
            candidate = Path(root or '') / 'Git' / 'bin' / 'bash.exe'
            if root and candidate.is_file():
                return str(candidate)
        return None
    return shutil.which('bash')


BASH = git_bash()


# ---------------------------------------------------------------------------
# A demo repository built in process with Dulwich: C0 the code and its tests, C1 a README change, C2 the accepted
# design (the change folder), C3 the task file; each a full tree.

def _tree(d, repo, files):
    """The tree object of FILES ({path: bytes or (mode, bytes or oid)}), written into REPO; its id."""
    nested = {}
    for path, value in files.items():
        head, _, rest = path.partition('/')
        if rest:
            nested.setdefault(head, {})[rest] = value
        else:
            nested[head] = value
    tree = d.objects.Tree()
    for name, value in sorted(nested.items()):
        if isinstance(value, dict):
            tree.add(name.encode('utf-8'), AR.TREE_MODE, _tree(d, repo, value))
            continue
        mode, data = value if isinstance(value, tuple) else (AR.FILE_MODE, value)
        if mode == AR.GITLINK_MODE:
            tree.add(name.encode('utf-8'), mode, data)
            continue
        blob = d.objects.Blob.from_string(data)
        repo.object_store.add_object(blob)
        tree.add(name.encode('utf-8'), mode, blob.id)
    repo.object_store.add_object(tree)
    return tree.id


def demo_trees(work_id, change, extra=None):
    c0 = {'README.md': b'# demo\n', 'aieh_d1_demo/__init__.py': b'',
          'tests/__init__.py': b'',
          'tests/test_demo.py': b'import unittest\n\n\nclass Demo(unittest.TestCase):\n'
                                b'    def test_true(self):\n        self.assertTrue(True)\n'}
    c1 = dict(c0, **{'README.md': b'# demo\n\nThe D1 demo.\n'})
    c2 = dict(c1, **{f'openspec/changes/{change}/proposal.md': b'# Add slugify\n',
                     f'openspec/changes/{change}/tasks.md': b'- [ ] slugify\n'})
    task = (f'---\nid: {work_id}\ntitle: {TITLE}\nstatus: To Do\n---\n\n## Description\n\nslugify\n').encode()
    c3 = dict(c2, **{f'backlog/tasks/{work_id.lower()} - Implement-slugify.md': task})
    c3.update(extra or {})
    return [('C0', c0), ('C1', c1), ('C2', c2), ('C3', c3)]


def make_repository(path, trees, branch=b'refs/heads/main'):
    """A work-tree repository at PATH whose BRANCH holds TREES as one commit each (fixed identity and times); the
    commit ids by name."""
    d = ra.dulwich_modules()
    repo = d.repo.Repo.init(str(path), mkdir=True)
    try:
        commits, parent = {}, None
        for n, (name, files) in enumerate(trees):
            commit = d.objects.Commit()
            commit.tree = _tree(d, repo, files)
            commit.parents = [parent] if parent else []
            commit.author = commit.committer = b'Fixture <fixture@localhost.invalid>'
            commit.author_time = commit.commit_time = 1763164800 + n
            commit.author_timezone = commit.commit_timezone = 0
            commit.encoding = None
            commit.message = f'{name}\n'.encode()
            repo.object_store.add_object(commit)
            parent = commit.id
            commits[name] = commit.id.decode('ascii')
        repo.refs[branch] = parent
        repo.refs.set_symbolic_ref(b'HEAD', branch)
    finally:
        repo.close()
    return commits


class Scratch(unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.tmp = Path(tempfile.mkdtemp(prefix='aieh-attempt-run-'))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def demo(self, work_id='TASK-1', change='add-slugify', repository='aieh-d1-demo', extra=None, name=None):
        path = self.tmp / (name or f'demo-{len(list(self.tmp.glob("demo*")))}')
        commits = make_repository(path, demo_trees(work_id, change, extra))
        return AR.read_base(path, repository=repository, design_commit=commits['C2']), commits


# ---------------------------------------------------------------------------
# The host's shell: the command's text run against a temporary workspace

def run_command(command, workspace, timeout=240):
    """COMMAND run by bash as the container would run it, with ``/workspace/<repository>`` the directory WORKSPACE
    and ``python`` the base interpreter; (returncode, stdout)."""
    target = re.search(r"'(/workspace/[a-z0-9-]+)'", command).group(1)
    command = command.replace(f"'{target}'", f"'{Path(workspace).as_posix()}'")
    command = command.replace(' python -c ', f" '{Path(BASE_PYTHON).as_posix()}' -c ")
    # on standard input: Git for Windows' runtime re-parses a command line's single quotes itself
    done = subprocess.run([BASH, '-s'], input=command.encode('utf-8'), capture_output=True, timeout=timeout,
                          creationflags=NO_WINDOW)
    return done.returncode, done.stdout.decode('utf-8', 'replace').replace('\r\n', '\n'), \
        done.stderr.decode('utf-8', 'replace')


FRAME_RE = re.compile(r'^AIEH-EXCHANGE-PART bundle ([0-9a-f]{64}) ([0-9]+)\n((?:[0-9a-f]*\n)*)AIEH-EXCHANGE-END bundle$',
                      re.M)


def deliver(stdout, exchange, name):
    """The API probe's delivery, as tools/guest.py's API_PROBE makes it (tested there): the framed part written into
    the exchange, the frame replaced by one line; (stdout, delivered)."""
    found = list(FRAME_RE.finditer(stdout))
    if len(found) != 1:
        return stdout, {'error': 'PART_MALFORMED'}
    match = found[0]
    data = bytes.fromhex(''.join(match.group(3).split()))
    if hashlib.sha256(data).hexdigest() != match.group(1) or len(data) != int(match.group(2)):
        return stdout, {'error': 'DIGEST_MISMATCH'}
    with open(Path(exchange) / name, 'xb') as handle:
        handle.write(data)
    line = f'AIEH-EXCHANGE-DELIVERED bundle {match.group(1)} {len(data)}'
    return stdout[:match.start()] + line + stdout[match.end():], {'name': name, 'sha256': match.group(1),
                                                                   'size': len(data)}


class Puller:
    """tools/guest.py's exchange pull with the guest side replaced by a directory: the file staged in the instance's
    inbound staging and verified by the retained verifier (verify_pulled_bundle, real git, row R6)."""

    def __init__(self, tmp, exchange):
        state, elsewhere = Path(tmp) / 'state', Path(tmp) / 'home'
        state.mkdir()
        elsewhere.mkdir()
        # the state directory's own rule (A3: never inside the user's profile), as tools/tests' TempState meets it
        with mock.patch.dict(os.environ, {'USERPROFILE': str(elsewhere), 'HOME': str(elsewhere)}):
            self.ctx = guest.Context(str(PROFILE_DIR), str(state))
        self.exchange, self.names = Path(exchange), []

    def __call__(self, name):
        self.names.append(name)
        data = (self.exchange / name).read_bytes()
        local = guest.staging_dir(self.ctx, 'abc', 'inbound') / name
        local.write_bytes(data)
        try:
            bundle = guest.verify_pulled_bundle(self.ctx, 'abc', local)
        except guest.Refused as exc:
            bundle = {'verified': False, 'error': exc.code}
        return {'result': 'pulled' if bundle.get('verified') else 'unverified', 'bundle': bundle,
                'staged': {'path': str(local), 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}}


@unittest.skipIf(BASH is None, 'no Git Bash (Windows) or bash: the commands\' oracle needs a real shell')
class ShellFixture(Scratch):
    """A base seeded into a workspace by the real SEED command."""

    def seeded(self, **kwargs):
        base, commits = self.demo(**kwargs)
        workspace = self.tmp / f'workspace-{len(list(self.tmp.glob("workspace-*")))}' / base.repository
        workspace.parent.mkdir()
        rc, out, err = run_command(AR.build_seed(base).command, workspace)
        self.assertEqual(rc, 0, err)
        self.assertIn(f'AIEH-SEED ok {base.seed_sha256} {len(base.files)}', out.splitlines())
        return base, commits, workspace


# ---------------------------------------------------------------------------

class Goldens(Scratch):
    """The texts the agent's container runs and reads, pinned."""
    category = 'contract'

    def test_the_scripts_and_the_frame_are_the_pinned_texts(self):
        for name, text, pinned in (('SEED_SCRIPT', AR.SEED_SCRIPT, SEED_SCRIPT_SHA256),
                                   ('RESULT_SCRIPT', AR.RESULT_SCRIPT, RESULT_SCRIPT_SHA256),
                                   ('FRAME', AR.FRAME, FRAME_SHA256)):
            with self.subTest(name):
                self.assertEqual(hashlib.sha256(text.encode('utf-8')).hexdigest(), pinned)
        self.assertNotIn("'", AR.SEED_SCRIPT + AR.RESULT_SCRIPT)
        self.assertEqual(AR.FRAME_VERSION, 'aieh-d1-message/v1')

    def test_the_seed_command_of_the_fixture_is_pinned(self):
        import gzip
        base, _ = self.demo()
        self.assertEqual(hashlib.sha256(gzip.decompress(base.payload)).hexdigest(), SEED_TAR_SHA256)
        self.assertEqual(base.seed_sha256, hashlib.sha256(base.payload).hexdigest())
        self.assertEqual(base.payload, self.demo()[0].payload, 'the payload is deterministic')
        command = AR.build_seed(base)
        self.assertEqual(command.command, f"printf %s '{base.payload.hex()}' | python -c '{AR.SEED_SCRIPT}' "
                                          f"'/workspace/aieh-d1-demo' '{base.seed_sha256}'")
        self.assertEqual((command.builder, command.timeout, command.deliver), ('d1-seed', AR.SEED_TIMEOUT_S, None))
        self.assertTrue(command.command.startswith(f"printf %s '{base.payload.hex()}' | python -c '"))
        self.assertTrue(command.command.endswith(f"' '/workspace/aieh-d1-demo' '{base.seed_sha256}'"))

    def test_the_result_command_carries_only_its_named_values(self):
        base, _ = self.demo()
        attempt = '0f1e2d3c-4b5a-4968-8776-655443322110'
        command = AR.build_result(base, attempt_id=attempt, message='TASK-1: x\n', when=WHEN)
        payload = re.fullmatch(r"printf %s '([0-9a-f]+)' \| python -c '(.*)' '/workspace/aieh-d1-demo'",
                               command.command, re.S)
        self.assertIsNotNone(payload)
        self.assertEqual(payload.group(2), AR.RESULT_SCRIPT)
        params = json.loads(bytes.fromhex(payload.group(1)))
        self.assertEqual(params, {
            'base': base.commit, 'base_ref': 'refs/heads/main', 'bundle': base.bundle.hex(),
            'ref': f'refs/heads/work/{attempt}', 'name': 'aieh-bot-builder',
            'email': 'aieh-bot-builder@localhost.invalid', 'date': f'{WHEN} +0000', 'message': 'TASK-1: x\n',
            'test_timeout': AR.TEST_TIMEOUT_S, 'output_limit': AR.TEST_OUTPUT_BYTES, 'part': 'bundle',
            'part_begin': 'AIEH-EXCHANGE-PART', 'part_end': 'AIEH-EXCHANGE-END'})
        self.assertEqual((command.builder, command.timeout), ('d1-result', AR.RESULT_TIMEOUT_S))
        self.assertEqual(command.deliver, {'part': 'bundle', 'name': f'work-{attempt}.bundle'})
        for bad in ({'attempt_id': 'x'}, {'attempt_id': attempt.upper()}, {'when': 0}, {'when': 1.5},
                    {'when': True}):
            kwargs = dict({'attempt_id': attempt, 'message': 'm\n', 'when': WHEN}, **bad)
            with self.subTest(bad=bad), self.assertRaises(di.DispatchRefused) as caught:
                AR.build_result(base, **kwargs)
            self.assertEqual(caught.exception.code, 'TAIL_BODY_INVALID')

    def test_the_frame_matches_tools_guest(self):
        """The dispatch package imports nothing of tools/guest.py; its frame constants equal guest's."""
        self.assertEqual(guest.EXCHANGE_PART_BEGIN.split(' ')[0], AR.PART_BEGIN)
        self.assertEqual(guest.EXCHANGE_PART_END.split(' ')[0], AR.PART_END)
        self.assertEqual(guest.EXCHANGE_PART_DELIVERED.split(' ')[0], AR.PART_DELIVERED)
        self.assertRegex(AR.PART, guest.EXCHANGE_PART_RE.pattern)
        self.assertRegex(AR.result_name('0f1e2d3c-4b5a-4968-8776-655443322110'),
                         json.loads((PROFILE_DIR / 'profile.json').read_text(encoding='utf-8'))
                         ['exchange']['pull']['name_pattern'])


class Base(Scratch):
    category = 'integration'

    def test_the_base_is_the_branch_head_containing_the_design(self):
        base, commits = self.demo()
        self.assertEqual((base.repository, base.ref, base.commit, base.design_commit),
                         ('aieh-d1-demo', 'refs/heads/main', commits['C3'], commits['C2']))
        self.assertEqual([p for p, _, _ in base.files], sorted(p for p, _, _ in base.files))
        self.assertIn('backlog/tasks/task-1 - Implement-slugify.md', [p for p, _, _ in base.files])
        self.assertNotIn('.git', ' '.join(p for p, _, _ in base.files).split('/'))
        header = ra.parse_bundle_header(self._bundle(base))
        self.assertEqual(([list(r) for r in header['refs']], header['prerequisites']),
                         ([[commits['C3'], 'refs/heads/main']], []))
        self.assertEqual(base.summary()['seed'], {'sha256': base.seed_sha256, 'files': len(base.files)})

    def _bundle(self, base):
        path = self.tmp / 'b.bundle'
        path.write_bytes(base.bundle)
        return path

    def test_a_base_without_the_design_commit_is_refused(self):
        _, commits = self.demo(name='demo')
        other = make_repository(self.tmp / 'other', [('C0', {'unrelated.txt': b'another history\n'})])
        for design in (other['C0'], '0' * 40):
            with self.subTest(design=design), self.assertRaises(di.DispatchRefused) as caught:
                AR.read_base(self.tmp / 'demo', repository='aieh-d1-demo', design_commit=design)
            self.assertIn(caught.exception.code, ('BASE_LACKS_DESIGN', 'BASE_UNAVAILABLE'))
        with self.assertRaises(di.DispatchRefused) as caught:
            AR.read_base(self.tmp / 'demo', repository='aieh-d1-demo', design_commit=other['C0'])
        self.assertEqual(caught.exception.code, 'BASE_LACKS_DESIGN')
        for bad in (dict(design_commit='abc'), dict(design_commit=commits['C2'], ref='refs/heads/none')):
            with self.subTest(bad=bad), self.assertRaises(di.DispatchRefused) as caught:
                AR.read_base(self.tmp / 'demo', repository='aieh-d1-demo', **{'design_commit': commits['C2'],
                                                                               **bad})
            self.assertEqual(caught.exception.code, 'BASE_UNAVAILABLE')
        with self.assertRaises(di.DispatchRefused) as caught:
            AR.read_base(self.tmp / 'nowhere', repository='aieh-d1-demo', design_commit=commits['C2'])
        self.assertEqual(caught.exception.code, 'BASE_UNAVAILABLE')

    def test_a_tree_with_a_link_a_gitlink_or_a_forbidden_name_is_not_seeded(self):
        """R3 and the tree policy: refused anywhere in the tree, with the reason."""
        cases = {
            'a .claude directory': ({'.claude/settings.json': b'{}'}, 'forbidden-name'),
            'a nested .claude': ({'docs/.claude/x': b'{}'}, 'forbidden-name'),
            'an .mcp.json': ({'.mcp.json': b'{}'}, 'forbidden-name'),
            'a nested .mcp.json': ({'sub/.mcp.json': b'{}'}, 'forbidden-name'),
            'a symbolic link': ({'link': (AR.LINK_MODE, b'/etc/passwd')}, 'link'),
            'a gitlink': ({'vendor/mod': (AR.GITLINK_MODE, b'1' * 40)}, 'gitlink'),
        }
        for n, (name, (extra, reason)) in enumerate(cases.items()):
            with self.subTest(name), self.assertRaises(di.DispatchRefused) as caught:
                self.demo(extra=extra, name=f'bad{n}')
            self.assertEqual(caught.exception.code, 'SEED_TREE_REFUSED')
            self.assertEqual([p['reason'] for p in caught.exception.context['problems']], [reason])
        base, _ = self.demo(extra={'tools/run.sh': (AR.EXEC_MODE, b'#!/bin/sh\n')}, name='exec')
        self.assertIn(('tools/run.sh', AR.EXEC_MODE), [(p, m) for p, m, _ in base.files])


class Message(Scratch):
    category = 'unit'

    def resolved(self, **changes):
        policy = {'design': {'repository': 'aieh-d1-demo', 'change': 'add-slugify', 'commit': 'c' * 40}}
        values = dict(work_id='TASK-1', repository='aieh-d1-demo', outcome_ref='outcome:d1-demo@' + 'd' * 40,
                      design_revision='openspec:add-slugify@' + 'c' * 40, policy_inputs=policy)
        values.update(changes)
        return mock.Mock(**values)

    def test_the_frame_takes_its_slots_from_the_record_and_the_seeded_tree(self):
        base, _ = self.demo()
        text = AR.build_message(self.resolved(), base)
        self.assertEqual(text, (
            'You are the implementing agent for one task of the repository in /workspace/aieh-d1-demo.\n\n'
            'Task: TASK-1. Its Backlog.md file is /workspace/aieh-d1-demo/backlog/tasks/task-1 - '
            'Implement-slugify.md.\n'
            'Design: the accepted OpenSpec change add-slugify, in /workspace/aieh-d1-demo/openspec/changes/'
            'add-slugify/.\n\n'
            '1. Read the task file and the change\'s files, then implement the change as designed, in '
            '/workspace/aieh-d1-demo.\n'
            '2. Run the accepted design\'s test command there, offline, with what this container holds: '
            'python -m unittest discover -s tests\n'
            '3. Do not edit anything under backlog/ or openspec/: Backlog.md alone owns the task\'s status, and the '
            'accepted design is bound by its acceptance.\n'
            '4. Do not commit and do not push: the dispatcher records the result from the files you leave in '
            '/workspace/aieh-d1-demo.\n'))
        di.TAIL_GRAMMARS[di.MESSAGE_TAIL](AR.message_body(text))
        self.assertEqual(AR.commit_message(self.resolved(), base, 'a' * 8 + '-0000-4000-8000-' + '0' * 12), (
            f'TASK-1: {TITLE}\n\nTask: TASK-1\nAttempt: aaaaaaaa-0000-4000-8000-000000000000\n'
            f'Outcome: outcome:d1-demo@{"d" * 40}\nDesign: openspec:add-slugify@{"c" * 40}\n'))

    def test_an_unresolvable_slot_is_refused(self):
        base, _ = self.demo()
        two, _ = self.demo(extra={'backlog/tasks/task-1 - Another.md': b'---\ntitle: x\n---\n'}, name='two')
        untitled, _ = self.demo(extra={'backlog/tasks/task-1 - Implement-slugify.md': b'no front matter\n'},
                                name='untitled')
        cases = {
            'another change': (self.resolved(policy_inputs={'design': {'change': 'other-change', 'commit': 'c' * 40}}),
                               base, AR.build_message),
            'no design': (self.resolved(policy_inputs={}), base, AR.build_message),
            'a work id out of grammar': (self.resolved(work_id='TASK-1\nmore'), base, AR.build_message),
            'no task file': (self.resolved(work_id='TASK-2'), base, AR.build_message),
            'two task files': (self.resolved(), two, AR.build_message),
            'a repository out of grammar': (self.resolved(repository='../etc'), base, AR.build_message),
            'no title': (self.resolved(), untitled, lambda r, b: AR.commit_message(r, b, 'x')),
        }
        for name, (resolved, tree, build) in cases.items():
            with self.subTest(name), self.assertRaises(di.DispatchRefused) as caught:
                build(resolved, tree)
            self.assertEqual(caught.exception.code, 'MESSAGE_SLOT_UNRESOLVED')


# ---------------------------------------------------------------------------
# The oracle: the real commands, a real shell and git, the retained verifier, the host's intake

class OracleFixture(ShellFixture):
    """A confirmed native attempt (E-05.9's fixture) with its turn confirmed, a base for its repository and work
    item, and the real commands."""

    def confirmed(self):
        fixture = attempt_fixture(self)
        result = fixture.dispatch_native()
        resolved = di.stored_inputs(fixture.store, result.operation_key, state='confirmed')
        return fixture, result, resolved

    def run_result(self, base, workspace, fixture, result, resolved, when=WHEN, change=None):
        """RESULT run against WORKSPACE, delivered, pulled and verified: (printed, pulled, puller)."""
        attempt_id = store_mod.attempt_id_for(result.operation_key)
        message = AR.commit_message(resolved, base, attempt_id)
        command = AR.build_result(base, attempt_id=attempt_id, message=message, when=when)
        rc, out, err = run_command(command.command, workspace)
        exchange = self.tmp / f'exchange-{len(list(self.tmp.glob("exchange-*")))}'
        exchange.mkdir()
        stdout, delivered = deliver(out, exchange, command.deliver['name'])
        answer = {'status': 200, 'body': {'stdout': stdout, 'stderr': err, 'exit_code': rc}, 'delivered': delivered}
        host = exchange.parent / (exchange.name + '-host')
        host.mkdir()
        return answer, Puller(host, exchange), message


class OracleAttempt(te.EndFixture):
    """E-05.9's native fixture, set up by hand inside another test (made as OracleAttempt('dispatch_native'), so
    that the loader finds no test in it); its class-level state is this module's (setUpModule)."""


def attempt_fixture(test):
    fixture = OracleAttempt('dispatch_native')
    fixture.setUp()
    test.addCleanup(fixture.doCleanups)
    return fixture


def setUpModule():
    OracleAttempt.setUpClass()


def tearDownModule():
    OracleAttempt.tearDownClass()


class Oracle(OracleFixture):
    category = 'integration'

    def prepared(self, edit):
        fixture, result, resolved = self.confirmed()
        base, _, workspace = self.seeded(work_id=resolved.work_id, change=AR._design(resolved)['change'],
                                         repository=resolved.repository)
        confirm_turn(fixture.store, result.operation_key, base)
        edit(workspace)
        answer, puller, message = self.run_result(base, workspace, fixture, result, resolved)
        return fixture, result, base, answer, puller, message

    def accepted(self, edit):
        fixture, result, base, answer, puller, message = self.prepared(edit)
        printed = AR.parse_result(answer)
        verified = AR.intake_result(fixture.store, result.operation_key, base=base, printed=printed,
                                    pulled=puller(printed['delivered']['name']), message=message, when=WHEN)
        # the host's own computation over the verified objects: the commit id
        opened = ra.open_repository(verified.verify_repo, config='repository', work_tree=False)
        try:
            raw = opened.read(verified.commit)[2]
            files = {p: opened.read(o)[2] for p, _, o in AR.tree_entries(opened, verified.tree)}
        finally:
            opened.close()
        self.assertEqual(raw, AR.expected_commit(verified.tree, base.commit, message, WHEN))
        self.assertEqual(AR.object_id('commit', raw), verified.commit)
        self.assertEqual(verified.base, base.commit)
        self.assertEqual(verified.tests['label'], AR.TEST_LABEL)
        return verified, files, base

    def test_an_edited_tree_is_committed_once_on_the_base(self):
        def edit(ws):
            (ws / 'aieh_d1_demo' / 'slugify.py').write_text('def slugify(text):\n    return text.lower()\n',
                                                            encoding='utf-8', newline='\n')
            (ws / 'README.md').write_text('# demo, changed\n', encoding='utf-8', newline='\n')
            (ws / 'tests' / 'test_demo.py').unlink()
            (ws / 'tests' / 'test_slugify.py').write_text(
                'import unittest\nfrom aieh_d1_demo.slugify import slugify\n\n\n'
                'class S(unittest.TestCase):\n    def test_it(self):\n        self.assertEqual(slugify("A"), "a")\n',
                encoding='utf-8', newline='\n')
        verified, files, base = self.accepted(edit)
        self.assertEqual(files['README.md'], b'# demo, changed\n')
        self.assertIn('aieh_d1_demo/slugify.py', files)
        self.assertNotIn('tests/test_demo.py', files)
        self.assertEqual(verified.tests['status'], '0')
        self.assertIn('Ran 1 test', verified.tests['output'])
        self.assertIn('OK', verified.tests['output'])
        self.assertEqual(verified.files, len(files))

    def test_an_untouched_tree_is_the_base_tree_and_a_failing_run_is_reported(self):
        def edit(ws):
            pass
        verified, files, base = self.accepted(edit)
        self.assertEqual(verified.tree, base.tree)
        self.assertEqual(files, {p: d for p, _, d in base.files})

        def failing(ws):
            (ws / 'tests' / 'test_fail.py').write_text('import unittest\n\n\nclass F(unittest.TestCase):\n'
                                                      '    def test_no(self):\n        self.fail("no")\n',
                                                      encoding='utf-8', newline='\n')
        verified, _, _ = self.accepted(failing)
        self.assertEqual(verified.tests['status'], '1')     # R1: reported as it is; the path proceeds
        self.assertIn('FAILED', verified.tests['output'])

    def test_a_workspace_git_directory_its_hooks_and_its_config_change_nothing(self):
        marker = self.tmp / 'fsmonitor-ran'

        def edit(ws):
            (ws / '.git' / 'hooks').mkdir(parents=True)
            (ws / '.git' / 'HEAD').write_text('ref: refs/heads/evil\n', encoding='utf-8')
            hook = f'#!/bin/sh\necho ran > "{marker.as_posix()}"\n'
            for name in ('pre-commit', 'post-commit', 'reference-transaction', 'post-index-change'):
                (ws / '.git' / 'hooks' / name).write_text(hook, encoding='utf-8', newline='\n')
            (ws / '.git' / 'config').write_text(f'[core]\n\tfsmonitor = echo ran > "{marker.as_posix()}"\n'
                                                f'\thooksPath = .git/hooks\n', encoding='utf-8')
            (ws / 'new.txt').write_text('new\n', encoding='utf-8', newline='\n')
        verified, files, _ = self.accepted(edit)
        self.assertFalse(marker.exists(), 'a hook or the fsmonitor of the workspace\'s .git ran')
        self.assertNotIn('.git', {p.split('/')[0] for p in files})
        self.assertEqual(files['new.txt'], b'new\n')

    def refused(self, edit, code, reason=None):
        fixture, result, base, answer, puller, message = self.prepared(edit)
        with self.assertRaises(di.DispatchRefused) as caught:
            printed = AR.parse_result(answer)
            AR.intake_result(fixture.store, result.operation_key, base=base, printed=printed,
                             pulled=puller(printed['delivered']['name']), message=message, when=WHEN)
        self.assertEqual(caught.exception.code, code, caught.exception.detail)
        if reason:
            self.assertIn(reason, [p['reason'] for p in caught.exception.context['problems']])
        return caught.exception

    def test_a_forbidden_name_in_the_result_is_refused(self):
        """R3: never dropped silently: the intake refuses it with a stable code."""
        for n, path in enumerate(('.claude/settings.json', 'sub/.mcp.json')):
            with self.subTest(path=path):
                def edit(ws, path=path):
                    (ws / path).parent.mkdir(parents=True, exist_ok=True)
                    (ws / path).write_text('{}', encoding='utf-8')
                self.refused(edit, 'RESULT_TREE_REFUSED', 'forbidden-name')

    def test_a_nested_repository_is_a_gitlink_and_refused(self):
        def edit(ws):
            (ws / 'vendor').mkdir()
            make_repository(ws / 'vendor' / 'mod', [('M0', {'m.txt': b'm\n'})])
        self.refused(edit, 'RESULT_TREE_REFUSED', 'gitlink')

    def test_a_symbolic_link_is_refused(self):
        probe = self.tmp / 'link-probe'
        try:
            os.symlink('target', probe)
        except (OSError, NotImplementedError):
            self.skipTest('this host cannot create symbolic links (Windows without the privilege)')
        probe.unlink()

        def edit(ws):
            os.symlink('README.md', ws / 'link')
        self.refused(edit, 'RESULT_TREE_REFUSED', 'link')

    def test_another_time_or_message_is_not_the_specified_commit(self):
        fixture, result, base, answer, puller, message = self.prepared(lambda ws: None)
        printed = AR.parse_result(answer)
        pulled = puller(printed['delivered']['name'])
        for name, kwargs in (('another time', dict(message=message, when=WHEN + 1)),
                             ('another message', dict(message=message + 'x', when=WHEN))):
            with self.subTest(name), self.assertRaises(di.DispatchRefused) as caught:
                AR.intake_result(fixture.store, result.operation_key, base=base, printed=printed, pulled=pulled,
                                 **kwargs)
            self.assertEqual(caught.exception.code, 'RESULT_COMMIT_MISMATCH')

    def test_the_seed_refuses_an_existing_workspace(self):
        base, _, workspace = self.seeded()
        rc, out, _ = run_command(AR.build_seed(base).command, workspace)
        self.assertNotEqual(rc, 0)
        self.assertNotIn('AIEH-SEED ok', out)
        seeded = sorted(p.relative_to(workspace).as_posix() for p in workspace.rglob('*') if p.is_file())
        self.assertEqual(seeded, [p for p, _, _ in base.files])
        self.assertEqual({p: (workspace / p).read_bytes() for p, _, _ in base.files},
                         {p: d for p, _, d in base.files})


def confirm_turn(integration_store, operation_key, base, text='the message'):
    intent = AR.turn_intent(operation_key, base, text)
    key = AR.TURN_KEY.format(attempt_id=intent['attemptId'])
    integration_store.reserve(key, intent, actor='a2-test')
    di._mark(integration_store, key, 'reserved', 'dispatched', 'a2-test', 'send-message', None)
    di._mark(integration_store, key, 'dispatched', 'confirmed', 'a2-test', 'sent', {'status': 200})


# ---------------------------------------------------------------------------
# The intake's refusals on crafted pulls

class Intake(Scratch):
    category = 'integration'

    def setUp(self):
        super().setUp()
        self.fixture = attempt_fixture(self)
        self.result = self.fixture.dispatch_native()
        self.key = self.result.operation_key
        self.attempt = store_mod.attempt_id_for(self.key)
        self.base, _ = self.demo()
        confirm_turn(self.fixture.store, self.key, self.base)
        self.commit = '1' * 40
        self.printed = {'base': self.base.commit, 'tree': '2' * 40, 'commit': self.commit,
                        'tests': {'status': '0', 'output': '', 'command': AR.TEST_COMMAND, 'label': AR.TEST_LABEL},
                        'delivered': {'name': AR.result_name(self.attempt), 'sha256': 'a' * 64, 'size': 10}}

    def pulled(self, refs=None, prerequisites=(), verified=True, sha='a' * 64, size=10, result='pulled'):
        refs = [(self.commit, AR.result_ref(self.attempt))] if refs is None else refs
        return {'result': result, 'staged': {'path': 'x', 'bytes': size, 'sha256': sha},
                'bundle': {'verified': verified, 'verify_repo': str(self.tmp / 'nowhere'),
                           'header': {'refs': refs, 'prerequisites': list(prerequisites)}}}

    def refused(self, code, pulled, printed=None, key=None):
        with self.assertRaises(di.DispatchRefused) as caught:
            AR.intake_result(self.fixture.store, key or self.key, base=self.base, printed=printed or self.printed,
                             pulled=pulled, message='m\n', when=WHEN)
        self.assertEqual(caught.exception.code, code, caught.exception.detail)
        self.assertIn(code, di.REFUSALS)

    def test_the_references_must_be_exactly_the_work_branch(self):
        ref = AR.result_ref(self.attempt)
        for name, refs, prerequisites in (
                ('another reference', [(self.commit, 'refs/heads/main')], ()),
                ('a second reference', [(self.commit, ref), (self.commit, 'refs/heads/other')], ()),
                ('another attempt\'s branch', [(self.commit, AR.result_ref('0' * 8 + '-0000-4000-8000-' + '0' * 12))],
                 ()),
                ('no reference', [], ()),
                ('a prerequisite', [(self.commit, ref)], [('3' * 40, '')])):
            with self.subTest(name):
                self.refused('RESULT_REFS_INVALID', self.pulled(refs=refs, prerequisites=prerequisites))

    def test_an_unverified_pull_or_another_digest_is_refused(self):
        for name, pulled in (('not verified', self.pulled(verified=False)),
                             ('unverified result', self.pulled(result='unverified')),
                             ('another digest', self.pulled(sha='b' * 64)),
                             ('another size', self.pulled(size=11)), ('nothing', {})):
            with self.subTest(name):
                self.refused('RESULT_NOT_VERIFIED', pulled)

    def test_a_commit_other_than_the_printed_one_is_refused(self):
        self.refused('RESULT_COMMIT_MISMATCH', self.pulled(), dict(self.printed, commit='4' * 40))
        self.refused('RESULT_COMMIT_MISMATCH', self.pulled(), dict(self.printed, base='5' * 40))

    def test_an_ended_or_unconfirmed_attempt_or_turn_takes_no_result(self):
        self.fixture.server.set(self.result.conversation_id, status='error')
        AE.end_interrupted_attempt(self.fixture.store, self.key, transport=self.fixture.server, actor='a2-test',
                                   trigger=AE.ATTEMPT_STOPPED, dispatcher_records=[te.record('egress-stop')],
                                   read_artifact=self.fixture.read_artifact)
        self.refused('ATTEMPT_ENDED', self.pulled())
        second = attempt_fixture(self)
        other = second.dispatch_native()
        with self.assertRaises(di.DispatchRefused) as caught:        # its turn journal does not exist
            AR.intake_result(second.store, other.operation_key, base=self.base, printed=self.printed,
                             pulled=self.pulled(), message='m\n', when=WHEN)
        self.assertEqual(caught.exception.code, 'TURN_NOT_CONFIRMED')
        unconfirmed = 'attempt/v1/' + 'x' * 10
        with self.assertRaises(di.DispatchRefused) as caught:
            AR.intake_result(second.store, unconfirmed, base=self.base, printed=self.printed, pulled=self.pulled(),
                             message='m\n', when=WHEN)
        self.assertIn(caught.exception.code, ('RESERVATION_INVALID', 'ATTEMPT_NOT_CONFIRMED'))

    def test_the_result_output_is_parsed_strictly(self):
        good = '\n'.join(['noise', f'AIEH-RESULT base {"a" * 40}', f'AIEH-RESULT tree {"b" * 40}',
                          f'AIEH-RESULT commit {"c" * 40}', 'AIEH-RESULT tests 0',
                          'AIEH-RESULT test-output ' + 'ok\x1b[31m\n'.encode().hex(),
                          f'AIEH-EXCHANGE-DELIVERED bundle {"d" * 64} 7', 'AIEH-RESULT done'])
        delivered = {'name': 'w.bundle', 'sha256': 'd' * 64, 'size': 7}

        def answer(stdout, delivered=delivered, status=200):
            return {'status': status, 'body': {'stdout': stdout, 'exit_code': 0}, 'delivered': delivered}
        printed = AR.parse_result(answer(good))
        self.assertEqual((printed['commit'], printed['tests']['status'], printed['tests']['output']),
                         ('c' * 40, '0', 'ok[31m\n'))
        cases = {
            'a failed step': good.replace('AIEH-RESULT done', 'AIEH-RESULT failed commit ' + b'no'.hex()),
            'no commit': good.replace(f'AIEH-RESULT commit {"c" * 40}\n', ''),
            'a repeated commit': good + f'\nAIEH-RESULT commit {"c" * 40}',
            'no done': good.replace('\nAIEH-RESULT done', ''),
            'no delivered line': good.replace(f'AIEH-EXCHANGE-DELIVERED bundle {"d" * 64} 7\n', ''),
        }
        for name, stdout in cases.items():
            with self.subTest(name), self.assertRaises(di.DispatchRefused) as caught:
                AR.parse_result(answer(stdout))
            self.assertEqual(caught.exception.code, 'RESULT_COMMAND_FAILED')
        for name, kwargs in (('a delivery error', {'delivered': {'error': 'EXISTS'}}),
                             ('another delivered digest', {'delivered': dict(delivered, sha256='e' * 64)}),
                             ('no delivery', {'delivered': None}), ('a 500', {'status': 500})):
            with self.subTest(name), self.assertRaises(di.DispatchRefused) as caught:
                AR.parse_result(answer(good, **kwargs))
            self.assertEqual(caught.exception.code, 'RESULT_COMMAND_FAILED')


# ---------------------------------------------------------------------------
# The turn journal and the wait

class Turn(Scratch):
    category = 'integration'

    def setUp(self):
        super().setUp()
        self.fixture = attempt_fixture(self)
        self.result = self.fixture.dispatch_native()
        self.key, self.store = self.result.operation_key, self.fixture.store
        self.cid = self.result.conversation_id
        self.base, _ = self.demo()
        resolved = di.stored_inputs(self.store, self.key, state='confirmed')
        self.client = AE._client(resolved, self.transport)(self.fixture.read_artifact)
        self.posts, self.answer = [], {'status': 200, 'body': {'success': True}}

    def transport(self, method, path, body, **kwargs):
        if method == 'POST':
            held = self.store.get(AR.TURN_KEY.format(attempt_id=store_mod.attempt_id_for(self.key)))
            self.posts.append((path, body, held.state if held else None))
            if isinstance(self.answer, BaseException):
                raise self.answer
            return copy.deepcopy(self.answer)
        return self.fixture.server(method, path, body)

    def send(self, text='the message'):
        return AR.send_message(self.store, self.key, self.client, self.base, text, actor='a2-test')

    def journal(self):
        return self.store.get(AR.TURN_KEY.format(attempt_id=store_mod.attempt_id_for(self.key)))

    def test_the_journal_is_dispatched_before_the_one_post(self):
        record = self.send()
        self.assertEqual(self.posts, [(f'/api/conversations/{self.cid}/events', AR.message_body('the message'),
                                       'dispatched')])
        self.assertEqual(record['state'], 'confirmed')
        self.assertEqual(record['intent'], AR.turn_intent(self.key, self.base, 'the message'))
        self.assertEqual(record['intent']['messageSha256'], hashlib.sha256(b'the message').hexdigest())
        self.assertEqual(record['intent']['seed'], {'sha256': self.base.seed_sha256, 'files': len(self.base.files)})
        self.assertEqual(record['intent']['frame'], AR.FRAME_VERSION)

    def test_a_second_send_makes_zero_calls(self):
        self.send()
        for text in ('the message', 'another'):
            with self.subTest(text=text), self.assertRaises(di.DispatchRefused) as caught:
                self.send(text)
            self.assertIn(caught.exception.code, ('TURN_ALREADY_SENT', 'TURN_CONFLICT'))
        self.assertEqual(len(self.posts), 1)

    def test_a_lost_answer_is_settled_from_the_events_never_by_sending_again(self):
        self.answer = OSError('the channel dropped')
        with self.assertRaises(di.DispatchRefused) as caught:
            self.send()
        self.assertEqual(caught.exception.code, 'TURN_UNRECONCILED')
        self.assertEqual((self.journal().state, len(self.posts)), ('unknown', 1))
        with self.assertRaises(di.DispatchRefused) as again:
            self.send()
        self.assertEqual(again.exception.code, 'TURN_ALREADY_SENT')
        self.assertEqual(len(self.posts), 1, 'never sent twice')
        # the server did receive it: the events show it, and the journal is confirmed by reading them
        self.fixture.server.set(self.cid, events=[{'kind': 'MessageEvent', 'id': 'e1', 'source': 'user',
                                                   'llm_message': {'role': 'user', 'content': [
                                                       {'type': 'text', 'text': 'the message'}]}}])
        record = AR.reconcile_turn(self.store, self.key, self.client, actor='a2-test')
        self.assertEqual((record['state'], len(self.posts)), ('confirmed', 1))
        self.assertEqual(self.store.get(AR.TURN_KEY.format(attempt_id=store_mod.attempt_id_for(self.key)))
                         .reconciliation_status, 'reconciled')

    def test_a_5xx_is_unknown_and_a_4xx_failed(self):
        self.answer = {'status': 503, 'body': {}}
        self.fixture.server.set(self.cid, events=[{'kind': 'MessageEvent', 'id': 'e1', 'source': 'user',
                                                   'llm_message': {'content': [{'type': 'text',
                                                                                'text': 'the message'}]}}])
        self.assertEqual(self.send()['state'], 'confirmed')     # unknown, then settled from the events
        other = Turn('test_a_5xx_is_unknown_and_a_4xx_failed')
        other.setUp()
        self.addCleanup(other.doCleanups)
        other.answer = {'status': 422, 'body': {}}
        with self.assertRaises(di.DispatchRefused) as caught:
            other.send()
        self.assertEqual((caught.exception.code, other.journal().state), ('TURN_REFUSED', 'failed'))

    def test_the_wait_reads_to_a_terminal_status_within_its_ceiling(self):
        now, waits = [0.0], []

        def wait(seconds):
            waits.append(seconds)
            now[0] += seconds
        statuses = iter(['idle', 'running', 'finished'])

        def server(method, path, body):
            answer = self.fixture.server(method, path, body)
            if method == 'GET' and path == f'/api/conversations/{self.cid}':
                answer['body']['execution_status'] = next(statuses)
            return answer
        client = AE._client(di.stored_inputs(self.store, self.key, state='confirmed'), server)(
            self.fixture.read_artifact)
        self.assertEqual(AR.wait_for_turn(client, self.cid, ceiling_s=100, poll_s=10, clock=lambda: now[0],
                                          wait=wait), 'finished')
        self.assertEqual(waits, [10, 10])
        self.fixture.server.set(self.cid, status='running')
        now[0], waits[:] = 0.0, []
        with self.assertRaises(di.DispatchRefused) as caught:
            AR.wait_for_turn(self.client, self.cid, ceiling_s=25, poll_s=10, clock=lambda: now[0], wait=wait)
        self.assertEqual(caught.exception.code, 'TURN_CEILING')
        self.assertEqual(waits, [10, 10, 5])


# ---------------------------------------------------------------------------
# The run, against a fake Agent Server

class RunServer(te.ConversationServer):
    """ConversationServer with the inspection's count, the message and the command tails. SEED and RESULT run for
    real (``real``: bash and git against a temporary workspace) or, for SEED only, answer its success line."""

    def __init__(self, test, **kwargs):
        super().__init__(**kwargs)
        self.test, self.count, self.log, self.after_message = test, 1, [], 'finished'
        self.workspace = self.exchange = None

    def __call__(self, method, path, body, **kwargs):
        if path == '/api/conversations/count':
            self.log.append((method, 'count'))
            return {'status': 200, 'body': self.count}
        if not path.startswith('/api/conversations/') or path == '/api/conversations':
            return super().__call__(method, path, body)
        cid, tail = path.split('/')[3], '/'.join(path.split('/')[4:]).partition('?')[0]
        self.log.append((method, tail or 'conversation'))
        if (method, tail) == ('POST', 'events'):
            self.set(cid, status=self.after_message, events=[{'kind': 'MessageEvent', 'id': 'm1', 'source': 'user',
                                                              'llm_message': {'content': [{'type': 'text',
                                                                                           'text': body['content'][0]
                                                                                           ['text']}]}}])
            self.test.agent_edits(self.workspace)
            return {'status': 200, 'body': {'success': True}}
        if (method, tail) == ('POST', 'bash/execute_bash_command'):
            if self.workspace is None:
                return self.canned(body)
            rc, out, err = run_command(body['command'], self.workspace)
            deliver_to = kwargs.get('deliver')
            delivered = None
            if deliver_to:
                out, delivered = deliver(out, self.exchange, deliver_to['name'])
            answer = {'status': 200, 'body': {'stdout': out, 'stderr': err, 'exit_code': rc}}
            return dict(answer, delivered=delivered) if deliver_to else answer
        return super().__call__(method, path, body)

    def canned(self, body):
        base = self.test.base
        return {'status': 200, 'body': {'stdout': f'AIEH-SEED ok {base.seed_sha256} {len(base.files)}\n',
                                        'stderr': '', 'exit_code': 0}}


class Run(Scratch):
    category = 'integration'

    def setUp(self):
        super().setUp()
        self.fixture = attempt_fixture(self)
        self.server = RunServer(self)
        self.fixture.server = self.server
        self.result = self.fixture.dispatch_native()
        self.key, self.store, self.cid = self.result.operation_key, self.fixture.store, self.result.conversation_id
        self.server.set(self.cid, runtime='running')
        self.server.log.clear()
        resolved = di.stored_inputs(self.store, self.key, state='confirmed')
        self.base, self.commits = self.demo(work_id=resolved.work_id, change=AR._design(resolved)['change'],
                                            repository=resolved.repository)
        self.base = dataclasses.replace(self.base, design_commit=AR._design(resolved)['commit'])
        self.reserved, self.observed = [], []

    def agent_edits(self, workspace):
        if workspace is not None:
            (workspace / 'aieh_d1_demo' / 'slugify.py').write_text('def slugify(t):\n    return t\n',
                                                                  encoding='utf-8', newline='\n')

    def run_attempt(self, inspect=lambda cid: (), observe=None, pull=None):
        def recording(phase, **facts):
            self.observed.append(phase)
            return observe(phase, **facts) if observe else ()
        return AR.run_attempt(self.store, self.key, transport=self.server, base=self.base, actor='a2-test',
                              inspect=inspect, pull=pull or (lambda name: self.fail('no pull expected')),
                              observe=recording, reserve_result=self.reserved.append,
                              clock=lambda: 0.0, wait=lambda s: self.fail('no wait expected'),
                              read_artifact=self.fixture.read_artifact)

    def real(self):
        if BASH is None:
            self.skipTest('no Git Bash or bash')
        self.server.workspace = self.tmp / 'ws' / self.base.repository
        self.server.workspace.parent.mkdir()
        self.server.exchange = self.tmp / 'exchange'
        self.server.exchange.mkdir()
        (self.tmp / 'host').mkdir()
        return Puller(self.tmp / 'host', self.server.exchange)

    def test_the_whole_run_makes_exactly_the_declared_calls(self):
        puller = self.real()
        outcome = self.run_attempt(pull=puller)
        self.assertEqual(outcome.outcome, 'verified', outcome.to_json())
        self.assertEqual(self.server.log, [
            ('GET', 'count'), ('GET', 'conversation'), ('GET', 'runtime'),          # 1. inspect
            ('POST', 'bash/execute_bash_command'),                                    # 2. SEED
            ('POST', 'events'),                                                       # 3. the message
            ('GET', 'conversation'),                                                  # 4. the turn: finished
            ('POST', 'bash/execute_bash_command'),                                    # 5. RESULT
            ('DELETE', 'runtime'), ('GET', 'runtime')])                               # 7. the runtime stopped
        self.assertEqual(self.observed, ['before-message', 'after-turn', 'after-result'])
        self.assertEqual(puller.names, [AR.result_name(store_mod.attempt_id_for(self.key))])
        self.assertEqual(self.reserved, [outcome.result])
        self.assertEqual((outcome.runtime, outcome.turn_status), ('missing', 'finished'))
        self.assertEqual(outcome.result.base, self.base.commit)
        self.assertEqual(self.store.get(AR.TURN_KEY.format(attempt_id=outcome.attempt_id)).state, 'confirmed')
        self.assertIsNone(AE.end_record(self.store, outcome.attempt_id))
        json.dumps(outcome.to_json())

    def test_a_failed_inspection_sends_no_message_and_ends_the_attempt(self):
        cases = {
            'a second conversation': (lambda case: setattr(case.server, 'count', 2), lambda cid: ()),
            'a runtime not running': (lambda case: case.server.set(case.cid, runtime='available'), lambda cid: ()),
            'a container off its declaration': (lambda case: None, lambda cid: ['the image is not the pinned one']),
            'a hook that cannot answer': (lambda case: None, lambda cid: 1 / 0),
        }
        for name, (arrange, inspect) in cases.items():
            with self.subTest(name):
                case = Run('test_a_failed_inspection_sends_no_message_and_ends_the_attempt')
                case.setUp()
                self.addCleanup(case.doCleanups)
                arrange(case)
                outcome = case.run_attempt(inspect=inspect)
                self.assertEqual(outcome.outcome, 'inspection-failed')
                self.assertTrue(outcome.problems)
                self.assertNotIn(('POST', 'events'), case.server.log)
                self.assertNotIn(('POST', 'bash/execute_bash_command'), case.server.log)
                self.assertIsNone(case.store.get(AR.TURN_KEY.format(attempt_id=outcome.attempt_id)))
                self.assertEqual(outcome.end['surfaced']['dispatcherRecords'],
                                 [{'kind': 'containment-stop', 'code': 'INSPECTION_FAILED',
                                   'ref': f'attempt:{outcome.attempt_id}#inspection'}])
                self.assertEqual(outcome.end['classification'], AE.NON_RETRYABLE)
                self.assertEqual(case.observed, [])

    def test_a_turn_that_is_not_finished_runs_no_result(self):
        for status in ('error', 'stuck', 'paused'):
            with self.subTest(status=status):
                case = Run('test_a_turn_that_is_not_finished_runs_no_result')
                case.setUp()
                self.addCleanup(case.doCleanups)
                case.server.after_message = status
                outcome = case.run_attempt()
                self.assertEqual((outcome.outcome, outcome.turn_status), ('turn-not-finished', status))
                self.assertEqual([c for c in case.server.log if c == ('POST', 'bash/execute_bash_command')],
                                 [('POST', 'bash/execute_bash_command')], 'the SEED only, no RESULT')
                self.assertEqual(case.reserved, [])

    def test_an_observer_stop_ends_the_attempt_and_reserves_no_result(self):
        for phase, kind in (('before-message', 'credential-stop'), ('after-turn', 'model-stop')):
            with self.subTest(phase=phase):
                case = Run('test_an_observer_stop_ends_the_attempt_and_reserves_no_result')
                case.setUp()
                self.addCleanup(case.doCleanups)
                stop = te.record(kind, 'OBSERVED_STOP', f'run:{phase}')
                with mock.patch.object(AE, 'end_interrupted_attempt', wraps=AE.end_interrupted_attempt) as end:
                    outcome = case.run_attempt(observe=lambda p, **f: [stop] if p == phase else ())
                self.assertEqual(outcome.outcome, 'stopped')
                self.assertEqual(end.call_args.kwargs['dispatcher_records'], [stop])
                self.assertEqual(end.call_args.kwargs['trigger'], AE.ATTEMPT_STOPPED)
                self.assertEqual(outcome.end['classification'], AE.NON_RETRYABLE)
                self.assertEqual(case.reserved, [])
                self.assertEqual(case.server.log.count(('POST', 'bash/execute_bash_command')), 1, 'no RESULT')
                self.assertEqual(case.server.log.count(('POST', 'events')), 0 if phase == 'before-message' else 1)
                self.assertIsNone(case.store.get(AE.RESULT_KEY.format(attempt_id=outcome.attempt_id)))

    def test_a_stop_after_the_result_reserves_no_result(self):
        puller = self.real()
        stop = te.record('provider-stop', 'PROVIDER_PROCESS_LEFT', 'run:after-result')
        outcome = self.run_attempt(pull=puller, observe=lambda p, **f: [stop] if p == 'after-result' else ())
        self.assertEqual((outcome.outcome, outcome.end['classification']), ('stopped', AE.NON_RETRYABLE))
        self.assertEqual(self.reserved, [])
        self.assertEqual(outcome.end['causes'], ['provider-process'])

    def test_a_base_of_another_repository_or_design_is_refused_before_any_call(self):
        for change in (dict(repository='other-repo'), dict(design_commit='e' * 40)):
            with self.subTest(change=change), self.assertRaises(di.DispatchRefused) as caught:
                AR.run_attempt(self.store, self.key, transport=self.server, base=dataclasses.replace(self.base,
                                                                                                    **change),
                               actor='a2-test', inspect=lambda c: (), pull=lambda n: None,
                               read_artifact=self.fixture.read_artifact)
            self.assertEqual(caught.exception.code, 'BASE_LACKS_DESIGN')
        self.assertEqual(self.server.log, [])


# ---------------------------------------------------------------------------
# The end's exclusion and R2's kinds

class EndExclusion(te.EndFixture):
    category = 'integration'

    def result_journal(self, result, state):
        attempt = store_mod.attempt_id_for(result.operation_key)
        key = AE.RESULT_KEY.format(attempt_id=attempt)
        self.store.reserve(key, {'format': 'test/result', 'attemptId': attempt}, actor='a2-test')
        if state != 'reserved':
            di._mark(self.store, key, 'reserved', 'dispatched', 'a2-test', 'push', None)
        if state in ('confirmed', 'unknown'):
            di._mark(self.store, key, 'dispatched', state, 'a2-test', 'push', None)
        return attempt

    def test_a_reserved_result_journal_does_not_keep_a_security_stop_from_ending_the_attempt(self):
        result = self.interrupted(status='finished')
        self.result_journal(result, 'reserved')
        ended = self.end(result, trigger=AE.ATTEMPT_STOPPED, records=[te.record('model-stop')])
        self.assertEqual((ended['classification'], ended['causes']), (AE.NON_RETRYABLE, ['unexpected-model']))

    def test_an_attempt_whose_result_journal_is_dispatched_is_not_ended(self):
        result = self.interrupted(status='finished')
        attempt = self.result_journal(result, 'dispatched')
        calls = len(self.server.calls)
        self.refused_end('ATTEMPT_RESULT_HANDED_ON', result, trigger=AE.ATTEMPT_STOPPED,
                         records=[te.record('provider-stop')])
        self.assertEqual(len(self.server.calls), calls)
        self.assertIsNone(AE.end_record(self.store, attempt))

    def test_a_confirmed_or_unknown_result_journal_refuses_the_end_too(self):
        for state in ('confirmed', 'unknown'):
            with self.subTest(state=state):
                case = EndExclusion('test_a_confirmed_or_unknown_result_journal_refuses_the_end_too')
                case.setUp()
                self.addCleanup(case.doCleanups)
                result = case.interrupted(status='finished')
                case.result_journal(result, state)
                case.refused_end('ATTEMPT_RESULT_HANDED_ON', result, trigger=AE.ATTEMPT_STOPPED,
                                 records=[te.record('egress-stop')])

    def test_the_two_new_kinds_are_security_stops(self):
        self.assertEqual({k: AE.NON_RETRYABLE_RECORDS[k] for k in ('model-stop', 'provider-stop')},
                         {'model-stop': 'unexpected-model', 'provider-stop': 'provider-process'})
        for kind in ('model-stop', 'provider-stop'):
            with self.subTest(kind=kind):
                verdict = AE.classify('finished', [], AE.check_records([te.record(kind)]))
                self.assertEqual((verdict['classification'], verdict['securityStop']), (AE.NON_RETRYABLE, True))


if __name__ == '__main__':
    unittest.main()
