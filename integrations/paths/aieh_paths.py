"""The managed data root and configuration contract (plan leaf F-07.1, decision 0009).

One resolver computes the managed data root and every category below it from the platform convention,
AIEH_DATA_ROOT and the optional, gitignored <repo>/config.yml; components consume these paths and invent
none. Its JSON (aieh-paths/v1) is the cross-language contract; --format sh|ps1 are thin emitters of it.
resolve() creates nothing; ensure() and init() create directories under the rules below; nothing here
deletes anything, reads .env or uses the process working directory. Standard library only: PyYAML is
imported only when config.yml exists.

  python -I -B integrations/paths/aieh_paths.py show [--format json|sh|ps1] | init | doctor
"""
from __future__ import annotations

import argparse
import datetime
import importlib.util
import json
import ntpath
import os
import posixpath
import re
import sys
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath
from typing import Mapping, NamedTuple

REPO = Path(os.path.realpath(__file__)).parents[2]  # the source tree this resolver is loaded from
RESOLVER_VERSION = '1'
FORMAT, DOCTOR_FORMAT = 'aieh-paths/v1', 'aieh-paths-doctor/1'
MARKER_NAME, MARKER_FORMAT = 'aieh-root.json', 'aieh-root/1'
ASSET_RECORD_NAME, ASSET_FORMAT = 'aieh-asset.json', 'aieh-asset/1'
ENV_ROOT, CONFIG_NAME = 'AIEH_DATA_ROOT', 'config.yml'
LIFECYCLES = ('persistent', 'ephemeral', 'assets')
PROFILE_VARS = ('USERPROFILE', 'LOCALAPPDATA', 'APPDATA', 'HOME')
SECRET_SHAPED = re.compile('password|token|secret|key|credential', re.IGNORECASE)
SEGMENT = re.compile('[A-Za-z0-9][A-Za-z0-9._+-]*')
SHA256_HEX = re.compile('[0-9a-f]{64}')
NON_FIXED = (2, 4, 5, 6)  # storecore DRIVE_REMOVABLE, DRIVE_REMOTE, DRIVE_CDROM, DRIVE_RAMDISK
BS = chr(92)


class Category(NamedTuple):
    default: str    # below the root, '/'-separated
    lifecycle: str  # persistent: never implicitly deleted; ephemeral: controlled cleanup only;
    #                 assets: reclaimed only deliberately, with no required consumer and verified reacquisition
    cls: str        # directive class: B installed harness and its data, C durable user work, D disposable
    #                 execution data, E protected configuration, credentials and evidence (A, the checkout, never)
    layout: str     # the convention below the category path
    creator: str
    consumer: str


