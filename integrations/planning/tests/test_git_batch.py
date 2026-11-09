"""Tests of the planning adapter's batched git reads (stdlib unittest, plan leaf F-09.4).

Run from the repository root:

    python -I -B -m unittest discover -s integrations/planning/tests -v

``planning_adapter.Git`` reads objects through one ``git cat-file --batch`` process per
read session (``BatchReader``), with memos that last only for that session. These tests
check what that must keep: the answers of the one-shot commands it replaces (``rev-parse
--verify --quiet REV^{commit}``, ``cat-file -t``, ``cat-file blob``), names that could break
the line protocol refused before anything reaches the process, the reader closed on a normal
exit, on an exception and on a timeout (killed, and every later read fails closed), and no
memo outliving its session. Stand-in processes play a git that hangs or answers out of
protocol; every other process is the real git.
"""
import hashlib
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

CATEGORY = 'integration'

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import two_task_fixture as fx  # noqa: E402

adapter = fx.adapter
PlanningError = adapter.PlanningError
DESIGN = f'openspec/changes/{fx.CHANGE}/design.md'

# Every character the batch protocol cannot carry inside one name: whitespace (ASCII and
# Unicode) and the control characters.
UNSAFE_CHARACTERS = [chr(c) for c in (0, 1, 9, 10, 11, 12, 13, 0x1b, 0x1f, 0x20, 0x7f, 0x85, 0xa0, 0x2028, 0x3000)]
# A stand-in that reads a request and never answers, and one that answers out of protocol.
HANGS = [sys.executable, '-I', '-c', 'import sys, time; sys.stdin.readline(); time.sleep(300)']
GARBLES = [sys.executable, '-I', '-c',
           'import sys, time; sys.stdin.readline(); print("not an answer", flush=True); time.sleep(300)']
ANSWERS_ANOTHER = [sys.executable, '-I', '-c',
                   'import sys, time; sys.stdin.readline(); '
                   'sys.stdout.buffer.write(b"main^{commit} missing" + bytes([10])); sys.stdout.flush(); time.sleep(300)']


class Recorded(adapter.BatchReader):
    """A BatchReader that keeps every instance, so a test can check each process ended."""
    made = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        type(self).made.append(self)


class WriteRecorder:
    """Stands in for a reader's standard input and keeps what was written to it."""

    def __init__(self, stream):
        self.stream, self.written = stream, bytearray()

    def write(self, data):
        self.written.extend(data)
        return self.stream.write(data)

    def flush(self):
        return self.stream.flush()

    def close(self):
        return self.stream.close()


def bare_git():
    """A Git that never ran (no project): only argument checks can be exercised on it."""
    git = adapter.Git.__new__(adapter.Git)
    git.project, git._session = Path('no-project'), None
    return git


class BatchLine(unittest.TestCase):
    category = 'unit'

    def test_object_names_and_revisions_are_accepted(self):
        for name in ('HEAD', 'main', 'a' * 40, 'a' * 40 + ':openspec/changes/x/design.md', 'HEAD^{commit}',
                     'HEAD~2:README.md', 'v1.0^{}', 'é:ü/ö.md'):
            with self.subTest(name=name):
                self.assertEqual(adapter.batch_line(name), name.encode('utf-8'))

    def test_names_that_could_break_a_line_are_refused(self):
        bad = [f'HEAD{ch}' for ch in UNSAFE_CHARACTERS] + [f'{ch}HEAD' for ch in UNSAFE_CHARACTERS]
        bad += ['', '-', '--batch-all-objects', 'a' * 40 + ':docs/a b.md', 'HEAD:x' + chr(0xd800),
                None, b'HEAD', 7]
        for name in bad:
            with self.subTest(name=name):
                with self.assertRaises(PlanningError) as ctx:
                    adapter.batch_line(name)
                self.assertEqual(ctx.exception.code, 'OBJECT_NAME_INVALID')

    def test_refused_revisions_never_reach_a_reader(self):
        git = bare_git()
        with mock.patch.object(adapter, 'BatchReader', side_effect=AssertionError('a reader was started')), \
                mock.patch.object(adapter.subprocess, 'Popen', side_effect=AssertionError('launched')):
            for revision in [f'HEAD{ch}' for ch in UNSAFE_CHARACTERS] + ['', '-x', '--all', None]:
                with self.subTest(revision=revision):
                    with self.assertRaises(PlanningError) as ctx:
                        git.commit(revision)
                    self.assertEqual(ctx.exception.code, 'REVISION_INVALID')
            for path in [f'a{ch}b' for ch in UNSAFE_CHARACTERS]:
                for read in (git.object_type, git.blob):
                    with self.subTest(read=read.__name__, path=path):
                        with self.assertRaises(PlanningError) as ctx:
                            read('a' * 40, path)
                        self.assertEqual(ctx.exception.code, 'OBJECT_NAME_INVALID')


