"""The launch census guard (plan leaf F-10.5; decision 0014 sections 1 and 8).

Every place in the tracked Python sources that launches a ``git`` process must be on the retained
list of decision 0014 section 1: R6 (the exchange verifier), H1 (the publication-safety gate), B1
(``verify_seed.py --baseline``), B2 (``check_prereqs.py --tier basic``) and T (the test fixtures and
the differential suite's git oracle). The guard passes only when the set of sites it finds equals
``ALLOWLIST``, so a new launch site fails it, and so does a retained site that disappears.

Method: the sources are parsed (``ast``), never executed and never searched as text. The tracked
``*.py`` files are those of the repository's index, read in process by the shared
repository-access module (no git launch); each is read from the working tree.

- A **launch** is a call of a standard-library launcher (``subprocess.run``, ``Popen``, ``call``,
  ``check_call``, ``check_output``, ``getoutput``, ``getstatusoutput``; ``os.system``, ``popen``,
  ``exec*``, ``spawn*``, ``posix_spawn*``, ``startfile``; ``asyncio.create_subprocess_*``;
  ``pty.spawn``), reached through ``import x``, ``import x as y``, ``from x import f [as g]``, a
  name bound to the launcher (``run = subprocess.run``) or a parameter defaulting to it
  (``run=subprocess.run``). A function whose launch takes its program from one of its own
  parameters is a **wrapper** (``run_tree``, ``check_prereqs.output``, a test's ``git(*args)``
  helper is not one: its program is fixed); a call of a wrapper is a launch too, found by the
  wrapper's name (a module-level function or class anywhere in the tree, or a method through
  ``self``), to a fixed point.
- The **program** of a launch is git when its argv's first element (a list or tuple literal, a
  ``+`` concatenation, ``list()``/``tuple()``, a comprehension over an argv, a starred argv), a
  shell string's first word, or ``executable=`` is a git program: the text ``git`` or a path whose
  last component is ``git`` or ``git.exe``, ``shutil.which('git')``, ``str()``/``Path()``/
  ``os.fspath()`` of one, a name or ``self`` attribute assigned one anywhere in its function, an
  enclosing function or the module, or a call of a function of the module that returns one.
- A **site** is the innermost function holding a git launch (``path``, ``qualified.name``); a
  launch at module level is the site ``<module>``.

What it cannot see, by construction: a launcher reached dynamically (``getattr``, a launcher kept
in a container or passed in from another module, ``functools.partial``, ``eval``/``exec``); a
program computed at run time (read from a file, a record or the environment, as the guest's QEMU
argv is, or assembled from pieces such as ``'g' + 'it'``); a wrapper reached by another name
(an alias of a function, an inherited method called through a subclass); a git launched by a
child process (a hook, an upstream CLI, Dulwich itself) or inside the guest (Python source held in
strings, run by ``ssh``); code outside tracked ``*.py`` files (shell hooks, the Taskfile,
untracked files). Two blind spots are deliberately conservative: a git argv passed to any
function named like a tree wrapper counts as a launch, and every assignment of a name counts,
whatever the control flow. Each site is a function, so a second git launch added inside an
allowlisted function is not a new site (the R6 verifier's verb set is asserted by
``test_guest``).

The same parsed trees serve a second guard, the no-window guard (the Owner's rule of 2026-11-11):
every launch in a non-test module under tools/, integrations/ and composition/ passes the shared
helper's flags (integrations/platform/no_window.py) or, at the long-lived background starts only,
CREATE_NO_WINDOW unconditionally, and none names DETACHED_PROCESS or CREATE_NEW_CONSOLE
(``WindowCensus``; its rules and blind spots are stated there, its exact lists are
``WINDOW_ALLOWLIST`` and ``UNCONDITIONAL``).
"""
from __future__ import annotations

import ast
import gc
import importlib.util
import re
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DECISION = REPO / 'decisions' / '0014-dulwich-adoption-scope-and-repository-access-contracts.md'

CATEGORY = 'unit'

# The retained git launch sites, each with its row of decision 0014 section 1 (R6, H1, B1, B2 or T)
# and what it launches. Keep it equal to what the census finds (TreeCensus).
ALLOWLIST = {
    # R6: the exchange verifier keeps git as the integrity authority of bundles pulled from the guest
    # (gaps G6, no strict or connectivity fsck, and G7, no bundle verify; section 7).
    ('tools/guest.py', 'run_git'): 'R6: init --bare, fetch, bundle verify, rev-parse and fsck --strict for '
                                   'verify_pulled_bundle (gaps G6, G7)',
    # H1: the publication-safety gate runs inside git as its hooks and reads what git hands it (gap G4).
    ('tools/publication_gate.py', 'git'): 'H1: the gate\'s reads of the index, refs, blobs and commits (gap G4)',
    # B1, B2: bootstrap ordering; the basic tier runs before any package is installed.
    ('tools/verify_seed.py', 'git_reader'): 'B1: cat-file --batch for verify_seed.py --baseline',
    ('tools/verify_seed.py', 'git_reader.git'): 'B1: rev-parse for verify_seed.py --baseline',
    ('tools/check_prereqs.py', 'basic'): 'B2: git --version and cat-file -t <seed revision>, the basic tier',
    # T: git-built fixtures and the git oracle, the independent oracle of the differential suite (by design).
    ('integrations/gitea/tests/test_authorization_live.py', 'git'): 'T: the live authorization suite, git as each '
                                                                     'bot (opt-in, e2e)',
    ('integrations/gitea/tests/test_gitea_host.py',
     'TestCheckoutFiles.test_the_listing_of_this_checkout_is_gits'): 'T: oracle of the R9 listing (ls-files)',
    ('integrations/gitea/tests/test_transport_live.py',
     'TestClone.test_a_module_clone_passes_git_fsck_strict'): 'T: oracle of a module clone (fsck --strict; opt-in)',
    ('integrations/lineage/tests/test_traversal_git.py', 'OneTraversal.check_against_the_git_oracle'):
        'T: oracle of the traversal',
    ('integrations/lineage/tests/test_traversal_git.py', 'git_oracle'): 'T: oracle of the traversal',
    ('integrations/planning/tests/test_git_batch.py', 'Equivalence._write_ambiguous_blobs'): 'T: fixture',
    ('integrations/planning/tests/test_git_batch.py', 'Equivalence.one_shot'): 'T: oracle of the one-shot reads',
    ('integrations/planning/tests/test_git_batch.py', 'Equivalence.plumbing'): 'T: fixture',
    ('integrations/planning/tests/test_git_batch.py', 'RealLauncher.start'): 'T: the run_tree launcher test through '
                                                                             "Git for Windows' cmd\\git.exe",
    ('integrations/planning/tests/test_planning_adapter.py', 'GoldenRepository.ask'): 'T: oracle',
    ('integrations/planning/tests/two_task_fixture.py', 'git'): 'T: the planning and lineage fixture builder',
    ('integrations/repository/tests/repository_corpus.py', 'Oracle.run'): 'T: the differential suite\'s git oracle',
    ('integrations/repository/tests/repository_corpus.py', 'git'): 'T: the corpus builder (--record)',
    ('integrations/repository/tests/test_repository_oracle.py', 'OracleAgreement.test_ceilings_are_gits'):
        'T: the git oracle',
    ('integrations/repository/tests/test_repository_oracle.py', 'OracleHostFiles.git'): 'T: the git oracle',
    ('integrations/repository/tests/test_repository_oracle.py', 'OracleTransport.git'): 'T: the git oracle',
    ('integrations/repository/tests/test_repository_oracle.py', 'setUpModule'): 'T: git --version, the oracle\'s '
                                                                               'presence probe',
    ('integrations/store/tests/test_backup_restore.py', 'git'): 'T: fixture',
    ('tools/tests/test_guest.py', 'Exchange.test_a_dulwich_written_bundle_passes_git_bundle_verify'):
        'T: oracle (bundle verify of a module-written bundle)',
    ('tools/tests/test_guest.py', 'Exchange.test_incremental_bundle_verifies_against_the_pushed_history'):
        'T: fixture',
    ('tools/tests/test_guest.py', 'Exchange.test_the_incremental_pull_launches_only_the_verifiers_verbs'):
        'T: fixture',
    ('tools/tests/test_guest.py', 'Refusals.test_dirty_profiles_refused.git'): 'T: fixture',
    ('tools/tests/test_guest.py', '_build_fixture_repo'): 'T: fixture',
    ('tools/tests/test_publication_gate.py', 'GateRepo.remote_ref'): 'T: the gate\'s throwaway repositories',
    ('tools/tests/test_publication_gate.py', 'GateRepo.run'): 'T: the gate\'s throwaway repositories (git runs '
                                                              'the hooks)',
    ('tools/tests/test_publication_gate.py', '_golden_repositories'): 'T: the gate\'s golden repositories',
    ('tools/tests/test_publication_gate.py', '_golden_repositories.git'): 'T: the gate\'s golden repositories',
    ('tools/tests/test_verify_seed.py', 'checkout_has_full_history'): 'T: probe for the B1 tests',
    ('tools/tests/test_verify_seed.py', 'git'): 'T: fixture for the B1 tests',
    ('tools/tests/test_verify_seed.py', 'git_available'): 'T: probe for the B1 tests',
}

