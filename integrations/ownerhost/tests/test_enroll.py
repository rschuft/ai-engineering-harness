"""The Owner's enroll command and its console guard (plan leaf U-01.3; decision 0025 point 3; gate G8).

``enroll`` refuses unless standard input and standard output are both console handles (the broker's GetConsoleMode
check, reused): a pipe, a file or the null device on either handle is ``ENROLL_NOT_INTERACTIVE``, before the
managed root is resolved or the store is opened, so a tool shell's pipes obtain nothing. A console passes.

What the guard is, and what it is not: it refuses a plain pipe or a redirected handle, which is how an ordinary
tool shell would run the command by accident. It is no defence against a process of the Owner's account that gives
the command a console, as GuardScope below does with a hidden console of its own (a pseudoconsole, ConPTY, works the
same way), or that calls the library or writes the store: that is decision 0010 point 1's accepted same-account
limit. Any such enrollment supersedes the Owner's session, which then answers SESSION_CREDENTIAL_REVOKED at his
next request, unless a same-account writer of the store undoes it first (decision 0010 point 1). GuardScope runs the guard on its hidden console's real handles and on a real pipe in
either position, then the whole command against a throwaway managed root (the credential it shows goes to that
hidden console, which nobody reads). Nothing here touches the managed data root.
"""
from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import ownerhost_support as T

CATEGORY = 'unit'
E, CS = T.E, T.CS
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