class RepoCase(unittest.TestCase):
    """A design repository per class (read only by these tests unless a test copies it)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix='aieh-batch-test-'))
        cls.addClassCleanup(fx.rmtree, cls.tmp)
        cls.repo = cls.tmp / 'project'
        cls.commit = fx.build_repo(cls.repo)

    def setUp(self):
        Recorded.made = []
        patch = mock.patch.object(adapter, 'BatchReader', Recorded)
        patch.start()
        self.addCleanup(patch.stop)
        self.git = adapter.Git(self.repo)

    def assertEnded(self, readers):
        self.assertTrue(readers)
        for reader in readers:
            self.assertIsNotNone(reader.process.poll(), f'process {reader.process.pid} is still running')

    def expect(self, code, func, *args):
        with self.assertRaises(PlanningError) as ctx:
            func(*args)
        self.assertEqual(ctx.exception.code, code, ctx.exception.message)
        return ctx.exception


class Equivalence(RepoCase):
    """The batch reader answers as the one-shot commands it replaces, run as before."""

    def one_shot(self, *args):
        result = subprocess.run(['git', '-C', str(self.repo), *args], capture_output=True,
                                stdin=subprocess.DEVNULL, timeout=adapter.TOOL_TIMEOUT_S, env=adapter.tool_env())
        return result.stdout if result.returncode == 0 else None

    def ambiguous_prefix(self):
        """A four-digit prefix shared by two blobs written here (found by hashing, one launch)."""
        if getattr(type(self), 'prefix', None) is None:
            type(self).prefix = self._write_ambiguous_blobs()
        return type(self).prefix

    def _write_ambiguous_blobs(self):
        seen = {}
        for number in range(100000):
            data = f'ambiguous {number}'.encode()
            oid = hashlib.sha1(b'blob %d' % len(data) + bytes([0]) + data).hexdigest()
            if oid[:4] in seen:
                other = seen[oid[:4]]
                break
            seen[oid[:4]] = data
        with tempfile.TemporaryDirectory(prefix='aieh-batch-amb-') as tmp:
            paths = []
            for index, payload in enumerate((other, data)):
                path = Path(tmp, f'{index}.txt')
                path.write_bytes(payload)
                paths.append(str(path))
            written = subprocess.run(['git', '-C', str(self.repo), 'hash-object', '-w', '--stdin-paths'],
                                     input='\n'.join(paths).encode(), capture_output=True, check=True,
                                     timeout=adapter.TOOL_TIMEOUT_S, env=adapter.tool_env())
        self.assertEqual(written.stdout.split()[1].decode()[:4], oid[:4])
        return oid[:4]

    def test_revisions(self):
        tree = self.one_shot('rev-parse', f'{self.commit}^{{tree}}').decode().strip()
        blob = self.one_shot('rev-parse', f'{self.commit}:{DESIGN}').decode().strip()
        revisions = ['HEAD', 'main', 'refs/heads/main', self.commit, self.commit[:12], self.commit[:4], '@',
                     'HEAD~0', 'HEAD~1', 'HEAD^2', 'no-such-branch', '0' * 40, 'f' * 64, tree, blob,
                     f'HEAD:{DESIGN}', 'HEAD:openspec', 'main@{0}', 'HEAD^{tree}', self.ambiguous_prefix()]
        with self.git.session():
            for revision in revisions:
                with self.subTest(revision=revision):
                    expected = self.one_shot('rev-parse', '--verify', '--quiet', f'{revision}^{{commit}}')
                    self.assertEqual(self.git.commit(revision), expected.decode('ascii').strip() if expected else None)
        self.assertEqual(self.git.commit('HEAD'), self.commit)
        self.assertEnded(Recorded.made)

    def test_object_types_and_blobs(self):
        names = [DESIGN, 'openspec', 'openspec/', f'openspec/changes/{fx.CHANGE}/no-such.md', 'README.md',
                 'no/such/dir', f'openspec/changes/{fx.CHANGE}', 'openspec/config.yaml']
        with self.git.session():
            for revision in (self.commit, 'HEAD', '0' * 40):
                for path in names:
                    with self.subTest(revision=revision, path=path):
                        name = f'{revision}:{path}'
                        kind = self.one_shot('cat-file', '-t', name)
                        self.assertEqual(self.git.object_type(revision, path), kind.decode().strip() if kind else None)
                        data = self.one_shot('cat-file', 'blob', name)
                        if data is None:
                            self.expect('GIT_FAILED', self.git.blob, revision, path)
                        else:
                            self.assertEqual(self.git.blob(revision, path), data)
            for name in (self.commit, self.commit[:7], '0' * 40, self.ambiguous_prefix()):
                with self.subTest(name=name):
                    kind = self.one_shot('cat-file', '-t', name)
                    self.assertEqual(self.git.object_kind(name), kind.decode().strip() if kind else None)
        self.assertEnded(Recorded.made)

    def test_file_lists(self):
        with self.git.session():
            for directory in ('openspec/changes', f'openspec/changes/{fx.CHANGE}', 'no/such', DESIGN):
                with self.subTest(directory=directory):
                    out = self.one_shot('ls-tree', '-r', '-z', '--name-only', self.commit, '--', directory + '/')
                    expected = [n.decode() for n in out.split(bytes([0])) if n]
                    self.assertEqual(self.git.files(self.commit, directory), expected)
                    self.assertEqual(self.git.files(self.commit, directory), expected)  # the memo


class InputSafety(RepoCase):
    def test_a_refused_name_is_never_written_to_the_process(self):
        with self.git.session():
            self.assertEqual(self.git.commit('HEAD'), self.commit)
            reader = self.git._session.reader
            recorder = WriteRecorder(reader.process.stdin)
            reader.process.stdin = recorder
            for ch in UNSAFE_CHARACTERS:
                with self.subTest(ch=ord(ch)):
                    self.expect('REVISION_INVALID', self.git.commit, f'main{ch}HEAD')
                    self.expect('OBJECT_NAME_INVALID', self.git.object_type, self.commit, f'README.md{ch}x')
                    self.expect('OBJECT_NAME_INVALID', self.git.blob, self.commit, f'{ch}README.md')
                    self.expect('OBJECT_NAME_INVALID', self.git.object_kind, f'{self.commit}{ch}')
                    self.expect('OBJECT_NAME_INVALID', reader.read, f'HEAD{ch}')
            self.assertEqual(bytes(recorder.written), b'')
            # The protocol is still in step: the next request gets its own answer.
            self.assertEqual(self.git.object_type(self.commit, 'README.md'), 'blob')
            self.assertEqual(bytes(recorder.written), f'{self.commit}:README.md'.encode() + bytes([10]))
        self.assertEqual(len(Recorded.made), 1)
        self.assertEnded(Recorded.made)

    def test_a_refused_name_starts_no_process(self):
        with mock.patch.object(adapter.subprocess, 'Popen', side_effect=AssertionError('launched')):
            for ch in UNSAFE_CHARACTERS:
                with self.subTest(ch=ord(ch)):
                    self.expect('REVISION_INVALID', self.git.commit, f'HEAD{ch}')
                    self.expect('OBJECT_NAME_INVALID', self.git.object_type, self.commit, f'a{ch}')
        self.assertEqual(Recorded.made, [])


class Lifecycle(RepoCase):
    def test_a_normal_exit_ends_the_process(self):
        with self.git.session():
            self.assertEqual(self.git.commit('HEAD'), self.commit)
            self.assertEqual(self.git.object_type(self.commit, DESIGN), 'blob')
            (reader,) = Recorded.made
            self.assertIsNone(reader.process.poll())
        self.assertEnded([reader])
        self.expect('GIT_FAILED', reader.read, 'HEAD')  # closed: it fails closed

    def test_an_exception_ends_the_process(self):
        with self.assertRaises(RuntimeError):
            with self.git.session():
                self.git.commit('HEAD')
                raise RuntimeError('boom')
        self.assertEnded(Recorded.made)
        self.assertIsNone(self.git._session)

    def test_calls_outside_a_session_each_end_their_process(self):
        self.assertEqual(self.git.commit(self.commit), self.commit)
        self.assertEqual(self.git.blob(self.commit, 'README.md')[:9], b'Throwaway')
        self.expect('GIT_FAILED', self.git.blob, self.commit, 'openspec')
        self.assertEqual(len(Recorded.made), 3)
        self.assertEnded(Recorded.made)

    def test_a_timeout_kills_the_process_and_fails_closed(self):
        with mock.patch.object(adapter.Git, 'batch_argv', return_value=HANGS), \
                mock.patch.object(adapter, 'TOOL_TIMEOUT_S', 0.2):
            with self.git.session():
                started = time.monotonic()
                with self.assertRaises(subprocess.TimeoutExpired) as ctx:
                    self.git.commit('HEAD')
                self.assertGreaterEqual(time.monotonic() - started, 0.2)
                self.assertEqual(ctx.exception.timeout, 0.2)
                (reader,) = Recorded.made
                self.assertEnded([reader])  # killed at once, not at the end of the session
                error = self.expect('GIT_FAILED', self.git.object_type, self.commit, DESIGN)
                self.assertIn('killed', error.message)
            self.assertEnded(Recorded.made)
            self.assertEqual(len(Recorded.made), 1)

    def test_an_answer_out_of_protocol_fails_closed(self):
        with mock.patch.object(adapter.Git, 'batch_argv', return_value=GARBLES):
            with self.git.session():
                error = self.expect('GIT_FAILED', self.git.commit, 'HEAD')
                self.assertIn('unexpected answer', error.message)
                self.assertEnded(Recorded.made)
                self.expect('GIT_FAILED', self.git.commit, 'HEAD')
        self.assertEnded(Recorded.made)

    def test_an_answer_for_another_name_fails_closed(self):
        # "<name> missing" must echo the name asked; another name means the protocol is out of step.
        with mock.patch.object(adapter.Git, 'batch_argv', return_value=ANSWERS_ANOTHER):
            with self.git.session():
                error = self.expect('GIT_FAILED', self.git.commit, 'HEAD')
                self.assertIn('unexpected answer', error.message)
        self.assertEnded(Recorded.made)

    def test_a_reader_that_exits_fails_closed(self):
        with self.git.session():
            self.git.commit('HEAD')
            (reader,) = Recorded.made
            reader.process.kill()
            reader.process.wait(adapter.TOOL_TIMEOUT_S)
            error = self.expect('GIT_FAILED', self.git.object_type, self.commit, DESIGN)
            self.assertIn('exited', error.message)
        self.assertEnded(Recorded.made)


class Memo(RepoCase):
    def reads(self):
        return mock.patch.object(Recorded, 'read', autospec=True, side_effect=adapter.BatchReader.read)

    def test_a_session_reads_each_immutable_object_once(self):
        with self.reads() as read, self.git.session():
            for _ in range(3):
                self.assertEqual(self.git.commit('HEAD'), self.commit)
                self.assertEqual(self.git.object_type(self.commit, DESIGN), 'blob')
                self.git.blob(self.commit, DESIGN)
                self.assertIsNone(self.git.object_type(self.commit, 'no-such'))
        self.assertEqual([call.args[1] for call in read.call_args_list],
                         ['HEAD^{commit}', f'{self.commit}:{DESIGN}', f'{self.commit}:no-such'])

    def test_names_that_can_change_are_not_memoized(self):
        with self.reads() as read, self.git.session():
            for _ in range(2):
                self.assertEqual(self.git.object_type('HEAD', DESIGN), 'blob')
                self.assertEqual(self.git.object_type('main', DESIGN), 'blob')
        self.assertEqual(len(read.call_args_list), 4)

    def test_revisions_are_a_snapshot_of_one_session_only(self):
        repo = self.tmp / 'moving'
        fx.build_repo(repo)
        git = adapter.Git(repo)
        with git.session():
            self.assertEqual(git.commit('HEAD'), self.commit)
            fx.write(repo, {'README.md': b'moved on\n'})
            later = fx.commit_all(repo, 'later', date='2026-11-08T00:00:00Z')
            self.assertEqual(git.commit('HEAD'), self.commit)  # the session's snapshot
            self.assertEqual(git.commit(later), later)
        with git.session():
            self.assertEqual(git.commit('HEAD'), later)  # nothing kept from the last session
        self.assertEqual(git.commit('HEAD'), later)
        self.assertEqual(len(Recorded.made), 3)
        self.assertEnded(Recorded.made)

    def test_file_lists_are_kept_for_the_session_only(self):
        runs = []
        real_run = adapter.Git._run

        def counting(git, *args, **kwargs):
            runs.append(args[0])
            return real_run(git, *args, **kwargs)

        with mock.patch.object(adapter.Git, '_run', autospec=True, side_effect=counting):
            for _ in range(2):
                with self.git.session():
                    for _ in range(3):
                        self.assertIn(DESIGN, self.git.files(self.commit, 'openspec'))
                        self.assertIn(DESIGN, self.git.files('HEAD', 'openspec'))
        self.assertEqual(runs, ['ls-tree'] * 8)


if __name__ == '__main__':
    unittest.main()
