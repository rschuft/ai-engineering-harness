"""Tests for tools/check_prereqs.py's INFO line on the Python tools venv (plan leaf F-10.5).

Run from the repository root:  python -I -B -m unittest discover -s tools/tests -v

The basic tier reports the tools venv, the product runtime of decision 0014 section 9, as
information only: located as ``tools_install.py --python`` locates it, never a check of the tier,
without importing Dulwich and without launching anything. Everything runs in process with the
locator and the tier's launches replaced; no directory is created.
"""
from pathlib import Path
import contextlib
import importlib.util
import io
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
CHECK = REPO / 'tools' / 'check_prereqs.py'
TOOLS_INSTALL = REPO / 'integrations' / 'paths' / 'tools_install.py'

CATEGORY = 'unit'


def load():
    spec = importlib.util.spec_from_file_location('aieh_check_prereqs_info_test', CHECK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeTools:
    """Stands in for integrations/paths/tools_install.py: its locator and its paths module."""

    def __init__(self, python=None, error=None):
        self.python, self.error, self.asked = python, error, []
        self.paths = self

    def resolve(self, config):
        self.asked.append(('resolve', config))
        if self.error:
            raise self.error
        return 'resolved'

    def installed_python(self, res):
        self.asked.append(('installed_python', res))
        return self.python


class ToolsVenvInfo(unittest.TestCase):
    def setUp(self):
        self.check = load()

    def info(self, tools):
        with mock.patch.object(self.check, 'load', return_value=tools) as loaded:
            line = self.check.tools_venv_info()
        loaded.assert_called_once_with('aieh_tools_install', TOOLS_INSTALL)
        return line

    def test_an_installed_venv_is_named_with_its_interpreter(self):
        tools = FakeTools(python=Path('X:/root/installs/python-tools/cp312-abc/Scripts/python.exe'))
        line = self.info(tools)
        self.assertTrue(line.startswith('[INFO] tools venv: '), line)
        self.assertIn(str(tools.python), line)
        self.assertIn('Dulwich', line)
        self.assertEqual(tools.asked, [('resolve', {}), ('installed_python', 'resolved')])

    def test_a_missing_venv_names_the_target_that_installs_it(self):
        line = self.info(FakeTools(python=None))
        self.assertIn('not installed for the current lock (task tools:install)', line)
        self.assertTrue(line.startswith('[INFO] '), line)

    def test_a_root_that_cannot_be_resolved_is_reported_never_raised(self):
        line = self.info(FakeTools(error=ValueError('AIEH_DATA_ROOT is not absolute')))
        self.assertIn('cannot be located (ValueError: AIEH_DATA_ROOT is not absolute)', line)
        self.assertTrue(line.startswith('[INFO] '), line)

    def test_the_real_locator_imports_no_dulwich(self):
        # The real tools_install module (and the paths module it loads), with Dulwich, urllib3 and
        # PyYAML made unimportable: it loads, and its locator answers for an install directory that
        # does not exist (inside the checkout, so that nothing outside it is examined).
        with mock.patch.dict(sys.modules, {'dulwich': None, 'urllib3': None, 'yaml': None}):
            tools = self.check.load('aieh_tools_install_no_dulwich', TOOLS_INSTALL)
            res = SimpleNamespace(repo_root=REPO, paths={'installs': REPO / 'aieh-absent-installs'})
            self.assertIsNone(tools.installed_python(res))
            with mock.patch.object(tools.paths, 'resolve', return_value=res) as resolve, \
                    mock.patch.object(self.check, 'load', return_value=tools):
                line = self.check.tools_venv_info()
        resolve.assert_called_once_with(config={})
        self.assertIn('not installed for the current lock (task tools:install)', line)

    def test_the_basic_tier_prints_it_and_its_verdict_does_not_depend_on_it(self):
        def output(cmd):
            return {'--version': 'git version 2.52.0', '-t': 'commit'}.get(cmd[-2] if cmd[-2] == '-t' else cmd[-1])

        real_load = self.check.load

        for tools in (FakeTools(python=None), FakeTools(error=OSError('unreadable'))):
            def load(name, path, tools=tools):    # the tools locator is the fake; verify_seed is real
                return tools if name == 'aieh_tools_install' else real_load(name, path)

            with self.subTest(python=tools.python, error=tools.error), \
                    mock.patch.object(self.check, 'output', side_effect=output), \
                    mock.patch.object(self.check.shutil, 'which', side_effect=lambda name: name), \
                    mock.patch.dict('os.environ', {'AIEH_TASK_VERSION': '3.54.0'}), \
                    mock.patch.object(self.check, 'load', side_effect=load), \
                    contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertTrue(self.check.basic())
            lines = out.getvalue().splitlines()
            self.assertEqual(sum(line.startswith('[INFO] tools venv: ') for line in lines), 1, lines)
            self.assertTrue(lines[-1].startswith('[INFO] tools venv: '), lines)
            self.assertEqual(len([a for a in tools.asked if a[0] == 'resolve']), 1)


if __name__ == '__main__':
    unittest.main()
