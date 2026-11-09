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
  ``status``, ``index_entries``, ``listing`` (``ls-files``), ``write_bundle``, and the module
  functions ``parse_bundle_header`` and ``pack_trailer``.

Errors (decision 0014 section 3): ``RepositoryError`` with a stable ``code``
(``REVISION_INVALID``, ``OBJECT_NAME_INVALID``, ``GIT_FAILED``, ``EXPORT_REFUSED``,
``BUNDLE_INVALID``, ``FILTER_UNSUPPORTED``, ``ATTRIBUTES_UNSUPPORTED``, ``REPLACE_REFS_UNSUPPORTED``), and
``CannotRun`` (``NOT_A_WORK_TREE``,
``NOT_A_REPOSITORY``, ``REPOSITORY_NEEDS_DULWICH``). "No such object" and an ambiguous
abbreviation answer ``None``.

The standard library is imported at module import; Dulwich only when a repository is opened, so
that a missing Dulwich is the stable ``CannotRun`` ``REPOSITORY_NEEDS_DULWICH``, never an
``ImportError``.
"""
import collections
import hashlib
import os
import re
import stat
import sys
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
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('[attr]'):
            return line.split()[0]
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
                return token
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


def discover(path):
    """('worktree', root) or ('gitdir', directory) for the repository PATH is in, as git's
    discovery walks up from it; None outside any repository."""
    start = os.path.realpath(os.fspath(path))
    if not os.path.isdir(start):
        return None
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
        current = parent


def open_repository(path, *, config, work_tree=True):
    """Open the repository at or above PATH under the configuration policy CONFIG ('host',
    'repository' or 'none'). With WORK_TREE (the default) only a work tree is accepted, as git's
    ``rev-parse --show-toplevel``: any directory inside one, a linked worktree or a separate git
    directory's work tree; a bare repository or a .git directory is refused (CannotRun
    NOT_A_WORK_TREE). Without it a git directory is accepted too (NOT_A_REPOSITORY otherwise)."""
    if config not in POLICIES:
        raise ValueError(f'config must be one of {POLICIES}, not {config!r}')
    d = dulwich_modules()
    found = discover(path)
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


# ---------------------------------------------------------------------------- the repository

class _Missing(Exception):
    """git dies or answers nothing: the name resolves to no object."""


class _DateGap(Exception):
    """Resolution reached git's reading of a reflog date (the @{<date>} gap)."""


def _date_gap(name):
    return RepositoryError('REVISION_INVALID', f'{name!r} does not resolve without git reading the text after its '
                           'last @{ as a reflog date, the @{<date>} gap (decision 0014 section 2)',
                           gap='the reflog date @{<date>} (git fallback)')


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
        rows = []
        try:
            for path, entry in index.iteritems():
                name = path.decode('utf-8', 'surrogateescape')
                if isinstance(entry, d.index.ConflictedIndexEntry):
                    for stage, part in ((1, entry.ancestor), (2, entry.this), (3, entry.other)):
                        if part is not None:
                            rows.append(IndexEntry(part.mode, part.sha.decode('ascii'), stage, name))
                else:
                    rows.append(IndexEntry(entry.mode, entry.sha.decode('ascii'), 0, name))
        except Exception as exc:
            raise RepositoryError('GIT_FAILED', f'cannot read the index: {type(exc).__name__}: {exc}') from None
        rows.sort(key=lambda row: (row.path.encode('utf-8', 'surrogateescape'), row.stage))
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
        checker = _WorktreeChecker(self, index)
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

    def _ignore_manager(self):
        d = dulwich_modules()
        config = self._config()
        filters = []
        candidates = [os.path.join(self._dul.controldir(), 'info', 'exclude')]
        try:
            excludes = config.get((b'core',), b'excludesFile').decode('utf-8')
        except KeyError:
            excludes = d.config.get_xdg_config_home_path('git', 'ignore') if self.policy == 'host' else None
        if excludes:
            candidates.append(os.path.expanduser(excludes))
        ignorecase = self._config_bool(b'core', b'ignorecase', False)
        for index, path in enumerate(candidates):
            try:
                filters.append(d.ignore.IgnoreFilter.from_path(path, ignorecase))
            except OSError:
                continue
            path = os.path.normpath(path)
            if index and path not in self._dul._aieh_sources:
                self._dul._aieh_sources.append(path)
        return d.ignore.IgnoreFilterManager(self.root, filters, ignorecase), ignorecase

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
            found = status_attribute(text)
            if found:
                raise RepositoryError('ATTRIBUTES_UNSUPPORTED', f'{path} sets {found}, which git applies to status and '
                                      'this module does not read from that file', path=path, attribute=found)

    def _untracked(self, tracked, mode, exclude_standard):
        """The untracked paths git's read_directory reports: files, a nested repository as
        'dir/', and in 'normal' mode an untracked directory with content as 'dir/'."""
        manager, ignorecase = self._ignore_manager() if exclude_standard else (None, False)
        tracked_dirs = set()
        for path in tracked:
            parts = path.split('/')
            for i in range(1, len(parts)):
                tracked_dirs.add('/'.join(parts[:i]))

        def ignored(rel, is_dir):
            if manager is None:
                return False
            return manager.is_ignored(rel + ('/' if is_dir else '')) is True

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


class _WorktreeChecker:
    """Worktree against index, as git's diff-files sees it: 'D' removed, 'T' type changed, 'M'
    content (after git's clean conversion) or executable bit changed, ' ' unchanged."""

    def __init__(self, repository, index):
        self.repo = repository
        self.index = index
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
                self._attributes = self.repo._dul.get_gitattributes()
            except Exception as exc:
                raise RepositoryError('GIT_FAILED', f'cannot read the attributes: {type(exc).__name__}: {exc}') from None
        return self._attributes.match_path(path.encode('utf-8', 'surrogateescape'))

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
        if b'text' not in attrs and b'binary' in attrs:
            text = False if attrs[b'binary'] is True else None
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
