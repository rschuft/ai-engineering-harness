"""Resolve, lock and install the MSYS2 packages of a provider lock (plan leaf F-03.2.1, A2).

Standard library only. Windows' built-in ``%SystemRoot%\\System32\\tar.exe`` (bsdtar,
with zstd) is the only external program: it decodes each ``.pkg.tar.zst`` (and the
``ucrt64.db`` repository database) into an uncompressed pax stream on stdout
(``tar.exe -cf - --format=pax @archive``), which this tool reads with ``tarfile``.
bsdtar never writes to disk here. Nothing downloaded is ever executed.

Subcommands:

  resolve  --db ucrt64.db --root NAME
      Resolve NAME's dependency closure from the repository database, honouring
      ``depends`` (with versions), ``provides``, ``conflicts`` and ``replaces``, and
      print the decisions and the resolved set.

  lock     --db ucrt64.db --root NAME --template LOCK --downloads DIR --out LOCK
      Resolve, check every archive in DIR against the database sha256, validate
      every archive entry, run the whole-set overlap check, and write a lock whose
      packages and link policy come from that evidence (other fields are kept from
      the template).

  install  --lock LOCK --lock-sha256 HEX --downloads DIR --prefix DIR --report FILE
      fetch     download each missing package from the lock's base URL (HTTPS, no
                redirects, sha256 checked while streaming); an existing file is
                re-checked in place and never overwritten.
      validate  list and validate every entry of every archive, run the link
                policy and the whole-set overlap check, and build the expected
                manifest. Nothing is extracted unless everything passes.
      extract   PREFIX must not exist. Every package except those marked
                ``"extract": false`` is written from its validated stream: regular
                files and directories only, metadata members skipped, hardlinks
                materialised as regular-file copies of their in-package target.
      verify    every installed file against the manifest (sha256 and size), the
                lock's extracted-file pins, no extra or missing path, no reparse
                point, no file with more than one link.

Exit status 0 on success; 1 on any finding (the report says which); 2 on usage.
"""
import argparse
import contextlib
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import urllib.error
import urllib.request
from pathlib import Path

TAR = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32' / 'tar.exe'
# Windows: a console process started with this flag gets a console that no window shows (0 elsewhere);
# every process this module starts carries it (tools/tests/test_launch_census.py checks it).
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
META = ('.PKGINFO', '.BUILDINFO', '.MTREE', '.INSTALL')
LINK_POLICY = 'materialise-as-copy'
RESERVED = re.compile(r'(?i)^(con|prn|aux|nul|conin\$|conout\$|com[0-9\u00b9\u00b2\u00b3]|'
                      r'lpt[0-9\u00b9\u00b2\u00b3])(\..*)?$')
WINDOWS_SPECIAL = set('\\:*?"<>|')
FILENAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9._+~-]*\.pkg\.tar\.zst')
MAX_PATH = 250


class Stop(Exception):
    """A finding that must stop the procedure."""


# --------------------------------------------------------------------------- streams

@contextlib.contextmanager
def pax_stream(archive):
    """Yield a stream-mode TarFile over bsdtar's uncompressed rewrite of ARCHIVE."""
    proc = subprocess.Popen([str(TAR), '-cf', '-', '--format=pax', '@' + str(archive)],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=NO_WINDOW)
    try:
        with tarfile.open(fileobj=proc.stdout, mode='r|') as tf:
            yield tf
        trailing = proc.stdout.read()  # bsdtar pads the record after the end marker
        if trailing.strip(b'\0'):
            raise Stop(f'{archive}: data after the end-of-archive marker')
    finally:
        proc.stdout.close()
        err = proc.stderr.read().decode('utf-8', 'replace').strip()
        proc.stderr.close()
        if proc.wait() != 0:
            raise Stop(f'{archive}: tar.exe exited {proc.returncode}: {err}')


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


# --------------------------------------------------------------------------- database

DESC_FIELDS = {'NAME', 'VERSION', 'FILENAME', 'SHA256SUM', 'CSIZE', 'LICENSE', 'DEPENDS',
               'PROVIDES', 'CONFLICTS', 'REPLACES', 'PGPSIG'}


