"""The shared repository-access module (plan leaf F-10.2, decision 0014).

Read-only access to git repositories for AI Engineering's own Python components, implemented
over Dulwich (``integrations/repository/README.md``). The module launches no process: every
answer is computed in this process from the repository's own files.

- ``open_repository(path, config=..., work_tree=True)``: the work-tree check (git's
  ``rev-parse --show-toplevel`` acceptance) and an explicit configuration policy, ``host``,
  ``repository`` or ``none`` (decision 0014 section 5); ``Repository.config_sources`` lists the
  configuration files read.
- The preserved revision grammar of decision 0014 section 2: ``Repository.commit(revision)``
  answers as ``git rev-parse --verify <revision>^{commit}``; ``object_id``, ``object_kind``,
  ``read`` and ``blob`` answer object names as ``git cat-file`` does. The documented gap forms
  are refused with ``REVISION_INVALID`` before any repository access (``check_revision``,
  ``check_object_name``).
- ``files`` (``ls-tree -r --name-only``), ``export_tree`` (blob bytes, section 4), ``head``,
  ``full_name`` (``rev-parse --symbolic-full-name``, F-10.4), ``status``, ``index_entries``,
  ``listing`` (``ls-files``), ``write_bundle``, and the module functions ``parse_bundle_header``
  and ``pack_trailer``. Ignore rules and attributes are decided by the module as git decides
  them (``_Excludes``, ``_Attributes``), not by Dulwich's ``IgnoreFilterManager`` and
  ``GitAttributes`` (F-10.4).
- The smart-HTTP transports (F-10.6): ``ls_remote(url)``, ``clone(url, destination)`` (a bare
  clone) and ``Repository.push(url, refspec, credential)``, with a ``Credential`` held in memory
  and sent as HTTP Basic or ``Authorization: token`` to the remote's origin only; no credential
  helper, no ssh, no git configuration, no process. A push refuses a repository with client
  hooks (decision 0014 section 6).
- The commit write (decision 0014 sections 6 and 8; first needed by plan leaf P-04.1):
  ``Repository.write_commit(files, message, identity=, expected_head=)`` builds the commit as
  objects plus a compare-and-set update of the branch, runs no hook (a repository with client hooks
  is refused) and brings the work tree and the index to it.

Errors (decision 0014 section 3): ``RepositoryError`` with a stable ``code``
(``REVISION_INVALID``, ``OBJECT_NAME_INVALID``, ``GIT_FAILED``, ``EXPORT_REFUSED``,
``BUNDLE_INVALID``, ``FILTER_UNSUPPORTED``, ``ATTRIBUTES_UNSUPPORTED``, ``REPLACE_REFS_UNSUPPORTED``;
the transports' ``PUSH_REFUSED``, ``PUSH_REJECTED``, ``REMOTE_REFUSED``, ``REMOTE_FAILED`` and
``HOOKS_UNSUPPORTED``; the commit's ``COMMIT_REFUSED`` and ``HOOKS_UNSUPPORTED``), and ``CannotRun`` (``NOT_A_WORK_TREE``,
``NOT_A_REPOSITORY``, ``REPOSITORY_NEEDS_DULWICH``). "No such object" and an ambiguous
abbreviation answer ``None``.

The standard library is imported at module import; Dulwich only when a repository is opened, so
that a missing Dulwich is the stable ``CannotRun`` ``REPOSITORY_NEEDS_DULWICH``, never an
``ImportError``.
"""
import collections
import io
import hashlib
import os
import re
import stat
import sys
import time
from dataclasses import dataclass
from pathlib import Path

POLICIES = ('host', 'repository', 'none')
UNTRACKED_MODES = ('no', 'normal', 'all')
TOOLS_INSTALL_HINT = ('run task tools:install (python -I -B integrations/paths/tools_install.py) and rerun '
                      'with the interpreter it prints (python -I -B integrations/paths/tools_install.py --python)')

_CONTROL = re.compile(r'[\x00-\x1f\x7f]')
_HEX = frozenset('0123456789abcdefABCDEF')
_DIGITS = frozenset('0123456789')
_INT_MAX = 2 ** 31 - 1
_REFLOG_DATE_FLOOR = 100000000  # git: a numeric @{N} at or above this is a timestamp
_MINIMUM_ABBREV = 4
_SYMREF_MAX_DEPTH = 5
_PER_WORKTREE_PREFIXES = ('refs/bisect/', 'refs/worktree/', 'refs/rewritten/')
_TYPE_NAMES = {1: 'commit', 2: 'tree', 3: 'blob', 4: 'tag'}
_TYPE_NUMS = {name: num for num, name in _TYPE_NAMES.items()}
# The verified-object cache of one opened repository (decision 0014 section 3: an object enters it
# only after its content hashed to its id; ids are immutable, so an entry never goes stale). It
# holds at most this many bytes of object content, least recently used first out, and an object
# larger than an eighth of it is not kept. Missing objects are not remembered.
OBJECT_CACHE_BYTES = 32 * 1024 * 1024
_S_IFMT = 0o170000
_S_IFREG = 0o100000
_S_IFLNK = 0o120000
_S_IFGITLINK = 0o160000
_S_IFDIR = 0o040000
_WINDOWS = os.name == 'nt'
_WINDOWS_RESERVED = frozenset({'con', 'prn', 'aux', 'nul', 'conin$', 'conout$',
                               *(f'com{i}' for i in '123456789¹²³'),
                               *(f'lpt{i}' for i in '123456789¹²³')})
_WINDOWS_INVALID = frozenset('<>:"|?*\\')
# git's identity (ident.c): "Name <email>", neither part holding '<', '>', NUL or a line break.
IDENTITY = re.compile(r'[^<>\n\r\0]*[^<>\s\0][^<>\n\r\0]* <[^<>\s\0]+>')

# Commit expected (rev-parse X^{commit}, X~N, X^N): commits, and tags that peel to one.
_COMMIT, _COMMITTISH, _TREEISH = 'commit', 'committish', 'treeish'


class RepositoryError(Exception):
    """A visible failure with a stable code."""

    def __init__(self, code, message, **details):
        super().__init__(f'{code}: {message}')
        self.code = code
        self.message = message
        self.details = details


class CannotRun(Exception):
    """The repository cannot be used at all: not a work tree or repository, or no Dulwich."""

    def __init__(self, code, message):
        super().__init__(f'{code}: {message}')
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Head:
    """HEAD as git reads it: ``commit`` is ``rev-parse --verify HEAD`` (None when the branch is
    unborn), ``ref`` the branch it names (None when detached)."""
    commit: object
    ref: object


@dataclass(frozen=True)
class StatusEntry:
    """One ``git status --porcelain=v1 -z --no-renames`` entry: XY, then the path (a directory
    of untracked files ends with '/')."""
    xy: str
    path: str


@dataclass(frozen=True)
class IndexEntry:
    """One ``git ls-files -s`` entry."""
    mode: int
    oid: str
    stage: int
    path: str


# ---------------------------------------------------------------------------- Dulwich

_D = None


def dulwich_modules():
    """Dulwich's modules, imported on first use; CannotRun REPOSITORY_NEEDS_DULWICH without it."""
    global _D
    if _D is None:
        try:
            import dulwich
            from dulwich import attrs, bundle, config, errors, ignore, index, objects, reflog, repo
            from dulwich.file import GitFile
        except ImportError as exc:
            raise CannotRun('REPOSITORY_NEEDS_DULWICH',
                            f'Dulwich is not importable by {sys.executable} ({exc}); {TOOLS_INSTALL_HINT}') from None
        ns = type('Dulwich', (), {})()
        ns.version = '.'.join(map(str, dulwich.__version__))
        ns.attrs, ns.bundle, ns.config, ns.errors = attrs, bundle, config, errors
        ns.ignore, ns.index, ns.objects, ns.reflog, ns.repo, ns.GitFile = ignore, index, objects, reflog, repo, GitFile
        ns.Repo = _policy_repo_class(repo.Repo, config, GitFile)
        _D = ns
    return _D


def _policy_repo_class(base, config_module, git_file):
    class PolicyRepo(base):
        """A Dulwich Repo whose configuration stack is the call site's policy, and which records
        every configuration file it reads."""

        def __init__(self, *args, aieh_policy, **kwargs):
            self._aieh_policy = aieh_policy
            self._aieh_sources = []
            self._aieh_stack = None
            super().__init__(*args, **kwargs)

        def _aieh_open(self, path):
            handle = git_file(path, 'rb')
            path = os.path.normpath(path)
            if path not in self._aieh_sources:
                self._aieh_sources.append(path)
            return handle

        def _aieh_read(self, path, matchers=True):
            kwargs = {'file_opener': self._aieh_open}
            if matchers:
                kwargs['condition_matchers'] = self._get_config_condition_matchers()
            return config_module.ConfigFile.from_path(path, **kwargs)

        def get_config(self):
            path = os.path.join(self._commondir, 'config')
            try:
                return self._aieh_read(path)
            except FileNotFoundError:
                empty = config_module.ConfigFile()
                empty.path = path
                return empty

        def get_worktree_config(self):
            path = os.path.join(self.commondir(), 'config.worktree')
            try:
                return self._aieh_read(path)
            except FileNotFoundError:
                empty = config_module.ConfigFile()
                empty.path = path
                return empty

        def get_config_stack(self):
            if self._aieh_stack is None:
                backends = []
                if self._aieh_policy != 'none':
                    local = self.get_config()
                    backends.append(local)
                    if local.get_boolean((b'extensions',), b'worktreeconfig', False):
                        backends.append(self.get_worktree_config())
                if self._aieh_policy == 'host':
                    for path in host_config_paths():
                        try:
                            backends.append(self._aieh_read(path, matchers=False))
                        except FileNotFoundError:
                            continue
                self._aieh_stack = config_module.StackedConfig(backends)
            return self._aieh_stack

    return PolicyRepo


_TRUE = ('true', 'yes', 'on', '1')
_FALSE = ('false', 'no', 'off', '0', '')


def _env_bool(name):
    """git's git_env_bool: an unset or empty variable is false; otherwise a git boolean (an
    unrecognised value counts as true, as git would refuse it rather than ignore it)."""
    value = os.environ.get(name, '').strip().lower()
    return value not in _FALSE


def _registry_install_path():
    """Git for Windows' installation directory from the registry
    (``SOFTWARE\\GitForWindows``, value ``InstallPath``, machine before user, 64-bit view before
    32-bit), read only; None where there is none."""
    import winreg
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(hive, r'SOFTWARE\GitForWindows', 0, winreg.KEY_READ | view) as key:
                    value, kind = winreg.QueryValueEx(key, 'InstallPath')
            except OSError:
                continue
            if kind in (winreg.REG_SZ, winreg.REG_EXPAND_SZ) and value:
                return os.path.expandvars(value) if kind == winreg.REG_EXPAND_SZ else value
    return None


def system_file(name):
    """The system-wide git file NAME ('gitconfig' or 'gitattributes'), located without PATH:
    on Windows ``<InstallPath>\\etc\\<name>`` from Git for Windows' registry entry, elsewhere
    ``/etc/<name>``; None when there is no installation to locate."""
    if _WINDOWS:
        install = _registry_install_path()
        return os.path.join(install, 'etc', name) if install else None
    return f'/etc/{name}'


def _xdg_git_file(name):
    home = os.environ.get('XDG_CONFIG_HOME') or os.path.join(os.path.expanduser('~'), '.config')
    return os.path.join(home, 'git', name)


def host_config_paths():
    """The user and system configuration files the ``host`` policy reads (decision 0014
    section 5), in precedence order, located as git does and never through PATH:
    ``GIT_CONFIG_GLOBAL``, else ``~/.gitconfig`` and ``$XDG_CONFIG_HOME/git/config``; then
    ``GIT_CONFIG_SYSTEM``, else (unless ``GIT_CONFIG_NOSYSTEM``) the system file
    (``system_file``)."""
    paths = []
    if 'GIT_CONFIG_GLOBAL' in os.environ:
        paths.append(os.environ['GIT_CONFIG_GLOBAL'])
    else:
        paths.append(os.path.join(os.path.expanduser('~'), '.gitconfig'))
        paths.append(_xdg_git_file('config'))
    if 'GIT_CONFIG_SYSTEM' in os.environ:
        paths.append(os.environ['GIT_CONFIG_SYSTEM'])
    elif not _env_bool('GIT_CONFIG_NOSYSTEM'):
        system = system_file('gitconfig')
        if system:
            paths.append(system)
    return paths


# ---------------------------------------------------------------------------- grammar

def _invalid_text(text):
    if not isinstance(text, str) or not text or text.startswith('-') or _CONTROL.search(text):
        return True
    try:
        text.encode('utf-8')
    except UnicodeEncodeError:
        return True
    return False


def _revision_part(name):
    """The revision of an object name: the text before its first ':' outside braces (git's
    ``<rev>:<path>`` split), all of it without one, or None for the index forms (':' first)."""
    if name.startswith(':'):
        return None
    depth = 0
    for i, ch in enumerate(name):
        if ch == '{':
            depth += 1
        elif depth and ch == '}':
            depth -= 1
        elif not depth and ch == ':':
            return name[:i]
    return name


_RANGE_END = re.compile(r'\^(?:@|!|-[0-9]*)\Z')
_MARK = re.compile(r'@\{([^}]*)\}')


def gap_form(name):
    """The documented compatibility gap (decision 0014 section 2) NAME uses, or None. Purely
    syntactic: it reads no repository."""
    if name.startswith(':/') and len(name) > 2:
        return 'the history search :/<text>'
    revision = _revision_part(name)
    if revision is None:
        return None
    if revision.startswith('^'):
        return 'a range (^<rev>)'
    if '..' in revision:
        return 'a range (A..B or A...B)'
    if _RANGE_END.search(revision):
        return 'a range (<rev>^@, <rev>^! or <rev>^-N)'
    if '^{/' in revision:
        return 'the history search <rev>^{/<regex>}'
    for mark in _MARK.finditer(revision):
        content = mark.group(1)
        if content.startswith('-'):
            return 'the previous checkout @{-N}'
        if content.lower() in ('upstream', 'u', 'push'):
            return 'the configured branch @{upstream} or @{push}'
        if content.isascii() and content.isdigit():
            if int(content) < _REFLOG_DATE_FLOOR:
                continue
            return 'the reflog date @{<timestamp>}'
        return 'the reflog date @{<date>}'
    return None