CATEGORIES = {
    'state': Category('persistent/state', 'persistent', 'B', '<component>/', 'the component (ensure)',
                      'integration, planning and lineage stores (F-07.2)'),
    'gitea': Category('persistent/gitea', 'persistent', 'E', '', 'the Gitea installer (F-06.1)', 'Gitea (F-06.1)'),
    'installs': Category('persistent/installs', 'persistent', 'B', '<tool>/<version>/', 'tools:install; installers',
                         'the tools venv; unpacked tools (F-07.2, F-06.1)'),
    'logs': Category('persistent/logs', 'persistent', 'B', '<component>/', 'the component (ensure)', 'operators'),
    'workspaces': Category('persistent/workspaces', 'persistent', 'C', '', 'reserved', 'reserved'),
    'assets': Category('assets', 'assets', 'B', '<kind>/<name>/<version>/ + aieh-asset.json',
                       'downloaders: tools:install; F-07.2', 'installers and guest provisioning (F-07.2)'),
    'cache': Category('ephemeral/cache', 'ephemeral', 'D', '<component>/', 'the component (ensure)',
                      'pip (tools:install); components'),
    'scratch': Category('ephemeral/scratch', 'ephemeral', 'D', '', 'the component (ensure)', 'task qualify (F-07.2)'),
    'tmp': Category('ephemeral/tmp', 'ephemeral', 'D', '', 'the component (ensure)', 'components'),
}
STORE_CATEGORIES = frozenset({'state', 'gitea'})
EXTERNAL = ('effects_root', 'guest_state')  # registered: reported from config.yml, never defaulted, created or vetted
LEGACY = (  # former defaults that predate this contract; doctor reports them and moves nothing
    ('integration-store', 'data', ('state',), 'service database', 'F-07.2: back it up (task store:backup), copy '
     'it into <state>/integration/, verify the copy, switch the reference; removing the old tree is an Owner act'),
    ('gitleaks-cache', 'cache', ('tools', 'gitleaks'), 'installed binary (regenerable)', 'F-07.2: task '
     'hooks:install reacquires and verifies the pinned archive into assets/; removing the old cache is an Owner act'),
)
REMEDIES = {
    'DEFAULT_ROOT_UNAVAILABLE': 'set AIEH_DATA_ROOT to an absolute directory',
    'ROOT_NOT_ABSOLUTE_AFTER_ANCHOR': 'give AIEH_DATA_ROOT as an absolute path, or relative to the repository '
                                      'root without a drive or a leading separator',
    'ROOT_IS_DRIVE_ROOT': 'name a directory below the volume root, such as a sibling of the checkout',
    'ROOT_IS_PROFILE_ROOT': 'name a dedicated directory below it; the default is AIEH under LOCALAPPDATA',
    'ROOT_INSIDE_CHECKOUT': 'keep the root outside the checkout, for example AIEH_DATA_ROOT=../aieh-data',
    'ROOT_UNC_OR_NETWORK': 'keep the root on a local fixed volume',
    'CONFIG_UNREADABLE': 'make config.yml a readable UTF-8 YAML file, or remove it to use the defaults',
    'CONFIG_NEEDS_YAML': 'run task tools:install and rerun with the python it prints, or remove config.yml',
    'CONFIG_NOT_A_MAPPING': 'make config.yml, paths and each components entry mappings; see example_config.yml',
    'CONFIG_VERSION_UNSUPPORTED': 'set version: 1; see example_config.yml',
    'CONFIG_UNKNOWN_KEY': 'use only the keys shown in example_config.yml',
    'CONFIG_PATH_TYPE': 'give each path as a non-empty string, absolute or relative to the managed root '
                        '(registered external locations must be absolute)',
    'CONFIG_SECRET_SHAPED_KEY': 'remove it: secrets belong in the credential custody of decision 0007 '
                                '(the role-token matrix), never in config.yml',
    'PATH_INSIDE_CHECKOUT': 'point the override outside the checkout',
    'PATH_IS_DRIVE_ROOT': 'name a directory below the volume root',
    'PATH_OVERLAP': 'give each category its own directory, neither equal to nor inside another',
    'PATH_NETWORK_FOR_STORE': 'keep state and gitea on a local fixed volume',
    'DRIVE_ROOT_CREATE': 'run task paths:init to create a root directly below a volume root; create any other '
                         'such directory yourself',
    'ROOT_PARENT_MISSING': 'create the parent directory first; directories above the root are never created',
    'ROOT_MARKER_MISMATCH': 'use the resolver that wrote this root, or choose a new root',
    'LOCATION_MANAGED_ROOT': 'keep the effects root and the managed data apart, neither inside the other',
    'ASSET_RECORD_INVALID': 'write the record with asset_record() in the aieh-asset/1 format',
}


class PathsError(Exception):
    """A refusal with a stable code and its remedy."""

    def __init__(self, code: str, detail: str):
        self.code, self.detail, self.remedy = code, detail, REMEDIES[code]
        super().__init__(f'{code}: {detail}. Remedy: {self.remedy}.')


class Resolution(NamedTuple):
    root: PurePath
    root_source: str  # default, env or env-relative
    repo_root: PurePath
    platform: str
    paths: dict       # category -> PurePath
    sources: dict     # category -> root or config
    external: dict    # registered external location -> PurePath or None
    components: dict  # components.<name>, each validated by its component
    warnings: list

    def outside_root(self, name: str) -> bool:
        return not self.paths[name].is_relative_to(self.root)

    def to_json(self) -> dict:
        return {'format': FORMAT, 'root': str(self.root), 'root_source': self.root_source,
                'repo_root': str(self.repo_root), 'platform': self.platform,
                'paths': {n: {'path': str(p), 'lifecycle': CATEGORIES[n].lifecycle, 'class': CATEGORIES[n].cls,
                              'source': self.sources[n], 'outside_root': self.outside_root(n)}
                          for n, p in self.paths.items()},
                'external': {n: None if p is None else str(p) for n, p in self.external.items()},
                'warnings': list(self.warnings)}


