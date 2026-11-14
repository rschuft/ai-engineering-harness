"""The outbound search for the native Claude Code token (plan leaf E-05.9; decision 0023 section 5).

What leaves a native D1 attempt's guest (its result bundle, records and reports) is searched for the Owner's native
token, raw and in its common encodings, by a search that holds the token in memory only and reports counts, with
a positive control. It is S-03.2's provider-key containment search (integrations/inference/inference_key_search.py,
``Search``), reused, not copied: the same forms (the token and its body after the public ``sk-ant-<label>-``
prefix, raw, hexadecimal, base64 and base64url at three alignments, UTF-16, raw fragments), the same views (raw in
overlapping chunks, gzip, SQLite rows, HTTP bodies), the same surfaces (a capture held in memory, a file, a tree, a
tar stream, an environment) and the same positive controls, planted by the standard library's encoders.

What this module adds is the result bundle (``bundle``): a git bundle's pack holds every object deflated, and most
as deltas, so its raw bytes never show a committed copy of the token. ``pack_objects`` reads the bundle with the
standard library only (gitformat-bundle, gitformat-pack: the v2 or v3 header, then each object's type, size and
zlib stream; an ofs-delta's or ref-delta's instructions applied to its base, SHA-1 or SHA-256 object names) and
hands every object, inflated and resolved, to ``Search.objects``; the bundle's own bytes are searched too. Its
positive control (``bundle_control``) plants the token in a bundle built in memory: in a whole blob, split across a
delta's base and its inserted data (whole only once the delta is applied), and behind a ref-delta; every planted
copy must be found, or the verdict is ``invalid``.

Verdicts are the search's: ``found``, ``invalid``, ``incomplete`` or ``not-found``; ``not-found`` covers the bytes
searched and nothing else (the report's ``not_covered``). A fingerprint search alone is never proof of absence: this
search matches the token itself, and a report carries only its fingerprint and counts; a report that would hold the
token is withheld (OUTPUT_WITHHELD).

Its runs are E-05.11's and E-05.5's. The command line reads the token from its one entry (``native_token.read``,
the dispatcher's read: that entry and no other), refuses unless its fingerprint is the one given, and names the
Owner's act that covers the read (``--owner-act``, a label checked for its grammar, not against a record, as
S-03.3's real-key search does):

  <tools python> -I -B integrations/dispatch/native_token_search.py search --owner-act ACT \\
      --expect-fingerprint sha256:<16 hex> --surface LABEL=KIND:PATH [--surface ...]

KIND is file, tree, tar, bundle or environ (PATH self). Exit 0 not-found, 1 found, invalid or incomplete (or a
withheld report), 2 refused (a stable code). Standard library only.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import struct
import sys
import zlib
from pathlib import Path

HERE = Path(os.path.realpath(__file__)).parent
REPO = HERE.parents[1]


def _load(name: str, path: Path):
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            del sys.modules[name]
            raise
    return module


ks = _load('aieh_inference_key_search', REPO / 'integrations' / 'inference' / 'inference_key_search.py')
native_token = _load('aieh_dispatch_native_token', HERE / 'native_token.py')

FORMAT = 'aieh-native-token-search/1'
KINDS = ('file', 'tree', 'tar', 'bundle', 'environ')
BUNDLE_SIGNATURES = {b'# v2 git bundle\n': 2, b'# v3 git bundle\n': 3}
HEADER_LIMIT = 1 << 20
INFLATE_LIMIT = 1 << 30        # inflated bytes held per bundle; beyond it the bundle is incomplete
TYPES = {1: 'commit', 2: 'tree', 3: 'blob', 4: 'tag'}
OFS_DELTA, REF_DELTA = 6, 7
OWNER_ACT = re.compile(r'[A-Za-z0-9][A-Za-z0-9 ._:()/-]{0,63}')
CODES = {
    'OWNER_ACT_REQUIRED': 'name the Owner\'s act that covers reading the native token (OA-31) with --owner-act: a '
                          'letter or digit, then up to 63 letters, digits, spaces or ._:()/-',
    'SURFACE_INVALID': 'give each --surface as LABEL=KIND:PATH, a unique label of [A-Za-z0-9_.:-], KIND one of file, '
                       'tree, tar, bundle or environ (PATH self)',
    'FINGERPRINT_INVALID': 'give --expect-fingerprint as sha256:<16 hex digits>, the native token\'s recorded one',
    'FINGERPRINT_MISMATCH': 'the entry holds another token than the one of that fingerprint',
    'OUTPUT_WITHHELD': 'nothing to do here: the report would have held the token and was not printed',
}


class SearchRefused(Exception):
    def __init__(self, code: str, detail: str):
        self.code, self.detail, self.remedy = code, detail, CODES[code]
        super().__init__(f'{code}: {detail}. Remedy: {self.remedy}.')


# ---------------------------------------------------------------- the bundle's objects


class BundleError(ValueError):
    pass


def _varint(data, pos: int) -> tuple:
    value = shift = 0
    while True:
        if pos >= len(data):
            raise BundleError('a size runs past the delta')
        byte = data[pos]
        pos += 1
        value |= (byte & 0x7f) << shift
        shift += 7
        if not byte & 0x80:
            return value, pos


def apply_delta(base: bytes, delta: bytes) -> bytes:
    """A git delta (gitformat-pack, "Deltified representation") applied to BASE."""
    source, pos = _varint(delta, 0)
    target, pos = _varint(delta, pos)
    if source != len(base):
        raise BundleError('a delta\'s base size is not its base\'s')
    out = bytearray()
    while pos < len(delta):
        op = delta[pos]
        pos += 1
        if op & 0x80:
            offset = size = 0
            for bit, shift in ((0x01, 0), (0x02, 8), (0x04, 16), (0x08, 24)):
                if op & bit:
                    offset |= delta[pos] << shift
                    pos += 1
            for bit, shift in ((0x10, 0), (0x20, 8), (0x40, 16)):
                if op & bit:
                    size |= delta[pos] << shift
                    pos += 1
            size = size or 0x10000
            if offset + size > len(base):
                raise BundleError('a delta copies past its base')
            out += base[offset:offset + size]
        elif op:
            out += delta[pos:pos + op]
            pos += op
        else:
            raise BundleError('a delta holds the reserved instruction 0')
    if len(out) != target:
        raise BundleError('a delta\'s result is not its declared size')
    return bytes(out)


def _header(data: bytes) -> tuple:
    """(version, sha256, pack offset) of a git bundle (gitformat-bundle)."""
    first = data[:data.find(b'\n') + 1]
    if first not in BUNDLE_SIGNATURES:
        raise BundleError('not a v2 or v3 git bundle')
    end = data.find(b'\n\n', 0, HEADER_LIMIT)
    if end < 0:
        raise BundleError('the bundle header is not terminated')
    sha256 = BUNDLE_SIGNATURES[first] == 3 and b'\n@object-format=sha256\n' in data[:end + 1]
    return BUNDLE_SIGNATURES[first], sha256, end + 2


def pack_objects(data: bytes) -> tuple:
    """([(name, bytes)], [incomplete reasons]): every object of a git bundle's pack, inflated and with its delta
    applied, named by its index and type (never by its content)."""
    _, sha256, pos = _header(data)
    if data[pos:pos + 4] != b'PACK':
        raise BundleError('no pack after the bundle header')
    version, count = struct.unpack('>II', data[pos + 4:pos + 12])
    if version not in (2, 3):
        raise BundleError(f'pack version {version}')
    hash_len, view = (32 if sha256 else 20), memoryview(data)
    at, held, total, pending, incomplete = pos + 12, {}, 0, [], []
    by_name = {}

    def name_of(kind: str, body: bytes) -> bytes:
        digest = hashlib.sha256() if sha256 else hashlib.sha1()
        digest.update(f'{kind} {len(body)}\0'.encode('ascii') + body)
        return digest.digest()

    def keep(offset: int, kind: str, body: bytes) -> None:
        held[offset] = (kind, body)
        by_name[name_of(kind, body)] = offset

    for _ in range(count):
        start = at
        byte = data[at]
        at += 1
        kind_code, shift = (byte >> 4) & 7, 4
        while byte & 0x80:
            byte = data[at]
            at += 1
            shift += 7
        base = None
        if kind_code == OFS_DELTA:
            byte = data[at]
            at += 1
            offset = byte & 0x7f
            while byte & 0x80:
                byte = data[at]
                at += 1
                offset = ((offset + 1) << 7) | (byte & 0x7f)
            base = ('ofs', start - offset)
        elif kind_code == REF_DELTA:
            base = ('ref', bytes(data[at:at + hash_len]))
            at += hash_len
        elif kind_code not in TYPES:
            raise BundleError(f'object type {kind_code}')
        inflater = zlib.decompressobj()
        body = inflater.decompress(view[at:], INFLATE_LIMIT - total) if total < INFLATE_LIMIT else b''
        if not inflater.eof:
            incomplete.append(f'bundle: more than {INFLATE_LIMIT} inflated bytes')
            break
        at = len(data) - len(inflater.unused_data)
        total += len(body)
        if base is None:
            keep(start, TYPES[kind_code], body)
        else:
            pending.append((start, base, body))
    while pending:   # deltas, in as many passes as their bases need
        left = []
        for start, (how, ref), delta in pending:
            offset = ref if how == 'ofs' else by_name.get(ref)
            if offset in held:
                kind, base = held[offset]
                keep(start, kind, apply_delta(base, delta))
            else:
                left.append((start, (how, ref), delta))
        if len(left) == len(pending):
            incomplete.append(f'bundle: {len(left)} deltas whose base is not in the pack')
            break
        pending = left
    items = [(f'object {n} {kind}', body) for n, (_, (kind, body)) in enumerate(sorted(held.items()))]
    return items, incomplete


def search_bundle(search, label: str, data: bytes, *, expect: str = 'absent') -> dict:
    """One bundle surface: its own bytes and every object of its pack (``pack_objects``)."""
    try:
        objects, incomplete = pack_objects(bytes(data))
    except (BundleError, IndexError, struct.error, zlib.error) as exc:
        objects, incomplete = [], [f'bundle: {type(exc).__name__}']
    return search.objects(label, 'bundle', [('bytes', bytes(data)), *objects], expect=expect,
                          incomplete=incomplete)


# ---------------------------------------------------------------- the bundle's positive control


def _object_header(kind: int, size: int) -> bytes:
    out = bytearray([(kind << 4) | (size & 0x0f)])
    size >>= 4
    while size:
        out[-1] |= 0x80
        out.append(size & 0x7f)
        size >>= 7
    return bytes(out)


def _varint_bytes(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7f
        value >>= 7
        out.append(byte | (0x80 if value else 0))
        if not value:
            return bytes(out)


def _insert(data: bytes) -> bytes:
    """Delta insert instructions for DATA (at most 127 bytes each)."""
    return b''.join(bytes([len(data[i:i + 127])]) + data[i:i + 127] for i in range(0, len(data), 127))


def _copy(offset: int, size: int) -> bytes:
    """One delta copy instruction (SIZE below 65536, not 0)."""
    op, args = 0x80, bytearray()
    for n in range(4):
        if (offset >> (8 * n)) & 0xff:
            op |= 1 << n
            args.append((offset >> (8 * n)) & 0xff)
    for n in range(2):
        if (size >> (8 * n)) & 0xff:
            op |= 0x10 << n
            args.append((size >> (8 * n)) & 0xff)
    return bytes([op]) + bytes(args)


def _ofs_bytes(offset: int) -> bytes:
    out = [offset & 0x7f]
    offset >>= 7
    while offset:
        offset -= 1
        out.append(0x80 | (offset & 0x7f))
        offset >>= 7
    return bytes(reversed(out))


def control_bundle(token: str) -> bytes:
    """A v2 bundle built in memory (the standard library's zlib only) whose pack plants TOKEN three times: whole in
    a blob; split across an ofs-delta's base and its inserted data; and behind a ref-delta whose base is a blob that
    holds the token's body after its prefix, the delta inserting the prefix. No raw byte of the bundle holds it."""
    raw = token.encode('ascii')
    half = len(raw) // 2
    whole = b'planted: ' + raw + b'\n'
    # A: copy the base's first 5 + half bytes (offset 0, one size byte), then insert the token's second half.
    base_a = b'head ' + raw[:half] + b' tail\n'
    delta_a = (_varint_bytes(len(base_a)) + _varint_bytes(5 + len(raw)) + _copy(0, 5 + half) + _insert(raw[half:]))
    # B: insert the public prefix, then copy the whole base (the token's body).
    prefix = native_token.public_prefix(token).encode('ascii')
    base_b = raw[len(prefix):]
    delta_b = (_varint_bytes(len(base_b)) + _varint_bytes(len(raw)) + _insert(prefix) + _copy(0, len(base_b)))
    pack, offsets = bytearray(b'PACK' + struct.pack('>II', 2, 5)), []
    for kind, body in [(3, whole), (3, base_a)]:
        offsets.append(len(pack))
        pack += _object_header(kind, len(body)) + zlib.compress(body)
    at = len(pack)
    pack += _object_header(OFS_DELTA, len(delta_a)) + _ofs_bytes(at - offsets[1]) + zlib.compress(delta_a)
    pack += _object_header(3, len(base_b)) + zlib.compress(base_b)
    base_name = hashlib.sha1(f'blob {len(base_b)}\0'.encode('ascii') + base_b).digest()
    pack += _object_header(REF_DELTA, len(delta_b)) + base_name + zlib.compress(delta_b)
    pack += hashlib.sha1(bytes(pack)).digest()
    return b'# v2 git bundle\n' + b'0' * 40 + b' refs/heads/control\n\n' + bytes(pack)


def bundle_control(token: str, chunk: int | None = None) -> dict:
    """The bundle's positive control: the planted bundle searched with a search of the same token; valid only when
    the raw bytes hold no copy and the objects hold all three."""
    probe = ks.Search(token, chunk=chunk, prefix=native_token.public_prefix(token))
    data = control_bundle(token)
    raw_clean = not probe.holds(data)
    objects, incomplete = pack_objects(data)
    found = [name for name, body in objects if raw_clean and token.encode('ascii') in body]
    valid = raw_clean and not incomplete and len(found) == 3
    report = search_bundle(probe, 'control-bundle', data)
    valid = valid and report['found'] >= 3
    return {'valid': valid, 'planted': 3, 'found_whole': len(found), 'raw_holds_a_copy': not raw_clean,
            'how': 'a v2 bundle built in memory with zlib: the token whole in a blob, split across an ofs-delta\'s '
                   'base and its inserted data, and rebuilt by a ref-delta from a base holding its body; none of '
                   'them in the bundle\'s raw bytes'}


# ---------------------------------------------------------------- the search


def new_search(token: str):
    """S-03.2's Search for TOKEN (its public prefix ``sk-ant-<label>-`` is the part a body form strips)."""
    return ks.Search(token, prefix=native_token.public_prefix(token))


def report(search, token: str) -> dict:
    """The search's report with its controls (the shared ones and the bundle's): ``invalid`` unless both are valid.
    Counts and the fingerprint only; withheld if it would hold the token."""
    search.controls()
    bundle = bundle_control(token, search.chunk)
    out = search.report()
    out['format'], out['bundle_control'] = FORMAT, bundle
    out['key']['entry'] = native_token.ENTRY
    if not bundle['valid'] and out['verdict'] != 'found':
        out['verdict'] = 'invalid'
        out['statement'] = 'the search is not valid: the bundle\'s positive control missed a planted copy'
    if search.holds(json.dumps(out, sort_keys=True)):
        raise SearchRefused('OUTPUT_WITHHELD', 'the report held the token')
    return out


def parse_surface(value: str) -> tuple:
    label, sep, rest = str(value).partition('=')
    kind, sep2, path = rest.partition(':')
    if not sep or not sep2 or not ks.LABEL.fullmatch(label) or kind not in KINDS or not path \
            or (kind == 'environ' and path != 'self'):
        raise SearchRefused('SURFACE_INVALID', 'not LABEL=KIND:PATH')
    return label, kind, path


def run(token: str, expected: str, surfaces: list) -> dict:
    """Search SURFACES ([(label, kind, path)]) for TOKEN after checking its fingerprint; run the controls."""
    if not isinstance(expected, str) or not native_token.FINGERPRINT_SHAPE.fullmatch(expected):
        raise SearchRefused('FINGERPRINT_INVALID', 'not sha256:<16 hex digits>')
    if native_token.fingerprint(token) != expected:
        raise SearchRefused('FINGERPRINT_MISMATCH', 'the token read is not the one of that fingerprint')
    labels = [label for label, _, _ in surfaces]
    if not surfaces or len(set(labels)) != len(labels):
        raise SearchRefused('SURFACE_INVALID', 'give at least one surface, each label once')
    search = new_search(token)
    for label, kind, path in surfaces:
        if kind == 'file':
            search.file(label, path)
        elif kind == 'tree':
            search.tree(label, path)
        elif kind in ('tar', 'bundle'):
            try:
                with open(os.fspath(path), 'rb') as handle:
                    if kind == 'tar':
                        search.tar(label, handle)
                    else:
                        search_bundle(search, label, handle.read())
            except OSError as exc:
                search.objects(label, kind, [], incomplete=[f'unreadable: {type(exc).__name__}'])
        else:
            search.environ(label)
    return report(search, token)


def main(argv=None, provider=None, out=None, err=None) -> int:
    parser = argparse.ArgumentParser(prog='native_token_search.py', description='The outbound search for the native '
                                     'token (E-05.9): the token, raw and in its encodings, on the listed surfaces '
                                     '(a result bundle\'s objects inflated), with positive controls. Exit 0 '
                                     'not-found, 1 found, invalid or incomplete, 2 refused.')
    sub = parser.add_subparsers(dest='command', required=True)
    cmd = sub.add_parser('search', help='read the token from its one entry and search the surfaces')
    cmd.add_argument('--owner-act', required=True, help='the Owner\'s act that covers reading the token (OA-31)')
    cmd.add_argument('--expect-fingerprint', required=True, help='the token\'s recorded fingerprint')
    cmd.add_argument('--surface', action='append', required=True, dest='surfaces', help='LABEL=KIND:PATH')
    args = parser.parse_args(argv)
    out, err = out or sys.stdout, err or sys.stderr
    try:
        if not OWNER_ACT.fullmatch(args.owner_act):
            raise SearchRefused('OWNER_ACT_REQUIRED', 'not an act label')
        surfaces = [parse_surface(value) for value in args.surfaces]
        if provider is None:
            provider = _load('aieh_credential_provider', REPO / 'integrations' / 'credentials'
                             / 'credential_provider.py').select_provider()
        held = native_token.read(provider)
        try:
            result = run(held.token(), args.expect_fingerprint, surfaces)
        finally:
            held.drop()
    except (SearchRefused, native_token.NativeTokenError) as exc:
        err.write(f'native-token-search: {exc}\n')
        return 2
    result['owner_act'] = args.owner_act
    out.write(json.dumps(result, indent=2, sort_keys=True) + '\n')
    return 0 if result['verdict'] == 'not-found' else 1


if __name__ == '__main__':
    sys.exit(main())