# Standard-library launchers: module -> {function: how its program is given}. 'argv': an argv
# (list, or a string under shell=True) in the first positional or args=; 'shell': a command string;
# 'path0' / 'path1': the program path as positional 0 / 1.
STDLIB = {
    'subprocess': {**{name: 'argv' for name in ('run', 'Popen', 'call', 'check_call', 'check_output')},
                   'getoutput': 'shell', 'getstatusoutput': 'shell'},
    'os': {'system': 'shell', 'popen': 'shell', 'startfile': 'path0',
           **{name: 'path0' for name in ('execl', 'execle', 'execlp', 'execlpe', 'execv', 'execve', 'execvp',
                                         'execvpe', 'posix_spawn', 'posix_spawnp')},
           **{name: 'path1' for name in ('spawnl', 'spawnle', 'spawnlp', 'spawnlpe', 'spawnv', 'spawnve',
                                         'spawnvp', 'spawnvpe')}},
    'asyncio': {'create_subprocess_exec': 'path0', 'create_subprocess_shell': 'shell'},
    'pty': {'spawn': 'argv'},
}
LAUNCH_NAMES = {name for functions in STDLIB.values() for name in functions}
# Nodes that hold no call, binding or definition: the collector does not descend into them.
LEAVES = {ast.Constant, ast.Name, ast.Load, ast.Store, ast.Del, ast.Pass, ast.Break, ast.Continue,
          ast.Global, ast.Nonlocal, *ast.operator.__subclasses__(), *ast.unaryop.__subclasses__(),
          *ast.cmpop.__subclasses__(), *ast.boolop.__subclasses__()}
PATH_FUNCS = {'str', 'fspath', 'Path', 'PurePath', 'PurePosixPath', 'PureWindowsPath', 'abspath', 'realpath',
              'normpath', 'resolve', 'absolute'}
GIT_NAMES = ('git', 'git.exe')
JOIN_FUNCS = {'join', 'joinpath'}
SELF = ('self', 'cls')
MAX_DEPTH = 12


def git_text(text):
    """A program text naming git: 'git', 'git.exe', or a path ending in either."""
    return isinstance(text, str) and re.split(r'[\\/]', text.strip())[-1].lower() in GIT_NAMES


class Param:
    """A program taken from a parameter of the function being analysed (a wrapper's argv)."""

    def __init__(self, name):
        self.name = name


class Scope:
    def __init__(self, node, qualname, parent, module):
        self.node, self.qualname, self.parent, self.module = node, qualname, parent, module
        self.assigned = {}             # name -> [value expressions]
        self.params, self.defaults = [], {}
        self.launcher_alias = {}       # name -> (module, function)
        self.cls = None                # the class a method belongs to

    def lookup(self, name):
        scope = self
        while scope is not None:
            if name in scope.assigned or name in scope.params:
                return scope
            scope = scope.parent
        return None


class ModuleInfo:
    """One parsed source: its scopes, imports, launches and wrappers."""

    def __init__(self, path, tree):
        self.path, self.tree = path, tree
        self.modules = {}              # local name -> stdlib module name
        self.functions = {}            # local name -> (stdlib module, function)
        self.imported = set()          # names imported from other (non-stdlib) modules
        self.self_attrs = {}           # class name -> {attribute: [(scope, value)]} (self.X and cls.X)
        self.class_scopes = {}         # class name -> its Scope (class-body assignments)
        self.returns = {}              # function name (module level or method) -> [return values]
        self.scopes = []               # every Scope, module first
        self.calls = []                # (scope, ast.Call)
        self.local_defs = set()        # module-level function and class names
        self.memo = {}                 # program analysis results, (scope, expression, kind) ids
        self.stdlib = {}               # call id -> (label, result) of a standard-library launch, or None
        self.by_name = {}              # callee name (a name or an attribute) -> [(scope, call)]


class Collector(ast.NodeVisitor):
    _dispatch = {}

    def __init__(self, info):
        self.info = info
        self.scope = Scope(info.tree, '<module>', None, info)
        info.scopes.append(self.scope)
        self.classes = []

    def visit(self, node):
        if node.__class__ in LEAVES:
            return None
        method = self._dispatch.get(node.__class__)
        if method is None:
            method = getattr(Collector, 'visit_' + node.__class__.__name__, Collector.generic_visit)
            self._dispatch[node.__class__] = method
        return method(self, node)

    def generic_visit(self, node):
        for child in ast.iter_child_nodes(node):
            self.visit(child)

    # imports
    def visit_Import(self, node):
        for alias in node.names:
            top = alias.name.split('.')[0]
            if alias.name in STDLIB:
                self.info.modules[alias.asname or alias.name] = alias.name
            elif alias.asname is None and top in STDLIB:
                self.info.modules[top] = top
            else:
                self.info.imported.add(alias.asname or top)

    def visit_ImportFrom(self, node):
        for alias in node.names:
            local = alias.asname or alias.name
            if node.module in STDLIB and alias.name in STDLIB[node.module]:
                self.info.functions[local] = (node.module, alias.name)
            elif node.module == 'shutil' and alias.name == 'which':
                self.info.functions[local] = ('shutil', 'which')
            elif node.module == 'os' and alias.name == 'path':
                self.info.modules[local] = 'os.path'
            else:
                self.info.imported.add(local)

    # scopes
    def _function(self, node):
        if self.scope.node is self.info.tree:
            self.info.local_defs.add(node.name)
        qual = node.name if self.scope.qualname == '<module>' else f'{self.scope.qualname}.{node.name}'
        scope = Scope(node, qual, self.scope, self.info)
        scope.cls = self.classes[-1] if self.classes and self.scope.node is self.classes[-1][1] else None
        args = node.args
        positional = [*args.posonlyargs, *args.args]
        scope.params = [a.arg for a in [*positional, *args.kwonlyargs]]
        if args.vararg:
            scope.params.append(args.vararg.arg)
        if args.kwarg:
            scope.params.append(args.kwarg.arg)
        for arg, default in zip(positional[len(positional) - len(args.defaults):], args.defaults):
            scope.defaults[arg.arg] = default
        for arg, default in zip(args.kwonlyargs, args.kw_defaults):
            if default is not None:
                scope.defaults[arg.arg] = default
        self.info.scopes.append(scope)
        for default in [*args.defaults, *[d for d in args.kw_defaults if d is not None]]:
            self.visit(default)
        outer, self.scope = self.scope, scope
        for statement in node.body:
            self.visit(statement)
        self.scope = outer

    visit_FunctionDef = visit_AsyncFunctionDef = _function

    def visit_Lambda(self, node):
        self.visit(node.body)

    def visit_ClassDef(self, node):
        if self.scope.node is self.info.tree:
            self.info.local_defs.add(node.name)
        qual = node.name if self.scope.qualname == '<module>' else f'{self.scope.qualname}.{node.name}'
        scope = Scope(node, qual, self.scope, self.info)
        self.info.scopes.append(scope)
        self.info.class_scopes.setdefault(node.name, scope)
        for item in [*node.bases, *node.keywords, *node.decorator_list]:
            self.visit(item)
        outer, self.scope = self.scope, scope
        self.classes.append((node.name, node))
        for statement in node.body:
            self.visit(statement)
        self.classes.pop()
        self.scope = outer

    # bindings
    def _bind(self, target, value):
        if isinstance(target, ast.Name):
            self.scope.assigned.setdefault(target.id, []).append(value)
        elif isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and \
                target.value.id in SELF and self.classes:
            attrs = self.info.self_attrs.setdefault(self.classes[-1][0], {})
            attrs.setdefault(target.attr, []).append((self.scope, value))
        elif isinstance(target, (ast.Tuple, ast.List)):
            for element in target.elts:
                self._bind(element.value if isinstance(element, ast.Starred) else element, None)

    def visit_Assign(self, node):
        for target in node.targets:
            if isinstance(target, (ast.Tuple, ast.List)) and isinstance(node.value, (ast.Tuple, ast.List)) \
                    and len(target.elts) == len(node.value.elts):
                for t, v in zip(target.elts, node.value.elts):
                    self._bind(t, v)
            else:
                self._bind(target, node.value)
        self.generic_visit(node)

    def visit_AnnAssign(self, node):
        if node.value is not None:
            self._bind(node.target, node.value)
        self.generic_visit(node)

    def visit_AugAssign(self, node):
        self._bind(node.target, ast.BinOp(left=node.target, op=node.op, right=node.value))
        self.generic_visit(node)

    def visit_NamedExpr(self, node):
        self._bind(node.target, node.value)
        self.generic_visit(node)

    def visit_For(self, node):
        self._bind(node.target, None)
        self.generic_visit(node)

    visit_AsyncFor = visit_For

    def visit_With(self, node):
        for item in node.items:
            if item.optional_vars is not None:
                self._bind(item.optional_vars, None)
        self.generic_visit(node)

    visit_AsyncWith = visit_With

    def visit_Return(self, node):
        if node.value is not None and self.scope.node is not self.info.tree:
            name = self.scope.qualname.rsplit('.', 1)[-1]
            self.info.returns.setdefault(name, []).append((self.scope, node.value))
        self.generic_visit(node)

    def visit_Call(self, node):
        self.info.calls.append((self.scope, node))
        func = node.func
        name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else None
        if name is not None:
            self.info.by_name.setdefault(name, []).append((self.scope, node))
        self.generic_visit(node)


