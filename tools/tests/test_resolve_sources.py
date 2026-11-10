"""R11 on the shared repository-access module (plan leaf F-10.6, decision 0014 section 1):
composition/resolve.py lists the locked source tags with the module's ``ls_remote`` instead of
``git ls-remote``, and tools/check_prereqs.py, which loads the resolver's ``prerequisites``, stays
standard-library only. Offline: the module is a stand-in here (its transport has its own suite,
integrations/repository/tests/test_repository_transport.py); no test launches a process or opens
a socket.

    <tools python> -I -B -m unittest discover -s tools/tests -p test_resolve_sources.py -v
"""
import ast
import contextlib
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
RESOLVE = REPO / 'composition' / 'resolve.py'
CHECK_PREREQS = REPO / 'tools' / 'check_prereqs.py'
LOCK = json.loads((REPO / 'composition' / 'lock' / 'components.lock.json').read_text(encoding='utf-8'))
NOT_STDLIB = ('dulwich', 'urllib3', 'repository_access', 'yaml')


def load(name, path):
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


resolve = load('aieh_resolve_under_test', RESOLVE)


class RepositoryError(Exception):
    def __init__(self, code, message):
        super().__init__(f'{code}: {message}')
        self.code, self.message = code, message


def stand_in(answers=None, failing=None):
    """The module's surface resolve_sources uses: ls_remote, answering from the lock (or from
    ANSWERS {source id: refs}), raising for the ids in FAILING; every call recorded."""
    calls = []

    def ls_remote(url, credential=None, *, names=None):
        calls.append((url, credential, names))
        source = next(s for s in LOCK['sources'] if s['repository'].rstrip('/') + '.git' == url
                      and names == [f'refs/tags/{s["tag"]}'])
        if source['id'] in (failing or ()):
            raise RepositoryError('REMOTE_FAILED', f'ls-remote {url}: HTTP 503')
        if answers and source['id'] in answers:
            return answers[source['id']]
        name = f'refs/tags/{source["tag"]}'
        if source.get('tag_type') == 'annotated':
            return {name: source['tag_object'], name + '^{}': source['commit']}
        return {name: source['commit']}

    return SimpleNamespace(ls_remote=ls_remote, RepositoryError=RepositoryError), calls


class SourceTags(unittest.TestCase):
    category = 'unit'

    def setUp(self):
        patch = mock.patch.object(subprocess, 'Popen', side_effect=AssertionError('a process was launched'))
        patch.start()
        self.addCleanup(patch.stop)

    def run_sources(self, ra):
        checks = resolve.Checks()
        with contextlib.redirect_stdout(io.StringIO()):
            out = resolve.resolve_sources(LOCK, checks, ra)
        return out, {c['id'] if isinstance(c, dict) else c[0]: c for c in checks.items}

    def test_every_locked_tag_through_ls_remote_without_git(self):
        ra, calls = stand_in()
        out, checks = self.run_sources(ra)
        self.assertEqual(len(out), 8)
        self.assertTrue(all(row['verified'] for row in out), out)
        self.assertEqual([row['commit'] for row in out], [s['commit'] for s in LOCK['sources']])
        self.assertEqual(calls, [(s['repository'].rstrip('/') + '.git', None, [f'refs/tags/{s["tag"]}'])
                                 for s in LOCK['sources']])
        self.assertEqual(len(checks), 8)

    def test_a_mismatch_an_extra_peel_or_a_failure_fails_that_source_only(self):
        annotated = next(s for s in LOCK['sources'] if s.get('tag_type') == 'annotated')
        light = [s for s in LOCK['sources'] if s.get('tag_type') != 'annotated']
        answers = {annotated['id']: {f'refs/tags/{annotated["tag"]}': annotated['commit']},  # not peeled: wrong
                   light[0]['id']: {f'refs/tags/{light[0]["tag"]}': 'f' * 40},
                   light[1]['id']: {f'refs/tags/{light[1]["tag"]}': light[1]['commit'],
                                    f'refs/tags/{light[1]["tag"]}^{{}}': light[1]['commit']}}
        ra, _calls = stand_in(answers, failing={light[2]['id']})
        out, _checks = self.run_sources(ra)
        failed = {row['id'] for row in out if not row['verified']}
        self.assertEqual(failed, {annotated['id'], light[0]['id'], light[1]['id'], light[2]['id']})
        self.assertEqual(sum(row['verified'] for row in out), 4)

    def test_the_failure_code_is_reported(self):
        source = LOCK['sources'][0]
        ra, _calls = stand_in(failing={source['id']})
        checks = resolve.Checks()
        with contextlib.redirect_stdout(io.StringIO()):
            resolve.resolve_sources(LOCK, checks, ra)
        self.assertIn('REMOTE_FAILED', json.dumps(checks.items))