def _pure(platform: str) -> type[PurePath]:
    return PureWindowsPath if platform == 'win32' else PurePosixPath


def _norm(platform: str, path) -> PurePath:
    return _pure(platform)((ntpath if platform == 'win32' else posixpath).normpath(str(path)))


def _is_unc(path: PurePath) -> bool:
    return str(path).startswith(BS * 2 if isinstance(path, PureWindowsPath) else '//')


def _overlaps(a: PurePath, b: PurePath) -> bool:
    return a.is_relative_to(b) or b.is_relative_to(a)


def _comparable(path, platform: str | None = None) -> str:
    """PATH as the file system resolves it, for comparison only. On Windows (PLATFORM win32; default this host): a
    leading \\\\?\\ or \\\\.\\ removed and \\\\?\\UNC\\ made \\\\, '/' made '\\', the trailing spaces and dots Windows
    ignores removed from every component, then normpath and normcase. Elsewhere: normpath."""
    text = os.fspath(path) if not isinstance(path, PurePath) else str(path)
    if (platform or sys.platform) != 'win32':
        return posixpath.normpath(text)
    text = text.replace('/', BS)
    if text[:8].upper() == BS * 2 + '?' + BS + 'UNC' + BS:
        text = BS * 2 + text[8:]
    elif text[:4] in (BS * 2 + '?' + BS, BS * 2 + '.' + BS):
        text = text[4:]
    drive, rest = ntpath.splitdrive(text)
    rest = BS.join(part if part in ('.', '..') else part.rstrip(' .') for part in rest.split(BS))
    return ntpath.normcase(ntpath.normpath(drive + rest))


def inside_or_around(candidate, root, platform: str | None = None) -> bool:
    """Whether CANDIDATE is ROOT, lies inside it or contains it, in any form the file system resolves to the same
    path (_comparable). The one "inside or around the checkout" comparison of the harness: the managed root and its
    categories against the checkout here (decision 0009), the dispatch manifest's path (dispatch_inputs.load_manifest)
    and the S-03.3 proposal's --out (inference_qualification.proposal_target). Paths on different drives, or one
    relative and one absolute, do not overlap."""
    a, b = _comparable(candidate, platform), _comparable(root, platform)
    try:
        common = (ntpath if (platform or sys.platform) == 'win32' else posixpath).commonpath([a, b])
    except ValueError:
        return False
    return common in (a, b)


def _join(platform: str, base: PurePath, raw: str, code: str, what: str) -> PurePath:
    """raw as given when absolute, else below base; drive-relative and rooted forms are refused."""
    given = _pure(platform)(raw)
    if not given.is_absolute():
        if given.drive or given.root:
            raise PathsError(code, f'{what} {raw!r} is drive-relative or rooted, neither absolute nor relative')
        given = base / given
    if not (result := _norm(platform, given)).is_absolute():
        raise PathsError(code, f'{what} {raw!r} is not absolute after anchoring at {base}')
    return result


def default_root(environ: Mapping[str, str], platform: str) -> PurePath:
    """AIEH under LOCALAPPDATA; $XDG_DATA_HOME/aieh, else ~/.local/share/aieh; on macOS
    ~/Library/Application Support/aieh (unverified)."""
    def absolute(var: str) -> PurePath | None:
        value = environ.get(var, '')
        return _norm(platform, value) if value and _pure(platform)(value).is_absolute() else None
    if platform == 'win32':
        if (base := absolute('LOCALAPPDATA')) is None:
            raise PathsError('DEFAULT_ROOT_UNAVAILABLE', 'LOCALAPPDATA is not set to an absolute path')
        return base / 'AIEH'
    if platform != 'darwin' and (xdg := absolute('XDG_DATA_HOME')) is not None:
        return xdg / 'aieh'
    if (home := absolute('HOME')) is None:
        raise PathsError('DEFAULT_ROOT_UNAVAILABLE', 'HOME is not set to an absolute path')
    return home / ('Library/Application Support' if platform == 'darwin' else '.local/share') / 'aieh'