def parse_desc(text):
    fields, key = {}, None
    for line in text.splitlines():
        if line.startswith('%') and line.endswith('%') and len(line) > 2:
            key = line[1:-1]
            fields.setdefault(key, [])
        elif line and key is not None:
            fields[key].append(line)
        elif not line:
            key = None
    return fields


def package_from_desc(fields):
    one = lambda k: fields[k][0] if fields.get(k) else None  # noqa: E731
    return {
        'name': one('NAME'), 'version': one('VERSION'), 'filename': one('FILENAME'),
        'sha256': one('SHA256SUM'), 'csize': int(one('CSIZE') or 0),
        'license': ' '.join(fields.get('LICENSE', [])),  # pacman's list, as written
        'depends': fields.get('DEPENDS', []), 'provides': fields.get('PROVIDES', []),
        'conflicts': fields.get('CONFLICTS', []), 'replaces': fields.get('REPLACES', []),
    }


def read_db(tf):
    """Read a repository database from a stream-mode TarFile: {name: package}."""
    db = {}
    for member in tf:
        if member.isfile() and member.name.endswith('/desc'):
            pkg = package_from_desc(parse_desc(tf.extractfile(member).read().decode('utf-8')))
            if not pkg['name'] or pkg['name'] in db:
                raise Stop(f'database: bad or duplicate entry {member.name}')
            db[pkg['name']] = pkg
    return db


# --------------------------------------------------------------------------- versions

def _alnum(c):
    return c.isascii() and c.isalnum()


def _alpha(c):
    return c.isascii() and c.isalpha()


def _digit(c):
    return c.isascii() and c.isdigit()


def _rpmvercmp(a, b):
    """libalpm's rpmvercmp: compare two version segments (no epoch, no release)."""
    if a == b:
        return 0
    i = j = 0
    while i < len(a) and j < len(b):
        si, sj = i, j
        while i < len(a) and not _alnum(a[i]):
            i += 1
        while j < len(b) and not _alnum(b[j]):
            j += 1
        if i >= len(a) or j >= len(b):
            break
        if (i - si) != (j - sj):  # separator runs of different length
            return -1 if (i - si) < (j - sj) else 1
        isnum = _digit(a[i])
        same = _digit if isnum else _alpha
        ei, ej = i, j
        while ei < len(a) and same(a[ei]):
            ei += 1
        while ej < len(b) and same(b[ej]):
            ej += 1
        if j == ej:  # segments of different type: a number is newer than letters
            return 1 if isnum else -1
        sa, sb = a[i:ei], b[j:ej]
        if isnum:
            sa, sb = sa.lstrip('0'), sb.lstrip('0')
            if len(sa) != len(sb):
                return 1 if len(sa) > len(sb) else -1
        if sa != sb:
            return -1 if sa < sb else 1
        i, j = ei, ej
    if i >= len(a) and j >= len(b):
        return 0
    if (i >= len(a) and not (j < len(b) and _alpha(b[j]))) or (i < len(a) and _alpha(a[i])):
        return -1
    return 1


def _evr(version):
    epoch, _, rest = version.partition(':') if ':' in version else ('0', '', version)
    ver, _, rel = rest.rpartition('-') if '-' in rest else (rest, '', None)
    return epoch or '0', ver, rel


def vercmp(a, b):
    """libalpm's alpm_pkg_vercmp."""
    if a == b:
        return 0
    ea, va, ra = _evr(a)
    eb, vb, rb = _evr(b)
    result = _rpmvercmp(ea, eb) or _rpmvercmp(va, vb)
    if result == 0 and ra is not None and rb is not None:
        result = _rpmvercmp(ra, rb)
    return result


DEP = re.compile(r'^([^<>=]+?)(?:(<=|>=|=|<|>)(.+))?$')


def parse_dep(text):
    match = DEP.match(text.split(': ', 1)[0].strip())
    if not match:
        raise Stop(f'unparseable dependency {text!r}')
    return match.group(1), match.group(2), match.group(3)