def check_revision(revision):
    """Refuse (REVISION_INVALID), before any repository access, what is not a usable revision:
    not text, empty, a leading '-', whitespace, a C0 control or DEL, or a gap form."""
    if _invalid_text(revision) or any(ch.isspace() for ch in revision):
        raise RepositoryError('REVISION_INVALID', f'not a usable revision: {revision!r}')
    gap = gap_form(revision)
    if gap:
        raise RepositoryError('REVISION_INVALID', f'{revision!r} uses {gap}, a documented compatibility gap '
                              '(decision 0014 section 2)', gap=gap)
    return revision


def check_object_name(name):
    """Refuse, before any repository access, an object name outside the grammar: not text,
    empty, a leading '-' or a C0 control or DEL (OBJECT_NAME_INVALID), or a gap form in its
    revision (REVISION_INVALID). Spaces are part of a name."""
    if _invalid_text(name):
        raise RepositoryError('OBJECT_NAME_INVALID', f'not an object name: {name!r}')
    gap = gap_form(name)
    if gap:
        raise RepositoryError('REVISION_INVALID', f'{name!r} uses {gap}, a documented compatibility gap '
                              '(decision 0014 section 2)', gap=gap)
    return name


def _check_path(path, what='path', allow_root=False):
    """A repository-relative path argument: '/'-separated, no empty, '.' or '..' component, no
    control character. '' or '.' is the root when ALLOW_ROOT."""
    if not isinstance(path, str) or _CONTROL.search(path):
        raise RepositoryError('OBJECT_NAME_INVALID', f'not a repository-relative {what}: {path!r}')
    if path in ('', '.'):
        if allow_root:
            return ''
        raise RepositoryError('OBJECT_NAME_INVALID', f'not a repository-relative {what}: {path!r}')
    parts = path.split('/')
    if any(part in ('', '.', '..') for part in parts):
        raise RepositoryError('OBJECT_NAME_INVALID', f'not a repository-relative {what}: {path!r}')
    try:
        path.encode('utf-8')
    except UnicodeEncodeError:
        raise RepositoryError('OBJECT_NAME_INVALID', f'not a repository-relative {what}: {path!r}') from None
    return path


def refname_valid(name, onelevel=False):
    """git's check_refname_format for NAME (REFNAME_ALLOW_ONELEVEL when ONELEVEL)."""
    if not name or name == '@' or name.endswith('.') or name.startswith('/') or name.endswith('/'):
        return False
    parts = name.split('/')
    if len(parts) < 2 and not onelevel:
        return False
    for part in parts:
        if not part or part.startswith('.') or part.endswith('.lock'):
            return False
        if '..' in part or '@{' in part:
            return False
        if any(ord(ch) < 0x20 or ch in ' ~^:?*[\\\x7f' for ch in part):
            return False
    return True


# Attributes git's status never consults: setting them in a file outside the repository cannot
# change a status answer. Any other attribute (text, eol, crlf, binary, filter, ident,
# working-tree-encoding, a macro or an unknown name) can.
STATUS_NEUTRAL_ATTRIBUTES = frozenset({'diff', 'merge', 'whitespace', 'export-ignore', 'export-subst', 'delta',
                                       'encoding', 'conflict-marker-size'})


def status_attribute(text):
    """The first attribute in the gitattributes TEXT that git's status could apply (a macro
    definition counts), or None."""
    found = status_attribute_line(text)
    return found[1] if found else None


def status_attribute_line(text):
    """(line number, attribute) of the first attribute in the gitattributes TEXT that git's
    status could apply (a macro definition counts), or None."""
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('[attr]'):
            return lineno, line.split()[0]
        if line.startswith('"'):
            end = line.find('"', 1)
            while end > 0 and line[end - 1] == '\\':
                end = line.find('"', end + 1)
            rest = line[end + 1:] if end > 0 else ''
        else:
            parts = line.split(None, 1)
            rest = parts[1] if len(parts) > 1 else ''
        for token in rest.split():
            name = token.lstrip('-!').split('=', 1)[0]
            if name not in STATUS_NEUTRAL_ATTRIBUTES:
                return lineno, token
    return None


def _pseudoref_syntax(name):
    """git's is_pseudoref_syntax: upper-case letters, '-' and '_' only (HEAD, ORIG_HEAD, ...)."""
    return bool(name) and all(ch in '-_' or 'A' <= ch <= 'Z' for ch in name)


_DESCRIBE_TAIL = re.compile(r'-[0-9]+\Z')
_REFLOG_TIME = re.compile(rb'([0-9]+) [+-][0-9]{4}')


def _ambiguous_path(text):
    """git's ambiguous_path: empty, '/'-led, '//' inside, '/'-ended, or only dots and slashes."""
    slash = True
    for ch in text:
        if ch == '/':
            if slash:
                return True
            slash = True
        elif ch == '.':
            continue
        else:
            slash = False
    return slash


# ---------------------------------------------------------------------------- statistics (convert.c)

_NONPRINTABLE = bytes(c for c in range(32) if c not in (8, 9, 10, 12, 13, 27)) + bytes([127])


def _text_stats(data):
    crlf = data.count(b'\r\n')
    cr = data.count(b'\r')
    lf = data.count(b'\n')
    nul = data.count(b'\0')
    nonprintable = len(data) - len(data.translate(None, _NONPRINTABLE))
    if data.endswith(b'\x1a'):
        nonprintable -= 1
    printable = len(data) - cr - lf - nonprintable - (1 if data.endswith(b'\x1a') else 0)
    return {'crlf': crlf, 'lonecr': cr - crlf, 'nul': nul, 'printable': printable, 'nonprintable': nonprintable}


def _is_binary(stats):
    return bool(stats['lonecr'] or stats['nul'] or (stats['printable'] >> 7) < stats['nonprintable'])


def _ident_to_git(data):
    out, src = bytearray(), data
    while True:
        dollar = src.find(b'$')
        if dollar < 0:
            break
        out += src[:dollar + 1]
        src = src[dollar + 1:]
        if len(src) > 3 and src.startswith(b'Id:'):
            end = src.find(b'$', 3)
            if end < 0:
                break
            if b'\n' in src[3:end]:
                continue
            out += b'Id$'
            src = src[end + 1:]
    out += src
    return bytes(out)


# ---------------------------------------------------------------------------- discovery

def _read_gitfile(path):
    try:
        with open(path, 'rb') as handle:
            data = handle.read(4096)
    except OSError:
        return None
    if not data.startswith(b'gitdir: '):
        return None
    target = os.fsdecode(data[len(b'gitdir: '):].strip())
    return os.path.normpath(os.path.join(os.path.dirname(path), target))


def _valid_head(path):
    try:
        with open(os.path.join(path, 'HEAD'), 'rb') as handle:
            data = handle.read(256)
    except OSError:
        return False
    if data.startswith(b'ref: refs/'):
        return True
    text = data.strip()
    return len(text) in (40, 64) and all(chr(c) in _HEX for c in text)


def is_git_directory(path):
    """git's is_git_directory: a valid HEAD, and objects/ and refs/ in its common directory."""
    if not _valid_head(path):
        return False
    common = path
    try:
        with open(os.path.join(path, 'commondir'), 'rb') as handle:
            common = os.path.normpath(os.path.join(path, os.fsdecode(handle.read().strip())))
    except OSError:
        pass
    return os.path.isdir(os.path.join(common, 'objects')) and os.path.isdir(os.path.join(common, 'refs'))


def _ceiling_floor(start, ceilings):
    """git's ``longest_ancestor_length``: the longest of CEILINGS that is a proper ancestor of
    START (both real paths), normalized for comparison; None when there is none."""
    folded, best = os.path.normcase(start), None
    for ceiling in ceilings:
        ceiling = os.path.normcase(os.path.realpath(os.fspath(ceiling)))
        prefix = ceiling if ceiling.endswith(os.sep) else ceiling + os.sep
        if folded.startswith(prefix) and (best is None or len(ceiling) > len(best)):
            best = ceiling
    return best


def discover(path, ceilings=()):
    """('worktree', root) or ('gitdir', directory) for the repository PATH is in, as git's
    discovery walks up from it; None outside any repository. CEILINGS are git's ceiling
    directories (``GIT_CEILING_DIRECTORIES``): the walk never moves up into one of them or above
    it, so nothing there is examined (PATH itself is, even when it is a ceiling)."""
    start = os.path.realpath(os.fspath(path))
    if not os.path.isdir(start):
        return None
    floor = _ceiling_floor(start, ceilings)
    current = start
    while True:
        dotgit = os.path.join(current, '.git')
        if os.path.isfile(dotgit):
            target = _read_gitfile(dotgit)
            if target is None or not is_git_directory(target):
                raise CannotRun('NOT_A_WORK_TREE', f'invalid gitfile {dotgit}')
            return ('worktree', current)
        if os.path.isdir(dotgit) and is_git_directory(dotgit):
            return ('worktree', current)
        if is_git_directory(current):
            return ('gitdir', current)
        parent = os.path.dirname(current)
        if parent == current:
            return None
        if floor is not None and len(os.path.normcase(parent)) <= len(floor):
            return None  # the parent is the ceiling or above it
        current = parent


def ceiling_directories(environ=None):
    """git's ceiling directories from ``GIT_CEILING_DIRECTORIES`` (``os.pathsep``-separated; an
    empty or relative entry is skipped, as git skips it)."""
    value = (os.environ if environ is None else environ).get('GIT_CEILING_DIRECTORIES', '')
    return [entry for entry in value.split(os.pathsep) if entry and os.path.isabs(entry)]


def open_repository(path, *, config, work_tree=True, ceilings=None):
    """Open the repository at or above PATH under the configuration policy CONFIG ('host',
    'repository' or 'none'). With WORK_TREE (the default) only a work tree is accepted, as git's
    ``rev-parse --show-toplevel``: any directory inside one, a linked worktree or a separate git
    directory's work tree; a bare repository or a .git directory is refused (CannotRun
    NOT_A_WORK_TREE). Without it a git directory is accepted too (NOT_A_REPOSITORY otherwise).
    CEILINGS, git's ceiling directories, stop the upward search below them (``discover``); None
    (the default) takes them from ``GIT_CEILING_DIRECTORIES``, as git does, so that without it the
    search goes up to the file system's root."""
    if config not in POLICIES:
        raise ValueError(f'config must be one of {POLICIES}, not {config!r}')
    if ceilings is None:
        ceilings = ceiling_directories()
    elif isinstance(ceilings, (str, bytes, os.PathLike)):
        raise ValueError('ceilings must be a list of directories')
    d = dulwich_modules()
    found = discover(path, ceilings)
    if found is None or (work_tree and found[0] != 'worktree'):
        if work_tree:
            raise CannotRun('NOT_A_WORK_TREE', f'not a git working tree: {path}')
        raise CannotRun('NOT_A_REPOSITORY', f'not a git repository: {path}')
    kind, location = found
    try:
        if kind == 'worktree':
            repo = d.Repo(location, aieh_policy=config)
        else:
            repo = d.Repo(None, controldir=location, aieh_policy=config)
    except Exception as exc:  # the module boundary: an unreadable repository
        raise RepositoryError('GIT_FAILED', f'cannot open the repository at {location}: '
                              f'{type(exc).__name__}: {exc}') from None
    if work_tree and repo.bare:
        repo.close()
        raise CannotRun('NOT_A_WORK_TREE', f'not a git working tree: {path}')
    return Repository(repo, config, None if repo.bare else location)


# ---------------------------------------------------------------------------- transports (F-10.6)

CREDENTIAL_SCHEMES = ('basic', 'token')
TRANSPORT_TIMEOUT_S = 60  # connect and read, per request: a ceiling that bounds a hang
_REMOTE_REFUSED_STATUSES = (401, 403)
_T = None


@dataclass(frozen=True)
class Credential:
    """A credential held in memory and sent only in the ``Authorization`` header of a request to
    the remote's own origin: HTTP Basic (``scheme='basic'``: USERNAME and SECRET) or
    ``Authorization: token <SECRET>`` (``scheme='token'``). Never a URL, a configuration entry, a
    credential helper or a process argument. ``repr`` and ``str`` never show the secret."""
    username: str
    secret: str
    scheme: str = 'basic'

    def __post_init__(self):
        if self.scheme not in CREDENTIAL_SCHEMES:
            raise ValueError(f'scheme must be one of {CREDENTIAL_SCHEMES}')
        for name in ('username', 'secret'):
            value = getattr(self, name)
            if not isinstance(value, str) or not value or _CONTROL.search(value):
                raise ValueError(f'the credential {name} must be non-empty text without control characters')
        if ':' in self.username:
            raise ValueError('a basic-auth username cannot hold ":"')

    def __repr__(self):
        return f'Credential(username={self.username!r}, scheme={self.scheme!r}, secret=<hidden>)'

    __str__ = __repr__

    def authorization(self):
        """The ``Authorization`` header value."""
        if self.scheme == 'token':
            return 'token ' + self.secret
        import base64
        return 'Basic ' + base64.b64encode(f'{self.username}:{self.secret}'.encode('utf-8')).decode('ascii')


@dataclass(frozen=True)
class RefUpdate:
    """One reference update ``push`` made (or found already made): the remote reference NAME
    from OLD (None: it did not exist) to NEW (None: deleted)."""
    name: str
    old: str | None
    new: str | None


class _HttpStatus(Exception):
    def __init__(self, status, url):
        super().__init__(f'HTTP {status} from {url}')
        self.status = status


class _Rejected(Exception):
    pass


def _transport_modules():
    """Dulwich's HTTP client, imported on first transport use (CannotRun REPOSITORY_NEEDS_DULWICH
    without Dulwich), and the module's transport class over it."""
    global _T
    if _T is None:
        d = dulwich_modules()
        try:
            from dulwich import client, protocol
        except ImportError as exc:
            raise CannotRun('REPOSITORY_NEEDS_DULWICH',
                            f'Dulwich is not importable by {sys.executable} ({exc}); {TOOLS_INSTALL_HINT}') from None
        ns = type('Transport', (), {})()
        ns.client, ns.protocol, ns.d = client, protocol, d
        ns.Transport = _transport_class(client.Urllib3HttpGitClient)
        _T = ns
    return _T


def _origin(url):
    """(scheme, host, port) of URL, with the scheme's default port made explicit."""
    from urllib.parse import urlsplit
    parts = urlsplit(url)
    return (parts.scheme.lower(), (parts.hostname or '').lower(),
            parts.port or {'http': 80, 'https': 443}.get(parts.scheme.lower()))