def load_config(repo: PurePath):
    """Parse <repo>/config.yml, or return None when it does not exist (the supported default)."""
    path = Path(str(repo)) / CONFIG_NAME
    if not os.path.lexists(path):
        return None
    if not os.path.isfile(path):
        raise PathsError('CONFIG_UNREADABLE', f'{path} is not a regular file')
    try:
        import yaml
    except ImportError:
        raise PathsError('CONFIG_NEEDS_YAML', f'{path} exists and PyYAML is not importable') from None
    try:
        with open(path, encoding='utf-8') as handle:
            return yaml.safe_load(handle)
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        mark = getattr(exc, 'problem_mark', None)  # never echo document text: it may hold a value
        where = f' at line {mark.line + 1}' if mark is not None else ''
        raise PathsError('CONFIG_UNREADABLE', f'{path}: {type(exc).__name__}{where}') from None


def _refuse_secret_shaped(node, prefix: str) -> None:
    items = node.items() if isinstance(node, dict) else enumerate(node) if isinstance(node, list) else ()
    for key, value in items:
        name = f'{prefix}{key}' if isinstance(node, dict) else f'{prefix}[{key}]'
        if isinstance(node, dict) and SECRET_SHAPED.search(str(key)):
            raise PathsError('CONFIG_SECRET_SHAPED_KEY', f'{name} is secret-shaped (its value is not shown)')
        _refuse_secret_shaped(value, name + '.')


def _known(key, allowed: tuple, prefix: str) -> None:
    if key in ('data_root', 'root'):
        raise PathsError('CONFIG_UNKNOWN_KEY', f'{prefix}{key}: config.yml carries no root key; set the '
                                               f'managed root with {ENV_ROOT}')
    if key not in allowed:
        raise PathsError('CONFIG_UNKNOWN_KEY', f'unknown key {prefix}{key}; known: {", ".join(allowed)}')


def validate_config(data) -> tuple[dict, dict, dict]:
    """Schema v1: version, paths.<category or external location>, components.<name>.
    Returns (category overrides, registered external locations, components)."""
    if data is None or data == {}:
        return {}, {}, {}
    if not isinstance(data, dict):
        raise PathsError('CONFIG_NOT_A_MAPPING', f'config.yml holds a {type(data).__name__}, not a mapping')
    _refuse_secret_shaped(data, '')
    for key in data:
        _known(key, ('version', 'paths', 'components'), '')
    if type(version := data.get('version')) is not int or version != 1:
        raise PathsError('CONFIG_VERSION_UNSUPPORTED', f'version {version!r} is not supported; this resolver '
                                                       'reads version 1')
    for key in ('paths', 'components'):
        if data.get(key) is not None and not isinstance(data[key], dict):
            raise PathsError('CONFIG_NOT_A_MAPPING', f'{key} is a {type(data[key]).__name__}, not a mapping')
    paths, components = data.get('paths') or {}, data.get('components') or {}
    for key, value in paths.items():
        _known(key, tuple(CATEGORIES) + EXTERNAL, 'paths.')
        if not isinstance(value, str) or not value.strip() or chr(0) in value:
            raise PathsError('CONFIG_PATH_TYPE', f'paths.{key} must be a non-empty path string, not '
                                                 f'{type(value).__name__}')
    for key, value in components.items():
        if not isinstance(key, str) or not isinstance(value, (dict, type(None))):
            raise PathsError('CONFIG_NOT_A_MAPPING', f'components.{key} must be a mapping')
    return ({k: v for k, v in paths.items() if k in CATEGORIES},
            {k: v for k, v in paths.items() if k in EXTERNAL}, dict(components))


def _check_root(root: PurePath, repo: PurePath, environ: Mapping[str, str], platform: str) -> None:
    if _is_unc(root):
        raise PathsError('ROOT_UNC_OR_NETWORK', f'the root {root} is a network (UNC) path')
    if root.parent == root:
        raise PathsError('ROOT_IS_DRIVE_ROOT', f'the root {root} is a volume root')
    for var in PROFILE_VARS:
        value = environ.get(var, '')
        if value and _pure(platform)(value).is_absolute() and root == _norm(platform, value):
            raise PathsError('ROOT_IS_PROFILE_ROOT', f'the root {root} is {var} itself')
    if inside_or_around(root, repo, platform):
        raise PathsError('ROOT_INSIDE_CHECKOUT', f'the root {root} is inside or contains the checkout {repo}')