def _version_ok(version, op, want):
    if op is None:
        return True
    c = vercmp(version, want)
    return {'=': c == 0, '<': c < 0, '>': c > 0, '<=': c <= 0, '>=': c >= 0}[op]


def satisfies(pkg, dep):
    """libalpm's dependency check: the package itself or one of its provisions."""
    name, op, want = parse_dep(dep)
    if pkg['name'] == name and _version_ok(pkg['version'], op, want):
        return True
    for prov in pkg['provides']:
        pname, pop, pver = parse_dep(prov)
        if pname != name:
            continue
        if op is None:
            return True
        if pop == '=' and _version_ok(pver, op, want):
            return True
    return False


# --------------------------------------------------------------------------- resolver

def _closure(db, roots, excluded, log):
    selected, queue = [], list(roots)
    chosen = {}
    while queue:
        dep = queue.pop(0)
        if dep in chosen:
            continue
        sel = [db[n] for n in selected if satisfies(db[n], dep)]
        if sel:
            chosen[dep] = sel[0]['name']
            continue
        name = parse_dep(dep)[0]
        literal = db.get(name)
        if literal and name not in excluded and satisfies(literal, dep):
            pick = literal
        else:
            providers = sorted(p['name'] for p in db.values()
                               if p['name'] not in excluded and satisfies(p, dep))
            if not providers:
                raise Stop(f'unsatisfiable dependency {dep!r}')
            if len(providers) > 1:
                raise Stop(f'ambiguous dependency {dep!r}: provided by {providers}')
            pick = db[providers[0]]
            why = f'; {name} is {excluded[name]}' if name in excluded else ''
            log.append(f'{dep} -> {pick["name"]} (provider{why})')
        chosen[dep] = pick['name']
        selected.append(pick['name'])
        queue.extend(pick['depends'])
    return selected


def superseded(db):
    """Packages the repository replaces: X is superseded when another package R
    declares ``replaces`` matching X and itself satisfies X's name, so pacman's
    upgrade would swap X for R. A superseded package is never chosen."""
    out = {}
    for r in db.values():
        for rep in r['replaces']:
            for x in db.values():
                if x['name'] != r['name'] and satisfies(x, rep) and satisfies(r, x['name']):
                    out[x['name']] = f'replaced by {r["name"]}'
    return out


def resolve(db, roots):
    """Return (sorted package names, decision log). Raises Stop on any conflict left."""
    excluded, log = dict(superseded(db)), []
    for _ in range(len(db) + 1):
        selected = _closure(db, roots, excluded, log)
        drop = set()
        for a in selected:
            pa = db[a]
            for b in selected:
                if a == b:
                    continue
                pb = db[b]
                hit = [c for c in pa['conflicts'] + pa['replaces'] if satisfies(pb, c)]
                if not hit:
                    continue
                # pacman: of two conflicting targets, the one the other provides goes.
                if satisfies(pa, pb['name']) and not satisfies(pb, pa['name']):
                    drop.add(b)
                    log.append(f'{b} dropped: {a} declares {hit} and provides {b}')
                else:
                    raise Stop(f'unresolvable conflict between {a} and {b} ({hit})')
        if not drop:
            break
        excluded.update({b: 'dropped for a conflict' for b in drop})
    else:
        raise Stop('resolution did not converge')
    for a in selected:
        for dep in db[a]['depends']:
            if not any(satisfies(db[s], dep) for s in selected):
                raise Stop(f'{a}: dependency {dep!r} not satisfied by the resolved set')
    return sorted(selected), log


# --------------------------------------------------------------------------- entries

