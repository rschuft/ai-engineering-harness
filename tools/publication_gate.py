#!/usr/bin/env python3
"""Publication-safety gate for this public repository (stdlib only).

The gate keeps secrets and private machine information from being committed or
pushed. It runs Gitleaks locally, at a pinned and hash-verified release, from a
per-user cache outside the checkout. Nothing is sent to any external scanning
service; the only network access is ``install`` downloading the pinned release.

Modes (see CONTRIBUTING.md, "Publication-safety gate"):

  install      download, verify and cache the pinned Gitleaks; set core.hooksPath
  verify       check the cached binary's hash, its version and the hook wiring
  pre-commit   scan the exact staged content (called by .githooks/pre-commit)
  pre-push     scan every commit being introduced, from the pre-push stdin ref
               lines (called by .githooks/pre-push)
  history      read-only scan of every commit reachable from the given revisions
               (default: --all)

What is scanned: every blob a mode selects is read from git (the index or the
commits, never the working tree and never filtered by .gitignore), written into a
private temporary tree under its repository path, and scanned with the committed
.gitleaks.toml, which extends the Gitleaks default rules. gzip data is
decompressed and its content scanned. Any other binary or archive is refused
unless .gitleaks.toml allowlists its exact path with a reason. Every file the
scanner receives carries a per-run marker that the scanner must report, so a
scanner that silently skips a file, or "succeeds" without output, fails the gate.
A file that Gitleaks skips by a global path allowlist is rescanned under a
neutral name. Commit messages are scanned in pre-push and history modes.

Output never contains a matched value: only rule, path, line and commit.

Exit codes: 0 pass, 1 rejected (findings or refused content), 2 could not run.
Every failure to run (missing scanner, wrong hash, scanner error, timeout,
incomplete scan, unreadable configuration) exits 2, and the hooks then block.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import platform
import secrets
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import traceback
import urllib.request
import zipfile
import zlib
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

# --------------------------------------------------------------------------
# Pinned scanner. Asset hashes were checked against the release's checksums
# file and GitHub's per-asset sha256 digest when pinned; binary hashes are of
# the executable inside each archive. Gitleaks publishes no release signature.
# --------------------------------------------------------------------------
GITLEAKS_VERSION = '8.30.1'
RELEASE_BASE = f'https://github.com/gitleaks/gitleaks/releases/download/v{GITLEAKS_VERSION}/'
CHECKSUMS_ASSET = f'gitleaks_{GITLEAKS_VERSION}_checksums.txt'
CHECKSUMS_SHA256 = '061476c21adaf5441516f96f185c1a4706a83cd6329b9b38762271b3d4a52fae'


@dataclass(frozen=True)
class Artifact:
    asset: str
    asset_sha256: str
    member: str
    binary_sha256: str


ARTIFACTS = {
    ('windows', 'x86_64'): Artifact(
        f'gitleaks_{GITLEAKS_VERSION}_windows_x64.zip',
        'd29144deff3a68aa93ced33dddf84b7fdc26070add4aa0f4513094c8332afc4e',
        'gitleaks.exe', '17157e2ee8b76fc8b1d8bee607a250e34b8a8023c8bc81822d4b5ee4d78fcb7c'),
    ('windows', 'arm64'): Artifact(
        f'gitleaks_{GITLEAKS_VERSION}_windows_arm64.zip',
        'b95f5e4f5c425cedca7ee203d9afd29597e692c4924a12ed42f970537c72cc0f',
        'gitleaks.exe', '200df852fdecbedb19a33960657333cba5e231740bc8968972b507b50f93b194'),
    ('linux', 'x86_64'): Artifact(
        f'gitleaks_{GITLEAKS_VERSION}_linux_x64.tar.gz',
        '551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb',
        'gitleaks', '88f91962aa2f93ac6ab281d553b9e125f5197bbbce38f9f2437f7299c32e5509'),
    ('linux', 'arm64'): Artifact(
        f'gitleaks_{GITLEAKS_VERSION}_linux_arm64.tar.gz',
        'e4a487ee7ccd7d3a7f7ec08657610aa3606637dab924210b3aee62570fb4b080',
        'gitleaks', '00e91bbe655bd7c47753e8cfe61cb76ea1a5d7e7702fe161ee40102b46b3823b'),
    ('darwin', 'x86_64'): Artifact(
        f'gitleaks_{GITLEAKS_VERSION}_darwin_x64.tar.gz',
        'dfe101a4db2255fc85120ac7f3d25e4342c3c20cf749f2c20a18081af1952709',
        'gitleaks', 'cee01fea7173f1b779dff188e1c26ecbcb4027d394acc573b23aaf0be260e291'),
    ('darwin', 'arm64'): Artifact(
        f'gitleaks_{GITLEAKS_VERSION}_darwin_arm64.tar.gz',
        'b40ab0ae55c505963e365f271a8d3846efbc170aa17f2607f13df610a9aeb6a5',
        'gitleaks', 'ba52fb1bfabbcde42f032afad3d6e0b19dff8ed105229a16e7caa338bbc0e84f'),
}

# argv prefix for running the scanner. Empty in production; the tests replace
# it, in a throwaway copy of this file, to run a stub scanner.
SCANNER_PREFIX: tuple[str, ...] = ()

HOOKS_PATH = '.githooks'
HOOK_NAMES = ('pre-commit', 'pre-push')
CONFIG_PATH = '.gitleaks.toml'
CONFIG_SECTION = 'publication_gate'
LEAKS_EXIT = 42
DEFAULT_TIMEOUT = 600          # seconds per scanner run; AIEH_GATE_TIMEOUT overrides
GIT_TIMEOUT = 300
MAX_DOWNLOAD = 64 * 1024 * 1024
MAX_DECOMPRESSED = 256 * 1024 * 1024
MAX_GZIP_DEPTH = 3
CANARY_RULE_ID = 'publication-gate-canary'
CANARY_PREFIX = 'PUBLICATION_GATE_CANARY_'
CANARY_RULE = (
    '\n\n# Appended by tools/publication_gate.py to its private copy of the configuration.\n'
    '[[rules]]\n'
    f'id = "{CANARY_RULE_ID}"\n'
    'description = "Per-run marker written into every scanned file; proves the file was read."\n'
    f"regex = '''{CANARY_PREFIX}[0-9a-f]{{32}}'''\n"
    f'keywords = ["{CANARY_PREFIX.lower()}"]\n'
)
MESSAGE_PATH = 'COMMIT_EDITMSG'

# Content that cannot be inspected as text. gzip is decompressed instead.
BINARY_SUFFIXES = frozenset('''
    .zip .jar .war .ear .whl .egg .nupkg .apk .aab .ipa .vsix .crx .xpi
    .tar .tgz .tbz .tbz2 .txz .7z .rar .xz .bz2 .zst .lz .lz4 .lzma .z .cab .cpio .ar .deb .rpm
    .qcow .qcow2 .vmdk .vhd .vhdx .vdi .ova .ovf .img .iso .dmg .wim .esd
    .exe .dll .so .dylib .msi .msix .appx .sys .bin .o .a .lib .obj .pdb .pyc .pyo .class .wasm .elc
    .pdf .png .jpg .jpeg .gif .bmp .ico .icns .webp .tif .tiff .psd .heic .avif
    .doc .docx .xls .xlsx .ppt .pptx .odt .ods .odp .rtf
    .mp3 .mp4 .m4a .wav .flac .ogg .opus .mov .avi .mkv .webm
    .woff .woff2 .ttf .otf .eot
    .db .sqlite .sqlite3 .mdb .accdb .parquet .pkl .pickle .npy .npz .h5 .onnx .pt .safetensors
    .p12 .pfx .jks .keystore .kdbx .gpg .kbx .der
'''.split())
BINARY_MAGIC = (
    b'PK\x03\x04', b'PK\x05\x06', b'PK\x07\x08', b'7z\xbc\xaf\x27\x1c', b'Rar!\x1a\x07',
    b'\xfd7zXZ\x00', b'\x28\xb5\x2f\xfd', b'%PDF-', b'\x89PNG\r\n', b'GIF87a', b'GIF89a',
    b'\xff\xd8\xff', b'\x7fELF', b'QFI\xfb', b'\xcf\xfa\xed\xfe', b'\xce\xfa\xed\xfe',
    b'\xfe\xed\xfa\xce', b'\xfe\xed\xfa\xcf', b'\xca\xfe\xba\xbe', b'MSCF', b'\xd0\xcf\x11\xe0',
    b'SQLite format 3\x00', b'\x00asm',
)


class GateError(Exception):
    """The gate could not run to completion. Always fails closed (exit 2)."""


# --------------------------------------------------------------------------
# Scanner location and integrity
# --------------------------------------------------------------------------
def host_key():
    if sys.platform == 'win32':
        system = 'windows'
    elif sys.platform.startswith('linux'):
        system = 'linux'
    elif sys.platform == 'darwin':
        system = 'darwin'
    else:
        raise GateError(f'unsupported platform {sys.platform!r}; no pinned Gitleaks build')
    machine = platform.machine().lower()
    arch = {'amd64': 'x86_64', 'x86_64': 'x86_64', 'x64': 'x86_64',
            'arm64': 'arm64', 'aarch64': 'arm64'}.get(machine)
    if arch is None or (system, arch) not in ARTIFACTS:
        raise GateError(f'unsupported machine {machine!r} on {system}; no pinned Gitleaks build')
    return system, arch


def expected_scanner():
    """(file name, sha256) of the pinned scanner executable for this host."""
    artifact = ARTIFACTS[host_key()]
    return artifact.member, artifact.binary_sha256


def tool_dir(environ=None):
    """Deterministic per-user cache directory for the pinned scanner."""
    environ = os.environ if environ is None else environ
    if sys.platform == 'win32':
        base = environ.get('LOCALAPPDATA', '')
        if not base or not os.path.isabs(base):
            raise GateError('LOCALAPPDATA is not set to an absolute path; cannot locate the tool cache')
        root = Path(base)
    else:
        xdg = environ.get('XDG_CACHE_HOME', '')
        if xdg and os.path.isabs(xdg):
            root = Path(xdg)
        else:
            home = environ.get('HOME', '')
            if not home or not os.path.isabs(home):
                raise GateError('neither XDG_CACHE_HOME nor HOME is an absolute path; cannot locate the tool cache')
            root = Path(home) / '.cache'
    return root / 'ai-engineering-harness' / 'tools' / 'gitleaks' / GITLEAKS_VERSION


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def require_scanner():
    """Return the cached scanner path after re-verifying its sha256."""
    name, want = expected_scanner()
    path = tool_dir() / name
    if not path.is_file():
        raise GateError(f'Gitleaks {GITLEAKS_VERSION} is not installed in the per-user tool cache; '
                        'run `task hooks:install` (python -I -B tools/publication_gate.py install)')
    try:
        got = sha256_file(path)
    except OSError as exc:
        raise GateError(f'cannot read the cached scanner: {exc.strerror or exc}') from None
    if got != want:
        raise GateError(f'cached scanner sha256 {got} does not match the pinned {want}; '
                        'refusing to run it. Reinstall with `task hooks:install`')
    return path


# --------------------------------------------------------------------------
# git helpers
# --------------------------------------------------------------------------
def git(args, *, data=None, check=True):
    try:
        proc = subprocess.run(['git', *args], input=data, capture_output=True, timeout=GIT_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GateError(f'git {args[0]} could not run: {exc.__class__.__name__}') from None
    if check and proc.returncode != 0:
        message = proc.stderr.decode('utf-8', 'replace').strip().splitlines()
        raise GateError(f'git {args[0]} failed (exit {proc.returncode})'
                        + (f': {message[-1]}' if message else ''))
    return proc


def git_out(args, **kwargs):
    return git(args, **kwargs).stdout


def is_zero(sha):
    return set(sha) == {'0'}


def empty_tree():
    return git_out(['hash-object', '-t', 'tree', '--stdin'], data=b'').decode().strip()


def is_commit(rev):
    return git(['cat-file', '-e', f'{rev}^{{commit}}'], check=False).returncode == 0


def read_blobs(shas):
    unique = list(dict.fromkeys(shas))
    if not unique:
        return {}
    out = git_out(['cat-file', '--batch'], data=('\n'.join(unique) + '\n').encode())
    blobs, pos = {}, 0
    for sha in unique:
        end = out.find(b'\n', pos)
        header = out[pos:end].decode('ascii', 'replace').split()
        if end < 0 or len(header) != 3 or header[1] != 'blob':
            raise GateError(f'object {sha[:12]} is not a readable blob')
        size = int(header[2])
        start = end + 1
        blobs[sha] = out[start:start + size]
        pos = start + size + 1
    return blobs


def parse_raw_diff(out):
    """Yield (dst mode, dst sha, status letter, path) from `--raw -z --no-renames`."""
    parts = out.split(b'\0')
    i = 0
    while i < len(parts):
        meta = parts[i]
        if not meta:
            i += 1
            continue
        if not meta.startswith(b':') or i + 1 >= len(parts):
            raise GateError('unexpected git diff output')
        fields = meta[1:].decode('ascii', 'replace').split()
        if len(fields) < 5:
            raise GateError('unexpected git diff output')
        path = parts[i + 1].decode('utf-8', 'surrogateescape')
        i += 2
        yield fields[1], fields[3], fields[4][:1], path


def read_config(spec):
    proc = git(['cat-file', 'blob', spec], check=False)
    if proc.returncode != 0:
        raise GateError(f'the gate configuration {CONFIG_PATH} is not in {spec.split(":")[0] or "the index"}; '
                        'the gate cannot run without its committed configuration')
    return proc.stdout


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------
def load_gate_config(raw):
    """Validate the committed configuration; return the binary allowlist {path: reason}."""
    try:
        doc = tomllib.loads(raw.decode('utf-8'))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise GateError(f'{CONFIG_PATH} is not valid TOML: {exc.__class__.__name__}') from None
    extend = doc.get('extend')
    if not isinstance(extend, dict) or extend.get('useDefault') is not True:
        raise GateError(f'{CONFIG_PATH} must extend the Gitleaks default rules ([extend] useDefault = true)')
    for rule in doc.get('rules', []):
        if isinstance(rule, dict) and rule.get('id') == CANARY_RULE_ID:
            raise GateError(f'{CONFIG_PATH} must not define the reserved rule id {CANARY_RULE_ID}')
    section = doc.get(CONFIG_SECTION, {})
    if not isinstance(section, dict) or set(section) - {'binary_allowlist'}:
        raise GateError(f'[{CONFIG_SECTION}] in {CONFIG_PATH} may only contain binary_allowlist')
    allow = {}
    for entry in section.get('binary_allowlist', []):
        if (not isinstance(entry, dict) or set(entry) != {'path', 'reason'}
                or not isinstance(entry['path'], str) or not isinstance(entry['reason'], str)
                or not entry['path'].strip() or not entry['reason'].strip()):
            raise GateError(f'each binary_allowlist entry in {CONFIG_PATH} needs exactly a path and a non-empty reason')
        allow[entry['path']] = entry['reason']
    return allow


# --------------------------------------------------------------------------
# Content classification
# --------------------------------------------------------------------------
@dataclass
class Item:
    """One piece of git content to inspect: a blob at a path, or a commit message."""
    path: str
    data: bytes
    origins: list = field(default_factory=list)
    message: bool = False


@dataclass
class Entry:
    """One file handed to the scanner."""
    item: Item
    vpath: str            # path inside the scan tree (path rules see this)
    content: bytes
    decompressed: bool = False


def gunzip(data):
    out = bytearray()
    buf = data
    while buf:
        engine = zlib.decompressobj(16 + zlib.MAX_WBITS)
        out += engine.decompress(buf, MAX_DECOMPRESSED - len(out) + 1)
        if len(out) > MAX_DECOMPRESSED or engine.unconsumed_tail:
            raise ValueError('decompressed size exceeds the limit')
        if not engine.eof:
            raise ValueError('truncated gzip stream')
        buf = engine.unused_data
        if buf and not buf.startswith(b'\x1f\x8b'):
            if buf.strip(b'\0'):
                raise ValueError('trailing data after the gzip stream')
            break
    return bytes(out)


def looks_binary(vpath, data):
    if b'\0' in data:
        return True
    if PurePosixPath(vpath).suffix.lower() in BINARY_SUFFIXES:
        return True
    if data.startswith(BINARY_MAGIC) or data[257:262] == b'ustar':
        return True
    try:
        data.decode('utf-8')
        return False
    except UnicodeDecodeError:
        sample = data[:8192]
        control = sum(1 for b in sample if b < 9 or 13 < b < 32 or b == 127)
        return control * 10 > len(sample)


def decompressed_name(vpath):
    lower = vpath.lower()
    if lower.endswith('.gz'):
        return vpath[:-3]
    if lower.endswith('.tgz'):
        return vpath[:-4] + '.tar'
    return vpath + '.decompressed'


def classify(item, allow):
    """Return (entries, refusals, allowed binaries) for one item."""
    vpath = MESSAGE_PATH if item.message else item.path
    data, decompressed, depth, reason = item.data, False, 0, None
    while data.startswith(b'\x1f\x8b'):
        if depth == MAX_GZIP_DEPTH:
            reason = f'gzip nested deeper than {MAX_GZIP_DEPTH} levels'
            break
        try:
            data = gunzip(data)
        except (ValueError, zlib.error) as exc:
            reason = f'gzip data could not be decompressed ({exc.__class__.__name__})'
            break
        vpath, decompressed, depth = decompressed_name(vpath), True, depth + 1
    if reason is None and looks_binary(vpath, data):
        reason = 'binary or archive content cannot be inspected as text'
    if reason is None:
        return [Entry(item, vpath, data, decompressed)], [], []
    # Uninspectable: an empty placeholder keeps path-based rules effective.
    entry = Entry(item, vpath, b'', decompressed)
    if not item.message and item.path in allow:
        return [entry], [], [(item, allow[item.path])]
    return [entry], [(item, reason)], []


# --------------------------------------------------------------------------
# Scanning
# --------------------------------------------------------------------------
def scan_timeout():
    raw = os.environ.get('AIEH_GATE_TIMEOUT', '')
    if not raw:
        return DEFAULT_TIMEOUT
    try:
        value = int(raw)
    except ValueError:
        raise GateError('AIEH_GATE_TIMEOUT must be a positive integer number of seconds') from None
    if value <= 0:
        raise GateError('AIEH_GATE_TIMEOUT must be a positive integer number of seconds')
    return value


def safe_parts(vpath):
    parts = PurePosixPath(vpath).parts
    if not parts or vpath.startswith('/') or any(p in ('', '.', '..') or '\\' in p or ':' in p for p in parts):
        raise GateError(f'refusing to materialize an unusual path for scanning: {vpath!r}')
    return parts


def write_tree(root, numbered, canary, neutral):
    for index, entry in numbered:
        if neutral:
            target = root / f'{index}.txt'
        else:
            target = root.joinpath(str(index), *safe_parts(entry.vpath))
        body = entry.content
        if body and not body.endswith(b'\n'):
            body += b'\n'
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(body + canary + b'\n')
        except OSError as exc:
            raise GateError(f'cannot write a scan file for {entry.item.path}: {exc.strerror or exc}') from None


def run_scanner(binary, root, config_path, ignore_dir, report_path, timeout):
    argv = [*SCANNER_PREFIX, str(binary), 'dir', '.', '--config', str(config_path),
            '--report-format', 'json', '--report-path', str(report_path),
            '--exit-code', str(LEAKS_EXIT), '--redact', '--no-banner', '--no-color',
            '--ignore-gitleaks-allow', '--gitleaks-ignore-path', str(ignore_dir),
            '--log-level', 'error']
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith('GITLEAKS')}
    try:
        proc = subprocess.run(argv, cwd=root, env=env, stdin=subprocess.DEVNULL,
                              capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise GateError(f'the scanner timed out after {timeout}s; the scan did not complete') from None
    except OSError as exc:
        raise GateError(f'the scanner could not start: {exc.strerror or exc}') from None
    # Exit 0 means "no findings"; LEAKS_EXIT means findings. Either way the report
    # must exist, and the per-run markers are accounted for by the caller.
    if proc.returncode not in (0, LEAKS_EXIT):
        tail = proc.stderr.decode('utf-8', 'replace').strip().splitlines()[-5:]
        detail = ''.join(f'\n    scanner: {line[:300]}' for line in tail)
        raise GateError(f'the scanner failed (exit {proc.returncode}){detail}')
    try:
        report = json.loads(report_path.read_bytes())
    except (OSError, ValueError):
        if proc.returncode == 0:
            raise GateError('the scanner reported success without writing its report; '
                            'the scan did not complete') from None
        raise GateError('the scanner report is missing or unreadable; the scan did not complete') from None
    if not isinstance(report, list):
        raise GateError('the scanner report has an unexpected shape')
    findings = []
    for finding in report:
        if not (isinstance(finding, dict) and isinstance(finding.get('RuleID'), str)
                and isinstance(finding.get('File'), str) and isinstance(finding.get('StartLine'), int)):
            raise GateError('the scanner report has an unexpected shape')
        tags = finding.get('Tags') if isinstance(finding.get('Tags'), list) else []
        findings.append((finding['RuleID'], finding['File'].replace('\\', '/'),
                         finding['StartLine'], tuple(str(t) for t in tags)))
    return findings


def index_of(file_name, neutral, limit):
    head = file_name[2:] if file_name.startswith('./') else file_name
    head = head.split('/', 1)[0]
    if neutral:
        head = head[:-4] if head.endswith('.txt') else ''
    if not head.isdigit() or int(head) >= limit:
        raise GateError('the scanner reported a file the gate did not write')
    return int(head)


def scan(items, config_raw, binary):
    """Scan items; return (findings, refusals, allowed binaries)."""
    allow = load_gate_config(config_raw)
    entries, refusals, allowed = [], [], []
    for item in items:
        e, r, a = classify(item, allow)
        entries += e
        refusals += r
        allowed += a
    findings = set()
    if not entries:
        return [], refusals, allowed
    timeout = scan_timeout()
    with tempfile.TemporaryDirectory(prefix='aieh-gate-') as tmp:
        tmp = Path(tmp)
        config_text = config_raw + CANARY_RULE.encode()
        try:
            tomllib.loads(config_text.decode('utf-8'))
        except (UnicodeDecodeError, tomllib.TOMLDecodeError):
            raise GateError(f'{CONFIG_PATH} cannot be extended with the per-run marker rule') from None
        config_path = tmp / 'gitleaks.toml'
        config_path.write_bytes(config_text)
        ignore_dir = tmp / 'no-ignore-file'
        ignore_dir.mkdir()
        canary = (CANARY_PREFIX + secrets.token_hex(16)).encode()
        pending = list(enumerate(entries))
        for neutral in (False, True):
            root = tmp / ('neutral' if neutral else 'tree')
            root.mkdir()
            write_tree(root, pending, canary, neutral)
            seen = set()
            report = run_scanner(binary, root, config_path, ignore_dir, tmp / f'report-{int(neutral)}.json', timeout)
            for rule, file_name, line, tags in report:
                index = index_of(file_name, neutral, len(entries))
                if rule == CANARY_RULE_ID:
                    seen.add(index)
                else:
                    findings.add((index, rule, line, tags))
            # Files the scanner skipped (e.g. by a global path allowlist) are
            # rescanned once under a neutral name; anything still unseen fails.
            pending = [(i, e) for i, e in pending if i not in seen]
            if not pending:
                break
        if pending:
            names = ', '.join(sorted({e.item.path for _, e in pending})[:5])
            raise GateError(f'the scanner did not inspect {len(pending)} file(s) ({names}); the scan did not complete')
    return [(entries[i], rule, line, tags) for i, rule, line, tags in sorted(findings)], refusals, allowed


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------
def category(rule, tags):
    for tag in ('personal-path', 'credential-store'):
        if tag in tags:
            return tag
    return 'secret'


def where(item):
    if not item.origins:
        return 'staged'
    first = item.origins[0][:12]
    return f'commit {first}' + (f' (+{len(item.origins) - 1} more)' if len(item.origins) > 1 else '')


def location(entry, line):
    item = entry.item
    name = 'commit message' if item.message else item.path
    if entry.decompressed:
        name += ' (decompressed)'
    return f'{name}:{line}' if line > 0 else name


def report(mode, findings, refusals, allowed, scanned, stream):
    def out(text):
        print(text, file=stream)
    for item, reason in sorted(allowed, key=lambda a: a[0].path):
        out(f'publication-gate: {mode}: note: allowlisted binary, content not inspected: {item.path} ({reason})')
    rows = []
    for entry, rule, line, tags in findings:
        rows.append((category(rule, tags), rule, location(entry, line), where(entry.item)))
    for item, reason in refusals:
        rows.append(('uninspectable', 'binary-not-allowlisted', item.path, where(item) + f'; {reason}'))
    if not rows:
        out(f'publication-gate: {mode}: PASS ({scanned})')
        return 0
    out(f'publication-gate: {mode}: REJECTED, {len(rows)} finding(s) ({scanned}); values are never printed')
    for cat, rule, loc, origin in sorted(set(rows)):
        out(f'  [{cat}] {rule}  {loc}  ({origin})')
    out('  Remove the content before it is published. A credential that has ever left this machine')
    out('  is compromised: revoke and rotate it. False positive: propose a narrow, reasoned allowlist')
    out('  change in .gitleaks.toml. Never bypass with --no-verify. See CONTRIBUTING.md.')
    return 1


# --------------------------------------------------------------------------
# Item collection
# --------------------------------------------------------------------------
def staged_items():
    base = 'HEAD' if is_commit('HEAD') else empty_tree()
    out = git_out(['diff-index', '--cached', '--raw', '-z', '--no-renames', base])
    wanted = []
    for mode, sha, status, path in parse_raw_diff(out):
        if status == 'U':
            raise GateError('the index has unmerged paths; resolve them before committing')
        if status in 'AMT' and mode not in ('000000', '160000'):
            wanted.append((path, sha))
    blobs = read_blobs([sha for _, sha in wanted])
    return [Item(path, blobs[sha]) for path, sha in wanted]


def commit_items(commits):
    by_key, order = {}, []
    for commit in commits:
        out = git_out(['diff-tree', '-r', '-z', '--raw', '--no-renames', '--root', '-m',
                       '--no-commit-id', commit])
        for mode, sha, status, path in parse_raw_diff(out):
            if status in 'AMT' and mode not in ('000000', '160000'):
                key = (path, sha)
                if key not in by_key:
                    by_key[key] = []
                    order.append(key)
                if commit not in by_key[key]:
                    by_key[key].append(commit)
    blobs = read_blobs([sha for _, sha in order])
    items = [Item(path, blobs[sha], by_key[(path, sha)]) for path, sha in order]
    for commit in commits:
        raw = git_out(['cat-file', 'commit', commit])
        message = raw.split(b'\n\n', 1)[1] if b'\n\n' in raw else b''
        if message.strip():
            items.append(Item(f'commit message of {commit[:12]}', message, [commit], message=True))
    return items


def rev_list(args):
    return git_out(['rev-list', *args]).decode('ascii').split()


def pushed_commits(stdin_text):
    commits = []
    for line in stdin_text.splitlines():
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) != 4:
            raise GateError('unexpected pre-push input line')
        _local_ref, local_sha, _remote_ref, remote_sha = parts
        if is_zero(local_sha):
            continue  # deleting a remote ref introduces no content
        if not is_zero(remote_sha) and is_commit(remote_sha):
            commits += rev_list([local_sha, '--not', remote_sha])
        else:
            # New remote ref, or a remote tip not present locally: everything not
            # already reachable from a remote-tracking ref.
            commits += rev_list([local_sha, '--not', '--remotes'])
    return list(dict.fromkeys(commits))


# --------------------------------------------------------------------------
# Modes
# --------------------------------------------------------------------------
def mode_pre_commit():
    binary = require_scanner()
    config = read_config(f':{CONFIG_PATH}')
    items = staged_items()
    findings, refusals, allowed = scan(items, config, binary)
    return report('pre-commit', findings, refusals, allowed, f'{len(items)} staged file(s)', sys.stderr)


def mode_pre_push(stdin_text):
    binary = require_scanner()
    config = read_config(f'HEAD:{CONFIG_PATH}')
    commits = pushed_commits(stdin_text)
    items = commit_items(commits)
    findings, refusals, allowed = scan(items, config, binary)
    return report('pre-push', findings, refusals, allowed,
                  f'{len(commits)} new commit(s), {len(items)} blob(s) and message(s)', sys.stderr)


def mode_history(revs):
    binary = require_scanner()
    config = read_config(f'HEAD:{CONFIG_PATH}')
    commits = rev_list(revs or ['--all'])
    items = commit_items(commits)
    findings, refusals, allowed = scan(items, config, binary)
    return report('history', findings, refusals, allowed,
                  f'{len(commits)} commit(s), {len(items)} blob(s) and message(s)', sys.stdout)


def toplevel():
    out = git_out(['rev-parse', '--show-toplevel']).decode('utf-8').strip()
    return Path(out)


def download(asset):
    url = RELEASE_BASE + asset
    request = urllib.request.Request(url, headers={'User-Agent': 'ai-engineering-harness-publication-gate'})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            data = response.read(MAX_DOWNLOAD + 1)
    except OSError as exc:
        raise GateError(f'download of {asset} failed: {exc}') from None
    if len(data) > MAX_DOWNLOAD:
        raise GateError(f'download of {asset} exceeds the size limit')
    return data


def install_scanner(force=False):
    artifact = ARTIFACTS[host_key()]
    target = tool_dir() / artifact.member
    if target.is_file() and not force and sha256_file(target) == artifact.binary_sha256:
        print(f'Gitleaks {GITLEAKS_VERSION} already cached; sha256 verified')
        return target
    checksums = download(CHECKSUMS_ASSET)
    if sha256_bytes(checksums) != CHECKSUMS_SHA256:
        raise GateError(f'{CHECKSUMS_ASSET} does not match its pinned sha256')
    listed = {}
    for line in checksums.decode('ascii').splitlines():
        fields = line.split()
        if len(fields) == 2:
            listed[fields[1].lstrip('*')] = fields[0]
    if listed.get(artifact.asset) != artifact.asset_sha256:
        raise GateError(f'{CHECKSUMS_ASSET} does not list the pinned sha256 for {artifact.asset}')
    archive = download(artifact.asset)
    if sha256_bytes(archive) != artifact.asset_sha256:
        raise GateError(f'{artifact.asset} does not match its pinned sha256')
    try:
        if artifact.asset.endswith('.zip'):
            with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
                binary = bundle.read(artifact.member)
        else:
            with tarfile.open(fileobj=io.BytesIO(archive), mode='r:gz') as bundle:
                member = bundle.getmember(artifact.member)
                if not member.isfile():
                    raise GateError(f'{artifact.member} in {artifact.asset} is not a regular file')
                binary = bundle.extractfile(member).read()
    except (KeyError, zipfile.BadZipFile, tarfile.TarError) as exc:
        raise GateError(f'cannot extract {artifact.member} from {artifact.asset}: {exc}') from None
    if sha256_bytes(binary) != artifact.binary_sha256:
        raise GateError(f'{artifact.member} from {artifact.asset} does not match its pinned sha256')
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(f'.{artifact.member}.{secrets.token_hex(4)}.tmp')
    temp.write_bytes(binary)
    os.chmod(temp, 0o755)
    os.replace(temp, target)
    print(f'Gitleaks {GITLEAKS_VERSION} installed: {artifact.asset} sha256 verified against the pinned value '
          f'and {CHECKSUMS_ASSET}; binary sha256 {artifact.binary_sha256}')
    return target


def mode_install(force):
    top = toplevel()
    missing = [n for n in HOOK_NAMES if not (top / HOOKS_PATH / n).is_file()]
    if missing:
        raise GateError(f'hook script(s) missing from {HOOKS_PATH}/: {", ".join(missing)}')
    install_scanner(force)
    git(['config', '--local', 'core.hooksPath', HOOKS_PATH])
    print(f'core.hooksPath set to {HOOKS_PATH} in this repository\'s local git config')
    return 0


def mode_verify():
    failures = []
    binary = require_scanner()
    name, want = expected_scanner()
    print(f'scanner: Gitleaks {GITLEAKS_VERSION} {name} sha256 {want} OK (per-user cache)')
    try:
        proc = subprocess.run([*SCANNER_PREFIX, str(binary), 'version'], capture_output=True,
                              timeout=60, stdin=subprocess.DEVNULL)
        version = proc.stdout.decode('utf-8', 'replace').strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GateError(f'the scanner could not report its version: {exc.__class__.__name__}') from None
    if proc.returncode != 0 or version != GITLEAKS_VERSION:
        failures.append(f'scanner reports version {version!r}, expected {GITLEAKS_VERSION}')
    else:
        print(f'scanner: reports version {version}')
    top = toplevel()
    hooks_path = git(['config', '--local', '--get', 'core.hooksPath'], check=False).stdout.decode().strip()
    if hooks_path != HOOKS_PATH:
        failures.append(f'core.hooksPath is {hooks_path or "unset"}, expected {HOOKS_PATH} (run `task hooks:install`)')
    else:
        print(f'hooks: core.hooksPath = {HOOKS_PATH}')
    for hook in HOOK_NAMES:
        if not (top / HOOKS_PATH / hook).is_file():
            failures.append(f'hook {HOOKS_PATH}/{hook} is missing')
        else:
            print(f'hooks: {HOOKS_PATH}/{hook} present')
    allow = load_gate_config(read_config(f':{CONFIG_PATH}'))
    print(f'config: {CONFIG_PATH} (index) valid; {len(allow)} binary allowlist entr{"y" if len(allow) == 1 else "ies"}')
    for failure in failures:
        print(f'FAIL: {failure}')
    print('publication-gate: verify: ' + ('PASS' if not failures else 'FAIL'))
    return 0 if not failures else 1


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(errors='backslashreplace')
    parser = argparse.ArgumentParser(description='Publication-safety gate (see CONTRIBUTING.md).')
    sub = parser.add_subparsers(dest='mode', required=True)
    install = sub.add_parser('install', help='download, verify and cache Gitleaks; set core.hooksPath')
    install.add_argument('--force', action='store_true', help='download again even if the cache verifies')
    sub.add_parser('verify', help='check the cached scanner and the hook wiring')
    sub.add_parser('pre-commit', help='scan the staged content (git pre-commit hook)')
    push = sub.add_parser('pre-push', help='scan the commits being pushed (git pre-push hook; ref lines on stdin)')
    push.add_argument('remote', nargs='?')
    push.add_argument('url', nargs='?')
    history = sub.add_parser('history', help='read-only scan of all commits reachable from REVS (default --all)')
    history.add_argument('revs', nargs='*')
    args = parser.parse_args(argv)
    if sys.version_info < (3, 12):
        print('publication-gate: CANNOT RUN (fail closed): CPython >= 3.12 is required', file=sys.stderr)
        return 2
    try:
        if args.mode == 'install':
            return mode_install(args.force)
        if args.mode == 'verify':
            return mode_verify()
        if args.mode == 'pre-commit':
            return mode_pre_commit()
        if args.mode == 'pre-push':
            return mode_pre_push(sys.stdin.buffer.read().decode('utf-8', 'replace'))
        return mode_history(args.revs)
    except GateError as exc:
        print(f'publication-gate: {args.mode}: CANNOT RUN (fail closed): {exc}', file=sys.stderr)
        return 2
    except Exception as exc:  # never echo exception text: it could quote scanned content
        frames = ', '.join(f'line {f.lineno} in {f.name}' for f in traceback.extract_tb(exc.__traceback__))
        print(f'publication-gate: {args.mode}: CANNOT RUN (fail closed): internal error '
              f'{exc.__class__.__name__} at {frames}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