def _transport_class(base):
    class Transport(base):
        """Dulwich's urllib3 smart-HTTP client with no git configuration (so no
        ``http.extraHeader``, credential helper, ``insteadOf`` or ``sslVerify``) and the
        module's credential: its ``Authorization`` header goes only to the remote's origin; a
        redirect elsewhere carries none. Every non-200 answer becomes ``_HttpStatus``."""

        def __init__(self, base_url, credential):
            import urllib3
            self._aieh_authorization = None if credential is None else credential.authorization()
            self._aieh_origin = _origin(base_url)
            super().__init__(base_url, config=None, timeout=TRANSPORT_TIMEOUT_S)
            # One attempt per request, as git makes (urllib3 would retry a failed connection or
            # read three times); redirects are still followed.
            self.pool_manager.connection_pool_kw['retries'] = urllib3.util.Retry(
                total=None, connect=0, read=0, status=0, other=0, redirect=5)

        def _http_request(self, url, headers=None, data=None, raise_for_status=True):
            headers = dict(headers or {})
            if self._aieh_authorization is not None and _origin(url) == self._aieh_origin:
                headers['Authorization'] = self._aieh_authorization
            resp, read = super()._http_request(url, headers, data, raise_for_status=False)
            if raise_for_status and resp.status != 200:
                status = resp.status
                resp.close()
                raise _HttpStatus(status, url)
            return resp, read

    return Transport


def _remote(url, credential):
    """The module's client for the smart-HTTP URL, and the path on it."""
    from urllib.parse import urlsplit
    if not isinstance(url, str) or _CONTROL.search(url):
        raise ValueError('the remote URL must be text without control characters')
    parts = urlsplit(url)
    if parts.scheme.lower() not in ('http', 'https') or not parts.hostname:
        raise ValueError(f'only http and https remotes are supported (no ssh, git, file or local paths): {url!r}')
    if parts.username is not None or parts.password is not None:
        raise ValueError('the remote URL must not hold credentials: pass a Credential, held in memory')
    if parts.query or parts.fragment:
        raise ValueError('the remote URL must have no query or fragment')
    if credential is not None and not isinstance(credential, Credential):
        raise ValueError('credential must be a Credential or None')
    t = _transport_modules()
    netloc = parts.netloc
    return t, t.Transport(f'{parts.scheme.lower()}://{netloc}/', credential), parts.path or '/'


def _remote_failure(what, url, exc, refused_code):
    """The RepositoryError for EXC raised while talking to URL."""
    if isinstance(exc, RepositoryError):
        return exc
    if isinstance(exc, _HttpStatus):
        if exc.status in _REMOTE_REFUSED_STATUSES:
            return RepositoryError(refused_code, f'{what} {url}: the server refused the request (HTTP {exc.status})',
                                   status=exc.status)
        return RepositoryError('REMOTE_FAILED', f'{what} {url}: HTTP {exc.status}', status=exc.status)
    return RepositoryError('REMOTE_FAILED', f'{what} {url}: {type(exc).__name__}: {exc}')


def _as_text(value):
    return value.decode('utf-8', 'surrogateescape') if isinstance(value, bytes) else value


def ls_remote(url, credential=None, *, names=None):
    """The references of the smart-HTTP remote URL, as ``git ls-remote URL`` lists them:
    ``{name: object id}`` in the server's order, with each annotated tag's peeled commit under
    ``<tag>^{}``; an unborn HEAD is left out. NAMES, full reference names, keeps only those (and
    their ``^{}`` entries) and asks the server for no others. CREDENTIAL (a ``Credential``) is
    sent to the URL's origin only. ``REMOTE_REFUSED`` (HTTP 401 or 403), ``REMOTE_FAILED``
    (anything else). Launches no process."""
    if names is not None:
        if isinstance(names, str) or not all(isinstance(n, str) and n.startswith('refs/') and refname_valid(n)
                                              for n in names):
            raise ValueError('names must be a list of full reference names')
    t, client, path = _remote(url, credential)
    prefixes = None if names is None else [n.encode('utf-8') for n in names]
    failure = None
    try:
        result = client.get_refs(path, ref_prefix=prefixes)
    except Exception as exc:
        failure = _remote_failure('ls-remote', url, exc, 'REMOTE_REFUSED')
    if failure is not None:
        raise failure
    wanted = None if names is None else set(names)
    refs = {}
    for name, oid in result.refs.items():
        if oid is None:
            continue
        text = _as_text(name)
        if wanted is not None and text.removesuffix('^{}') not in wanted:
            continue
        refs[text] = _as_text(oid)
    return refs


def clone(url, destination, credential=None):
    """``git clone --bare URL DESTINATION`` over smart HTTP: a new bare repository holding the
    remote's branches (``refs/heads/*``) and tags (``refs/tags/*``) under their own names, HEAD
    pointing where the remote's HEAD points, and ``remote.origin.url`` (no credential in it).
    DESTINATION must not exist (its parent must). No git configuration is read and no hook
    runs. Returns ``{name: object id}`` of the references written. ``REMOTE_REFUSED`` (HTTP 401
    or 403), ``REMOTE_FAILED`` (anything else; DESTINATION is removed). Launches no process."""
    t, client, path = _remote(url, credential)
    dest = os.path.abspath(os.fspath(destination))
    if os.path.lexists(dest):
        raise ValueError(f'{dest} exists; clone makes a new repository')
    if not os.path.isdir(os.path.dirname(dest)):
        raise ValueError(f'the parent of {dest} is not a directory')
    d = t.d
    keep = (b'refs/heads/', b'refs/tags/')
    failure, target, written = None, None, {}
    try:
        target = d.repo.Repo.init_bare(dest, mkdir=True, config=d.config.StackedConfig([]),
                                       default_branch=b'master')

        def wants(refs, depth=None):
            return sorted({oid for name, oid in refs.items()
                           if oid is not None and name.startswith(keep) and not name.endswith(b'^{}')
                           and oid not in target.object_store})

        result = client.fetch(path, target, determine_wants=wants, ref_prefix=[b'HEAD', *keep])
        for name, oid in result.refs.items():
            if oid is not None and name.startswith(keep) and not name.endswith(b'^{}'):
                target.refs[name] = oid
                written[_as_text(name)] = _as_text(oid)
        head = result.symrefs.get(b'HEAD')
        if head is not None and head.startswith(b'refs/heads/'):
            target.refs.set_symbolic_ref(b'HEAD', head)
        elif result.refs.get(b'HEAD') is not None:
            target.refs[b'HEAD'] = result.refs[b'HEAD']
        config = target.get_config()
        config.set((b'remote', b'origin'), b'url', url.encode('utf-8'))
        config.write_to_path()
    except Exception as exc:
        failure = _remote_failure('clone', url, exc, 'REMOTE_REFUSED')
    finally:
        if target is not None:
            target.close()
    if failure is not None:
        import shutil

        def retry(func, path, _exc):
            os.chmod(path, stat.S_IWRITE)
            func(path)
        if os.path.lexists(dest):
            shutil.rmtree(dest, onexc=retry)
        raise failure
    return written


# ---------------------------------------------------------------------------- the repository

class _Missing(Exception):
    """git dies or answers nothing: the name resolves to no object."""


class _DateGap(Exception):
    """Resolution reached git's reading of a reflog date (the @{<date>} gap)."""


def _date_gap(name):
    return RepositoryError('REVISION_INVALID', f'{name!r} does not resolve without git reading the text after its '
                           'last @{ as a reflog date, the @{<date>} gap (decision 0014 section 2)',
                           gap='the reflog date @{<date>} (git fallback)')


def _now_and_offset():
    """(seconds since the epoch, the local offset east of UTC in seconds) now."""
    now = time.time()
    return int(now), time.localtime(now).tm_gmtoff


def _parse(type_num, data, oid, object_format):
    """The Dulwich object of verified content DATA (its id OID already checked)."""
    return dulwich_modules().objects.ShaFile.from_raw_string(type_num, data, oid.encode('ascii'), object_format=object_format)