def name_problems(name):
    problems = []
    if not name:
        return ['empty name']
    if name.startswith(('/', '\\')):
        problems.append('absolute path')
    if re.match(r'^[A-Za-z]:', name):
        problems.append('drive letter')
    if any(ord(c) < 32 or ord(c) == 127 for c in name):
        problems.append('control character')
    special = WINDOWS_SPECIAL & set(name)
    if special:
        problems.append('Windows-special character ' + ''.join(sorted(special)))
    parts = name.split('/')
    for i, comp in enumerate(parts):
        if comp == '..':
            problems.append("traversal '..'")
        elif comp in ('', '.'):
            problems.append("empty or '.' component")
        elif RESERVED.match(comp):
            problems.append(f'reserved device name {comp!r}')
        elif comp.endswith(('.', ' ')):
            problems.append(f'trailing dot or space {comp!r}')
        elif comp in META and len(parts) > 1:
            problems.append(f'metadata name {comp!r} below the archive root')
    return problems


def entry_kind(member):
    if member.type in (tarfile.REGTYPE, tarfile.AREGTYPE):
        return 'file'
    return {tarfile.DIRTYPE: 'dir', tarfile.SYMTYPE: 'symlink', tarfile.LNKTYPE: 'hardlink',
            tarfile.CHRTYPE: 'chardev', tarfile.BLKTYPE: 'blockdev',
            tarfile.FIFOTYPE: 'fifo'}.get(member.type, f'other:{member.type!r}')


def scan_archive(tf, prefix_len=0):
    """Read one package stream: entries (with sha256 of regular files) and problems.

    Hardlinks are checked against the link policy: the link and its target are both
    under ucrt64/, and the target is a regular file earlier in the same package."""
    entries, problems, regular = [], [], {}
    for member in tf:
        name = member.name
        kind = entry_kind(member)
        entry = {'name': name, 'kind': kind}
        if name in META:
            entry['meta'] = True
            entries.append(entry)
            if kind != 'file':
                problems.append({'name': name, 'kind': kind,
                                 'problems': [f'metadata member of type {kind}']})
            continue
        probs = name_problems(name)
        if prefix_len and prefix_len + 1 + len(name) > MAX_PATH:
            probs.append('installed path too long')
        if kind == 'file':
            digest, size = hashlib.sha256(), 0
            fh = tf.extractfile(member)
            for block in iter(lambda: fh.read(1 << 20), b''):
                digest.update(block)
                size += len(block)
            entry.update(sha256=digest.hexdigest(), size=size)
            regular[name] = entry
        elif kind == 'hardlink':
            target = member.linkname
            entry['target'] = target
            tprobs = name_problems(target)
            if tprobs:
                probs.append(f'hardlink target {target!r}: {tprobs}')
            if not (name.startswith('ucrt64/') and target.startswith('ucrt64/')):
                probs.append('hardlink or its target outside ucrt64/')
            if target not in regular:
                probs.append(f'hardlink target {target!r} is not an earlier regular file '
                             f'in this package')
            else:
                entry.update(sha256=regular[target]['sha256'], size=regular[target]['size'])
        elif kind == 'symlink':
            entry['target'] = member.linkname
            probs.append('symlink')
        elif kind != 'dir':
            probs.append(f'entry type {kind}')
        if probs:
            problems.append({'name': name, 'kind': kind, 'problems': probs})
        entries.append(entry)
    return entries, problems


def listing_digest(entries):
    digest = hashlib.sha256()
    for e in entries:
        digest.update(json.dumps([e['name'], e['kind'], e.get('sha256'), e.get('target')])
                      .encode('utf-8') + b'\n')
    return digest.hexdigest()


def overlap_findings(per_package):
    """Whole-set check: no installed non-directory path (case-insensitive) in two
    packages, and no path that is a directory in one package and not in another."""
    owners, findings = {}, []
    for pkg, entries in per_package.items():
        for e in entries:
            if e.get('meta'):
                continue
            owners.setdefault(e['name'].casefold(), []).append((pkg, e['kind'], e['name']))
    for key, claims in sorted(owners.items()):
        kinds = {k for _, k, _ in claims}
        pkgs = sorted({p for p, _, _ in claims})
        if kinds == {'dir'}:
            continue
        if len(claims) > 1:
            findings.append({'path': claims[0][2], 'claims': [[p, k] for p, k, _ in claims],
                             'packages': pkgs})
    return findings