class Census:
    """The git launch sites of a set of sources: {relative path: text}."""

    def __init__(self, sources):
        self.infos = {}
        self.errors = {}
        self.wrappers = {}            # name -> (position or None, name) of the argv parameter
        self.methods = {}             # (path, class, method) -> the same
        # The cyclic collector would scan the growing trees again and again while they are built
        # (about 0.4 s of the 1.1 s parse on the verification host); nothing here needs it early.
        enabled = gc.isenabled()
        gc.disable()
        try:
            for path in sorted(sources):
                info = parsed(path, sources[path])
                if isinstance(info, str):
                    self.errors[path] = info
                else:
                    self.infos[path] = info
            self._find_wrappers()
            self.sites = self._sites()
        finally:
            if enabled:
                gc.enable()

    # launcher resolution
    def stdlib_launcher(self, scope, func):
        """(module, function) when FUNC calls a standard-library launcher."""
        info = scope.module
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            module = info.modules.get(func.value.id)
            if module in STDLIB and func.attr in STDLIB[module] and scope.lookup(func.value.id) is None:
                return module, func.attr
        if isinstance(func, ast.Name):
            owner = scope.lookup(func.id)
            if owner is None and func.id in info.functions and info.functions[func.id][0] in STDLIB:
                return info.functions[func.id]
            if owner is not None:
                values = list(owner.assigned.get(func.id, []))
                if func.id in owner.defaults:
                    values.append(owner.defaults[func.id])
                for value in values:
                    if value is not None and value is not func:
                        found = self.stdlib_launcher(owner, value) if isinstance(value, (ast.Attribute, ast.Name)) \
                            else None
                        if found:
                            return found
        return None

    def wrapper_param(self, scope, func):
        """The argv parameter (index or name) when FUNC calls a wrapper of the tree."""
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id in SELF:
            cls = self._class_of(scope)
            if cls is not None:
                return self.methods.get((scope.module.path, cls, func.attr))
            return None
        name = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else None
        if name is None:
            return None
        if isinstance(func, ast.Name) and scope.lookup(name) is not None:
            return None
        return self.wrappers.get(name)

    @staticmethod
    def _class_of(scope):
        while scope is not None:
            if scope.cls is not None:
                return scope.cls[0]
            scope = scope.parent
        return None

    @staticmethod
    def call_argument(call, how, param=None):
        """The expression giving a launch's program, and whether it is an argv or a program path."""
        if how in ('argv', 'shell'):
            for keyword in call.keywords:
                if keyword.arg == 'args':
                    return keyword.value, 'argv'
            return (call.args[0], 'argv') if call.args else (None, None)
        if how in ('path0', 'path1'):
            index = 0 if how == 'path0' else 1
            return (call.args[index], 'path') if len(call.args) > index else (None, None)
        # a tree wrapper: param is (position or None, name) of its argv parameter
        index, name = param
        starred = any(isinstance(a, ast.Starred) for a in call.args[:(index or 0) + 1])
        if index is not None and len(call.args) > index and not starred:
            return call.args[index], 'argv'
        for keyword in call.keywords:
            if keyword.arg == name:
                return keyword.value, 'argv'
        return None, None

    # program analysis
    def program(self, scope, expr, kind, depth=0):
        """True when EXPR (an argv or a program path) names git, a Param when it comes from a
        parameter of SCOPE's function, else False."""
        if expr is None or depth > MAX_DEPTH:
            return False
        memo, key = scope.module.memo, (id(scope), id(expr), kind)
        if key not in memo:
            memo[key] = False              # a cycle (a name assigned from itself) answers False
            memo[key] = self._argv(scope, expr, depth) if kind == 'argv' else self._scalar(scope, expr, depth)
        return memo[key]

    def _first(self, results):
        for result in results:
            if result is True:
                return True
        for result in results:
            if isinstance(result, Param):
                return result
        return False

    def _name(self, scope, name, kind, depth):
        owner = scope.lookup(name)
        if owner is None:
            owner = scope.module.scopes[0] if name in scope.module.scopes[0].assigned else None
        if owner is None:
            return False
        if name in owner.params and owner.node is not scope.module.tree:
            reassigned = owner.assigned.get(name, [])
            results = [self.program(owner, v, kind, depth + 1) for v in reassigned if v is not None]
            if name in owner.defaults:
                results.append(self.program(owner, owner.defaults[name], kind, depth + 1))
            found = self._first(results)
            return True if found is True else Param(name) if owner is scope or self._encloses(owner, scope) \
                else found
        return self._first([self.program(owner, v, kind, depth + 1) for v in owner.assigned.get(name, [])
                            if v is not None])

    @staticmethod
    def _encloses(outer, inner):
        while inner is not None:
            if inner is outer:
                return True
            inner = inner.parent
        return False

    def _self_attr(self, scope, attr, kind, depth):
        """self.X or cls.X: every value assigned to it in the class's methods, or in the class body."""
        cls = self._class_of(scope)
        if cls is None:
            return False
        values = list(scope.module.self_attrs.get(cls, {}).get(attr, []))
        body = scope.module.class_scopes.get(cls)
        if body is not None:
            values += [(body, v) for v in body.assigned.get(attr, [])]
        return self._first([self.program(owner, v, kind, depth + 1) for owner, v in values if v is not None])

    def _returns(self, scope, name, kind, depth):
        results = []
        for owner, value in scope.module.returns.get(name, []):
            results.append(self.program(owner, value, kind, depth + 1))
        return True if self._first(results) is True else False

    def _argv(self, scope, expr, depth):
        if isinstance(expr, (ast.List, ast.Tuple)):
            if not expr.elts:
                return False
            first = expr.elts[0]
            if isinstance(first, ast.Starred):
                return self.program(scope, first.value, 'argv', depth + 1)
            return self.program(scope, first, 'path', depth + 1)
        if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Add):
            if isinstance(expr.left, (ast.List, ast.Tuple)) and not expr.left.elts:
                return self.program(scope, expr.right, 'argv', depth + 1)
            return self.program(scope, expr.left, 'argv', depth + 1)
        if isinstance(expr, (ast.ListComp, ast.GeneratorExp)):
            return self.program(scope, expr.generators[0].iter, 'argv', depth + 1)
        if isinstance(expr, ast.Starred):
            return self.program(scope, expr.value, 'argv', depth + 1)
        if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
            words = expr.value.split()
            return bool(words) and git_text(words[0])
        if isinstance(expr, ast.JoinedStr):
            head = expr.values[0] if expr.values else None
            if isinstance(head, ast.Constant) and isinstance(head.value, str) and head.value.split():
                words = head.value.split()
                return git_text(words[0]) and (len(words) > 1 or head.value[len(head.value.rstrip()):] != '')
            return False
        if isinstance(expr, ast.Name):
            return self._name(scope, expr.id, 'argv', depth)
        if isinstance(expr, ast.Attribute) and isinstance(expr.value, ast.Name) and expr.value.id in SELF:
            return self._self_attr(scope, expr.attr, 'argv', depth)
        if isinstance(expr, ast.Call):
            func = expr.func
            if isinstance(func, ast.Name) and func.id in ('list', 'tuple') and expr.args:
                return self.program(scope, expr.args[0], 'argv', depth + 1)
            name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) \
                and isinstance(func.value, ast.Name) and func.value.id in SELF else None
            if name is not None:
                return self._returns(scope, name, 'argv', depth)
        if isinstance(expr, ast.IfExp):
            return self._first([self.program(scope, expr.body, 'argv', depth + 1),
                                self.program(scope, expr.orelse, 'argv', depth + 1)])
        if isinstance(expr, ast.BoolOp):
            return self._first([self.program(scope, v, 'argv', depth + 1) for v in expr.values])
        return False

    def _scalar(self, scope, expr, depth):
        if isinstance(expr, ast.Constant):
            return git_text(expr.value)
        if isinstance(expr, ast.Name):
            return self._name(scope, expr.id, 'path', depth)
        if isinstance(expr, ast.Attribute) and isinstance(expr.value, ast.Name) and expr.value.id in SELF:
            return self._self_attr(scope, expr.attr, 'path', depth)
        if isinstance(expr, ast.Call):
            func = expr.func
            name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else None
            info = scope.module
            which = (isinstance(func, ast.Name) and info.functions.get(func.id) == ('shutil', 'which')) or \
                (isinstance(func, ast.Attribute) and func.attr == 'which' and isinstance(func.value, ast.Name)
                 and func.value.id == 'shutil')
            if which:
                return bool(expr.args) and self._scalar(scope, expr.args[0], depth + 1) is True
            if name in PATH_FUNCS:
                target = expr.args[0] if expr.args else func.value if isinstance(func, ast.Attribute) else None
                return self.program(scope, target, 'path', depth + 1) if target is not None else False
            if name in JOIN_FUNCS and expr.args:
                return self.program(scope, expr.args[-1], 'path', depth + 1)
            if isinstance(func, ast.Name) or (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)
                                              and func.value.id in SELF):
                return self._returns(scope, name, 'path', depth)
        if isinstance(expr, ast.BinOp) and isinstance(expr.op, (ast.Div, ast.Add)):
            return self.program(scope, expr.right, 'path', depth + 1)   # a path's last component
        if isinstance(expr, ast.IfExp):
            return self._first([self.program(scope, expr.body, 'path', depth + 1),
                                self.program(scope, expr.orelse, 'path', depth + 1)])
        if isinstance(expr, ast.BoolOp):
            return self._first([self.program(scope, v, 'path', depth + 1) for v in expr.values])
        return False

    # wrappers and sites
    def launch(self, scope, call):
        """(launcher label, program result) of CALL, or None when it is not a launch."""
        known = scope.module.stdlib
        if id(call) not in known:
            known[id(call)] = None
            found = self.stdlib_launcher(scope, call.func)
            if found is not None:
                module, function = found
                expr, kind = self.call_argument(call, STDLIB[module][function])
                result = self.program(scope, expr, kind)
                for keyword in call.keywords:
                    if keyword.arg == 'executable':
                        result = self._first([result, self.program(scope, keyword.value, 'path')])
                known[id(call)] = (f'{module}.{function}', result)
        if known[id(call)] is not None:
            return known[id(call)]
        param = self.wrapper_param(scope, call.func)
        if param is not None:
            expr, kind = self.call_argument(call, 'wrapper', param)
            label = ast.unparse(call.func)
            return label, self.program(scope, expr, kind)
        return None

    @staticmethod
    def _param_ref(scope, param):
        """(position for positional calls or None, name) of the parameter, as a wrapper records it."""
        node = scope.node
        positional = [a.arg for a in [*node.args.posonlyargs, *node.args.args]]
        if param.name not in positional:
            return None, param.name
        index = positional.index(param.name)
        if scope.cls is not None and positional[0] in ('self', 'cls'):
            index -= 1
        return index, param.name

    def _calls_named(self, names):
        """Every (module, scope, call) whose callee is named one of NAMES (a name or an attribute)."""
        for info in self.infos.values():
            for name in names:
                for scope, call in info.by_name.get(name, ()):
                    yield info, scope, call

    def _register(self, info, scope, param):
        """Record the function of SCOPE as a wrapper; the names its callers use, when new."""
        ref = self._param_ref(scope, param)
        name, new = scope.node.name, []
        if scope.cls is not None:
            key = (info.path, scope.cls[0], name)
            if key not in self.methods:
                self.methods[key] = ref
                new.append(name)
            if name == '__init__' and scope.cls[0] not in self.wrappers:
                self.wrappers[scope.cls[0]] = ref
                new.append(scope.cls[0])
        elif scope.parent is not None and scope.parent.node is info.tree and name not in self.wrappers:
            self.wrappers[name] = ref
            new.append(name)
        return new

    def _bound_calls(self):
        """Calls of a name bound in the caller's scopes (an alias or a parameter of a launcher)."""
        for info in self.infos.values():
            for scope, call in info.calls:
                if isinstance(call.func, ast.Name) and call.func.id not in LAUNCH_NAMES and \
                        scope.lookup(call.func.id) is not None:
                    yield info, scope, call

    def _find_wrappers(self):
        """A worklist: the launchers' calls first, then the calls of each newly found wrapper's name."""
        work = list(self._calls_named(LAUNCH_NAMES | {n for i in self.infos.values() for n in i.functions})) + \
            list(self._bound_calls())
        while work:
            names = []
            for info, scope, call in work:
                if scope.node is info.tree or isinstance(scope.node, ast.ClassDef):
                    continue
                found = self.launch(scope, call)
                if found is not None and isinstance(found[1], Param):
                    names += self._register(info, scope, found[1])
            work = list(self._calls_named(set(names)))

    def _sites(self):
        names = LAUNCH_NAMES | set(self.wrappers) | {key[2] for key in self.methods} | \
            {n for i in self.infos.values() for n in i.functions}
        sites, seen = {}, set()
        for info, scope, call in [*self._calls_named(names), *self._bound_calls()]:
            if id(call) in seen:
                continue
            seen.add(id(call))
            found = self.launch(scope, call)
            if found is not None and found[1] is True:
                sites.setdefault((info.path, scope.qualname), []).append((call.lineno, found[0]))
        for launches in sites.values():
            launches.sort()
        return sites


