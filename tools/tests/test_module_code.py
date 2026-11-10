"""Tests for tools/tests/module_code.py, the test modules' loader with shared compiled code (F-09).

Run from the repository root:  python -I -B -m unittest discover -s tools/tests -v

Each load must be what spec_from_file_location and exec_module give: a new module, executed
afresh in its own namespace. Only the compilation is shared, and only while the file's content
is the same. The files loaded are written in one temporary directory per class.
"""
from pathlib import Path
import importlib.machinery
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import module_code  # noqa: E402

CATEGORY = 'unit'

SOURCE = 'loads = []\nloads.append(__name__)\nVALUE = {value!r}\n\n\ndef value():\n    return VALUE\n'


class Load(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.TemporaryDirectory(prefix='aieh-module-code-')
        cls.addClassCleanup(tmp.cleanup)
        cls.tmp = Path(tmp.name)

    def write(self, name, value, mtime_ns=None):
        path = self.tmp / name
        path.write_text(SOURCE.format(value=value), encoding='utf-8')
        if mtime_ns is not None:
            os.utime(path, ns=(mtime_ns, mtime_ns))
        return path

    def compiles(self):
        """A patch counting the loader's compilations (SourceLoader.source_to_code)."""
        real = importlib.machinery.SourceFileLoader.source_to_code
        return mock.patch.object(module_code._SharedCodeLoader, 'source_to_code', autospec=True,
                                 side_effect=lambda loader, *a, **k: real(loader, *a, **k))

    def test_each_load_is_a_new_module_executed_afresh(self):
        path = self.write('fresh.py', 'one')
        first = module_code.load('aieh_fresh_a', path)
        second = module_code.load('aieh_fresh_b', path)
        self.assertIsNot(first, second)
        self.assertIsNot(first.loads, second.loads)          # module-level state is not shared
        self.assertEqual((first.loads, second.loads), (['aieh_fresh_a'], ['aieh_fresh_b']))
        self.assertEqual((first.__name__, first.__file__), ('aieh_fresh_a', str(path)))
        self.assertEqual(first.value(), 'one')
        self.assertIs(first.value.__globals__, vars(first))
        self.assertIs(second.value.__globals__, vars(second))
        self.assertNotIn('aieh_fresh_a', sys.modules)       # as exec_module alone: not registered

    def test_a_file_is_compiled_once_per_content(self):
        path = self.write('once.py', 'same')
        with self.compiles() as compiled:
            modules = [module_code.load(f'aieh_once_{n}', path) for n in range(3)]
        self.assertEqual(compiled.call_count, 1)
        self.assertEqual([m.value() for m in modules], ['same'] * 3)
        self.assertIs(modules[0].value.__code__, modules[2].value.__code__)

    def test_a_changed_file_is_compiled_again(self):
        path = self.write('changed.py', 'before', mtime_ns=1_700_000_000_000_000_000)
        self.assertEqual(module_code.load('aieh_changed_a', path).value(), 'before')
        # An edit: another size and a later modification time (the cache key's two parts).
        self.write('changed.py', 'after, longer', mtime_ns=1_700_000_001_000_000_000)
        with self.compiles() as compiled:
            self.assertEqual(module_code.load('aieh_changed_b', path).value(), 'after, longer')
        self.assertEqual(compiled.call_count, 1)


if __name__ == '__main__':
    unittest.main()