def _check_path(name: str, path: PurePath, repo: PurePath, platform: str | None = None) -> None:
    if name in STORE_CATEGORIES and _is_unc(path):
        raise PathsError('PATH_NETWORK_FOR_STORE', f'paths.{name} {path} is a network (UNC) path')
    if path.parent == path:
        raise PathsError('PATH_IS_DRIVE_ROOT', f'paths.{name} {path} is a volume root')
    if inside_or_around(path, repo, platform):
        raise PathsError('PATH_INSIDE_CHECKOUT', f'paths.{name} {path} is inside or contains the checkout {repo}')


def _drive_type(drive: str) -> int:
    """storecore's GetDriveTypeW check, loaded as the effects store loads it."""
    if (module := sys.modules.get('aieh_storecore')) is None:
        spec = importlib.util.spec_from_file_location('aieh_storecore',
                                                      REPO / 'integrations' / 'storecore' / 'storecore.py')
        module = sys.modules['aieh_storecore'] = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module.drive_type(drive)


def _filesystem_checks(res: Resolution) -> None:
    """After every lexical check, reading only: link-resolved locations against the checkout, and on
    Windows the volume type of the root and of the store categories."""
    real_repo = _norm(res.platform, os.path.realpath(str(res.repo_root)))
    for name, path in [('root', res.root)] + list(res.paths.items()):
        real = _norm(res.platform, os.path.realpath(str(path)))
        if inside_or_around(real, real_repo, res.platform):
            raise PathsError('ROOT_INSIDE_CHECKOUT' if name == 'root' else 'PATH_INSIDE_CHECKOUT',
                             f'{name} {path} resolves to {real}, inside or containing the checkout {real_repo}')
        if res.platform == 'win32' and (name == 'root' or name in STORE_CATEGORIES):
            drive = ntpath.splitdrive(str(real))[0]
            if drive.startswith(BS * 2) or (drive and _drive_type(drive) in NON_FIXED):
                raise PathsError('ROOT_UNC_OR_NETWORK' if name == 'root' else 'PATH_NETWORK_FOR_STORE',
                                 f'{name} {path} is not on a local fixed volume')


def resolve(environ: Mapping[str, str] | None = None, *, platform: str | None = None, repo_root=None,
            config=None) -> Resolution:
    """Compute the root and every category. Precedence, highest first: a config.yml override, then
    AIEH_DATA_ROOT, then the OS default. Creates nothing. config None reads <repo>/config.yml when it
    exists (host platform only); any other value is used as the parsed configuration."""
    env = os.environ if environ is None else environ
    plat = platform or sys.platform
    if not (repo := _norm(plat, REPO if repo_root is None else repo_root)).is_absolute():
        raise ValueError(f'the repository anchor must be absolute: {repo}')
    if raw := env.get(ENV_ROOT, ''):
        root = _join(plat, repo, raw, 'ROOT_NOT_ABSOLUTE_AFTER_ANCHOR', ENV_ROOT)
        source = 'env' if _pure(plat)(raw).is_absolute() else 'env-relative'
    else:
        root, source = default_root(env, plat), 'default'
    _check_root(root, repo, env, plat)
    if config is None and plat == sys.platform:
        config = load_config(repo)
    overrides, external, components = validate_config(config)
    paths, sources, warnings = {}, {}, []
    for name, category in CATEGORIES.items():
        if name in overrides:
            paths[name] = _join(plat, root, overrides[name], 'CONFIG_PATH_TYPE', f'paths.{name}')
        else:
            paths[name] = _norm(plat, root / category.default)
        sources[name] = 'config' if name in overrides else 'root'
        _check_path(name, paths[name], repo, plat)
        if not paths[name].is_relative_to(root):
            warnings.append(f'paths.{name} lies outside the managed root: {paths[name]}')
    names = list(paths)
    for index, a in enumerate(names):
        for b in names[index + 1:]:
            if _overlaps(paths[a], paths[b]):
                raise PathsError('PATH_OVERLAP', f'paths.{a} ({paths[a]}) and paths.{b} ({paths[b]}) overlap')
    for name, value in external.items():
        if not _pure(plat)(value).is_absolute():
            raise PathsError('CONFIG_PATH_TYPE', f'paths.{name} must be absolute: a registered external '
                                                 'location is never relative to the managed root')
    ext = {name: _norm(plat, external[name]) if name in external else None for name in EXTERNAL}
    res = Resolution(root, source, repo, plat, paths, sources, ext, components, warnings)
    if plat == sys.platform:
        _filesystem_checks(res)
    return res