_PARSED = {}


def parsed(path, text):
    """The analysed module of PATH with TEXT (kept: an unchanged source is parsed once per process), or
    the syntax error's description."""
    key = (path, text)
    if key not in _PARSED:
        try:
            tree = ast.parse(text, filename=path)
        except SyntaxError as exc:
            _PARSED[key] = f'{exc.msg} (line {exc.lineno})'
        else:
            info = ModuleInfo(path, tree)
            Collector(info).visit(tree)
            _PARSED[key] = info
    return _PARSED[key]


def compare(found, allowlist):
    """(unexpected, missing): sites found but not allowlisted, and allowlisted but not found."""
    return sorted(set(found) - set(allowlist)), sorted(set(allowlist) - set(found))


def describe(sites, keys):
    return '\n'.join(f'  {path}:{name} (line {", ".join(str(line) for line, _ in sites.get((path, name), []))}; '
                     f'via {", ".join(sorted({via for _, via in sites.get((path, name), [])}))})'
                     for path, name in keys)


def repository_access():
    module = sys.modules.get('repository_access')
    if module is None:
        spec = importlib.util.spec_from_file_location(
            'repository_access', REPO / 'integrations' / 'repository' / 'repository_access.py')
        module = importlib.util.module_from_spec(spec)
        sys.modules['repository_access'] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            del sys.modules['repository_access']
            raise
    return module


def tracked_python():
    """{path: text} of every tracked *.py file (the index, read in process), from the working tree."""
    ra = repository_access()
    with ra.open_repository(REPO, config='repository', work_tree=True, ceilings=[str(REPO.parent)]) as repo:
        paths = sorted({e.path for e in repo.index_entries() if e.path.endswith('.py')})
    sources = {}
    for path in paths:
        file = REPO / path
        if file.is_file():
            sources[path] = file.read_bytes().decode('utf-8')
    return sources


def guard_failures(sites, errors, allowlist=None):
    """The guard's verdict on a census: the messages that fail it, none when it passes."""
    allowlist = ALLOWLIST if allowlist is None else allowlist
    unexpected, missing = compare(sites, allowlist)
    message = []
    if errors:
        message.append('tracked Python sources that do not parse (the census cannot read them):\n'
                       + '\n'.join(f'  {path}: {why}' for path, why in sorted(errors.items())))
    if unexpected:
        message.append('git launch sites outside the retained list of decision 0014 section 1 (migrate '
                       'them to integrations/repository, or record a documented gap first):\n'
                       + describe(sites, unexpected))
    if missing:
        message.append('allowlisted sites the census no longer finds (remove them from ALLOWLIST):\n'
                       + describe(sites, missing))
    return message


def release():
    """Drop the parsed trees, breaking the scope cycles first, so that they are freed at once rather
    than left for the cyclic collector to scan during later tests."""
    for info in _PARSED.values():
        if isinstance(info, ModuleInfo):
            for container in (info.scopes, info.calls, info.returns, info.self_attrs, info.class_scopes,
                              info.memo, info.stdlib, info.by_name):
                container.clear()
    _PARSED.clear()


# ---------------------------------------------------------------- the no-window guard
#
# The Owner's rule of 2026-11-11: no process the harness starts ever opens a visible console window,
# and none is started with DETACHED_PROCESS (under which each console child opens a window of its own,
# and CREATE_NO_WINDOW is ignored) or CREATE_NEW_CONSOLE. The shared helper
# integrations/platform/no_window.py gives CREATE_NO_WINDOW only where the starting process has no
# console (a child of a process attached to a console shares it and opens no window; the flag costs a
# console host per launch). The guard reads the non-test modules under tools/, integrations/ and
# composition/ from the census's parsed trees:
#
# - every launch (a standard-library launcher reached as the census resolves it, a parameter that
#   receives a launcher from a call in the same module, or a ``self`` attribute assigned one) passes
#   ``creationflags=`` an expression that carries either the helper's value (a call
#   ``….no_window_flags()``) or the unconditional flag (the module's ``NO_WINDOW``,
#   ``getattr(subprocess, 'CREATE_NO_WINDOW', 0)`` or ``subprocess.CREATE_NO_WINDOW``): either alone,
#   in a ``|``, in either branch of a conditional expression, or through a name every assignment of
#   which carries it;
# - the unconditional flag is used exactly at the long-lived background starts of ``UNCONDITIONAL``,
#   whose window state must never depend on their parent; every other launch uses the helper;
# - ``no_window_flags`` is defined only by the helper; ``NO_WINDOW`` is bound only at module level, and
#   only to ``getattr(subprocess, 'CREATE_NO_WINDOW', 0)`` (0 off Windows: POSIX launches unchanged);
# - no name, attribute or string names DETACHED_PROCESS or CREATE_NEW_CONSOLE.
#
# Blind spots, by construction: a launcher passed in from another module is checked where it is
# called only when the receiving parameter defaults to a launcher (the repository's
# ``run=subprocess.run`` form); ``**kwargs`` carrying creationflags is not followed (the launch
# fails); guest-side Python held in strings is not parsed (it runs in a Linux guest). The allowlist
# and ``UNCONDITIONAL`` are exact, as the census's allowlist is: an entry that no longer applies fails.