# --------------------------------------------------------------------------- lock

def check_lock_policy(pkg, entries, problems):
    """Apply the lock's policy to one package's scan. Returns findings (strings)."""
    findings = []
    hardlinks = sum(1 for e in entries if e['kind'] == 'hardlink')
    symlinks = sum(1 for e in entries if e['kind'] == 'symlink')
    if pkg.get('extract', True) is False:
        if hardlinks:
            findings.append(f'{pkg["filename"]}: not extracted but holds hardlinks')
        unexpected = [p for p in problems if p['problems'] != ['symlink']]
        if unexpected:
            findings.append(f'{pkg["filename"]}: {len(unexpected)} unsafe entries {unexpected[:3]}')
        return findings
    if symlinks:
        findings.append(f'{pkg["filename"]}: {symlinks} symlinks in an extracted package')
    if problems:
        findings.append(f'{pkg["filename"]}: {len(problems)} rejected entries {problems[:3]}')
    want = pkg.get('hardlinks', 0)
    if hardlinks != want or (hardlinks and pkg.get('link_policy') != LINK_POLICY):
        findings.append(f'{pkg["filename"]}: {hardlinks} hardlinks, lock records {want} '
                        f'with policy {pkg.get("link_policy")!r}')
    return findings


def build_lock(template, db, names, scans, roots, decisions):
    """A lock from the resolved names and their archive scans. Only a package the
    template already marks ``"extract": false`` may hold symlinks; it stays unextracted."""
    not_extracted = {p['name']: p for p in template['packages'] if p.get('extract') is False}
    packages = []
    for name in names:
        p = db[name]
        entry = {'name': p['name'], 'version': p['version'], 'filename': p['filename'],
                 'sha256': p['sha256'], 'license': p['license']}
        entries, problems = scans[name]
        symlinks = sum(1 for e in entries if e['kind'] == 'symlink')
        hardlinks = sum(1 for e in entries if e['kind'] == 'hardlink')
        unsafe = [x for x in problems if x['problems'] != ['symlink']]
        if unsafe:
            raise Stop(f'{p["filename"]}: unsafe entries {unsafe[:3]}')
        if name in not_extracted:
            if hardlinks:
                raise Stop(f'{p["filename"]}: unextracted package holds hardlinks')
            entry['extract'] = False
            entry['extract_reason'] = not_extracted[name]['extract_reason']
        elif symlinks:
            raise Stop(f'{p["filename"]}: {symlinks} symlinks in a package to be extracted')
        if hardlinks:
            entry['hardlinks'] = hardlinks
            entry['link_policy'] = LINK_POLICY
        packages.append(entry)
    missing = sorted(set(not_extracted) - set(names))
    if missing:
        raise Stop(f'packages marked "extract": false are no longer resolved: {missing}')
    resolution = {
        'tool': 'tools/msys2_lock.py lock',
        'roots': list(roots),
        'rules': ('libalpm dependency semantics: a dependency is met by a selected package, '
                  'else by the package of that name, else by its only provider; versioned '
                  'dependencies use alpm vercmp; a package another repository package '
                  'replaces and provides is never chosen; of two conflicting selected '
                  'packages, the one the other provides is dropped, any other conflict '
                  'stops; finally no two packages may install the same path'),
        'decisions': list(decisions),
    }
    lock = {}
    for key, value in template.items():
        if key == 'package_count' and 'resolution' not in template:
            lock['resolution'] = resolution
        lock[key] = value
    lock['resolution'] = resolution
    lock['package_count'] = len(packages)
    lock['packages'] = packages
    return lock


def dump_lock(lock):
    return (json.dumps(lock, indent=2, ensure_ascii=False) + '\n').encode('utf-8')


# --------------------------------------------------------------------------- install

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, f'redirect refused: {newurl}',
                                     headers, fp)