class WithoutDulwich(unittest.TestCase):
    """The module is loaded lazily, on the source-tag path only; without Dulwich the resolver
    stops there with REPOSITORY_NEEDS_DULWICH (exit 2), naming task tools:install. No git
    fallback."""
    category = 'unit'

    def test_the_resolver_stops_with_the_module_s_code(self):
        # The module's own CannotRun and hint, from the module loaded by path (it imports Dulwich
        # only when a repository is opened); resolve finds the stand-in in its place.
        real = load('aieh_repository_access_for_codes', resolve.REPOSITORY_ACCESS)
        refusal = real.CannotRun('REPOSITORY_NEEDS_DULWICH', f'Dulwich is not importable; {real.TOOLS_INSTALL_HINT}')
        stub = SimpleNamespace(dulwich_modules=mock.Mock(side_effect=refusal))
        with mock.patch.dict(sys.modules, {'repository_access': stub}):
            with self.assertRaises(real.CannotRun) as caught:
                resolve.repository_access()
            self.assertEqual(caught.exception.code, 'REPOSITORY_NEEDS_DULWICH')
            with tempfile.TemporaryDirectory(prefix='aieh-resolve-test-') as tmp, \
                    mock.patch.object(resolve, 'prerequisites', return_value=(True, {}, 'npm')), \
                    mock.patch.object(subprocess, 'Popen', side_effect=AssertionError('a process was launched')), \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as err:
                code = resolve.main(['--work', str(Path(tmp) / 'work')])
        self.assertEqual(code, 2)
        self.assertIn('REPOSITORY_NEEDS_DULWICH', err.getvalue())
        self.assertIn('task tools:install', err.getvalue())


class StandardLibraryOnly(unittest.TestCase):
    """resolve.py imports the module only inside ``repository_access``; nothing in it launches git;
    check_prereqs.py never imports Dulwich or the module."""
    category = 'unit'

    @staticmethod
    def imports(tree):
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                yield node, [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                yield node, [node.module or '']

    def test_the_resolver_imports_the_module_lazily_and_launches_no_git(self):
        source = RESOLVE.read_text(encoding='utf-8')
        tree = ast.parse(source)
        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or '']
                self.assertFalse(any(n.split('.')[0] in NOT_STDLIB for n in names), names)
        prerequisites = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'prerequisites')
        self.assertNotIn('repository_access', ast.unparse(prerequisites))
        self.assertNotIn('"git"', source)
        self.assertNotIn("'git'", source)
        self.assertNotIn('ls-remote', source.replace('ls_remote', ''))

    def test_check_prereqs_never_imports_dulwich(self):
        tree = ast.parse(CHECK_PREREQS.read_text(encoding='utf-8'))
        for _node, names in self.imports(tree):
            self.assertFalse(any(n.split('.')[0] in NOT_STDLIB for n in names), names)
        self.assertNotIn('repository_access', CHECK_PREREQS.read_text(encoding='utf-8'))

    def test_the_components_tier_takes_the_resolver_s_prerequisites(self):
        check = load('aieh_check_prereqs_under_test', CHECK_PREREQS)
        fake = SimpleNamespace(Checks=resolve.Checks,
                               prerequisites=mock.Mock(return_value=(True, {'python': '3.12'}, 'npm')))
        with mock.patch.object(check, 'load', return_value=fake), contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(check.components())
        fake.prerequisites.assert_called_once()


class ResolveTarget(unittest.TestCase):
    """Taskfile.yml's resolve target runs the resolver under the python-tools interpreter; the
    components tier check keeps the plain one."""
    category = 'contract'

    def target(self, name):
        lines = (REPO / 'Taskfile.yml').read_text(encoding='utf-8').splitlines()
        start = lines.index(f'  {name}:')
        body = []
        for line in lines[start + 1:]:
            if line.strip() and not line.startswith('    '):
                break
            body.append(line.strip())
        return body

    def test_the_resolve_target(self):
        body = self.target('resolve')
        self.assertIn("sh: '{{.PYTHON}} -I -B integrations/paths/tools_install.py --python'", body)
        self.assertIn('PYTHON: \'"{{.TOOLS_PYTHON}}"\'', body)
        self.assertIn('- \'{{.PYTHON}} -I -B composition/resolve.py --work "{{.WORK}}"\'', body)
        components = self.target('prereqs:components')
        self.assertIn("- '{{.PYTHON}} -I -B tools/check_prereqs.py --tier components'", components)
        self.assertNotIn('TOOLS_PYTHON', ' '.join(components))


if __name__ == '__main__':
    unittest.main()