WINDOW_ROOTS = ('tools/', 'integrations/', 'composition/')
HELPER = 'integrations/platform/no_window.py'
WINDOW_ALLOWLIST = {
    ('tools/guest.py', 'exec_command'): "the operator's interactive passthrough (Overseer ruling, 2026-11-11): ssh "
                                        "shares the operator's console and opens no window of its own; with "
                                        'CREATE_NO_WINDOW it would get a console of its own and could not reach the '
                                        "operator's (its output and input are lost, probed 2026-11-11)",
    ('tools/guest_drill.py', 'run'): 'guest-side: the drill guest\'s root helper, copied byte for byte into a '
                                     'Linux guest and run there only; Windows creation flags do not exist there',
    ('tools/verify_seed.py', 'git_reader'): 'integrity-tracked (SEED_MANIFEST.json): changed only by the '
                                            'Owner\'s documented process; open finding for the Owner',
    ('tools/verify_seed.py', 'git_reader.git'): 'integrity-tracked (SEED_MANIFEST.json): changed only by the '
                                                'Owner\'s documented process; open finding for the Owner',
}
UNCONDITIONAL = {
    ('tools/guest.py', 'launch'): 'QEMU, in its own process group; it outlives its caller',
    ('tools/guest.py', 'forward_spawn'): 'the inference forward holder, in its own process group',
    ('integrations/platform/platform_windows.py', 'WindowsAdapter.launch_supervisor'): 'the Gitea supervisor, '
                                                                                         'broken away from the caller',
    ('integrations/gitea/gitea_host.py', 'supervise'): 'Gitea itself, for as long as its supervisor runs',
}
WINDOW_OPENERS = ('DETACHED_PROCESS', 'CREATE_NEW_CONSOLE')
OPENER_TEXT = re.compile(r'\b(?:DETACHED_PROCESS|CREATE_NEW_CONSOLE)\b')
NO_WINDOW_FORM = ast.dump(ast.parse("getattr(subprocess, 'CREATE_NO_WINDOW', 0)", mode='eval').body)
HELPER_CALL, CONSTANT = 'helper', 'constant'


def window_scanned(path):
    """A non-test module under tools/, integrations/ or composition/: any module outside a tests/
    directory, whatever its name (tools/test_profile.py is a tool, not a test)."""
    parts = path.split('/')
    return path.startswith(WINDOW_ROOTS) and 'tests' not in parts[:-1]


def _kind(kinds):
    """The combined kind of the parts of a flags expression: the constant when any part is it (the start is
    then unconditional), else the helper when any part is it, else None (the flag is not carried)."""
    return CONSTANT if CONSTANT in kinds else HELPER_CALL if HELPER_CALL in kinds else None


class WindowCensus:
    """The launches of the scanned modules: ``findings`` is {(path, site): [(line, problem)]} for launches
    that carry neither the helper's value nor the flag, ``unconditional`` {(path, site): [line]} for those
    that carry the flag unconditionally, ``problems`` [(path, line, problem)] for what no allowlist admits
    (a window-opening flag, a ``NO_WINDOW`` bound to anything else, a ``no_window_flags`` of another
    module)."""

    def __init__(self, census, sources):
        self.census, self.sources = census, sources
        self.infos = {path: info for path, info in census.infos.items() if window_scanned(path)}
        self.marked = set()                # (id(function node), parameter): receives a launcher
        self.findings, self.unconditional, self.problems = {}, {}, []
        self.functions, self.methods = {}, {}  # path -> {name: scope}, path -> {(class, name): scope}
        for path, info in self.infos.items():
            self._index(path, info)
        self._propagate()
        for path, info in sorted(self.infos.items()):
            self._module(path, info)

    def _index(self, path, info):
        functions, methods = self.functions.setdefault(path, {}), self.methods.setdefault(path, {})
        for scope in info.scopes:
            if not isinstance(scope.node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if scope.node.name == 'no_window_flags' and path != HELPER:
                self.problems.append((path, scope.node.lineno, f'no_window_flags defined outside {HELPER}'))
            if scope.cls is not None:
                methods[(scope.cls[0], scope.node.name)] = scope
            elif scope.parent is not None and scope.parent.node is info.tree:
                functions[scope.node.name] = scope

    def launcher(self, scope, expr, depth=0):
        """True when EXPR (a callee or an argument) is a launcher."""
        if depth > MAX_DEPTH or not isinstance(expr, (ast.Name, ast.Attribute)):
            return False
        if self.census.stdlib_launcher(scope, expr):
            return True
        if isinstance(expr, ast.Name):
            owner = scope.lookup(expr.id)
            return owner is not None and (id(owner.node), expr.id) in self.marked
        if isinstance(expr.value, ast.Name) and expr.value.id in SELF:
            cls = Census._class_of(scope)
            values = scope.module.self_attrs.get(cls, {}).get(expr.attr, []) if cls else []
            return any(v is not None and self.launcher(owner, v, depth + 1) for owner, v in values)
        return False

    def _callee(self, scope, func):
        """The scope of a function of the same module that FUNC calls, and whether it is a method."""
        path = scope.module.path
        if isinstance(func, ast.Name) and scope.lookup(func.id) is None:
            return self.functions[path].get(func.id), False
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id in SELF:
            cls = Census._class_of(scope)
            return self.methods[path].get((cls, func.attr)), True
        return None, False

    def _propagate(self):
        """Mark the parameters that receive a launcher, to a fixed point."""
        passed = []                        # (caller's scope, (id(function node), parameter), argument)
        for info in self.infos.values():
            for scope, call in info.calls:
                target, method = self._callee(scope, call.func)
                if target is None:
                    continue
                args = target.node.args
                positional = [a.arg for a in [*args.posonlyargs, *args.args]][1 if method else 0:]
                pairs = []
                for index, arg in enumerate(call.args):
                    if isinstance(arg, ast.Starred):
                        break
                    if index < len(positional):
                        pairs.append((positional[index], arg))
                pairs += [(k.arg, k.value) for k in call.keywords if k.arg in target.params]
                passed += [(scope, (id(target.node), name), arg) for name, arg in pairs
                           if isinstance(arg, (ast.Name, ast.Attribute))]
        changed = True
        while changed:
            changed = False
            for scope, key, arg in passed:
                if key not in self.marked and self.launcher(scope, arg):
                    self.marked.add(key)
                    changed = True

    def carries(self, scope, expr, depth=0):
        """What EXPR, a creationflags value, carries: HELPER_CALL, CONSTANT or None."""
        if depth > MAX_DEPTH:
            return None
        info = scope.module
        if isinstance(expr, ast.Name):
            owner = scope.lookup(expr.id)
            if owner is None:
                return None
            values = owner.assigned.get(expr.id, [])   # a parameter's own value is unknown: never carries
            if expr.id == 'NO_WINDOW':
                return CONSTANT if owner.node is info.tree and values and \
                    all(v is not None and ast.dump(v) == NO_WINDOW_FORM for v in values) else None
            kinds = [self.carries(owner, v, depth + 1) if v is not None else None for v in values]
            return _kind(kinds) if kinds and None not in kinds else None
        if isinstance(expr, ast.Attribute):
            return CONSTANT if expr.attr == 'CREATE_NO_WINDOW' and isinstance(expr.value, ast.Name) and \
                info.modules.get(expr.value.id) == 'subprocess' and scope.lookup(expr.value.id) is None else None
        if isinstance(expr, ast.Call):
            if isinstance(expr.func, ast.Attribute) and expr.func.attr == 'no_window_flags' and not expr.args \
                    and not expr.keywords:
                return HELPER_CALL
            return CONSTANT if ast.dump(expr) == NO_WINDOW_FORM and scope.lookup('subprocess') is None and \
                info.modules.get('subprocess') == 'subprocess' else None
        if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.BitOr):
            return _kind([self.carries(scope, expr.left, depth + 1), self.carries(scope, expr.right, depth + 1)])
        if isinstance(expr, ast.IfExp):
            return _kind([self.carries(scope, expr.body, depth + 1), self.carries(scope, expr.orelse, depth + 1)])
        return None

    def _module(self, path, info):
        for scope, call in info.calls:
            found = self.census.stdlib_launcher(scope, call.func)
            if found is not None:
                via = '.'.join(found)
            elif self.launcher(scope, call.func):
                via = ast.unparse(call.func)
            else:
                continue
            flags = [k.value for k in call.keywords if k.arg == 'creationflags']
            kind = self.carries(scope, flags[0]) if flags else None
            if kind == CONSTANT:
                self.unconditional.setdefault((path, scope.qualname), []).append(call.lineno)
                continue
            if kind == HELPER_CALL:
                continue
            problem = f'no creationflags (via {via})' if not flags else \
                f'creationflags with neither no_window_flags() nor CREATE_NO_WINDOW (via {via})'
            self.findings.setdefault((path, scope.qualname), []).append((call.lineno, problem))
        for scope in info.scopes:
            if 'NO_WINDOW' in scope.assigned:
                if scope.node is not info.tree:
                    self.problems.append((path, scope.node.lineno, f'NO_WINDOW bound in {scope.qualname}'))
                elif any(v is None or ast.dump(v) != NO_WINDOW_FORM for v in scope.assigned['NO_WINDOW']):
                    self.problems.append((path, 1, "NO_WINDOW bound to something other than "
                                                   "getattr(subprocess, 'CREATE_NO_WINDOW', 0)"))
        # Only the top-level statements holding a line that names a window-opening flag are walked.
        text = self.sources[path]
        lines = {text.count('\n', 0, m.start()) + 1 for m in OPENER_TEXT.finditer(text)}
        for statement in info.tree.body if lines else ():
            if not any(statement.lineno <= line <= statement.end_lineno for line in lines):
                continue
            for node in ast.walk(statement):
                name = node.attr if isinstance(node, ast.Attribute) else node.id if isinstance(node, ast.Name) \
                    else node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None
                if name in WINDOW_OPENERS:
                    self.problems.append((path, node.lineno, f'{name} (opens a console window)'))