def fetch(lock, downloads, report):
    base = lock['repository']['base_url']
    if not base.startswith('https://') or not base.endswith('/'):
        raise Stop(f'base_url {base!r} is not an https directory URL')
    downloads.mkdir(parents=True, exist_ok=True)
    opener = urllib.request.build_opener(_NoRedirect())
    opener.addheaders = [('User-Agent', 'aieh-msys2-lock/1')]
    reused = fetched = size = 0
    bad = []
    for p in lock['packages']:
        fn = p['filename']
        if not FILENAME.fullmatch(fn):
            raise Stop(f'unexpected filename {fn!r}')
        dest = downloads / fn
        if dest.exists():
            got, n = sha256_file(dest), dest.stat().st_size
            reused += 1
        else:
            url = base + fn
            part = downloads / (fn + '.part')
            digest, n = hashlib.sha256(), 0
            with opener.open(url, timeout=120) as resp:
                if resp.status != 200 or resp.geturl() != url:
                    raise Stop(f'{url}: unexpected response {resp.status} {resp.geturl()}')
                with open(part, 'xb') as out:
                    for block in iter(lambda: resp.read(1 << 20), b''):
                        digest.update(block)
                        n += len(block)
                        out.write(block)
            got = digest.hexdigest()
            os.rename(part, dest)
            fetched += 1
        size += n
        if got != p['sha256']:
            bad.append({'filename': fn, 'sha256': got})
    report['fetch'] = {'packages': len(lock['packages']), 'reused': reused, 'fetched': fetched,
                       'bytes': size, 'bad': bad}
    if bad:
        raise Stop(f'{len(bad)} packages do not match the lock')


def validate(lock, downloads, prefix, report):
    scans, findings = {}, []
    totals = {'entries': 0, 'rejected': 0, 'hardlinks': {}, 'symlinks': {}}
    for p in lock['packages']:
        path = downloads / p['filename']
        if sha256_file(path) != p['sha256']:
            raise Stop(f'{p["filename"]}: changed since fetch')
        with pax_stream(path) as tf:
            entries, problems = scan_archive(tf, len(str(prefix)))
        scans[p['name']] = (entries, problems)
        totals['entries'] += len(entries)
        totals['rejected'] += len(problems)
        for kind in ('hardlinks', 'symlinks'):
            n = sum(1 for e in entries if e['kind'] == kind[:-1])
            if n:
                totals[kind][p['name']] = n
        findings += check_lock_policy(p, entries, problems)
    overlaps = overlap_findings({n: e for n, (e, _) in scans.items()})
    findings += [f'overlap {o["path"]}: {o["claims"]}' for o in overlaps]
    report['validate'] = dict(totals, overlaps=len(overlaps), findings=findings)
    if findings:
        raise Stop(f'{len(findings)} validation findings')
    files, dirs = {}, set()
    for p in lock['packages']:
        if p.get('extract', True) is False:
            continue
        for e in scans[p['name']][0]:
            if e.get('meta'):
                continue
            if e['kind'] == 'dir':
                dirs.add(e['name'])
            elif e['kind'] in ('file', 'hardlink'):
                files[e['name']] = {'sha256': e['sha256'], 'size': e['size'],
                                    'package': p['name'], 'kind': e['kind']}
            else:
                raise Stop(f'{e["name"]}: {e["kind"]} passed validation')
            parts = e['name'].split('/')
            dirs.update('/'.join(parts[:i]) for i in range(1, len(parts)))
    report['validate'].update(expected_files=len(files), expected_dirs=len(dirs),
                              expected_bytes=sum(f['size'] for f in files.values()))
    return scans, {'files': files, 'dirs': sorted(dirs)}


def _dest(prefix, name):
    dest = prefix.joinpath(*name.split('/'))
    real = os.path.realpath(dest)
    root = os.path.realpath(prefix)
    if os.path.commonpath([real, root]) != root or real == root:
        raise Stop(f'{name}: resolves outside the install directory')
    return dest