class Repository:
    """One opened repository. Close it (or use it as a context manager) when done."""

    def __init__(self, repo, policy, root):
        self._dul = repo
        self.policy = policy
        self.root = root
        fmt = repo.object_format
        self.object_format = fmt.name
        self._hexsz = fmt.hex_length
        self._packed = None
        self._replace = None
        self._index_sizes = {}
        self._objects = collections.OrderedDict()  # oid -> [type name, bytes, parsed ShaFile or None]
        self._object_bytes = 0
        try:
            storage = repo.get_config().get((b'extensions',), b'refstorage')
        except KeyError:
            storage = b'files'
        if storage.lower() != b'files':
            repo.close()
            raise RepositoryError('GIT_FAILED', f'reference storage {storage.decode("utf-8", "replace")} is not '
                                  'read by this module (only the files backend)')

    # -- lifetime and facts

    def close(self):
        self._objects.clear()
        self._object_bytes = 0
        repo, self._dul = self._dul, None
        if repo is not None:
            try:
                repo.close()
            except BufferError:
                # A pack whose read failed may still hold an exported buffer (the failure was
                # already raised as GIT_FAILED): release the buffers and close again; closing
                # must not crash.
                import gc
                gc.collect()
                try:
                    repo.close()
                except BufferError:
                    pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    @property
    def bare(self):
        return self.root is None

    @property
    def controldir(self):
        return self._dul.controldir()

    @property
    def commondir(self):
        return self._dul.commondir()

    @property
    def config_sources(self):
        """Every configuration file read so far, in reading order (the repository's own config is
        read to open it under every policy, for its format; see the README)."""
        self._dul.get_config_stack()
        return tuple(self._dul._aieh_sources)

    def _config(self):
        return self._dul.get_config_stack()

    def _config_bool(self, section, name, default):
        try:
            return self._config().get_boolean((section,), name, default)
        except ValueError:
            return default

    # -- objects

    def _boundary(self, oid, call, *args):
        """CALL(*ARGS) at the module boundary (decision 0014 section 3): KeyError (no such
        object) passes; any other Dulwich or OS error becomes GIT_FAILED naming OID, raised after
        the failing call's frames are released (they may pin a pack's buffer, which would keep
        the pack open after close)."""
        failure = None
        try:
            return call(*args)
        except KeyError:
            raise
        except Exception as exc:
            failure = f'{type(exc).__name__}: {exc}'
        raise RepositoryError('GIT_FAILED', f'cannot read object {oid}: {failure}', object=oid)

    def replace_refs(self):
        """The replace references (``refs/replace/``, loose and packed) of the repository."""
        if self._replace is None:
            found = set()
            base = os.path.join(self._dul.commondir(), 'refs', 'replace')
            for top, _dirs, files in os.walk(base):
                for name in files:
                    found.add('/'.join(['refs', 'replace',
                                        *os.path.relpath(os.path.join(top, name), base).split(os.sep)]))
            found.update(name for name in self._packed_refs() if name.startswith('refs/replace/'))
            self._replace = sorted(found)
        return self._replace

    def _refuse_replacement(self):
        """git applies replace references to every object read (core.useReplaceRefs, default
        true); this module does not, so it refuses to read objects where git would replace them."""
        refs = self.replace_refs()
        if refs and self._config_bool(b'core', b'useReplaceRefs', True):
            raise RepositoryError('REPLACE_REFS_UNSUPPORTED', f'the repository has replace references ({refs[0]}'
                                  f'{" and others" if len(refs) > 1 else ""}), which git applies to object reads and '
                                  'this module does not', refs=refs)

    def _cached(self, oid):
        """The verified-object cache entry of OID, or None (OBJECT_CACHE_BYTES)."""
        self._refuse_replacement()
        entry = self._objects.get(oid)
        if entry is not None:
            self._objects.move_to_end(oid)
            return entry
        try:
            type_num, data = self._boundary(oid, self._dul.object_store.get_raw, oid.encode('ascii'))
        except KeyError:
            return None
        kind = _TYPE_NAMES.get(type_num)
        algorithm = hashlib.sha256 if self._hexsz == 64 else hashlib.sha1
        # Every object read is checked against its id before its content is used (Dulwich 1.2.21
        # does not check a loose object's id on this path).
        if kind is None or algorithm(b'%s %d\0' % (kind.encode(), len(data)) + data).hexdigest() != oid:
            raise RepositoryError('GIT_FAILED', f'cannot read object {oid}: its content does not hash to its id',
                                  object=oid)
        entry = [kind, data, None]
        if len(data) <= OBJECT_CACHE_BYTES // 8:
            self._objects[oid] = entry
            self._object_bytes += len(data)
            while self._object_bytes > OBJECT_CACHE_BYTES:
                _, (_, evicted, _) = self._objects.popitem(last=False)
                self._object_bytes -= len(evicted)
        return entry

    def _raw(self, oid):
        """(type name, bytes) of object OID, or None when the repository has none. The content
        hashed to OID when it was read."""
        entry = self._cached(oid)
        return None if entry is None else (entry[0], entry[1])

    def _object(self, oid):
        """The parsed object OID (a Dulwich ShaFile), or None when the repository has none: parsed
        from the verified bytes, once, not read again."""
        entry = self._cached(oid)
        if entry is None:
            return None
        if entry[2] is None:
            kind, data = entry[0], entry[1]
            entry[2] = self._boundary(oid, _parse, _TYPE_NUMS[kind], data, oid, self._dul.object_store.object_format)
        return entry[2]

    def _kind(self, oid):
        found = self._raw(oid)
        return found[0] if found else None

    def _deref_tag(self, oid):
        """Follow tags; the first non-tag object id, or None (missing)."""
        seen = 0
        while True:
            obj = self._object(oid)
            if obj is None:
                return None
            if obj.type_name != b'tag':
                return oid
            oid = obj.object[1].decode('ascii')
            seen += 1
            if seen > 1000:
                return None

    def _commit_reference(self, oid):
        """git's lookup_commit_reference: OID dereferenced to a commit, or None."""
        target = self._deref_tag(oid)
        if target is None or self._kind(target) != 'commit':
            return None
        return target

    def _parents(self, oid):
        commit = self._object(oid)  # verified, so the parents provider reads nothing again
        if commit is None:
            return None
        try:
            return [p.decode('ascii') for p in self._boundary(oid, self._dul.get_parents, oid.encode('ascii'), commit)]
        except KeyError:
            return None

    def _peel_to_type(self, oid, wanted):
        """git's peel_to_type: tags to their targets and commits to their trees until WANTED
        ('commit', 'tree', 'blob', 'tag' or 'object'), else None."""
        while True:
            kind = self._kind(oid)
            if kind is None:
                return None
            if wanted == 'object' or kind == wanted:
                return oid
            if kind == 'tag':
                oid = self._object(oid).object[1].decode('ascii')
            elif kind == 'commit':
                oid = self._object(oid).tree.decode('ascii')
            else:
                return None

    def _to_tree(self, oid):
        """git's read_object_with_reference(OBJ_TREE)."""
        for _ in range(1000):
            kind = self._kind(oid)
            if kind == 'tree':
                return oid
            if kind == 'commit':
                oid = self._object(oid).tree.decode('ascii')
            elif kind == 'tag':
                oid = self._object(oid).object[1].decode('ascii')
            else:
                return None
        return None

    def _tree_items(self, oid):
        """[(name str, mode int, oid str)] of tree OID in git's order."""
        tree = self._object(oid)
        if tree is None or tree.type_name != b'tree':
            raise RepositoryError('GIT_FAILED', f'cannot read tree {oid}: no such tree', object=oid)
        items = self._boundary(oid, lambda: list(tree.iteritems()))
        return [(entry.path.decode('utf-8', 'surrogateescape'), entry.mode, entry.sha.decode('ascii'))
                for entry in items]

    def _tree_entry(self, tree_oid, path):
        """git's get_tree_entry: (oid, mode) of PATH below the tree TREE_OID refers to, or None."""
        root = self._to_tree(tree_oid)
        if root is None:
            return None
        if path == '':
            return root, _S_IFDIR
        current = root
        remaining = path
        while True:
            tree = self._object(current)
            if tree is None or tree.type_name != b'tree':
                return None
            name, sep, rest = remaining.partition('/')
            try:
                mode, sha = self._boundary(current, tree.__getitem__, name.encode('utf-8', 'surrogateescape'))
            except KeyError:
                return None
            sha = sha.decode('ascii')
            if not sep:
                return sha, mode
            if mode & _S_IFMT != _S_IFDIR:
                return None
            if rest == '':
                return sha, mode
            remaining = rest
            sub = self._to_tree(sha)
            if sub is None:
                return None
            current = sub

    # -- references (read from the repository's files as git's files backend reads them)

    def _ref_base(self, name):
        """(directory, name below it) where git's files backend keeps the reference NAME:
        per-worktree references (one-level upper-case names such as HEAD and ORIG_HEAD,
        refs/bisect/, refs/worktree/, refs/rewritten/) in this worktree's git directory,
        main-worktree/ and worktrees/<id>/ in those worktrees', all others in the common one."""
        common = self._dul.commondir()
        if name.startswith('main-worktree/'):
            return common, name[len('main-worktree/'):]
        if name.startswith('worktrees/'):
            parts = name.split('/', 2)
            if len(parts) == 3:
                return os.path.join(common, 'worktrees', parts[1]), parts[2]
        if name.startswith(_PER_WORKTREE_PREFIXES) or ('/' not in name and _pseudoref_syntax(name)):
            return self._dul.controldir(), name
        return common, name

    def _packed_refs(self):
        if self._packed is None:
            packed = {}
            path = os.path.join(self._dul.commondir(), 'packed-refs')
            try:
                with open(path, 'rb') as handle:
                    data = handle.read()
            except FileNotFoundError:
                data = b''
            except OSError as exc:
                raise RepositoryError('GIT_FAILED', f'cannot read {path}: {exc}') from None
            for line in data.splitlines():
                if not line or line[:1] in (b'#', b'^'):
                    continue
                oid, _, name = line.partition(b' ')
                packed[name.decode('utf-8', 'surrogateescape')] = oid.decode('ascii', 'replace').lower()
            self._packed = packed
        return self._packed

    def _read_raw_ref(self, name):
        """('symref', target) or ('oid', id) for the reference NAME, loose before packed, or None
        (absent or broken). NAME is a valid reference name, so its path stays below the git
        directory."""
        base, rel = self._ref_base(name)
        path = os.path.join(base, *rel.split('/'))
        data = None
        if os.path.isfile(path):
            try:
                with open(path, 'rb') as handle:
                    data = handle.read(4096)
            except OSError as exc:
                raise RepositoryError('GIT_FAILED', f'cannot read the reference {name}: {exc}') from None
        if data is not None:
            if data.startswith(b'ref:'):
                return 'symref', data[4:].strip().decode('utf-8', 'surrogateescape')
            text = data[:self._hexsz].decode('ascii', 'replace')
            rest = data[self._hexsz:self._hexsz + 1]
            if len(text) == self._hexsz and all(ch in _HEX for ch in text) and (not rest or rest.isspace()):
                return 'oid', text.lower()
            return None
        if base == self._dul.commondir() and rel == name:
            oid = self._packed_refs().get(name)
            if oid is not None:
                return 'oid', oid
        return None

    def _ref_value(self, name):
        """(resolved full name, oid) of the reference NAME, following up to five symbolic
        references as git does, or None (absent, dangling, broken or not a valid name)."""
        if not refname_valid(name, onelevel=True):
            return None
        for _ in range(_SYMREF_MAX_DEPTH):
            found = self._read_raw_ref(name)
            if found is None:
                return None
            kind, value = found
            if kind == 'oid':
                return name, value
            if not refname_valid(value, onelevel=True):
                return None
            name = value
        return None

    def _dwim_candidates(self, text):
        rules = [text] if refname_valid(text, onelevel=True) else []
        for pattern in ('refs/{}', 'refs/tags/{}', 'refs/heads/{}', 'refs/remotes/{}', 'refs/remotes/{}/HEAD'):
            full = pattern.format(text)
            if refname_valid(full):
                rules.append(full)
        return rules

    def _dwim_ref(self, text):
        """git's repo_dwim_ref: (resolved full name, oid) of the first rule that resolves."""
        for candidate in self._dwim_candidates(text):
            found = self._ref_value(candidate)
            if found is not None:
                return found
        return None

    def _reflog_path(self, refname):
        base, rel = self._ref_base(refname)
        return os.path.join(base, 'logs', *rel.split('/'))

    def _reflog_exists(self, refname):
        return os.path.isfile(self._reflog_path(refname))

    def _dwim_log(self, text):
        """git's repo_dwim_log: (log name, current oid) of the first rule whose reflog exists."""
        for candidate in self._dwim_candidates(text):
            found = self._ref_value(candidate)
            if found is None:
                continue
            resolved, oid = found
            if self._reflog_exists(candidate):
                return candidate, oid
            if resolved != candidate and self._reflog_exists(resolved):
                return resolved, oid
        return None

    def _reflog(self, refname):
        """[(old, new, timestamp)] of REFNAME's reflog, oldest first; lines git would skip as
        corrupt (no trailing newline, a malformed identity or time) are skipped."""
        path = self._reflog_path(refname)
        try:
            with open(path, 'rb') as handle:
                data = handle.read()
        except FileNotFoundError:
            return []
        except OSError as exc:
            raise RepositoryError('GIT_FAILED', f'cannot read the reflog of {refname}: {exc}') from None
        size, entries = self._hexsz, []
        for line in data.splitlines(keepends=True):
            if not line.endswith(b'\n') or len(line) < 2 * size + 2:
                continue
            old, new = line[:size].decode('ascii', 'replace'), line[size + 1:2 * size + 1].decode('ascii', 'replace')
            if line[size:size + 1] != b' ' or line[2 * size + 1:2 * size + 2] != b' ' \
                    or not all(ch in _HEX for ch in old + new):
                continue
            rest = line[2 * size + 2:]
            email_end = rest.find(b'>')
            if email_end < 0 or rest[email_end + 1:email_end + 2] != b' ':
                continue
            match = _REFLOG_TIME.match(rest, email_end + 2)
            if not match or int(match.group(1)) == 0:
                continue
            entries.append((old.lower(), new.lower(), int(match.group(1))))
        return entries

    def _read_ref_at(self, refname, nth, current):
        """git's read_ref_at for the Nth entry (at_time 0), as get_oid_basic uses it."""
        entries = self._reflog(refname)
        null = '0' * self._hexsz
        if not entries:
            if nth == 0:
                return current
            raise _Missing
        cnt, ooid, result = nth, None, current
        for old, new, timestamp in reversed(entries):
            if cnt == 0:
                if ooid is not None and ooid != null:
                    result = new
                elif timestamp == 0:
                    result = new
                return result
            ooid = old
            cnt -= 1
        oldest_old = entries[0][0]
        if nth == len(entries) and oldest_old != null:
            return oldest_old
        raise _Missing

    # -- the revision grammar (git's object-name.c)

    def _short_oid(self, text, hint):
        if not (_MINIMUM_ABBREV <= len(text) <= self._hexsz) or not all(ch in _HEX for ch in text):
            return None
        prefix = text.lower()
        try:
            candidates = sorted({sha.decode('ascii') for sha in
                                 self._dul.object_store.iter_prefix(prefix.encode('ascii'))})
        except Exception as exc:
            raise RepositoryError('GIT_FAILED', f'cannot search objects by prefix {prefix}: '
                                  f'{type(exc).__name__}: {exc}') from None
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]
        if hint is None:
            return None
        fitting = [oid for oid in candidates if self._fits(oid, hint)]
        return fitting[0] if len(fitting) == 1 else None

    def _fits(self, oid, hint):
        kind = self._kind(oid)
        if hint == _COMMIT:
            return kind == 'commit'
        wanted = ('commit',) if hint == _COMMITTISH else ('commit', 'tree')
        if kind in wanted:
            return True
        if kind != 'tag':
            return False
        target = self._deref_tag(oid)
        return target is not None and self._kind(target) in wanted

    def _describe(self, text):
        """git describe output, <anything>-<number>-g<hex>: the commit the abbreviation names."""
        for p in range(len(text) - 1, 1, -1):
            if text[p] == 'g' and text[p - 1] == '-' and _DESCRIBE_TAIL.search(text, 0, p - 1):
                return self._short_oid(text[p + 1:], _COMMIT)
        return None

    def _peel_onion(self, text, hint):
        if len(text) < 4 or text[-1] != '}':
            return None
        sp = len(text) - 1
        while sp >= 0:
            if text[sp] == '{' and sp > 0 and text[sp - 1] == '^':
                break
            sp -= 1
        if sp <= 0:
            return None
        rest = text[sp + 1:]
        for name in ('commit', 'tag', 'tree', 'blob', 'object'):
            if rest.startswith(name + '}'):
                wanted = name
                break
        else:
            if rest.startswith('}'):
                wanted = None
            else:
                return None  # '/' (a search) never reaches here: refused as a gap
        inner_hint = _COMMITTISH if wanted == 'commit' else _TREEISH if wanted == 'tree' else None
        outer = self._oid_1(text[:sp - 1], inner_hint)
        if outer is None or self._kind(outer) is None:
            return None
        if wanted is None:
            return self._deref_tag(outer)
        return self._peel_to_type(outer, wanted)

    def _oid_basic(self, text, hint):
        if len(text) == self._hexsz and all(ch in _HEX for ch in text):
            return text.lower()
        base, reflog = text, None
        if text.endswith('}'):
            for at in range(len(text) - 4, -1, -1):
                if text[at] == '@' and text[at + 1] == '{':
                    if text[at + 2] == '-':
                        return None  # @{-N}: refused as a gap before any access; elsewhere git fails
                    if not text[at:].lower().startswith(('@{upstream}', '@{u}', '@{push}')):
                        reflog = text[at + 2:-1]
                        base = text[:at]
                    break
        if base and _ambiguous_path(base):
            return None
        if base == '@':
            base = 'HEAD'
        if reflog is None:
            found = self._dwim_ref(base)
            return found[1] if found else None
        found = self._dwim_ref('HEAD') if not base else self._dwim_log(base)
        if found is None:
            return None
        log, current = found
        if not reflog.isascii() or not reflog.isdigit() or int(reflog) >= _REFLOG_DATE_FLOOR:
            # git reads this selector as a date (approxidate) against the wall clock and time
            # zone: the @{<date>} gap. A selector written as a date is refused before any access
            # (gap_form); this one arises when a name holding @{N} did not resolve otherwise and
            # git rereads the text after its last @{ as a date.
            raise _DateGap(text)
        return self._read_ref_at(log, int(reflog), current)

    def _oid_1(self, text, hint=None):
        """git's get_oid_1."""
        i = len(text) - 1
        while i >= 0 and text[i] in _DIGITS:
            i -= 1
        if i >= 0 and text[i] in '~^':
            suffix, base, digits = text[i], text[:i], text[i + 1:]
            num = int(digits) if digits else 1
            if num > _INT_MAX:
                return None
            start = self._oid_1(base, _COMMITTISH)
            if start is None:
                return None
            commit = self._commit_reference(start)
            if commit is None:
                return None
            if suffix == '^':
                if num == 0:
                    return commit
                parents = self._parents(commit)
                return parents[num - 1] if parents is not None and len(parents) >= num else None
            for _ in range(num):
                parents = self._parents(commit)
                if not parents:
                    return None
                commit = parents[0]
            return commit
        found = self._peel_onion(text, hint)
        if found is not None:
            return found
        found = self._oid_basic(text, hint)
        if found is not None:
            return found
        found = self._describe(text)
        if found is not None:
            return found
        return self._short_oid(text, hint)

    def _relative(self, path):
        """git's resolve_relative_path from the work tree root: './' and '../' forms, or PATH."""
        if not (path.startswith('./') or path.startswith('../')):
            return path
        if self.bare:
            raise _Missing
        parts = []
        for part in path.split('/'):
            if part in ('', '.'):
                continue
            if part == '..':
                if not parts:
                    raise _Missing  # outside the repository
                parts.pop()
            else:
                parts.append(part)
        return '/'.join(parts) + ('/' if path.endswith('/') and parts else '')

    def _index_entry(self, path, stage):
        if self.bare:
            return None
        for entry in self._index_rows():
            if entry.path == path and entry.stage == stage:
                return entry.oid
        return None

    def _resolve(self, name, shown=None):
        """git's get_oid_with_context: the object id NAME names, or None."""
        try:
            return self._resolve_1(name)
        except _DateGap:
            raise _date_gap(shown or name) from None

    def _resolve_1(self, name):
        try:
            found = self._oid_1(name)
            if found is not None:
                return found
            if name.startswith(':'):
                if len(name) >= 3 and name[2] == ':' and name[1] in '0123':
                    stage, path = int(name[1]), name[3:]
                else:
                    stage, path = 0, name[1:]
                return self._index_entry(self._relative(path), stage)
            revision = _revision_part(name)
            if revision is None or revision == name:
                return None
            tree = self._oid_1(revision, _TREEISH)
            if tree is None:
                return None
            entry = self._tree_entry(tree, self._relative(name[len(revision) + 1:]))
            return entry[0] if entry else None
        except _Missing:
            return None

    # -- public reads

    def commit(self, revision):
        """The full commit id ``git rev-parse --verify <revision>^{commit}`` prints, or None."""
        check_revision(revision)
        oid = self._resolve(revision + '^{commit}', revision)
        if oid is None or self._kind(oid) != 'commit':
            return None
        return oid

    def object_id(self, name):
        """The object id NAME names when the repository has that object (``git cat-file -t``
        succeeds), else None."""
        check_object_name(name)
        oid = self._resolve(name)
        if oid is None or self._kind(oid) is None:
            return None
        return oid

    def object_kind(self, name):
        """The type of object NAME ('blob', 'tree', 'commit' or 'tag'), or None."""
        found = self.read(name)
        return found[1] if found else None

    def read(self, name):
        """(oid, type, bytes) of object NAME, or None."""
        check_object_name(name)
        oid = self._resolve(name)
        if oid is None:
            return None
        found = self._raw(oid)
        if found is None:
            return None
        return oid, found[0], found[1]

    def blob(self, commit, path):
        """The bytes of the blob at PATH in COMMIT; GIT_FAILED when there is none."""
        name = f'{commit}:{path}'
        found = self.read(name)
        if found is None or found[1] != 'blob':
            raise RepositoryError('GIT_FAILED', f'blob {name}: '
                                  + ('no such object' if found is None else f'a {found[1]}, not a blob'))
        return found[2]

    def files(self, commit, directory):
        """``git ls-tree -r --name-only <commit> -- <directory>/``: the paths below DIRECTORY,
        in git's order; [] when it is absent or not a directory."""
        check_object_name(commit)
        directory = _check_path(directory, 'directory')
        tree = self._tree_of(commit)
        entry = self._tree_entry(tree, directory)
        if entry is None or entry[1] & _S_IFMT != _S_IFDIR:
            return []
        out = []
        self._walk(entry[0], directory, out)
        return [path for path, _mode, _oid in out]

    def _tree_of(self, name):
        try:
            oid = self._resolve(name)
        except _Missing:
            oid = None
        tree = self._to_tree(oid) if oid is not None else None
        if tree is None:
            raise RepositoryError('GIT_FAILED', f'not a tree-ish: {name}', object=name)
        return tree

    def _walk(self, tree_oid, prefix, out):
        for name, mode, oid in self._tree_items(tree_oid):
            path = f'{prefix}/{name}' if prefix else name
            if mode & _S_IFMT == _S_IFDIR:
                self._walk(oid, path, out)
            else:
                out.append((path, mode, oid))

    def head(self):
        """HEAD: its commit id (``rev-parse --verify HEAD``) and the branch it names."""
        found = self._read_raw_ref('HEAD')
        if found is None:
            return Head(None, None)
        if found[0] == 'oid':
            return Head(found[1], None)
        resolved = self._ref_value(found[1])
        return Head(resolved[1] if resolved else None, found[1])

    def full_name(self, name):
        """The full reference name ``git rev-parse --verify --quiet --symbolic-full-name NAME``
        prints, or None (F-10.4): NAME must name an object (``--verify``), and is then read as a
        reference in git's order (``repo_dwim_ref``: ``NAME``, ``refs/NAME``, ``refs/tags/NAME``,
        ``refs/heads/NAME``, ``refs/remotes/NAME``, ``refs/remotes/NAME/HEAD``; ``@`` is HEAD),
        following symbolic references to the name they end at. None when NAME is no reference
        (an object id, a navigation, a reflog entry, a path) and when it is ambiguous: when more
        than one rule resolves (a tag shadowing a branch), git prints nothing, unless
        ``core.warnAmbiguousRefs`` is false, when the first rule wins."""
        check_revision(name)
        if self.object_id(name) is None:
            return None
        text = 'HEAD' if name == '@' else name
        warn = self._config_bool(b'core', b'warnambiguousrefs', True)
        found = []
        for candidate in self._dwim_candidates(text):
            resolved = self._ref_value(candidate)
            if resolved is not None:
                found.append(resolved[0])
                if not warn:
                    break
        return found[0] if len(found) == 1 else None

    # -- export (decision 0014 section 4)

    def export_tree(self, commit, subtree, destination):
        """Write the blob bytes of SUBTREE ('.' for the whole tree) of COMMIT into the empty
        directory DESTINATION, each at its repository-relative path: no end-of-line conversion,
        no attribute filtering (export-ignore included), regular files 0644 and executables
        0755 where the OS has modes, a gitlink as an empty directory, a symbolic link as a link
        only when its target stays inside DESTINATION. Refused (EXPORT_REFUSED) before anything
        is written: an unsafe name, an escaping link, a destination that is not an empty
        directory. Returns counts."""
        check_object_name(commit)
        subtree = _check_path(subtree, 'subtree', allow_root=True)
        dest = Path(destination)
        try:
            if not dest.is_dir() or any(dest.iterdir()):
                raise RepositoryError('EXPORT_REFUSED', f'{dest} is not an empty directory')
        except OSError as exc:
            raise RepositoryError('EXPORT_REFUSED', f'{dest}: {exc}') from None
        tree = self._tree_of(commit)
        entries = []
        if subtree == '':
            self._walk(tree, '', entries)
        else:
            entry = self._tree_entry(tree, subtree)
            if entry is None:
                raise RepositoryError('GIT_FAILED', f'{commit} has no path {subtree}', object=f'{commit}:{subtree}')
            if entry[1] & _S_IFMT == _S_IFDIR:
                self._walk(entry[0], subtree, entries)
            else:
                entries.append((subtree, entry[1], entry[0]))
        links = {path for path, mode, _ in entries if mode & _S_IFMT == _S_IFLNK}
        dirs = {path for path, mode, _ in entries if mode & _S_IFMT == _S_IFGITLINK}
        for path, _mode, _oid in entries:
            for part in path.split('/'):
                why = _unsafe_component(part)
                if why:
                    raise RepositoryError('EXPORT_REFUSED', f'{path}: {why}', path=path)
        targets = {}
        oids = {path: oid for path, _mode, oid in entries}
        for path in sorted(links):
            oid = oids[path]
            found = self._raw(oid)
            if found is None:
                raise RepositoryError('GIT_FAILED', f'cannot read link {path}: no such object {oid}', object=oid)
            targets[path] = _link_target(path, found[1], links)
        counts = {'files': 0, 'links': 0, 'directories': 0, 'bytes': 0}
        try:
            for path, mode, oid in entries:
                kind = mode & _S_IFMT
                target = dest.joinpath(*path.split('/'))
                target.parent.mkdir(parents=True, exist_ok=True)
                if kind == _S_IFGITLINK:
                    target.mkdir()
                    counts['directories'] += 1
                elif kind == _S_IFREG:
                    found = self._raw(oid)
                    if found is None or found[0] != 'blob':
                        raise RepositoryError('GIT_FAILED', f'cannot read {path}: no such blob {oid}', object=oid)
                    with open(target, 'xb') as handle:
                        handle.write(found[1])
                    if not _WINDOWS:
                        os.chmod(target, 0o755 if mode & 0o111 else 0o644)
                    counts['files'] += 1
                    counts['bytes'] += len(found[1])
            for path in sorted(links):
                target = dest.joinpath(*path.split('/'))
                link = targets[path]
                is_dir = _link_points_to_directory(path, link, entries, dirs)
                # Windows resolves a relative link only through '\' (the target holds no '\').
                os.symlink(link.replace('/', '\\') if _WINDOWS else link, target, target_is_directory=is_dir)
                counts['links'] += 1
        except RepositoryError:
            raise
        except OSError as exc:
            raise RepositoryError('EXPORT_REFUSED', f'cannot write the export into {dest}: '
                                  f'{type(exc).__name__}: {exc}') from None
        return counts

    # -- index, status and listing

    def _index(self):
        if self.bare:
            raise RepositoryError('GIT_FAILED', 'a bare repository has no index')
        try:
            return self._dul.open_index()
        except Exception as exc:
            raise RepositoryError('GIT_FAILED', f'cannot read the index: {type(exc).__name__}: {exc}') from None

    def _index_rows(self):
        d = dulwich_modules()
        index = self._index()
        rows, sizes = [], {}
        try:
            for path, entry in index.iteritems():
                name = path.decode('utf-8', 'surrogateescape')
                if isinstance(entry, d.index.ConflictedIndexEntry):
                    for stage, part in ((1, entry.ancestor), (2, entry.this), (3, entry.other)):
                        if part is not None:
                            rows.append(IndexEntry(part.mode, part.sha.decode('ascii'), stage, name))
                else:
                    rows.append(IndexEntry(entry.mode, entry.sha.decode('ascii'), 0, name))
                    sizes[name] = entry.size
        except Exception as exc:
            raise RepositoryError('GIT_FAILED', f'cannot read the index: {type(exc).__name__}: {exc}') from None
        rows.sort(key=lambda row: (row.path.encode('utf-8', 'surrogateescape'), row.stage))
        self._index_sizes = sizes
        return rows

    def index_entries(self):
        """``git ls-files -s``: every index entry (mode, oid, stage, path) in index order."""
        return list(self._index_rows())

    def _require_work_tree(self):
        if self.bare:
            raise RepositoryError('GIT_FAILED', 'a bare repository has no work tree')

    def status(self, paths=None, untracked='no'):
        """``git status --porcelain=v1 -z --no-renames --untracked-files=<untracked> --
        <paths>`` (literal paths): tracked changes, then untracked paths, each sorted. Renames
        are not detected. A path whose content git would pass through a configured filter
        driver or a working-tree-encoding is refused (FILTER_UNSUPPORTED): converting it needs a
        process or an encoding this module does not run."""
        self._require_work_tree()
        if untracked not in UNTRACKED_MODES:
            raise ValueError(f'untracked must be one of {UNTRACKED_MODES}')
        selected = self._path_filter(paths)
        self._check_attribute_files()
        rows = self._index_rows()
        stages, index = {}, {}
        for row in rows:
            stages.setdefault(row.path, set()).add(row.stage)
            if row.stage == 0:
                index[row.path] = row
        head = self.head().commit
        head_files = {}
        if head is not None:
            tree = self._to_tree(head)
            if tree is not None:
                out = []
                self._walk(tree, '', out)
                head_files = {path: (mode, oid) for path, mode, oid in out}
        checker = _WorktreeChecker(self, index, self._index_sizes)
        changes = []
        for path in sorted(set(stages) | set(head_files), key=lambda p: p.encode('utf-8', 'surrogateescape')):
            if not selected(path):
                continue
            conflict = stages.get(path, set()) - {0}
            if conflict:
                mask = sum(1 << (s - 1) for s in conflict)
                changes.append(StatusEntry(_UNMERGED[mask], path))
                continue
            x = ' '
            entry = index.get(path)
            if entry is None:
                x = 'D'
            elif path not in head_files:
                x = 'A'
            else:
                mode, oid = head_files[path]
                if (mode ^ entry.mode) & _S_IFMT:
                    x = 'T'
                elif oid != entry.oid or mode != entry.mode:
                    x = 'M'
            y = checker.change(entry) if entry is not None else ' '
            if x != ' ' or y != ' ':
                changes.append(StatusEntry(x + y, path))
        others = []
        if untracked != 'no':
            others = [StatusEntry('??', p) for p in self._untracked(set(stages), untracked, True)
                      if selected(p.rstrip('/'))]
        return changes + others

    def _path_filter(self, paths):
        if paths is None:
            return lambda path: True
        if isinstance(paths, str):
            raise ValueError('paths must be a list of repository-relative paths')
        literal = [_check_path(p, 'path', allow_root=True) for p in paths]
        if '' in literal:
            return lambda path: True
        return lambda path: any(path == p or path.startswith(p + '/') for p in literal)

    def listing(self, cached=True, others=False, exclude_standard=False):
        """``git ls-files -z [--cached] [--others] [--exclude-standard]``: untracked files first
        (sorted; a nested repository as 'dir/'), then the index entries in index order, one per
        stage."""
        self._require_work_tree()
        rows = self._index_rows()
        out = []
        if others:
            out.extend(self._untracked({row.path for row in rows}, 'all', exclude_standard))
        if cached or not others:
            out.extend(row.path for row in rows)
        return out

    def _excludes(self):
        """git's exclude levels for this work tree (``_Excludes``): ``core.excludesFile`` (else,
        under ``host``, ``$XDG_CONFIG_HOME/git/ignore``), then ``info/exclude``, then each
        directory's ``.gitignore``, read as the walk reaches it."""
        d = dulwich_modules()
        config = self._config()
        try:
            excludes = config.get((b'core',), b'excludesFile').decode('utf-8')
        except KeyError:
            excludes = d.config.get_xdg_config_home_path('git', 'ignore') if self.policy == 'host' else None
        ignorecase = self._config_bool(b'core', b'ignorecase', False)
        levels = []
        if excludes:
            # git resolves a relative path from the top of the work tree, where it runs.
            path = os.path.join(self.root, os.path.expanduser(excludes))
            patterns = _Excludes.read(path, ignorecase)
            if patterns is not None:
                levels.append(patterns)
                path = os.path.normpath(path)
                if path not in self._dul._aieh_sources:
                    self._dul._aieh_sources.append(path)
        info = _Excludes.read(os.path.join(self._dul.controldir(), 'info', 'exclude'), ignorecase)
        if info is not None:
            levels.append(info)
        return _Excludes(self.root, levels, ignorecase)

    def attribute_files(self):
        """The attribute files outside the repository git would read for this policy, lowest
        precedence first: under ``host`` the system file (unless ``GIT_ATTR_NOSYSTEM``) and the
        global one (``core.attributesFile``, else ``$XDG_CONFIG_HOME/git/attributes``); under
        ``repository`` only a ``core.attributesFile`` the repository's configuration sets."""
        if self.policy == 'none':
            return []
        files = []
        if self.policy == 'host' and not _env_bool('GIT_ATTR_NOSYSTEM'):
            system = system_file('gitattributes')
            if system:
                files.append(system)
        try:
            configured = self._config().get((b'core',), b'attributesFile').decode('utf-8')
        except KeyError:
            configured = None
        if configured:
            files.append(os.path.expanduser(configured))
        elif self.policy == 'host':
            files.append(_xdg_git_file('attributes'))
        return files

    def _check_attribute_files(self):
        """Read the attribute files of ``attribute_files``; refuse (ATTRIBUTES_UNSUPPORTED) when
        one sets an attribute ``status`` consults, which Dulwich's attribute matching does not
        apply. Attributes status never consults (``diff``, ``merge``, ...) cannot change its
        answer and are ignored. Each file read is listed in ``config_sources``."""
        for path in self.attribute_files():
            try:
                with open(path, 'rb') as handle:
                    text = handle.read().decode('utf-8', 'replace')
            except FileNotFoundError:
                continue
            except OSError as exc:
                raise RepositoryError('ATTRIBUTES_UNSUPPORTED', f'cannot read the attribute file {path}: {exc}',
                                      path=path) from None
            path = os.path.normpath(path)
            if path not in self._dul._aieh_sources:
                self._dul._aieh_sources.append(path)
            found = status_attribute_line(text)
            if found:
                lineno, attribute = found
                what = 'defines the macro' if attribute.startswith('[attr]') else 'sets'
                raise RepositoryError('ATTRIBUTES_UNSUPPORTED', f'{path}:{lineno} {what} {attribute}, which git '
                                      'applies to status and this module does not read from that file',
                                      path=path, line=lineno, attribute=attribute)

    def _untracked(self, tracked, mode, exclude_standard):
        """The untracked paths git's read_directory reports: files, a nested repository as
        'dir/', and in 'normal' mode an untracked directory with content as 'dir/'."""
        excludes = self._excludes() if exclude_standard else None
        ignorecase = excludes.ignorecase if excludes is not None else False
        tracked_dirs = set()
        for path in tracked:
            parts = path.split('/')
            for i in range(1, len(parts)):
                tracked_dirs.add('/'.join(parts[:i]))

        def ignored(rel, is_dir):
            return excludes is not None and excludes.excluded(rel, is_dir)

        def is_dot_git(name):
            return name.casefold() == '.git' if ignorecase or _WINDOWS else name == '.git'

        def has_content(full, rel):
            try:
                children = list(os.scandir(full))
            except OSError:
                return False
            for child in children:
                if is_dot_git(child.name):
                    continue
                child_rel = f'{rel}/{child.name}'
                if child.is_dir(follow_symlinks=False):
                    if ignored(child_rel, True):
                        continue
                    if _nested_repository(child.path) or has_content(child.path, child_rel):
                        return True
                elif not ignored(child_rel, False):
                    return True
            return False

        out = []

        def walk(full, rel):
            try:
                children = sorted(os.scandir(full), key=lambda e: e.name)
            except OSError:
                return
            for child in children:
                if is_dot_git(child.name):
                    continue
                child_rel = f'{rel}/{child.name}' if rel else child.name
                if child.is_dir(follow_symlinks=False):
                    if child_rel in tracked:
                        continue  # a gitlink's directory
                    if ignored(child_rel, True):
                        continue
                    if _nested_repository(child.path):
                        out.append(child_rel + '/')
                    elif child_rel in tracked_dirs or mode == 'all':
                        walk(child.path, child_rel)
                    elif has_content(child.path, child_rel):
                        out.append(child_rel + '/')
                else:
                    if child_rel in tracked or ignored(child_rel, False):
                        continue
                    out.append(child_rel)

        walk(self.root, '')
        out.sort(key=lambda p: p.encode('utf-8', 'surrogateescape'))
        return out

    # -- bundles (R5)

    def write_bundle(self, refs, destination):
        """Write a complete git bundle (no prerequisites) of the full reference names REFS to the
        new file DESTINATION (never overwritten): v2, or v3 with object-format=sha256 in a
        SHA-256 repository. Returns its parsed header with its recomputed pack trailer."""
        d = dulwich_modules()
        if isinstance(refs, str) or not refs:
            raise RepositoryError('BUNDLE_INVALID', 'refs must be a non-empty list of full reference names')
        values = {}
        for ref in refs:
            if not isinstance(ref, str) or not ref.startswith('refs/') or not refname_valid(ref):
                raise RepositoryError('BUNDLE_INVALID', f'not a full reference name: {ref!r}')
            found = self._ref_value(ref)
            if found is None or self._kind(found[1]) is None:
                raise RepositoryError('BUNDLE_INVALID', f'no such reference: {ref}')
            values[ref] = found[1]
        dest = Path(destination)
        if os.path.lexists(dest):
            raise RepositoryError('BUNDLE_INVALID', f'{dest} exists; a bundle is never overwritten')
        sha256 = self.object_format == 'sha256'
        bundle = d.bundle.Bundle()
        bundle.version = 3 if sha256 else 2
        bundle.capabilities = {'object-format': 'sha256'} if sha256 else {}
        bundle.prerequisites = []
        bundle.references = {ref.encode('utf-8'): oid.encode('ascii') for ref, oid in values.items()}
        try:
            count, objects = self._dul.generate_pack_data(have=set(), want=set(bundle.references.values()))
            bundle.pack_data = _PackData(count, list(objects), self._dul.object_format)
            with bundle, open(dest, 'xb') as handle:
                d.bundle.write_bundle(handle, bundle)
        except Exception as exc:
            if os.path.lexists(dest):
                os.remove(dest)
            if isinstance(exc, RepositoryError):
                raise
            raise RepositoryError('GIT_FAILED', f'cannot write the bundle {dest}: {type(exc).__name__}: {exc}') from None
        header = parse_bundle_header(dest)
        header['pack_trailer'] = pack_trailer(dest, header)
        return header

    # -- transports (F-10.6)

    def client_hooks(self):
        """The first client hook git would run for this repository, or None: ``core.hooksPath``
        set (in the repository's own configuration or the policy's), or a file under
        ``<common directory>/hooks/`` that is not a ``.sample`` (decision 0014 section 6)."""
        for config in (self._dul.get_config(), self._config()):
            try:
                value = config.get((b'core',), b'hooksPath')
            except KeyError:
                continue
            if value is not None:
                return f'core.hooksPath={_as_text(value)}'
        base = os.path.join(self.commondir, 'hooks')
        try:
            names = sorted(os.listdir(base))
        except OSError:
            return None
        for name in names:
            if not name.endswith('.sample') and os.path.isfile(os.path.join(base, name)):
                return f'hooks/{name}'
        return None

    def _fast_forward(self, old, new):
        """git's ref_newer: both peel to commits and OLD is NEW or one of its ancestors."""
        old, new = self._commit_reference(old), self._commit_reference(new)
        if old is None or new is None:
            return False
        seen, todo = {new}, [new]
        while todo:
            oid = todo.pop()
            if oid == old:
                return True
            for parent in self._parents(oid) or ():
                if parent not in seen:
                    seen.add(parent)
                    todo.append(parent)
        return False

    def push(self, url, refspec, credential=None):
        """``git push URL REFSPEC`` over smart HTTP, with CREDENTIAL (a ``Credential`` held in
        memory, sent to the URL's origin only) and no credential helper, ssh or process.
        REFSPEC is ``[+]<src>:<dst>``: SRC a preserved object name (empty to delete DST), DST a
        full reference name, ``+`` to force. As git: an update that is not a fast-forward (or
        that replaces an existing tag) is refused without ``+``, before anything is sent; so is
        deleting a reference the remote does not have. Nothing local is written (no
        remote-tracking reference). Returns a ``RefUpdate``.

        Refused before any network access: ``HOOKS_UNSUPPORTED`` when the repository has client
        hooks (git would run ``pre-push``; a Dulwich push runs none). Then ``PUSH_REFUSED`` (the
        server answered HTTP 401 or 403), ``PUSH_REJECTED`` (the update was rejected: by the
        rules above, or by the server, e.g. a protected branch), ``REMOTE_FAILED`` (anything
        else)."""
        if not isinstance(refspec, str) or refspec.count(':') != 1:
            raise ValueError('refspec must be [+]<src>:<dst> with a full destination reference name')
        force = refspec.startswith('+')
        src, dst = refspec[force:].split(':')
        if not dst.startswith('refs/') or not refname_valid(dst):
            raise ValueError(f'the destination must be a full reference name: {dst!r}')
        hooks = self.client_hooks()
        if hooks is not None:
            raise RepositoryError('HOOKS_UNSUPPORTED', f'the repository has a client hook ({hooks}); git would run '
                                  'it before a push and this module runs none, so it does not push', hook=hooks)
        new = None
        if src:
            new = self.object_id(src)
            if new is None:
                raise RepositoryError('PUSH_REJECTED', f'{src} names no object of this repository', ref=dst)
        t, client, path = _remote(url, credential)
        zero = '0' * self._hexsz
        dst_b = dst.encode('utf-8')
        seen = {}
        messages = []

        def update_refs(remote):
            old = remote.get(dst_b)
            seen['old'] = None if old is None else _as_text(old)
            if new is None:
                if old is None:
                    raise _Rejected('remote ref does not exist')
                return {dst_b: zero.encode('ascii')}
            if old is not None and _as_text(old) != new and not force:
                if dst.startswith('refs/tags/'):
                    raise _Rejected('already exists')
                if self._kind(_as_text(old)) is None:
                    raise _Rejected('fetch first')
                if not self._fast_forward(_as_text(old), new):
                    raise _Rejected('non-fast-forward')
            return {dst_b: new.encode('ascii')}

        def pack_data(have, want, *, ofs_delta=False, progress=None):
            return self._dul.generate_pack_data(set(have), set(want), progress=progress, ofs_delta=ofs_delta)

        failure, result = None, None
        try:
            result = client.send_pack(path, update_refs, generate_pack_data=pack_data, progress=messages.append)
        except _Rejected as exc:
            failure = RepositoryError('PUSH_REJECTED', f'{dst}: rejected ({exc}), nothing sent', ref=dst,
                                      reason=str(exc))
        except t.client.SendPackError as exc:
            failure = RepositoryError('PUSH_REJECTED', f'{dst}: the remote did not unpack the objects '
                                      f'({_as_text(exc.args[0]) if exc.args else exc})', ref=dst)
        except Exception as exc:
            failure = _remote_failure('push to', url, exc, 'PUSH_REFUSED')
        if failure is not None:
            raise failure
        error = (result.ref_status or {}).get(dst_b)
        if error is not None:
            remote_text = _sanitize_remote(b''.join(messages))
            raise RepositoryError('PUSH_REJECTED', f'{dst}: the remote rejected the update ({error})'
                                  + (f'; remote: {remote_text}' if remote_text else ''), ref=dst, reason=error,
                                  remote=remote_text)
        return RefUpdate(dst, seen.get('old'), new)

    # -- writes (decision 0014 sections 6 and 8: the commit, first needed by plan leaf P-04.1)

    def write_commit(self, files, message, *, identity, expected_head, when=None, check=None):
        """Commit FILES ({repository-relative path: bytes}: regular, non-executable files, each
        added or replaced) on the branch HEAD names, as writing them into the work tree and running
        ``git commit --only -- <paths>`` would, with author and committer IDENTITY (``Name
        <email>``) at WHEN ((seconds since the epoch, offset east of UTC in seconds); now and the
        local offset when None) and MESSAGE. Returns the new commit id. This is decision 0014's
        ``commit`` write; it is named apart from ``commit(revision)``, the read.

        Built as objects plus a compare-and-set update of the branch, never through a porcelain
        (section 6): the blobs, trees and the commit are written first; then CHECK(commit id), when
        given, may refuse by raising, and nothing visible has changed; then the branch moves only if
        it still holds EXPECTED_HEAD (its reflog and HEAD's get a ``commit:`` line, as git writes
        them); then each file is written into the work tree as its blob's bytes (no end-of-line
        conversion; ``status`` answers it clean under any ``core.autocrlf``) and its index entry is
        set from the written file. The index's cache-tree and the other optional extensions git
        rebuilds (untracked cache, fsmonitor, offset tables) are dropped, so that none goes stale;
        resolve-undo is kept.

        Refused before anything is written: ``HOOKS_UNSUPPORTED`` when the repository has a client
        hook (git would run ``pre-commit`` and ``commit-msg``; this module runs none); and
        ``COMMIT_REFUSED`` (``details['reason']``) when HEAD is not a branch with a commit
        (``head``), the branch does not hold EXPECTED_HEAD (``head-moved``, also when it moves
        before the update), ``commit.gpgSign`` is set (``signing``), the repository is not SHA-1
        (``object-format``), the index has unmerged entries or an extension git requires to be
        understood, such as a split or sparse index (``index``), a path has local changes in the
        index or the work tree, or is an untracked or ignored file, or a directory or a symbolic
        link leads to it (``local-changes``), a file or a directory is in the way of a path
        (``path-conflict``), or nothing would change (``nothing-to-commit``). A path outside the
        repository-relative grammar, or a name the work tree cannot hold, is
        ``OBJECT_NAME_INVALID``. A failure after the branch moved is ``GIT_FAILED`` with
        ``details['committed']``: the commit is made, the work tree or the index is not brought to
        it."""
        d = dulwich_modules()
        if not isinstance(files, dict) or not files:
            raise ValueError('files must be a non-empty {path: bytes} mapping')
        changes = {}
        for path, data in files.items():
            _check_path(path)
            for part in path.split('/'):
                why = _unsafe_component(part)
                if why:
                    raise RepositoryError('OBJECT_NAME_INVALID', f'{path}: {why}', path=path)
            if not isinstance(data, bytes):
                raise ValueError(f'{path}: the content must be bytes')
            changes[path] = data
        if not isinstance(message, str) or not message.strip():
            raise ValueError('message must be non-empty text')
        if not isinstance(identity, str) or not IDENTITY.fullmatch(identity):
            raise ValueError('identity must be "Name <email>"')
        if not isinstance(expected_head, str) or not re.fullmatch(r'[0-9a-f]{40}', expected_head):
            raise ValueError('expected_head must be a full commit id')
        self._require_work_tree()

        def refuse(reason, text, **details):
            return RepositoryError('COMMIT_REFUSED', f'{text}; nothing was written', reason=reason, **details)

        hooks = self.client_hooks()
        if hooks is not None:
            raise RepositoryError('HOOKS_UNSUPPORTED', f'the repository has a client hook ({hooks}); git would run '
                                  'it before a commit and this module runs none, so it does not commit', hook=hooks)
        if self._hexsz != 40:
            raise refuse('object-format', f'the repository uses {self.object_format} object ids; this module '
                         'commits only in SHA-1 repositories')
        if self._config_bool(b'commit', b'gpgsign', False):
            raise refuse('signing', 'commit.gpgSign is set: git would sign the commit and this module does not')
        head = self.head()
        if head.ref is None or not head.ref.startswith('refs/heads/') or head.commit is None:
            raise refuse('head', 'HEAD does not name a branch with a commit')
        if head.commit != expected_head:
            raise refuse('head-moved', f'{head.ref} is at {head.commit}, not {expected_head}', ref=head.ref,
                         current=head.commit)
        index = self._index()
        kept_extensions = self._writable_index_extensions(index, refuse)
        head_tree = self._to_tree(head.commit)
        root = self.root
        for path in sorted(changes):
            entry = self._tree_entry(head_tree, path)
            full = os.path.join(root, *path.split('/'))
            if _has_symlink_leading_path(root, path) or os.path.islink(full):
                raise refuse('local-changes', f'a symbolic link leads to {path}', path=path)
            if entry is None:
                if os.path.lexists(full):
                    raise refuse('local-changes', f'{path} exists in the work tree but not in HEAD', path=path)
            elif entry[1] & _S_IFMT != _S_IFREG:
                raise refuse('path-conflict', f'{path} is not a regular file in HEAD', path=path)
        dirty = self.status(paths=sorted(changes), untracked='no')
        if dirty:
            raise refuse('local-changes', f'{dirty[0].path} has local changes ({dirty[0].xy.strip()})',
                         path=dirty[0].path)
        blobs = {path: d.objects.Blob.from_string(data) for path, data in changes.items()}
        new_objects = list(blobs.values())
        nested = {tuple(path.encode('utf-8').split(b'/')): (_S_IFREG | 0o644, blob.id)
                  for path, blob in blobs.items()}
        tree = self._tree_with(head_tree, nested, new_objects, refuse)
        if tree == head_tree:
            raise refuse('nothing-to-commit', 'every file already has this content in HEAD')
        timestamp, offset = when if when is not None else _now_and_offset()
        author = identity.encode('utf-8')
        commit = d.objects.Commit()
        commit.tree = tree.encode('ascii')
        commit.parents = [head.commit.encode('ascii')]
        commit.author = commit.committer = author
        commit.author_time = commit.commit_time = int(timestamp)
        commit.author_timezone = commit.commit_timezone = int(offset)
        commit.message = (message if message.endswith('\n') else message + '\n').encode('utf-8')
        new_objects.append(commit)
        oid = commit.id.decode('ascii')
        try:
            for obj in new_objects:
                self._dul.object_store.add_object(obj)
        except Exception as exc:
            raise RepositoryError('GIT_FAILED', f'cannot write the commit objects: {type(exc).__name__}: {exc}') \
                from None
        if check is not None:
            check(oid)
        subject = message.strip().splitlines()[0].encode('utf-8')
        reflog = b'commit: ' + subject
        failure = None
        try:
            moved = self._dul.refs.set_if_equals(head.ref.encode('utf-8'), expected_head.encode('ascii'),
                                                 oid.encode('ascii'), committer=author, timestamp=int(timestamp),
                                                 timezone=int(offset), message=reflog)
        except Exception as exc:
            failure = f'{type(exc).__name__}: {exc}'
        self._packed = None
        if failure is not None:
            raise RepositoryError('GIT_FAILED', f'cannot update {head.ref}: {failure}')
        if not moved:
            raise refuse('head-moved', f'{head.ref} moved before the update', ref=head.ref)
        try:
            with open(os.path.join(self.controldir, 'logs', 'HEAD'), 'ab') as handle:
                handle.write(d.reflog.format_reflog_line(expected_head.encode('ascii'), oid.encode('ascii'), author,
                                                         int(timestamp), int(offset), reflog) + b'\n')
            for path, data in changes.items():
                full = os.path.join(root, *path.split('/'))
                os.makedirs(os.path.dirname(full), exist_ok=True)
                with open(full, 'wb') as handle:
                    handle.write(data)
            index = self._index()
            self._writable_index_extensions(index, refuse)
            for path, blob in blobs.items():
                full = os.path.join(root, *path.split('/'))
                index[path.encode('utf-8')] = d.index.index_entry_from_stat(os.lstat(full), blob.id,
                                                                            mode=_S_IFREG | 0o644)
            index._extensions = kept_extensions
            index.write()
        except Exception as exc:
            failure = f'{type(exc).__name__}: {exc}'
        if failure is not None:
            raise RepositoryError('GIT_FAILED', f'the commit {oid} is made on {head.ref}, but the work tree or the '
                                  f'index was not brought to it: {failure}', committed=oid)
        return oid

    def _writable_index_extensions(self, index, refuse):
        """The index extensions a commit keeps (resolve-undo), or COMMIT_REFUSED ``index`` for an
        index this module must not rewrite: unmerged entries, or an extension git must understand
        (a signature starting with a lower-case letter: a split or sparse index). Every other
        optional extension (cache-tree, untracked cache, fsmonitor, offset tables) is dropped:
        git rebuilds them, and a stale one would mislead it. The extensions are read through
        Dulwich's ``Index._extensions`` (pin-sensitive: Dulwich 1.2.21 writes them back as read)."""
        if index.has_conflicts():
            raise refuse('index', 'the index has unmerged entries')
        extensions = getattr(index, '_extensions', None)
        if extensions is None:
            raise refuse('index', 'the index extensions cannot be read')
        kept = []
        for extension in extensions:
            signature = bytes(extension.signature)
            if signature[:1].islower():
                raise refuse('index', f'the index has the extension {signature.decode("ascii", "replace")}, which '
                             'this module does not maintain')
            if signature == b'REUC':
                kept.append(extension)
        return kept

    def _tree_with(self, tree_oid, changes, new_objects, refuse):
        """The id of the tree TREE_OID (None: an empty tree) with CHANGES ({tuple of name bytes:
        (mode, blob id bytes)}) applied; each new tree is appended to NEW_OBJECTS."""
        d = dulwich_modules()
        tree = d.objects.Tree()
        if tree_oid is not None:
            for name, mode, oid in self._tree_items(tree_oid):
                tree.add(name.encode('utf-8', 'surrogateescape'), mode, oid.encode('ascii'))
        nested = {}
        for parts, value in changes.items():
            if len(parts) == 1:
                tree.add(parts[0], *value)
            else:
                nested.setdefault(parts[0], {})[parts[1:]] = value
        for name, sub in sorted(nested.items()):
            try:
                mode, oid = tree[name]
            except KeyError:
                mode, oid = None, None
            if oid is not None and mode & _S_IFMT != _S_IFDIR:
                raise refuse('path-conflict', f'{name.decode("utf-8", "surrogateescape")} is a file in HEAD, in the '
                             'way of a path below it')
            sub_id = self._tree_with(None if oid is None else oid.decode('ascii'), sub, new_objects, refuse)
            tree.add(name, _S_IFDIR, sub_id.encode('ascii'))
        new_objects.append(tree)
        return tree.id.decode('ascii')


