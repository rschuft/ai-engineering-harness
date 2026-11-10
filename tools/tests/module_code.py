"""Load a module from its file with the compiled code shared in the test process (plan leaf F-09).

Not a test module. ``load(name, path)`` is ``importlib.util.spec_from_file_location`` followed by
``exec_module``, as the test modules did, and each call still returns a new module object with
its own namespace, executed afresh. Only the compilation of the source is done once per file
content: the tests run with ``-B`` and the checkout has no ``__pycache__``, so every load used
to compile the file again, and ``tools/guest.py`` (about 0.7 MB of source) takes about a third
of a second to compile on the verification host. A code object is immutable; executing it again
in a new namespace is what a second load does. The key is the file's path, size and
modification time, so a file that changes is compiled again.
"""
import importlib.machinery
import importlib.util
import os

_code = {}


class _SharedCodeLoader(importlib.machinery.SourceFileLoader):
    def get_code(self, fullname):
        path = self.get_filename(fullname)
        st = os.stat(path)
        key = (os.path.normcase(os.path.abspath(path)), st.st_size, st.st_mtime_ns)
        code = _code.get(key)
        if code is None:
            code = _code[key] = super().get_code(fullname)
        return code


def load(name, path):
    """A new module NAME executed from PATH (not entered in sys.modules)."""
    path = os.fspath(path)
    spec = importlib.util.spec_from_file_location(name, path, loader=_SharedCodeLoader(name, path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