def extract(lock, downloads, prefix, scans, report):
    if os.path.lexists(prefix):
        raise Stop(f'{prefix} already exists')
    prefix.parent.mkdir(parents=True, exist_ok=True)
    prefix.mkdir()
    done, copies = 0, {}
    for p in lock['packages']:
        if p.get('extract', True) is False:
            continue
        expected, problems = scans[p['name']]
        if problems:
            raise Stop(f'{p["filename"]}: unvalidated entries reached extraction')
        # Each entry written must be the validated entry: same name, type and link
        # target in the same order, and each file's bytes hash to the validated sha256.
        written = set()
        with pax_stream(downloads / p['filename']) as tf:
            members = iter(tf)
            for entry in expected:
                member = next(members, None)
                if member is None or member.name != entry['name'] \
                        or entry_kind(member) != entry['kind'] \
                        or (entry.get('target') or '') != (member.linkname or ''):
                    raise Stop(f'{p["filename"]}: archive differs from its validated listing')
                if entry.get('meta'):
                    continue
                dest = _dest(prefix, entry['name'])
                if entry['kind'] == 'dir':
                    dest.mkdir(parents=True, exist_ok=True)
                elif entry['kind'] == 'file':
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    digest = hashlib.sha256()
                    src = tf.extractfile(member)
                    with open(dest, 'xb') as out:
                        for block in iter(lambda: src.read(1 << 20), b''):
                            digest.update(block)
                            out.write(block)
                    if digest.hexdigest() != entry['sha256']:
                        raise Stop(f'{entry["name"]}: content changed between passes')
                    written.add(entry['name'])
                elif entry['kind'] == 'hardlink':
                    target = _dest(prefix, entry['target'])
                    if entry['target'] not in written:
                        raise Stop(f'{entry["name"]}: target not written by this package')
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    with open(target, 'rb') as src, open(dest, 'xb') as out:
                        shutil.copyfileobj(src, out, 1 << 20)
                    copies[p['name']] = copies.get(p['name'], 0) + 1
                else:
                    raise Stop(f'{entry["name"]}: {entry["kind"]} reached extraction')
            if next(members, None) is not None:
                raise Stop(f'{p["filename"]}: archive has entries beyond its validated listing')
        done += 1
    report['extract'] = {'packages': done, 'failures': 0, 'materialised_hardlinks': copies}