def _sanitize_remote(data, limit=600):
    """The remote's progress messages as one line of printable text, at most LIMIT characters
    (its tail)."""
    text = data.decode('utf-8', 'replace')
    text = ' '.join(part.strip() for part in re.split(r'[\r\n]+', text) if part.strip())
    text = _CONTROL.sub('?', text)
    return text[-limit:]


class _PackData:
    """The pack data of a bundle being written (Dulwich's ``PackDataLike``)."""

    def __init__(self, count, objects, object_format):
        self._count, self._objects, self.object_format = count, objects, object_format

    def __len__(self):
        return self._count

    def iter_unpacked(self):
        return iter(self._objects)

    def close(self):
        pass


_UNMERGED = {1: 'DD', 2: 'AU', 3: 'UD', 4: 'UA', 5: 'DU', 6: 'AA', 7: 'UU'}


def _nested_repository(path):
    dotgit = os.path.join(path, '.git')
    if os.path.isfile(dotgit):
        target = _read_gitfile(dotgit)
        return target is not None and is_git_directory(target)
    return os.path.isdir(dotgit) and is_git_directory(dotgit)


def _has_symlink_leading_path(root, path):
    current = root
    for part in path.split('/')[:-1]:
        current = os.path.join(current, part)
        if os.path.islink(current):
            return True
    return False