def window_failures(window, allowlist=None, unconditional=None):
    """The no-window guard's verdict: the messages that fail it, none when it passes."""
    allowlist = WINDOW_ALLOWLIST if allowlist is None else allowlist
    unconditional = UNCONDITIONAL if unconditional is None else unconditional
    unexpected, missing = compare(window.findings, allowlist)
    message = []
    if unexpected:
        message.append('launches that may open a console window (pass creationflags=_no_window().no_window_flags(), '
                       f'the helper of {HELPER}):\n'
                       + '\n'.join(f'  {path}:{name} ' + '; '.join(f'line {line}: {problem}'
                                                                     for line, problem in window.findings[(path, name)])
                                   for path, name in unexpected))
    if missing:
        message.append('allowlisted sites the no-window guard no longer finds (remove them from '
                       'WINDOW_ALLOWLIST):\n' + '\n'.join(f'  {path}:{name}' for path, name in missing))
    extra, gone = compare(window.unconditional, unconditional)
    if extra:
        message.append('unconditional CREATE_NO_WINDOW outside the long-lived background starts (use the helper, '
                       'or add the start to UNCONDITIONAL with its reason):\n'
                       + '\n'.join(f'  {path}:{name} (line {", ".join(map(str, window.unconditional[(path, name)]))})'
                                   for path, name in extra))
    if gone:
        message.append('UNCONDITIONAL starts the guard no longer finds (remove them from UNCONDITIONAL):\n'
                       + '\n'.join(f'  {path}:{name}' for path, name in gone))
    if window.problems:
        message.append('window-opening flags, a NO_WINDOW of another value or a no_window_flags of another module:\n'
                       + '\n'.join(f'  {path} line {line}: {problem}' for path, line, problem in window.problems))
    return message


INJECTED = '''

def injected_status(path):
    return subprocess.run(['git', '-C', str(path), 'status'], capture_output=True)
'''
INJECTED_LINE = 4   # the subprocess.run line, counted from the end of the source it is appended to
ADAPTER = 'integrations/planning/planning_adapter.py'
NEWCOMER = 'integrations/newcomer/newcomer.py'
GATE = 'tools/publication_gate.py'
PLATFORM = 'integrations/platform/platform_windows.py'
NO_WINDOW_SUPERVISOR = 'base = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP'
PREREQS = 'tools/check_prereqs.py'
HELPER_FLAGS = 'creationflags=_no_window().no_window_flags())'


def injected(sources):
    """The tracked sources, copied, with a git launch injected into a module that is not
    allowlisted, a new module launching git, and the gate's retained site removed. For the no-window
    guard, the injected launches carry no creationflags, the Gitea supervisor's start is put back
    to DETACHED_PROCESS (the defect of 2026-11-11), and a short launch (check_prereqs.output) takes the
    unconditional flag instead of the helper's."""
    sources = dict(sources)
    sources[ADAPTER] = sources[ADAPTER] + INJECTED
    sources[NEWCOMER] = 'import subprocess\n' + INJECTED
    sources[GATE] = sources[GATE].replace("['git', *args]", "['true', *args]")
    sources[PLATFORM] = sources[PLATFORM].replace(NO_WINDOW_SUPERVISOR, NO_WINDOW_SUPERVISOR.replace(
        'CREATE_NO_WINDOW', 'DETACHED_PROCESS'))
    sources[PREREQS] = sources[PREREQS].replace(HELPER_FLAGS, 'creationflags=subprocess.CREATE_NO_WINDOW)')
    return sources


class TreeCensus(unittest.TestCase):
    """The tracked sources launch git only at the retained sites of decision 0014 section 1, and the
    guard fails on an injected launch (the tracked sources, copied in memory, with an injected
    subprocess.run(['git', ...]): no product file is edited). Both censuses are made once, and the
    no-window guard reads both."""
    category = 'contract'

    @classmethod
    def setUpClass(cls):
        cls.sources = tracked_python()
        enabled = gc.isenabled()
        gc.disable()                                   # see Census: the trees hold no cycle to collect
        try:
            census = Census(cls.sources)
            cls.sites, cls.errors = census.sites, census.errors
            cls.failures = guard_failures(census.sites, census.errors)
            window = WindowCensus(census, cls.sources)
            cls.window = (window.findings, window.unconditional, window.problems, window_failures(window))
            cls.injected_sources = injected(cls.sources)
            census = Census(cls.injected_sources)
            cls.injected_sites = census.sites
            cls.injected_failures = guard_failures(census.sites, census.errors)
            window = WindowCensus(census, cls.injected_sources)
            cls.injected_window = (window.findings, window.unconditional, window.problems, window_failures(window))
            del census, window
        finally:
            release()
            if enabled:
                gc.enable()

    def test_every_git_launch_site_is_retained_and_every_retained_site_exists(self):
        self.assertFalse(self.failures, '\n'.join(self.failures))

    def test_the_census_reads_the_tracked_sources(self):
        expected = {'tools/guest.py', 'tools/publication_gate.py', 'tools/verify_seed.py', 'tools/check_prereqs.py',
                    'integrations/repository/repository_access.py', ADAPTER}
        self.assertEqual(expected - set(self.sources), set())
        self.assertGreater(len(self.sources), 80)
        self.assertFalse(any(p.startswith(('evidence/', 'decisions/')) for p in self.sources))
        self.assertEqual(self.errors, {})

    def test_each_allowlisted_site_names_a_retained_row_of_decision_0014(self):
        retained = retained_rows()
        self.assertEqual(sorted(retained), ['B1', 'B2', 'H1', 'R6', 'T'])
        for (path, name), label in ALLOWLIST.items():
            with self.subTest(site=f'{path}:{name}'):
                row = label.split(':', 1)[0]
                self.assertIn(row, retained, label)
                is_test = '/tests/' in f'/{path}'
                self.assertEqual(row == 'T', is_test, 'T is the test fixtures; product sites have their row')

    def test_the_guard_fails_on_an_injected_launch_and_on_a_removed_site(self):
        self.assertNotIn(ADAPTER, {p for p, _ in ALLOWLIST})
        self.assertIn('\nimport subprocess\n', self.sources[ADAPTER])
        self.assertEqual(self.sources[GATE].count("['git', *args]"), 1)
        self.assertEqual(compare(self.injected_sites, ALLOWLIST),
                         ([(NEWCOMER, 'injected_status'), (ADAPTER, 'injected_status')], [(GATE, 'git')]))
        line = INJECTED_LINE + self.sources[ADAPTER].count('\n')
        self.assertEqual(self.injected_sites[(ADAPTER, 'injected_status')], [(line, 'subprocess.run')])
        # The guard's verdict on these sources fails, and names each site.
        message = '\n'.join(self.injected_failures)
        self.assertEqual(len(self.injected_failures), 2, message)
        for site in (f'{ADAPTER}:injected_status (line {line}; via subprocess.run)',
                     f'{NEWCOMER}:injected_status', f'{GATE}:git'):
            self.assertIn(site, message)


    def test_every_launch_outside_the_tests_opens_no_window(self):
        findings, unconditional, problems, failures = self.window
        self.assertFalse(failures, '\n'.join(failures))
        self.assertEqual((sorted(findings), sorted(unconditional), problems),
                         (sorted(WINDOW_ALLOWLIST), sorted(UNCONDITIONAL), []))
        self.assertTrue(HELPER in self.sources, f'{HELPER} is not a tracked source')

    def test_the_no_window_guard_fails_on_the_injected_launches_and_a_detached_start(self):
        self.assertEqual(self.sources[PLATFORM].count(NO_WINDOW_SUPERVISOR), 1)
        self.assertEqual(self.sources[PREREQS].count(HELPER_FLAGS), 1)
        findings, unconditional, problems, failures = self.injected_window
        supervisor = (PLATFORM, 'WindowsAdapter.launch_supervisor')
        self.assertEqual(compare(findings, WINDOW_ALLOWLIST),
                         ([(NEWCOMER, 'injected_status'), (ADAPTER, 'injected_status'), supervisor], []))
        self.assertEqual({problem for _, problem in findings[supervisor]},
                         {'creationflags with neither no_window_flags() nor CREATE_NO_WINDOW (via subprocess.Popen)'})
        self.assertEqual(compare(unconditional, UNCONDITIONAL), ([(PREREQS, 'output')], [supervisor]))
        self.assertEqual([(path, problem) for path, _, problem in problems],
                         [(PLATFORM, 'DETACHED_PROCESS (opens a console window)')])
        message = '\n'.join(failures)
        self.assertEqual(len(failures), 4, message)
        line = INJECTED_LINE + self.sources[ADAPTER].count('\n')
        for site in (f'{ADAPTER}:injected_status line {line}: no creationflags (via subprocess.run)',
                     f'{NEWCOMER}:injected_status', f'{PLATFORM}:WindowsAdapter.launch_supervisor',
                     f'outside the long-lived background starts (use the helper, or add the start to UNCONDITIONAL '
                     f'with its reason):\n  {PREREQS}:output', f'no longer finds (remove them from UNCONDITIONAL):\n  '
                     f'{PLATFORM}:WindowsAdapter.launch_supervisor'):
            self.assertIn(site, message)