def check_effects_root(effects_root, res: Resolution) -> None:
    """For the effects store (F-07.2): refuse an effects root inside or containing the managed root or a
    category relocated outside it. Directory placement is not a security control; custody checks are."""
    path = _norm(res.platform, effects_root)
    for name, managed in [('the managed root', res.root)] + [
            (f'paths.{n}', p) for n, p in res.paths.items() if res.outside_root(n)]:
        if _overlaps(path, managed):
            raise PathsError('LOCATION_MANAGED_ROOT', f'the effects root {path} is inside or contains {name} '
                                                      f'{managed}')


def emit(res: Resolution, fmt: str) -> str:
    """json, or sh / ps1 assignments of AIEH_PATH_<NAME>. No adapter re-implements precedence."""
    if fmt == 'json':
        return json.dumps(res.to_json(), indent=2) + '\n'
    pairs = [('ROOT', res.root)] + list(res.paths.items()) + [(n, p) for n, p in res.external.items() if p]
    lines = []
    for name, path in pairs:
        key, text = 'AIEH_PATH_' + name.upper(), str(path)
        if fmt == 'sh':
            lines.append(f"export {key}='" + text.replace("'", "'" + BS + "''") + "'")
        else:  # PowerShell also treats the typographic single quotes as quotes
            for quote in ("'", chr(0x2018), chr(0x2019), chr(0x201A), chr(0x201B)):
                text = text.replace(quote, quote * 2)
            lines.append(f"$env:{key} = '{text}'")
    return '\n'.join(lines) + '\n'


def marker_state(root: Path, *, refuse_mismatch: bool = False) -> str:
    """present, missing or mismatch (refused with ROOT_MARKER_MISMATCH when asked)."""
    if not os.path.lexists(marker := Path(root) / MARKER_NAME):
        return 'missing'
    try:
        with open(marker, encoding='utf-8') as handle:
            found = json.load(handle).get('format')
    except (OSError, ValueError, AttributeError):
        found = None
    if found != MARKER_FORMAT and refuse_mismatch:
        raise PathsError('ROOT_MARKER_MISMATCH', f'{marker} is not an {MARKER_FORMAT} marker')
    return 'present' if found == MARKER_FORMAT else 'mismatch'


def _make(base: Path, target: Path, *, volume_child_ok: bool) -> list[str]:
    """Create base, only when its parent exists, then each directory down to target. Each refusal is
    decided before the first mkdir. Never deletes."""
    created = []
    for directory in [p for p in (target, *target.parents) if p.is_relative_to(base)][::-1]:
        if os.path.isdir(directory):
            continue
        if directory == base:
            if base.parent.parent == base.parent and not volume_child_ok:
                raise PathsError('DRIVE_ROOT_CREATE', f'{base} would be created directly below a volume root')
            if not os.path.isdir(base.parent):
                raise PathsError('ROOT_PARENT_MISSING', f'the parent of {base} does not exist')
        try:
            os.mkdir(directory) if os.name == 'nt' else os.mkdir(directory, 0o700)
        except FileExistsError:
            if not os.path.isdir(directory):
                raise
            continue
        created.append(str(directory))
    return created


def _host_root(res: Resolution) -> Path:
    if res.platform != sys.platform:
        raise ValueError(f'cannot create {res.platform} paths on {sys.platform}')
    return Path(str(res.root))