class Guard(unittest.TestCase):
    """The real console check on streams that are not consoles (no console is needed or read here)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='aieh-ownerhost-enroll-'))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def streams(self):
        read_fd, write_fd = os.pipe()
        pipe_in, pipe_out = os.fdopen(read_fd, 'r'), os.fdopen(write_fd, 'w')
        file_in = open(self.tmp / 'in.txt', 'w+')
        null = open(os.devnull, 'w')
        for stream in (pipe_in, pipe_out, file_in, null):
            self.addCleanup(stream.close)
        return {'a pipe (read end)': pipe_in, 'a pipe (write end)': pipe_out, 'a file': file_in,
                'the null device': null, 'a stream without a descriptor': io.StringIO()}

    def test_a_pipe_a_file_or_the_null_device_is_not_a_console(self):
        for name, stream in self.streams().items():
            with self.subTest(stream=name):
                self.assertFalse(E.is_console(stream))

    def test_either_handle_not_a_console_is_refused(self):
        console_in, console_out = object(), object()

        def check(stream):
            return stream in (console_in, console_out)
        E.console_guard(console_in, console_out, check)
        for name, (stdin, stdout) in (('standard input', (io.StringIO(), console_out)),
                                      ('standard output', (console_in, io.StringIO())),
                                      ('standard input', (io.StringIO(), io.StringIO()))):
            with self.subTest(handle=name), self.assertRaises(E.EnrollRefused) as caught:
                E.console_guard(stdin, stdout, check)
            self.assertEqual(caught.exception.code, 'ENROLL_NOT_INTERACTIVE')
            self.assertIn(name, caught.exception.detail)

    def test_the_command_refuses_before_resolving_the_root_or_opening_the_store(self):
        streams = self.streams()
        for stdin, stdout in ((streams['a pipe (read end)'], streams['a pipe (write end)']),
                              (streams['the null device'], io.StringIO())):
            err = io.StringIO()
            with mock.patch.object(E, '_paths', side_effect=AssertionError('the root was resolved')), \
                    mock.patch.object(CS, 'open_store', side_effect=AssertionError('the store was opened')), \
                    mock.patch.object(E, 'mint', side_effect=AssertionError('a credential was minted')):
                self.assertEqual(E.main([], stdin=stdin, stdout=stdout, stderr=err), 2)
            self.assertTrue(err.getvalue().startswith('ENROLL_NOT_INTERACTIVE: standard input is not a console'))
        self.assertEqual([p.name for p in self.tmp.iterdir()], ['in.txt'])

    def test_the_command_checks_the_validity_before_anything_is_written(self):
        err = io.StringIO()
        with mock.patch.object(E, '_paths', side_effect=AssertionError('the root was resolved')):
            self.assertEqual(E.main(['--hours', '169'], stdin=io.StringIO(), stdout=io.StringIO(), stderr=err,
                                    check=lambda stream: True), 2)
        self.assertIn('ENROLL_HOURS_INVALID', err.getvalue())


CHILD = r'''
import importlib.util, io, json, os, sys
spec = importlib.util.spec_from_file_location('aieh_ownerhost_enroll', sys.argv[1])
E = importlib.util.module_from_spec(spec); sys.modules[spec.name] = E; spec.loader.exec_module(E)
report = {'stdin_console': E.is_console(sys.stdin), 'stdout_console': E.is_console(sys.stdout)}
read_fd, write_fd = os.pipe()
pipe_in, pipe_out = os.fdopen(read_fd, 'r'), os.fdopen(write_fd, 'w')
outcomes = {}
for name, (stdin, stdout) in (('console', (sys.stdin, sys.stdout)), ('stdin pipe', (pipe_in, sys.stdout)),
                              ('stdout pipe', (sys.stdin, pipe_out))):
    try:
        E.console_guard(stdin, stdout)
        outcomes[name] = 'passed'
    except E.EnrollRefused as exc:
        outcomes[name] = exc.code
report['guard'] = outcomes
report['main'] = E.main(['--hours', '2'], config={}, stderr=io.StringIO())
with open(sys.argv[2], 'w', encoding='utf-8') as handle:
    json.dump(report, handle)
'''


@unittest.skipUnless(sys.platform == 'win32', 'the Windows console (GetConsoleMode)')
class GuardScope(unittest.TestCase):
    """Gate G8's scope: a redirected handle is refused; any console passes, a hidden one that a same-account process
    made included. The guard stops an accidental piped run, not a same-account process (decision 0010 point 1)."""
    category = 'integration'

    def test_a_pipe_is_refused_and_any_console_passes_even_one_without_a_window(self):
        tmp = Path(tempfile.mkdtemp(prefix='aieh-ownerhost-g8-'))
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / 'root').mkdir()
        script, report = tmp / 'child.py', tmp / 'report.json'
        script.write_text(CHILD, encoding='utf-8')
        env = {k: v for k, v in os.environ.items() if k.upper() in ('SYSTEMROOT', 'SYSTEMDRIVE', 'WINDIR', 'TEMP',
                                                                    'TMP', 'LOCALAPPDATA', 'USERPROFILE')}
        env['AIEH_DATA_ROOT'] = str(tmp / 'root')
        # no standard handle is given, so the child's are those of its own console, which no window shows
        child = subprocess.Popen([sys.executable, '-I', '-B', str(script), str(T.PACKAGE / 'enroll.py'), str(report)],
                                 env=env, cwd=str(tmp), creationflags=NO_WINDOW)
        self.assertEqual(child.wait(timeout=T.WAIT_CEILING_S), 0)
        result = json.loads(report.read_text(encoding='utf-8'))
        self.assertEqual(result, {'stdin_console': True, 'stdout_console': True, 'main': 0,
                                  'guard': {'console': 'passed', 'stdin pipe': 'ENROLL_NOT_INTERACTIVE',
                                            'stdout pipe': 'ENROLL_NOT_INTERACTIVE'}})
        stores = list((tmp / 'root').rglob(CS.DB_NAME))
        self.assertEqual([p.relative_to(tmp / 'root').as_posix() for p in stores],
                         ['persistent/state/owner-host/conversation.sqlite'])
        with CS.open_store(stores[0], apply_migrations=False) as store:
            (session,) = store.sessions()
            self.assertTrue(session.current)
            self.assertEqual((T.datetime.datetime.fromisoformat(session.expires_at.replace('Z', '+00:00'))
                              - T.datetime.datetime.fromisoformat(session.issued_at.replace('Z', '+00:00'))),
                             T.datetime.timedelta(hours=2))


if __name__ == '__main__':
    unittest.main()