def verify(lock, prefix, manifest, report):
    files, dirs, reparse, odd, multi = {}, set(), [], [], []
    for root, dnames, fnames in os.walk(prefix):
        rel = Path(root).relative_to(prefix).as_posix()
        for name in dnames + fnames:
            full = os.path.join(root, name)
            st = os.lstat(full)
            r = name if rel == '.' else f'{rel}/{name}'
            if getattr(st, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT \
                    or stat.S_ISLNK(st.st_mode):
                reparse.append(r)
            if name in dnames:
                dirs.add(r)
            elif not stat.S_ISREG(st.st_mode):
                odd.append(r)
            else:
                if st.st_nlink != 1:
                    multi.append([r, st.st_nlink])
                files[r] = (st.st_size, full)
    exp = manifest['files']
    mismatch = [r for r, (size, full) in sorted(files.items())
                if r in exp and (size != exp[r]['size'] or sha256_file(full) != exp[r]['sha256'])]
    pins = {}
    for r, want in lock.get('extracted_files', {}).items():
        full = prefix.joinpath(*r.split('/'))
        got = sha256_file(full) if full.is_file() else None
        pins[r] = {'sha256': got, 'ok': got == want}
    result = {
        'installed_files': len(files), 'installed_bytes': sum(s for s, _ in files.values()),
        'installed_dirs': len(dirs), 'expected_files': len(exp),
        'expected_dirs': len(manifest['dirs']),
        'missing': sorted(set(exp) - set(files)), 'extra': sorted(set(files) - set(exp)),
        'missing_dirs': sorted(set(manifest['dirs']) - dirs),
        'extra_dirs': sorted(dirs - set(manifest['dirs'])),
        'mismatch': mismatch, 'reparse_points': reparse, 'non_regular': odd,
        'multi_link_files': multi, 'pins': pins,
    }
    report['verify'] = result
    bad = [k for k in ('missing', 'extra', 'missing_dirs', 'extra_dirs', 'mismatch',
                       'reparse_points', 'non_regular', 'multi_link_files') if result[k]]
    if bad or not all(v['ok'] for v in pins.values()):
        raise Stop(f'verification failed: {bad or "pins"}')


# --------------------------------------------------------------------------- main

def _load_db(path):
    with pax_stream(path) as tf:
        return read_db(tf)


def main(argv=None):
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    r = sub.add_parser('resolve')
    r.add_argument('--db', type=Path, required=True)
    r.add_argument('--root', action='append', required=True)
    lk = sub.add_parser('lock')
    lk.add_argument('--db', type=Path, required=True)
    lk.add_argument('--root', action='append', required=True)
    lk.add_argument('--template', type=Path, required=True)
    lk.add_argument('--downloads', type=Path, required=True)
    lk.add_argument('--out', type=Path, required=True)
    lk.add_argument('--report', type=Path, required=True)
    ins = sub.add_parser('install')
    ins.add_argument('--lock', type=Path, required=True)
    ins.add_argument('--lock-sha256', required=True)
    ins.add_argument('--downloads', type=Path, required=True)
    ins.add_argument('--prefix', type=Path, required=True)
    ins.add_argument('--report', type=Path, required=True)
    ins.add_argument('--validate-only', action='store_true')
    args = ap.parse_args(argv)

    report = {'command': args.cmd}
    status = 0
    try:
        if args.cmd in ('resolve', 'lock'):
            db = _load_db(args.db)
            names, log = resolve(db, args.root)
            report['resolve'] = {'database_sha256': sha256_file(args.db), 'roots': args.root,
                                 'packages': len(names), 'decisions': log, 'names': names}
            print(f'resolved {len(names)} packages; decisions: {log}')
        if args.cmd == 'lock':
            template = json.loads(args.template.read_text(encoding='utf-8'))
            if template['repository']['database']['sha256'] != report['resolve']['database_sha256']:
                raise Stop('database is not the one the template records')
            scans = {}
            for name in names:
                p = db[name]
                path = args.downloads / p['filename']
                if sha256_file(path) != p['sha256']:
                    raise Stop(f'{p["filename"]}: does not match the database sha256')
                with pax_stream(path) as tf:
                    scans[name] = scan_archive(tf)
            overlaps = overlap_findings({n: e for n, (e, _) in scans.items()})
            report['overlaps'] = overlaps
            if overlaps:
                raise Stop(f'{len(overlaps)} overlapping paths in the resolved set')
            lock = build_lock(template, db, names, scans, args.root, log)
            data = dump_lock(lock)
            args.out.write_bytes(data)
            report['lock_sha256'] = hashlib.sha256(data).hexdigest()
            print(f'lock written: {len(names)} packages, sha256 {report["lock_sha256"]}')
        if args.cmd == 'install':
            raw = args.lock.read_bytes()
            got = hashlib.sha256(raw).hexdigest()
            if got != args.lock_sha256:
                raise Stop(f'lock sha256 {got} is not {args.lock_sha256}')
            lock = json.loads(raw)
            fetch(lock, args.downloads, report)
            print('fetch', json.dumps(report['fetch']))
            scans, manifest = validate(lock, args.downloads, args.prefix, report)
            print('validate', json.dumps({k: v for k, v in report['validate'].items()}))
            if not args.validate_only:
                extract(lock, args.downloads, args.prefix, scans, report)
                print('extract', json.dumps(report['extract']))
                verify(lock, args.prefix, manifest, report)
                v = report['verify']
                print('verify', json.dumps({k: (len(x) if isinstance(x, list) else x)
                                            for k, x in v.items() if k != 'pins'}))
                for k, x in v['pins'].items():
                    print(f'{x["ok"]} {k} {x["sha256"]}')
    except Stop as stop:
        report['stop'] = str(stop)
        print(f'STOP: {stop}')
        status = 1
    if getattr(args, 'report', None):
        args.report.write_text(json.dumps(report, indent=1), encoding='utf-8')
    return status


if __name__ == '__main__':
    sys.exit(main())