def ensure(category: str, res: Resolution | None = None, *parts: str) -> Path:
    """Create if needed and return a category directory, optionally with one-segment parts such as a
    component name. The root is created only when its parent exists and is not a volume root."""
    res = resolve() if res is None else res
    if category not in CATEGORIES:
        raise KeyError(f'{category!r} is not a managed category; registered external locations are never created')
    if not all(isinstance(part, str) and SEGMENT.fullmatch(part) for part in parts):
        raise ValueError(f'unsafe path segment in {parts!r}')
    root, path = _host_root(res), Path(str(res.paths[category]))
    if os.path.isdir(root):
        marker_state(root, refuse_mismatch=True)
    _make(path if res.outside_root(category) else root, path.joinpath(*parts), volume_child_ok=False)
    return path.joinpath(*parts)


def init(res: Resolution | None = None) -> dict:
    """task paths:init: create the root (also directly below a volume root, where the Owner named it so),
    its persistent/, ephemeral/ and assets/ directories, and the aieh-root/1 marker."""
    res = resolve() if res is None else res
    root = _host_root(res)
    created = _make(root, root, volume_child_ok=True)
    if marker_state(root, refuse_mismatch=True) == 'missing':
        with open(root / MARKER_NAME, 'x', encoding='utf-8') as handle:
            json.dump({'format': MARKER_FORMAT, 'created_at': now(), 'resolver_version': RESOLVER_VERSION},
                      handle, indent=2)
            handle.write('\n')
        created.append(str(root / MARKER_NAME))
    for lifecycle in LIFECYCLES:
        created += _make(root, root / lifecycle, volume_child_ok=False)
    return {'root': str(root), 'root_source': res.root_source, 'created': created}


def legacy_locations(environ: Mapping[str, str], platform: str) -> list[dict]:
    """The former per-user defaults of the integration store and of the gate's Gitleaks cache."""
    def base(var: str, *fallback: str) -> PurePath | None:
        value, home, pure = environ.get(var, ''), environ.get('HOME', ''), _pure(platform)
        if value and pure(value).is_absolute():
            return pure(value)
        return pure(home).joinpath(*fallback) if fallback and home and pure(home).is_absolute() else None
    if platform == 'win32':
        bases = {'data': base('LOCALAPPDATA'), 'cache': base('LOCALAPPDATA')}
    else:
        bases = {'data': base('XDG_DATA_HOME', '.local', 'share'), 'cache': base('XDG_CACHE_HOME', '.cache')}
    return [{'name': name, 'classification': kind, 'migration': recipe, 'path': None if bases[which] is None
             else str(_norm(platform, bases[which].joinpath('ai-engineering-harness', *parts)))}
            for name, which, parts, kind, recipe in LEGACY]


def doctor(res: Resolution | None = None, environ: Mapping[str, str] | None = None) -> dict:
    """task paths:doctor: the resolution, what exists, the marker and the legacy locations. Reads only."""
    env = os.environ if environ is None else environ
    res = resolve(env) if res is None else res
    exists = os.path.isdir(root := _host_root(res))
    report = {'format': DOCTOR_FORMAT, 'root': str(root), 'root_source': res.root_source, 'root_exists': exists,
              'marker': marker_state(root) if exists else 'missing',
              'categories': [{'name': n, 'path': str(res.paths[n]), 'lifecycle': c.lifecycle, 'class': c.cls,
                              'layout': c.layout, 'creator': c.creator, 'consumer': c.consumer,
                              'source': res.sources[n], 'exists': os.path.isdir(res.paths[n])}
                             for n, c in CATEGORIES.items()],
              'external': res.to_json()['external'], 'effects_root_check': 'not set',
              'legacy': [dict(row, exists=row['path'] is not None and os.path.isdir(row['path']))
                         for row in legacy_locations(env, res.platform)],
              'warnings': list(res.warnings)}
    if report['marker'] != 'present':
        report['warnings'].append(f'the root marker is {report["marker"]}: run task paths:init')
    if res.external['effects_root'] is not None:
        try:
            check_effects_root(res.external['effects_root'], res)
            report['effects_root_check'] = 'ok'
        except PathsError as exc:
            report['effects_root_check'] = exc.code
    return report