def retained_rows():
    """The rows decision 0014 section 1 retains git for (its 'retain git' dispositions)."""
    text = DECISION.read_text(encoding='utf-8')
    section = text.split('### 1. Scope', 1)[1].split('\n### ', 1)[0]
    rows = set()
    for line in section.splitlines():
        cells = [c.strip() for c in line.strip().strip('|').split('|')]
        if len(cells) >= 3 and 'retain git' in cells[1]:
            rows.add(re.sub(r'\*', '', cells[0]).split()[0])
    return rows


def sites_of(source, path='pkg/mod.py', extra=None):
    sources = {path: source, **(extra or {})}
    return sorted(Census(sources).sites)


class Detection(unittest.TestCase):
    """The detection rules, each on a synthetic source."""

    def test_direct_launchers_and_their_import_forms(self):
        cases = {
            'import subprocess\ndef f():\n    subprocess.run(["git", "status"])\n': ['f'],
            'import subprocess as sp\ndef f():\n    sp.Popen(("git",))\n': ['f'],
            'from subprocess import check_output as co\ndef f():\n    co(["git", "log"])\n': ['f'],
            'import os\ndef f():\n    os.system("git gc")\n': ['f'],
            'import os\ndef f():\n    os.execvp("git", ["git", "x"])\n': ['f'],
            'import os\ndef f():\n    os.spawnl(os.P_WAIT, "/usr/bin/git", "git")\n': ['f'],
            'import asyncio\nasync def f():\n    await asyncio.create_subprocess_exec("git", "x")\n': ['f'],
            'import subprocess\nsubprocess.run(["git", "x"])\n': ['<module>'],
            'import subprocess\nclass C:\n    def m(self):\n        subprocess.run(["git"])\n': ['C.m'],
            'import subprocess\ndef f():\n    def inner():\n        subprocess.call(["git"])\n    inner()\n':
                ['f.inner'],
            'import subprocess\ndef f():\n    subprocess.run(args=["git", "x"])\n': ['f'],
            'import subprocess\ndef f():\n    subprocess.run(["x"], executable="git")\n': ['f'],
            'import subprocess\ndef f():\n    subprocess.run(f"git -C {p} status", shell=True)\n': ['f'],
        }
        for source, names in cases.items():
            with self.subTest(source=source):
                self.assertEqual(sites_of(source), [('pkg/mod.py', n) for n in names])

    def test_program_forms(self):
        cases = {
            'import subprocess, shutil\ndef f():\n    g = shutil.which("git")\n    subprocess.run([g, "x"])\n': True,
            'import subprocess\nfrom shutil import which\nGIT = which("git")\ndef f():\n    subprocess.run([GIT])\n':
                True,
            'import subprocess, shutil\ndef b():\n    p = shutil.which("git")\n    return p\n'
            'def f():\n    argv = [b(), "-c", "x"]\n    argv += ["-C", "d"]\n    subprocess.run(argv + list(a))\n': True,
            'import subprocess\ndef f():\n    subprocess.run([str(r"C:\\Git\\cmd\\git.exe"), "x"])\n': True,
            'import subprocess\ndef f():\n    subprocess.run(["/usr/bin/git", "x"])\n': True,
            'import subprocess\ndef f():\n    subprocess.run([*PREFIX, "x"])\nPREFIX = ["git", "-c", "a=b"]\n': True,
            'import subprocess\nclass C:\n    def __init__(self):\n        self.git = "git"\n'
            '    def m(self):\n        subprocess.run([self.git, "x"])\n': True,
            'import subprocess\ndef f(git="git"):\n    subprocess.run([git])\n': True,
            'import subprocess\ndef f():\n    subprocess.run([str(c) for c in ["git", "x"]])\n': True,
            'import subprocess\ndef f():\n    subprocess.run(["gitea", "x"])\n': False,
            'import subprocess\ndef f():\n    subprocess.run(["legit"])\n': False,
            'import subprocess, sys\ndef f():\n    subprocess.run([sys.executable, "-m", "git"])\n': False,
            'import subprocess\ndef f():\n    subprocess.run(["ssh", "host", "git", "status"])\n': False,
            'import subprocess\ndef f():\n    subprocess.run("gitleaks dir x", shell=True)\n': False,
            'import subprocess\ndef f(argv):\n    subprocess.run(argv)\n': False,
        }
        for source, git in cases.items():
            with self.subTest(source=source):
                self.assertEqual(bool(sites_of(source)), git)

    def test_aliases_and_injectable_runners(self):
        cases = {
            'import subprocess\nrun = subprocess.run\ndef f():\n    run(["git"])\n': ['f'],
            'import subprocess\ndef f(run=subprocess.run):\n    run(["git", "x"])\n': ['f'],
            'import subprocess\ndef f(*, run=subprocess.Popen):\n    run(["git", "x"])\n': ['f'],
            'import subprocess\ndef f(run):\n    run(["git", "x"])\n': [],
        }
        for source, names in cases.items():
            with self.subTest(source=source):
                self.assertEqual(sites_of(source), [('pkg/mod.py', n) for n in names])

    def test_wrappers_are_followed_to_their_callers(self):
        wrapper = ('import subprocess\n'
                   'def run_tree(argv, timeout=None):\n    return subprocess.run(argv, timeout=timeout)\n'
                   'def output(cmd):\n    return run_tree([str(c) for c in cmd])\n'
                   'class Tree:\n    def __init__(self, argv):\n        self.p = subprocess.Popen(argv)\n'
                   '    def again(self, argv):\n        return self.start(argv)\n'
                   '    def start(self, argv):\n        return subprocess.Popen(argv)\n')
        caller = ('import shutil\nimport lib\n'
                  'def a():\n    lib.run_tree(["git", "status"])\n'
                  'def b():\n    git = shutil.which("git")\n    lib.output([git, "--version"])\n'
                  'def c():\n    lib.Tree(["git"])\n'
                  'def d():\n    lib.run_tree(["node", "x"])\n'
                  'def e():\n    lib.run_tree(argv=["git"])\n')
        found = sorted(Census({'lib.py': wrapper, 'app.py': caller}).sites)
        self.assertEqual(found, [('app.py', 'a'), ('app.py', 'b'), ('app.py', 'c'), ('app.py', 'e')])
        method = wrapper + 'def g():\n    pass\n'
        own = ('import subprocess\nclass Tree:\n    def start(self, argv):\n        return subprocess.Popen(argv)\n'
               '    def go(self):\n        return self.start(["git", "x"])\n')
        self.assertEqual(sorted(Census({'lib.py': method, 'own.py': own}).sites), [('own.py', 'Tree.go')])

    def test_class_attributes_and_path_joins(self):
        source = ('import shutil\nfrom pathlib import Path\nimport lib\n'
                  'def launcher():\n    found = shutil.which("x")\n    root = Path(found).parent\n'
                  '    return root / "cmd" / "git.exe"\n'
                  'class Real:\n    @classmethod\n    def setUpClass(cls):\n        cls.launcher = launcher()\n'
                  '    def start(self, *args):\n        return lib.Tree([str(self.launcher), "-C", "r", *args])\n'
                  'class Body:\n    exe = "C:/Git/bin/git.exe"\n    def go(self):\n        lib.Tree([self.exe])\n')
        wrapper = 'import subprocess\nclass Tree:\n    def __init__(self, argv):\n        subprocess.Popen(argv)\n'
        self.assertEqual(sorted(Census({'lib.py': wrapper, 'app.py': source}).sites),
                         [('app.py', 'Body.go'), ('app.py', 'Real.start')])

    def test_a_fixed_helper_is_the_site_not_its_callers(self):
        source = ('import subprocess\ndef git(*args):\n    return subprocess.run(["git", *args])\n'
                  'def a():\n    git("status")\n')
        self.assertEqual(sites_of(source), [('pkg/mod.py', 'git')])

    def test_compare_reports_both_directions(self):
        found = {('a.py', 'f'): [(3, 'subprocess.run')], ('b.py', 'g'): [(1, 'subprocess.run')]}
        allow = {('a.py', 'f'): 'R6', ('c.py', 'h'): 'H1'}
        self.assertEqual(compare(found, allow), ([('b.py', 'g')], [('c.py', 'h')]))
        self.assertIn('b.py:g (line 1; via subprocess.run)', describe(found, [('b.py', 'g')]))

    def test_unparseable_sources_are_reported(self):
        census = Census({'bad.py': 'def (:\n'})
        self.assertIn('bad.py', census.errors)


def window_of(source, path='tools/mod.py', extra=None, unconditional=False):
    """The no-window guard's census of synthetic sources: (findings by site name, problems), and with
    ``unconditional`` the names of the sites that carry the flag unconditionally too."""
    sources = {path: source, **(extra or {})}
    window = WindowCensus(Census(sources), sources)
    result = ({name: [p for _, p in found] for (p_, name), found in window.findings.items() if p_ == path},
              [problem for _, _, problem in window.problems])
    if unconditional:
        result += (sorted(name for p_, name in window.unconditional if p_ == path),)
    return result