_UTF8_BOM = b'\xef\xbb\xbf'
_ATTR_BLANK = b' \t\r\n'
_ATTR_NAME = re.compile(rb'[-._0-9A-Za-z]+\Z')
_ATTR_MAX_LINE = 2048  # git ignores longer attribute lines
_UNSPECIFIED = object()  # '!name': determined as unspecified, which hides lower lines
_BUILTIN_MACROS = {b'binary': [(b'diff', False), (b'merge', False), (b'text', False)]}
_C_ESCAPES = {ord('a'): 7, ord('b'): 8, ord('f'): 12, ord('n'): 10, ord('r'): 13, ord('t'): 9, ord('v'): 11,
              ord('\\'): 92, ord('"'): 34}


def _unquote_c(data):
    """git's unquote_c_style of a pattern that starts with '"': (pattern, rest) or None."""
    out, i = bytearray(), 1
    while i < len(data):
        ch = data[i]
        if ch == ord('"'):
            return bytes(out), data[i + 1:]
        if ch == ord('\\'):
            i += 1
            if i >= len(data):
                return None
            ch = data[i]
            if ch in _C_ESCAPES:
                out.append(_C_ESCAPES[ch])
            elif ord('0') <= ch <= ord('3') and i + 2 < len(data) and \
                    all(ord('0') <= c <= ord('7') for c in data[i + 1:i + 3]):
                out.append(int(data[i:i + 3], 8))
                i += 2
            else:
                return None
        else:
            out.append(ch)
        i += 1
    return None