def asset_record(kind: str, name: str, version: str, *, source: str, reacquire: str,
                 sha256: Mapping[str, str] | None = None, pin: str | None = None, consumers=()) -> dict:
    """An aieh-asset/1 record, kept as assets/<kind>/<name>/<version>/aieh-asset.json: the version, the
    provenance (source URL or registry), the integrity (sha256 per file, the pin, or both) and how to
    reacquire it. consumers names who depends on it; an asset is reclaimed only deliberately."""
    integrity = {**({'sha256': dict(sha256)} if sha256 else {}), **({'pin': pin} if pin else {})}
    record = {'format': ASSET_FORMAT, 'kind': kind, 'name': name, 'version': version,
              'provenance': {'source': source}, 'integrity': integrity, 'reacquire': reacquire,
              'acquired_at': now(), 'consumers': list(consumers)}
    check_asset_record(record)
    return record


def check_asset_record(record) -> None:
    def require(ok, why: str) -> None:
        if not ok:
            raise PathsError('ASSET_RECORD_INVALID', why)
    fields = {'format', 'kind', 'name', 'version', 'provenance', 'integrity', 'reacquire', 'acquired_at', 'consumers'}
    require(isinstance(record, dict) and record.get('format') == ASSET_FORMAT, f'the record is not {ASSET_FORMAT}')
    require(set(record) == fields, f'fields differ from the format: {sorted(set(record) ^ fields)}')
    for field in ('kind', 'name', 'version'):
        require(isinstance(record[field], str) and SEGMENT.fullmatch(record[field]), f'{field}: one path segment')
    provenance, integrity = record['provenance'], record['integrity']
    require(isinstance(provenance, dict) and set(provenance) == {'source'} and isinstance(provenance['source'], str)
            and provenance['source'], 'provenance.source (a source URL or registry) is required')
    require(isinstance(integrity, dict) and integrity and set(integrity) <= {'sha256', 'pin'},
            'integrity needs sha256 digests, a pin, or both')
    digests, pin = integrity.get('sha256'), integrity.get('pin')
    require(digests is None or isinstance(digests, dict) and digests and all(
        isinstance(f, str) and SEGMENT.fullmatch(f) and isinstance(d, str) and SHA256_HEX.fullmatch(d)
        for f, d in digests.items()), 'integrity.sha256 maps file names to lowercase sha256 hex digests')
    require(pin is None or isinstance(pin, str) and pin, 'integrity.pin must be a non-empty string')
    for field in ('reacquire', 'acquired_at'):
        require(isinstance(record[field], str) and record[field], f'{field} is required')
    require(isinstance(record['consumers'], list) and all(isinstance(c, str) for c in record['consumers']),
            'consumers is a list of names')


def write_asset_record(directory, record: dict) -> Path:
    check_asset_record(record)
    with open(path := Path(directory) / ASSET_RECORD_NAME, 'x', encoding='utf-8') as handle:
        json.dump(record, handle, indent=2)
        handle.write('\n')
    return path


def read_asset_record(directory) -> dict:
    try:
        with open(Path(directory) / ASSET_RECORD_NAME, encoding='utf-8') as handle:
            record = json.load(handle)
    except (OSError, ValueError) as exc:
        raise PathsError('ASSET_RECORD_INVALID', f'{directory}: {type(exc).__name__}') from None
    check_asset_record(record)
    return record


def now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def main(argv=None, environ: Mapping[str, str] | None = None, repo_root=None, out=None, err=None) -> int:
    parser = argparse.ArgumentParser(prog='aieh_paths.py', description='The managed data root and its categories '
                                     '(decision 0009). Exit 0 done, 2 refused (a stable code and its remedy).')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('show', help='print the resolution; creates nothing').add_argument(
        '--format', choices=('json', 'sh', 'ps1'), default='json')
    sub.add_parser('init', help='create the root, its lifecycle directories and its marker')
    sub.add_parser('doctor', help='report what exists, the marker and the legacy locations; changes nothing')
    args = parser.parse_args(argv)
    env = os.environ if environ is None else environ
    out, err = out or sys.stdout, err or sys.stderr
    if out is sys.stdout and hasattr(out, 'reconfigure'):
        out.reconfigure(encoding='utf-8')
    try:
        res = resolve(env, repo_root=repo_root)
        if args.command == 'show':
            out.write(emit(res, args.format))
        else:
            out.write(json.dumps(init(res) if args.command == 'init' else doctor(res, env), indent=2) + '\n')
    except PathsError as exc:
        err.write(f'aieh-paths: {exc}\n')
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