class WindowDetection(unittest.TestCase):
    """The no-window guard's rules, each on a synthetic source."""

    def test_each_launch_form_needs_the_flag(self):
        cases = {
            'import subprocess\ndef f():\n    subprocess.run(["x"])\n': 'f',
            'import subprocess as sp\ndef f():\n    sp.Popen(["x"])\n': 'f',
            'from subprocess import check_output as co\ndef f():\n    co(["x"])\n': 'f',
            'import os\ndef f():\n    os.system("x")\n': 'f',
            'import subprocess\nsubprocess.call(["x"])\n': '<module>',
            'import subprocess\nrun = subprocess.run\ndef f():\n    run(["x"])\n': 'f',
            'import subprocess\ndef f(run=subprocess.run):\n    run(["x"])\n': 'f',
            # a launcher passed on to a function of the same module, and kept on self
            'import subprocess\ndef g(run, argv):\n    run(argv)\ndef f(run=subprocess.run):\n    g(run, ["x"])\n': 'g',
            'import subprocess\ndef g(argv, *, run):\n    run(argv)\ndef f():\n    g(["x"], run=subprocess.run)\n': 'g',
            'import subprocess\nclass C:\n    def __init__(self, run=subprocess.run):\n        self.run = run\n'
            '    def m(self):\n        self.run(["x"])\n': 'C.m',
            'import subprocess\nclass C:\n    def m(self, run):\n        run(["x"])\n'
            '    def n(self):\n        self.m(subprocess.run)\n': 'C.m',
        }
        for source, site in cases.items():
            with self.subTest(source=source):
                findings, problems = window_of(source)
                self.assertEqual(list(findings), [site])
                self.assertIn('no creationflags', findings[site][0])
                self.assertEqual(problems, [])

    def test_the_helpers_value_is_the_flag_of_every_ordinary_launch(self):
        head = "import subprocess, os\nNO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)\n"
        helper = [
            'def f():\n    subprocess.run(["x"], creationflags=_no_window().no_window_flags())\n',
            'def f():\n    subprocess.run(["x"], creationflags=nw.no_window_flags())\n',
            'def f(a):\n    flags = a.pop("creationflags", 0) | 4 | _no_window().no_window_flags()\n'
            '    subprocess.Popen(["x"], creationflags=flags)\n',
            'def f(run=subprocess.run):\n    run(["x"], creationflags=_no_window().no_window_flags())\n',
        ]
        for body in helper:
            with self.subTest(body=body):
                self.assertEqual(window_of(head + body, unconditional=True), ({}, [], []))
        # the unconditional flag is carried too, and the site is listed as an unconditional start
        self.assertEqual(window_of(head + 'def f():\n    subprocess.Popen(["x"], creationflags=_no_window().'
                                   'no_window_flags() | NO_WINDOW)\n', unconditional=True), ({}, [], ['f']))
        # a helper of another name, or the helper called with an argument, carries nothing
        for body in ('def f():\n    subprocess.run(["x"], creationflags=_no_window().other_flags())\n',
                     'def f():\n    subprocess.run(["x"], creationflags=nw.no_window_flags(True))\n'):
            with self.subTest(body=body):
                self.assertEqual(list(window_of(head + body)[0]), ['f'])
        # no_window_flags is the shared helper's own: another module's definition is refused
        self.assertEqual(window_of('def no_window_flags():\n    return 0\n')[1],
                         [f'no_window_flags defined outside {HELPER}'])
        self.assertEqual(window_of('def no_window_flags():\n    return 0\n', HELPER)[1], [])

    def test_the_unconditional_forms_that_carry_it(self):
        head = "import subprocess, os\nNO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)\n"
        carried = [
            'def f():\n    subprocess.run(["x"], creationflags=NO_WINDOW)\n',
            'def f():\n    subprocess.run(["x"], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))\n',
            'def f():\n    subprocess.run(["x"], creationflags=subprocess.CREATE_NO_WINDOW)\n',
            'def f():\n    subprocess.Popen(["x"], creationflags=NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP)\n',
            'def f():\n    flags = NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0\n'
            '    subprocess.Popen(["x"], creationflags=flags)\n',
            'def f(a):\n    flags = a.pop("creationflags", 0) | 4 | NO_WINDOW\n    subprocess.Popen(["x"], creationflags=flags)\n',
            'def f(run=subprocess.run):\n    run(["x"], creationflags=NO_WINDOW)\n',
            'def f(flags):\n    flags = flags | NO_WINDOW\n    subprocess.run(["x"], creationflags=flags)\n',
        ]
        for body in carried:
            with self.subTest(body=body):
                self.assertEqual(window_of(head + body, unconditional=True), ({}, [], ['f']))
        missing = [
            'def f():\n    subprocess.run(["x"], creationflags=0)\n',
            'def f():\n    subprocess.run(["x"], creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)\n',
            'def f(flags=NO_WINDOW):\n    subprocess.run(["x"], creationflags=flags)\n',
            'def f():\n    flags = NO_WINDOW\n    flags = 0\n    subprocess.run(["x"], creationflags=flags)\n',
            'def f():\n    subprocess.run(["x"], creationflags=NO_WINDOW & 0)\n',
            'def f(kw):\n    subprocess.run(["x"], **kw)\n',
            'def f():\n    subprocess.run(["x"], creationflags=OTHER.CREATE_NO_WINDOW)\n',
        ]
        for body in missing:
            with self.subTest(body=body):
                findings, _ = window_of(head + body)
                self.assertEqual(list(findings), ['f'], findings)

    def test_no_window_is_the_one_definition(self):
        cases = {
            'import subprocess\nNO_WINDOW = 0\ndef f():\n    subprocess.run(["x"], creationflags=NO_WINDOW)\n':
                (['f'], ["NO_WINDOW bound to something other than getattr(subprocess, 'CREATE_NO_WINDOW', 0)"]),
            "import subprocess\nNO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)\n"
            'def f():\n    NO_WINDOW = 0\n    subprocess.run(["x"], creationflags=NO_WINDOW)\n':
                (['f'], ['NO_WINDOW bound in f']),
            'import subprocess\ndef f():\n    subprocess.run(["x"], creationflags=NO_WINDOW)\n': (['f'], []),
        }
        for source, (sites, problems) in cases.items():
            with self.subTest(source=source):
                findings, found = window_of(source)
                self.assertEqual((list(findings), found), (sites, problems))

    def test_window_opening_flags_fail_wherever_they_are_named(self):
        for line in ('flags = subprocess.DETACHED_PROCESS\n', 'flags = subprocess.CREATE_NEW_CONSOLE\n',
                     'flags = getattr(subprocess, "DETACHED_PROCESS", 0)\n', 'from subprocess import DETACHED_PROCESS\n'
                     'flags = DETACHED_PROCESS\n'):
            with self.subTest(line=line):
                _, problems = window_of('import subprocess\n' + line)
                self.assertTrue(problems and all('opens a console window' in p for p in problems), problems)
        # prose and comments that name them are not flags
        self.assertEqual(window_of('import subprocess\n# never DETACHED_PROCESS\n'
                                   'def f():\n    """never DETACHED_PROCESS here"""\n'), ({}, []))

    def test_only_non_test_modules_under_tools_integrations_and_composition_are_read(self):
        launch = 'import subprocess\ndef f():\n    subprocess.run(["x"], creationflags=subprocess.DETACHED_PROCESS)\n'
        for path, read in (('tools/mod.py', True), ('integrations/a/mod.py', True), ('tools/tests/mod.py', False),
                           ('integrations/a/tests/helper.py', False), ('tools/test_mod.py', True),
                           ('tools/tests/test_mod.py', False), ('integrations/a/tests/test_mod.py', False),
                           ('composition/mod.py', True), ('composition/inventory/scan.py', True),
                           ('profiles/x/netprobe.py', False), ('conftest.py', False)):
            with self.subTest(path=path):
                self.assertEqual(window_scanned(path), read)
                findings, problems = window_of(launch, path)
                self.assertEqual(bool(findings) and bool(problems), read)
        # guest-side Python held in a string is never parsed as a launch
        self.assertEqual(window_of('SCRIPT = """\nimport subprocess\nsubprocess.run(["id"])\n"""\n'), ({}, []))

    def test_the_verdict_names_each_site_and_each_stale_allowance(self):
        sources = {'tools/a.py': 'import subprocess\ndef f():\n    subprocess.run(["x"])\n'
                                 'def g():\n    subprocess.run(["x"], creationflags=subprocess.CREATE_NO_WINDOW)\n'}
        window = WindowCensus(Census(sources), sources)
        message = '\n'.join(window_failures(window, {('tools/b.py', 'g'): 'gone'}, {('tools/c.py', 'h'): 'gone'}))
        self.assertIn('tools/a.py:f line 3: no creationflags (via subprocess.run)', message)
        self.assertIn('no longer finds (remove them from WINDOW_ALLOWLIST):\n  tools/b.py:g', message)
        self.assertIn('with its reason):\n  tools/a.py:g (line 5)', message)
        self.assertIn('no longer finds (remove them from UNCONDITIONAL):\n  tools/c.py:h', message)
        self.assertEqual(window_failures(window, {('tools/a.py', 'f'): 'reason'}, {('tools/a.py', 'g'): 'reason'}),
                         [])


if __name__ == '__main__':
    unittest.main()