def parse_attribute_lines(data, macros_allowed):
    """The lines of a gitattributes file as git's ``parse_attr_line`` reads them: a list of
    ``(lineno, kind, pattern, states)``, ``kind`` 'macro' (``[attr]<name>``, where allowed) or
    'pattern', ``states`` the ``(name, value)`` pairs in line order (True, False, a bytes value,
    or ``_UNSPECIFIED`` for ``!name``). Dropped as git drops them: comments and blank lines,
    a macro where none is allowed, a negative pattern, an invalid attribute name."""
    if data.startswith(_UTF8_BOM):
        data = data[len(_UTF8_BOM):]
    lines = []
    for lineno, line in enumerate(data.split(b'\n'), start=1):
        text = line.lstrip(_ATTR_BLANK)
        if not text or text.startswith(b'#') or len(line) >= _ATTR_MAX_LINE:
            continue
        quoted = _unquote_c(text) if text.startswith(b'"') else None
        if quoted is not None:
            name, rest = quoted
        else:
            cut = next((i for i, ch in enumerate(text) if ch in _ATTR_BLANK), len(text))
            name, rest = text[:cut], text[cut:]
        states = []
        for token in rest.split():
            attr = token[1:] if token[:1] in (b'-', b'!') else token
            attr, equals, value = attr.partition(b'=')
            if not _ATTR_NAME.match(attr) or attr.startswith(b'-'):
                break  # git drops the whole line
            if token[:1] == b'-':
                states.append((attr, False))
            elif token[:1] == b'!':
                states.append((attr, _UNSPECIFIED))
            else:
                states.append((attr, value if equals else True))
        else:
            if name.startswith(b'[attr]'):
                # A macro definition, never a glob pattern (git reads '[attr]' alone as one).
                macro = name[len(b'[attr]'):]
                if macros_allowed and _ATTR_NAME.match(macro) and not macro.startswith(b'-'):
                    lines.append((lineno, 'macro', macro, states))
            elif not name.startswith(b'!'):  # git: negative patterns are ignored in attributes
                lines.append((lineno, 'pattern', name, states))
    return lines


class _Attributes:
    """git's attributes for status (``attr.c``, the check-in direction), evaluated here and not
    by Dulwich's ``GitAttributes``, which expands no macro, neither the built-in ``binary``
    (``-diff -merge -text``) nor ``[attr]`` definitions, and so let an earlier ``text`` win
    over a later ``binary`` (F-10.4).

    The stack, lowest precedence first: the built-in macro, the root ``.gitattributes``, each
    deeper directory's ``.gitattributes`` down to the path's own, then ``info/attributes``; a
    ``.gitattributes`` is read from the work tree (a regular file, not a symbolic link), else
    from the index. The user and system attribute files are refused before this
    (``_check_attribute_files``) whenever they set an attribute status consults, a macro
    definition included, so they contribute nothing here. As git's ``fill``: from the highest
    line down, each matching line determines its attributes not yet determined, last on the
    line first, and a macro set true then determines its own attributes the same way. Macro
    definitions are read where git allows them (the root file and ``info/attributes``); the
    definition of highest precedence wins. A pattern ending in '/' never matches a file; the
    other patterns are matched by Dulwich's attribute ``Pattern`` (relative to the file's
    directory), case-insensitively (ASCII) when ``core.ignorecase`` is set, as git matches."""

    def __init__(self, repository, index):
        self.repo = repository
        self.index = index            # path -> stage-0 IndexEntry
        self.ignorecase = repository._config_bool(b'core', b'ignorecase', False)
        self._files = {}
        info = os.path.join(repository._dul.controldir(), 'info', 'attributes')
        try:
            with open(info, 'rb') as handle:
                self._info = self._compile(handle.read(), '', True)
        except OSError:
            self._info = ([], {})
        self.macros = dict(_BUILTIN_MACROS)
        self.macros.update(self._directory('')[1])
        self.macros.update(self._info[1])

    def _compile(self, data, base, macros_allowed):
        d = dulwich_modules()
        patterns, macros = [], {}
        base_bytes = base.encode('utf-8', 'surrogateescape')
        for _lineno, kind, name, states in parse_attribute_lines(data, macros_allowed):
            if kind == 'macro':
                macros[name] = states
                continue
            if name.endswith(b'/'):
                continue  # git: a directory-only pattern never matches a file
            if self.ignorecase:
                name, pattern_base = name.lower(), base_bytes.lower()
            else:
                pattern_base = base_bytes
            try:
                patterns.append((d.attrs.Pattern(name, pattern_base), states))
            except (re.error, ValueError):
                continue
        return patterns, macros

    def _read(self, rel):
        """The bytes of the ``.gitattributes`` of directory REL ('' for the root), or None."""
        name = f'{rel}/.gitattributes' if rel else '.gitattributes'
        full = os.path.join(self.repo.root, *name.split('/'))
        if os.path.isfile(full) and not os.path.islink(full):
            try:
                with open(full, 'rb') as handle:
                    return handle.read()
            except OSError:
                pass
        entry = self.index.get(name)
        if entry is not None:
            found = self.repo._raw(entry.oid)
            if found is not None and found[0] == 'blob':
                return found[1]
        return None

    def _directory(self, rel):
        if rel not in self._files:
            data = self._read(rel)
            self._files[rel] = self._compile(data, rel, rel == '') if data is not None else ([], {})
        return self._files[rel]

    def _fill(self, states, found):
        for name, value in reversed(states):
            if name not in found:
                found[name] = value
                if value is True and name in self.macros:
                    self._fill(self.macros[name], found)

    def match(self, path):
        """{name: True, False or bytes} of PATH (repository-relative), unspecified ones left out."""
        parts = path.split('/')
        stack = [self._directory('/'.join(parts[:depth]))[0] for depth in range(len(parts))]
        stack.append(self._info[0])
        subject = path.encode('utf-8', 'surrogateescape')
        if self.ignorecase:
            subject = subject.lower()
        found = {}
        for patterns in reversed(stack):
            for pattern, states in reversed(patterns):
                if pattern.match(subject):
                    self._fill(states, found)
        return {name: value for name, value in found.items() if value is not _UNSPECIFIED}



class _Excludes:
    """git's exclude decision for the untracked walk (``dir.c``, ``last_matching_pattern``),
    made here and not by Dulwich's ``IgnoreFilterManager``, which reports a directory ignored
    when a pattern only reaches inside it (``logs/*``), so that a negation re-including a
    directory below it (``!logs/keep/``) was never reached (F-10.4).

    An entry is decided by the last pattern that matches the entry itself, searched level by
    level from the highest precedence: the ``.gitignore`` of the entry's own directory, then of
    each directory above it up to the root, then ``info/exclude``, then ``core.excludesFile``.
    A negated pattern re-includes. The walk prunes a directory only when the directory itself is
    excluded, and reads a directory's ``.gitignore`` only when it reaches the directory. Each
    pattern is matched by Dulwich's ``Pattern.matches`` (git's wildmatch rules, for the entry's
    path relative to the file's directory and whether it is a directory)."""

    def __init__(self, root, levels, ignorecase):
        self.root = root
        self.levels = levels          # lowest precedence first: core.excludesFile, info/exclude
        self.ignorecase = ignorecase
        self._directories = {}

    @staticmethod
    def read(path, ignorecase, follow=True):
        """The patterns of the exclude file PATH, in file order, or None when it cannot be read
        (absent, a directory; an in-tree ``.gitignore`` that is a symbolic link, which git does
        not follow)."""
        d = dulwich_modules()
        try:
            if not follow and os.path.islink(path):
                return None
            with open(path, 'rb') as handle:
                data = handle.read()
        except OSError:
            return None
        if data.startswith(_UTF8_BOM):
            data = data[len(_UTF8_BOM):]
        patterns = []
        for line in d.ignore.read_ignore_patterns(io.BytesIO(data)):
            try:
                patterns.append(d.ignore.Pattern(line, ignorecase))
            except d.ignore.MalformedPattern:
                continue  # git's wildmatch never matches it
        return patterns

    def _directory(self, rel):
        if rel not in self._directories:
            path = os.path.join(self.root, *rel.split('/'), '.gitignore') if rel else \
                os.path.join(self.root, '.gitignore')
            self._directories[rel] = self.read(path, self.ignorecase, follow=False) or []
        return self._directories[rel]

    @staticmethod
    def _last(patterns, name, is_dir):
        for pattern in reversed(patterns):
            if pattern.matches(name, is_dir):
                return pattern
        return None

    def excluded(self, rel, is_dir):
        """Whether git excludes the untracked entry REL (repository-relative, '/'-separated)."""
        parts = rel.split('/')
        for depth in range(len(parts) - 1, -1, -1):
            name = '/'.join(parts[depth:]).encode('utf-8', 'surrogateescape')
            found = self._last(self._directory('/'.join(parts[:depth])), name, is_dir)
            if found is not None:
                return found.is_exclude
        name = rel.encode('utf-8', 'surrogateescape')
        for patterns in reversed(self.levels):
            found = self._last(patterns, name, is_dir)
            if found is not None:
                return found.is_exclude
        return False


class _WorktreeChecker:
    """Worktree against index, as git's diff-files sees it: 'D' removed, 'T' type changed, 'M'
    content (after git's clean conversion) or executable bit changed, ' ' unchanged."""

    def __init__(self, repository, index, sizes):
        self.repo = repository
        self.index = index
        self.sizes = sizes            # path -> the size git recorded in the index (stage 0)
        self.symlinks = repository._config_bool(b'core', b'symlinks', True)
        self.filemode = repository._config_bool(b'core', b'filemode', True) and not _WINDOWS
        try:
            value = repository._config().get((b'core',), b'autocrlf').decode('utf-8').strip().lower()
        except KeyError:
            value = 'false'
        if value == 'input':
            self.autocrlf = 'input'
        else:
            self.autocrlf = 'true' if value in ('true', 'yes', 'on', '1') else 'false'
        self._attributes = None

    def attributes(self, path):
        if self._attributes is None:
            try:
                self._attributes = _Attributes(self.repo, self.index)
            except RepositoryError:
                raise
            except Exception as exc:
                raise RepositoryError('GIT_FAILED', f'cannot read the attributes: {type(exc).__name__}: {exc}') from None
        return self._attributes.match(path)

    def change(self, entry):
        root = self.repo.root
        if _has_symlink_leading_path(root, entry.path):
            return 'D'
        full = os.path.join(root, *entry.path.split('/'))
        try:
            st = os.lstat(full)
        except (FileNotFoundError, NotADirectoryError):
            return 'D'
        kind = entry.mode & _S_IFMT
        if stat.S_ISDIR(st.st_mode):
            if kind == _S_IFGITLINK:
                return ' '
            return 'T' if _nested_repository(full) else 'D'
        if kind == _S_IFGITLINK:
            return 'T'
        if kind == _S_IFLNK:
            if stat.S_ISLNK(st.st_mode):
                data = os.fsencode(os.readlink(full))
            elif stat.S_ISREG(st.st_mode) and not self.symlinks:
                data = Path(full).read_bytes()
            else:
                return 'T'
            return ' ' if self.blob_id(data) == entry.oid else 'M'
        if not stat.S_ISREG(st.st_mode):
            return 'T'
        if self.filemode and bool(st.st_mode & 0o100) != bool(entry.mode & 0o100):
            return 'M'
        recorded = self.sizes.get(entry.path, 0)
        if recorded and recorded != st.st_size & 0xffffffff:
            # git's ie_match_stat: a recorded size (non-zero: zero means not yet known, or
            # smudged as racily clean) that differs from the file's is a change, without a
            # content comparison or any conversion (F-10.4).
            return 'M'
        data = self.clean(entry, Path(full).read_bytes())
        return ' ' if self.blob_id(data) == entry.oid else 'M'

    def blob_id(self, data):
        algorithm = hashlib.sha256 if self.repo.object_format == 'sha256' else hashlib.sha1
        return algorithm(b'blob %d\0' % len(data) + data).hexdigest()

    def clean(self, entry, data):
        """git's convert_to_git for status: refuse filter drivers and encodings, then the
        end-of-line conversion and ident."""
        attrs = self.attributes(entry.path)
        driver = attrs.get(b'filter')
        if isinstance(driver, bytes):
            config = self.repo._config()
            for key in (b'clean', b'process'):
                try:
                    config.get((b'filter', driver), key)
                except KeyError:
                    continue
                raise RepositoryError('FILTER_UNSUPPORTED', f'{entry.path}: git would run the configured filter '
                                      f'driver {driver.decode("utf-8", "replace")}, a process', path=entry.path)
        encoding = attrs.get(b'working-tree-encoding')
        if isinstance(encoding, bytes):
            raise RepositoryError('FILTER_UNSUPPORTED', f'{entry.path}: working-tree-encoding '
                                  f'{encoding.decode("utf-8", "replace")} is not converted by this module',
                                  path=entry.path)
        action = self.crlf_action(attrs)
        if data and action != 'binary' and b'\r\n' in data:
            convert = True
            if action.startswith('auto'):
                stats = _text_stats(data)
                if _is_binary(stats):
                    convert = False
                elif self.crlf_in_index(entry):
                    convert = False
            if convert:
                data = data.replace(b'\r\n', b'\n')
        if attrs.get(b'ident') is True and b'$Id:' in data:
            data = _ident_to_git(data)
        return data

    def crlf_action(self, attrs):
        text = attrs.get(b'text')
        if text is True:
            action = 'text'
        elif text is False:
            action = 'binary'
        elif text == b'auto':
            action = 'auto'
        else:
            crlf = attrs.get(b'crlf')
            action = {True: 'text', False: 'binary', b'input': 'text-input'}.get(crlf, 'undefined')
        if action != 'binary':
            eol = attrs.get(b'eol')
            if action == 'auto' and eol in (b'lf', b'crlf'):
                action = 'auto-' + eol.decode()
            elif eol == b'lf':
                action = 'text-input'
            elif eol == b'crlf':
                action = 'text-crlf'
        if action == 'undefined':
            action = {'false': 'binary', 'true': 'auto-crlf', 'input': 'auto-input'}[self.autocrlf]
        return action

    def crlf_in_index(self, entry):
        found = self.repo._raw(entry.oid)
        if found is None or b'\r' not in found[1]:
            return False
        stats = _text_stats(found[1])
        return not _is_binary(stats) and stats['crlf'] > 0


# ---------------------------------------------------------------------------- export helpers

def _unsafe_component(part):
    if part in ('', '.', '..') or '/' in part or '\0' in part:
        return f'unsafe name {part!r}'
    folded = part.casefold()
    stripped = folded.rstrip(' .') if _WINDOWS else folded
    if stripped == '.git' or (_WINDOWS and stripped == 'git~1'):
        return f'refused name {part!r} (git metadata)'
    if _WINDOWS:
        if any(ch in _WINDOWS_INVALID or ord(ch) < 32 for ch in part):
            return f'name {part!r} is not valid on Windows'
        if part != part.rstrip(' .'):
            return f'name {part!r} ends with a dot or a space (Windows would rename it)'
        if folded.split('.')[0].rstrip(' ') in _WINDOWS_RESERVED:
            return f'name {part!r} is a Windows device name'
    return None


def _link_target(path, data, links):
    """The target text of the link at PATH, refused unless it stays inside the export."""
    try:
        target = data.decode('utf-8')
    except UnicodeDecodeError:
        raise RepositoryError('EXPORT_REFUSED', f'{path}: link target is not UTF-8', path=path) from None
    if not target or '\0' in target or '\\' in target or target.startswith('/') or re.match(r'[A-Za-z]:', target):
        raise RepositoryError('EXPORT_REFUSED', f'{path}: link target {target!r} is absolute or not portable',
                              path=path)
    stack = path.split('/')[:-1]
    for part in target.split('/'):
        if part in ('', '.'):
            continue
        if part == '..':
            if not stack:
                raise RepositoryError('EXPORT_REFUSED', f'{path}: link target {target!r} leaves the export',
                                      path=path)
            if '/'.join(stack) in links:
                raise RepositoryError('EXPORT_REFUSED', f'{path}: link target {target!r} climbs out of another '
                                      'link', path=path)
            stack.pop()
        else:
            stack.append(part)
    return target


def _link_points_to_directory(path, target, entries, gitlinks):
    stack = path.split('/')[:-1]
    for part in target.split('/'):
        if part in ('', '.'):
            continue
        if part == '..':
            stack.pop()
        else:
            stack.append(part)
    resolved = '/'.join(stack)
    if not resolved or resolved in gitlinks:
        return True
    return any(p.startswith(resolved + '/') for p, _m, _o in entries)


# ---------------------------------------------------------------------------- bundle files

BUNDLE_SIGNATURES = {b'# v2 git bundle\n': 2, b'# v3 git bundle\n': 3}
BUNDLE_REF = re.compile(r'([0-9a-f]{40}|[0-9a-f]{64}) (refs/\S+|HEAD)')
BUNDLE_HEADER_MAX = 1 << 20


def parse_bundle_header(path):
    """The header of a git bundle file (gitformat-bundle): version, capabilities,
    prerequisites, references and where the pack starts. Anything else is BUNDLE_INVALID."""
    try:
        handle = open(path, 'rb')
    except OSError as exc:
        raise RepositoryError('BUNDLE_INVALID', f'{path}: {exc}') from None
    with handle:
        first = handle.readline(64)
        if first not in BUNDLE_SIGNATURES:
            raise RepositoryError('BUNDLE_INVALID', f'{path}: not a v2 or v3 git bundle')
        out = {'version': BUNDLE_SIGNATURES[first], 'capabilities': [], 'prerequisites': [], 'refs': []}
        total = len(first)
        while True:
            line = handle.readline(4096)
            total += len(line)
            if not line or not line.endswith(b'\n') or total > BUNDLE_HEADER_MAX:
                raise RepositoryError('BUNDLE_INVALID', f'{path}: bundle header not terminated')
            if line == b'\n':
                out['pack_offset'] = total
                return out
            try:
                text = line[:-1].decode('ascii')
            except UnicodeDecodeError:
                raise RepositoryError('BUNDLE_INVALID', f'{path}: non-ASCII header line') from None
            if text.startswith('@') and out['version'] == 3:
                out['capabilities'].append(text[1:])
            elif text.startswith('-'):
                out['prerequisites'].append(text[1:].split(' ', 1)[0])
            else:
                match = BUNDLE_REF.fullmatch(text)
                if not match:
                    raise RepositoryError('BUNDLE_INVALID', f'{path}: unparsable header line {text!r}')
                out['refs'].append([match.group(1), match.group(2)])


def pack_trailer(path, header):
    """The bundle's pack checksum, recomputed: the pack starts with 'PACK' after the header and
    ends with the hash of everything before the trailer (SHA-1, or SHA-256 when the v3 header
    says object-format=sha256)."""
    sha256 = 'object-format=sha256' in header.get('capabilities', [])
    size = 32 if sha256 else 20
    digest = hashlib.sha256() if sha256 else hashlib.sha1()
    with open(path, 'rb') as handle:
        handle.seek(header['pack_offset'])
        magic = handle.read(4)
        digest.update(magic)
        tail = b''
        for block in iter(lambda: handle.read(1 << 20), b''):
            data = tail + block
            digest.update(data[:-size])
            tail = data[-size:]
    ok = magic == b'PACK' and len(tail) == size and digest.digest() == tail
    return {'ok': ok, 'algorithm': 'sha256' if sha256 else 'sha1', 'trailer': tail.hex()}
