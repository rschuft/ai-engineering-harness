"""The provider-key containment search (plan leaf S-03.2, slice 5; its proof as amended on 2026-11-11, Owner
decision OA-19; decision 0015 sections 2, 4.5, 6 and 8).

The Owner's words: preserve the provider-key containment requirement; a fingerprint-only search must not be
described as proof of absence of the underlying raw credential; use evidence appropriate to the actual secret
exposure boundary, with a positive control, without printing or persisting credential material.

A Search holds one key in memory (the synthetic qualification key: the qualification launcher of
inference_qualification.py serves it to the broker; the real key's containment is S-03.3's) and searches byte
surfaces for the key itself and for its encodings, never by fingerprint:

- forms, each of the whole key ("key") and of its secret part, the key without the public synthetic prefix
  ("body", a leak with the prefix stripped): raw bytes (also what JSON string escaping, URL and form encoding,
  HTML escaping and shell quoting give for this alphabet, all identities on it); hexadecimal in lower and upper
  case (a bytes value dumped as hex); standard base64 and base64url, each at the three alignments a value can
  take inside a larger encoded stream (HTTP Basic credentials, cloud-init's b64 write_files, a base64 JSON or
  archive, a JWT-like token); UTF-16LE and UTF-16BE (Windows wide strings: PowerShell transcripts, the
  registry, .NET, credential blobs). And raw fragments: every window of 16 body characters at a stride of 8, so
  that a raw leak of at least 23 consecutive body characters is found (a truncated or masked copy).
- views of each blob: its raw bytes, read in chunks with an overlap of the longest needle less one byte, so a
  copy split across a read boundary is found; a gzip blob also decompressed (every member); an SQLite database
  also read row by row (a value split across overflow pages is whole there); a tar stream member by member, with
  each member's name and link target; an HTTP/1.x capture also message by message, its body de-chunked and
  decoded from gzip or deflate (a copy split across two chunks is whole there).

Surfaces: capture (bytes held in memory), http (a captured HTTP exchange), file, tree (a directory, links not
followed), tar (a tar stream, compressed or not) and environ (this process's environment). Each reports what it
searched: bytes per view, items, items it could not read and why (by error type), links and special files it
did not follow, and the matches per form. A surface's name, a member's name and a label are shown only if they
hold no match; nothing reported ever holds the key or a part of it, and the command line's report is searched
for the key before it is printed and withheld if it holds one.

The positive control (controls()) plants copies of the key, made by the standard library's own encoders and not
by this module's needle builder, in every form and in every kind of surface, in memory: the search's verdict is
"invalid" unless every planted copy is found. A surface expected to hold the key (the broker's own request to
its upstream, in the offline test) is a further control: "invalid" if it is not found there.

Verdicts: "found" (a match on a surface expected not to hold the key), "invalid" (a control missed),
"incomplete" (a surface not searched in full), "not-found". "not-found" covers the bytes searched and nothing
else; the report's not_covered list says what lies outside them (process memory above all).

  <synthetic key> | <tools python> -I -B integrations/inference/inference_key_search.py search \\
      --expect-fingerprint sha256:<16 hex> --surface LABEL=KIND:PATH [--surface ...]

KIND is file, tree, tar or environ (PATH self). Exit 0 not-found, 1 found, invalid or incomplete, 2 refused (a
stable code). Standard library only; it imports nothing of the broker, so its evidence is independent of the
broker's own I7 scan and report. It writes no file and keeps no log.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import collections
import gzip
import hashlib
import io
import json
import os
import re
import sqlite3
import stat
import sys
import tarfile
import urllib.parse
import zlib

FORMAT = 'aieh-inference-key-search/1'
SYNTHETIC_PREFIX = 'aieh-qualification-synthetic-'
SYNTHETIC_SHAPE = re.compile(re.escape(SYNTHETIC_PREFIX) + r'[A-Za-z0-9_-]{16,128}')
KEY_LIMIT = 1024
CHUNK = 1 << 20
FRAGMENT, STRIDE = 16, 8
GZIP_MAGIC = b'\x1f\x8b\x08'
SQLITE_MAGIC = b'SQLite format 3\x00'
GZIP_LIMIT = 4 << 30          # decompressed bytes per blob; beyond it the view is incomplete
SQLITE_LIMIT = 1 << 30        # database bytes held for the row view; beyond it the view is incomplete
WHERE_LIMIT = 50
WITHHELD = '<a name that holds a match: withheld>'
LABEL = re.compile(r'[A-Za-z0-9_.:-]{1,64}')
FINGERPRINT = re.compile(r'sha256:[0-9a-f]{16}')
KINDS = ('file', 'tree', 'tar', 'environ')

FORMS = {
    'raw': 'the bytes as written; JSON string escaping, URL and form encoding, HTML escaping and shell quoting '
           'leave this alphabet unchanged, so they are this form too',
    'hex': 'lower-case hexadecimal of the bytes (a bytes value dumped or logged as hex)',
    'HEX': 'upper-case hexadecimal of the bytes',
    'base64': 'standard base64 at each of the three alignments inside a larger encoded stream (HTTP Basic '
              'credentials, cloud-init b64 write_files, a base64 JSON document or archive)',
    'base64url': 'URL-safe base64 at each of the three alignments (JWT-like tokens, URL-safe fields)',
    'utf-16-le': 'UTF-16 little-endian (Windows wide strings: PowerShell transcripts, the registry, .NET)',
    'utf-16-be': 'UTF-16 big-endian',
    'fragment': f'raw windows of {FRAGMENT} body characters at a stride of {STRIDE}: a raw copy of at least '
                f'{FRAGMENT + STRIDE - 1} consecutive body characters (truncated or masked)',
}
VIEWS = {
    'raw': 'every byte, read in chunks that overlap by the longest needle less one byte',
    'gzip': 'a blob that starts with the gzip magic, decompressed (every member)',
    'sqlite': 'an SQLite database read row by row, every table, and its schema',
    'http-body': 'each HTTP/1.x message of a capture, its body de-chunked',
    'http-decoded': 'such a body decoded from its gzip or deflate Content-Encoding',
}
NOT_COVERED = (
    'process memory: the broker holds the key in memory by design, and no process memory is read here',
    'any byte not on a listed surface, and any surface not searched in full (see each surface)',
    'other forms: two encodings stacked (for example base64 of hex), encoded fragments (line-wrapped base64, '
    'truncated hex), case-changed text, encryption, a hash or fingerprint of the key, and compression other than '
    'gzip (and an HTTP body\'s gzip or deflate): zip, xz, bzip2, zstd, compressed disk-image clusters',
    'a copy split across storage that is not contiguous: disk-image clusters, SQLite overflow pages in the raw '
    'view (the row view joins them), text split across server-sent events or JSON fields by a reader',
    'SQLite write-ahead-log frames that were never checkpointed are searched in the raw view only',
)
CODES = {
    'KEY_STDIN_TTY': 'pipe the key on standard input; a terminal would show it',
    'KEY_INVALID': 'pipe exactly one key, optionally followed by one newline',
    'KEY_NOT_SYNTHETIC': f'pipe the synthetic qualification key ({SYNTHETIC_PREFIX} and 16 to 128 letters, '
                         'digits, "_" or "-"); the real key\'s containment is S-03.3\'s',
    'FINGERPRINT_INVALID': 'give --expect-fingerprint as sha256:<16 hex digits>, the broker start receipt\'s',
    'FINGERPRINT_MISMATCH': 'pipe the key the broker was started with: its fingerprint is in the start receipt',
    'SURFACE_INVALID': 'give each --surface as LABEL=KIND:PATH, a unique label of [A-Za-z0-9_.:-], KIND one of '
                       'file, tree, tar or environ (PATH self)',
    'OUTPUT_WITHHELD': 'nothing to do here: the report would have held the key and was not printed',
}


class SearchError(Exception):
    """A refusal (exit 2, or 1 for OUTPUT_WITHHELD) with a stable code of CODES and its remedy; never the key."""

    def __init__(self, code: str, detail: str):
        self.code, self.detail, self.remedy = code, detail, CODES[code]
        super().__init__(f'{code}: {detail}. Remedy: {self.remedy}.')


def fingerprint(key: str) -> str:
    """The reports' fingerprint of a secret (the start receipt's): sha256: and the first 16 hex digits."""
    return 'sha256:' + hashlib.sha256(key.encode('utf-8')).hexdigest()[:16]


def _b64(value: bytes, encode) -> list:
    """Each of the three alignments: the encoding of the groups that lie wholly inside VALUE."""
    out = []
    for shift in range(3):
        part = value[shift:]
        text = encode(part)[:4 * (len(part) // 3)]
        if text:
            out.append((shift, text))
    return out


def body_of(key: str, prefix: str = SYNTHETIC_PREFIX) -> str:
    """The secret part: the key without its public PREFIX, the synthetic one unless another is given (E-05.9's
    native token search gives the token's sk-ant-<label>- prefix); the whole key when it has none."""
    return key[len(prefix):] if prefix and key.startswith(prefix) and len(key) > len(prefix) else key


def needles(key: str, prefix: str = SYNTHETIC_PREFIX) -> dict:
    """{needle bytes: (labels...)}: every form of the whole key and of its body (without its public PREFIX), and the
    body's raw fragments."""
    found = collections.defaultdict(set)
    for part, text in (('key', key), ('body', body_of(key, prefix))):
        value = text.encode('utf-8')
        found[value].add(f'{part}/raw')
        found[binascii.hexlify(value)].add(f'{part}/hex')
        found[binascii.hexlify(value).upper()].add(f'{part}/HEX')
        for shift, encoded in _b64(value, base64.b64encode):
            found[encoded].add(f'{part}/base64@{shift}')
        for shift, encoded in _b64(value, base64.urlsafe_b64encode):
            found[encoded].add(f'{part}/base64url@{shift}')
        found[text.encode('utf-16-le')].add(f'{part}/utf-16-le')
        found[text.encode('utf-16-be')].add(f'{part}/utf-16-be')
    body = body_of(key, prefix).encode('utf-8')
    starts = sorted(set(range(0, max(len(body) - FRAGMENT, 0) + 1, STRIDE)) | {max(len(body) - FRAGMENT, 0)})
    for start in starts:
        found[body[start:start + FRAGMENT]].add('fragment')
    return {needle: tuple(sorted(labels)) for needle, labels in found.items() if needle}


def read_key(stream) -> str:
    """The synthetic key from STREAM (standard input): never a terminal; exactly one key, optionally followed by
    one newline; the synthetic shape. No message repeats what was read."""
    if stream is None or stream.isatty():
        raise SearchError('KEY_STDIN_TTY', 'standard input is a terminal')
    raw = getattr(stream, 'buffer', stream).read(KEY_LIMIT + 3)
    try:
        text = raw.decode('utf-8') if isinstance(raw, bytes) else raw
    except UnicodeDecodeError:
        raise SearchError('KEY_INVALID', 'standard input is not UTF-8') from None
    for ending in ('\r\n', '\n'):
        if text.endswith(ending):
            text = text[:-len(ending)]
            break
    if not 16 <= len(text) <= KEY_LIMIT or not all(33 <= ord(c) <= 126 for c in text):
        raise SearchError('KEY_INVALID', 'standard input is not exactly one key (what was read is not shown)')
    if not SYNTHETIC_SHAPE.fullmatch(text):
        raise SearchError('KEY_NOT_SYNTHETIC', 'standard input is not a synthetic qualification key (what was '
                                               'read is not shown)')
    return text


def check_fingerprint(key: str, expected) -> str:
    """The key's fingerprint, refused unless it is EXPECTED (the broker start receipt's)."""
    if not isinstance(expected, str) or not FINGERPRINT.fullmatch(expected):
        raise SearchError('FINGERPRINT_INVALID', 'not sha256:<16 hex digits>')
    if fingerprint(key) != expected:
        raise SearchError('FINGERPRINT_MISMATCH', 'the piped key is not the key of that fingerprint')
    return expected


# ---------------------------------------------------------------- the scanning


class _Stream:
    """One view of one blob: fed chunk by chunk; a match is counted once, by its start, also when it straddles
    two chunks (the tail kept is the longest needle less one byte). found counts occurrences of needles; hits
    counts them per form (a needle two forms share, such as base64 and base64url without '+' or '/', under both)."""

    def __init__(self, table: dict, longest: int):
        self.table, self.keep = table, longest - 1
        self.tail, self.bytes, self.found, self.hits = b'', 0, 0, collections.Counter()

    def feed(self, data: bytes) -> None:
        if not data:
            return
        buf = self.tail + data
        held = len(self.tail)
        for needle, labels in self.table.items():
            at = buf.find(needle, max(0, held - len(needle) + 1))
            while at != -1:
                self.found += 1
                for label in labels:
                    self.hits[label] += 1
                at = buf.find(needle, at + 1)
        self.tail = buf[-self.keep:] if self.keep > 0 else b''
        self.bytes += len(data)


class _Gunzip:
    """The gzip view: every member decompressed as the compressed bytes arrive, output bounded per call."""

    def __init__(self, stream: _Stream, chunk: int, limit: int):
        self.stream, self.chunk, self.limit = stream, chunk, limit
        self.inflate = zlib.decompressobj(31)
        self.error = None

    def feed(self, data: bytes) -> None:
        """Decompress what DATA completes. Bytes after a member that are not (yet) another member's start stay in
        the finished member's unused_data, which grows with each feed until they are."""
        while self.error is None:
            try:
                out = self.inflate.decompress(data, self.chunk)
            except zlib.error:
                self.error = 'gzip: zlib.error'
                return
            self.stream.feed(out)
            if self.stream.bytes > self.limit:
                self.error = f'gzip: more than {self.limit} bytes decompressed'
                return
            if self.inflate.eof:
                rest = self.inflate.unused_data
                if not rest.startswith(GZIP_MAGIC):
                    return                       # trailing bytes that are not another member: raw view only
                self.inflate = zlib.decompressobj(31)
                data = rest
            elif self.inflate.unconsumed_tail:
                data = self.inflate.unconsumed_tail
            elif len(out) == self.chunk:
                data = b''                       # the output was cut at the bound: ask for the rest
            else:
                return

    def finish(self) -> None:
        if self.error is None and not self.inflate.eof:
            self.error = 'gzip: the stream ends inside a member'


def _sqlite_values(data: bytes):
    """Every value of every table of an SQLite database image, and its schema, read in an in-memory copy: the
    file on disk is never opened by SQLite. A write-ahead-log image is read as a rollback-journal one."""
    image = bytearray(data)
    if image[18:20] == b'\x02\x02':
        image[18:20] = b'\x01\x01'
    connection = sqlite3.connect(':memory:')
    try:
        connection.deserialize(bytes(image))
        tables = connection.execute("SELECT name, sql FROM sqlite_master WHERE type = 'table'").fetchall()
        for row in connection.execute('SELECT sql FROM sqlite_master WHERE sql IS NOT NULL'):
            yield row[0]
        for name, sql in tables:
            if (sql or '').upper().startswith('CREATE VIRTUAL TABLE'):
                continue                         # its content is in its shadow tables, read as tables
            for row in connection.execute('SELECT * FROM "%s"' % name.replace('"', '""')):
                yield from row
    finally:
        connection.close()


def _http_messages(data: bytes):
    """(body, content-encoding) of each HTTP/1.x message of a capture, the body de-chunked; ValueError when the
    capture does not parse as a sequence of messages."""
    at = 0
    while at < len(data):
        end = data.find(b'\r\n\r\n', at)
        if end < 0:
            raise ValueError('a message without the end of its headers')
        lines = data[at:end].split(b'\r\n')
        at = end + 4
        start = lines[0]
        if not (start.startswith(b'HTTP/1.') or start.endswith((b' HTTP/1.1', b' HTTP/1.0'))):
            raise ValueError('not an HTTP/1.x start line')
        headers = collections.defaultdict(list)
        for line in lines[1:]:
            name, sep, value = line.partition(b':')
            if not sep:
                raise ValueError('a header line without a colon')
            headers[name.strip().lower()].append(value.strip().lower())
        status = start.split(b' ')[1] if start.startswith(b'HTTP/') else b''
        coding = b','.join(headers.get(b'content-encoding', [])).decode('latin-1')
        if b'chunked' in b','.join(headers.get(b'transfer-encoding', [])):
            body = bytearray()
            while True:
                eol = data.find(b'\r\n', at)
                if eol < 0:
                    raise ValueError('a chunk without its size line')
                size = int(data[at:eol].split(b';')[0].strip() or b'x', 16)
                at = eol + 2
                if size == 0:
                    trailer = data.find(b'\r\n\r\n', at - 2)
                    if trailer < 0:
                        raise ValueError('a chunked body without its end')
                    at = trailer + 4
                    break
                if at + size + 2 > len(data) or data[at + size:at + size + 2] != b'\r\n':
                    raise ValueError('a chunk shorter than its size')
                body += data[at:at + size]
                at += size + 2
            yield bytes(body), coding
        elif headers.get(b'content-length'):
            size = int(headers[b'content-length'][0])
            if at + size > len(data):
                raise ValueError('a body shorter than its Content-Length')
            yield data[at:at + size], coding
            at += size
        elif status[:1] == b'1' or status in (b'204', b'304') or not start.startswith(b'HTTP/'):
            yield b'', coding
        else:
            yield data[at:], coding
            at = len(data)


def _decode_body(body: bytes, coding: str, limit: int) -> bytes | None:
    """BODY decoded from its gzip or deflate Content-Encoding (None for another or none); ValueError if it fails."""
    coding = coding.strip()
    try:
        if coding in ('gzip', 'x-gzip'):
            inflate = zlib.decompressobj(31)
        elif coding == 'deflate':
            inflate = zlib.decompressobj(15 if body[:1] == b'\x78' else -15)
        else:
            return None
        out = inflate.decompress(body, limit + 1)
    except zlib.error:
        raise ValueError('the body does not decode') from None
    if len(out) > limit:
        raise ValueError('the decoded body is over the bound')
    return out


class _Surface:
    def __init__(self, label: str, kind: str, expect: str):
        self.label, self.kind, self.expect = label, kind, expect
        self.searched = False
        self.bytes = collections.Counter()
        self.items = 0
        self.unreadable = collections.Counter()
        self.incomplete = collections.Counter()
        self.skipped = collections.Counter()
        self.matched = 0
        self.hits = collections.Counter()
        self.views = collections.defaultdict(collections.Counter)
        self.where = []

    def complete(self) -> bool:
        return self.searched and not self.unreadable and not self.incomplete

    def found(self) -> int:
        return self.matched

    def report(self) -> dict:
        return {'label': self.label, 'kind': self.kind, 'expect': self.expect, 'searched': self.searched,
                'complete': self.complete(), 'bytes': dict(sorted(self.bytes.items())),
                'bytes_total': sum(self.bytes.values()), 'items': self.items,
                'unreadable': dict(sorted(self.unreadable.items())),
                'incomplete': dict(sorted(self.incomplete.items())),
                'not_followed': dict(sorted(self.skipped.items())), 'found': self.found(),
                'matches': dict(sorted(self.hits.items())),
                'matches_by_view': {view: dict(sorted(c.items())) for view, c in sorted(self.views.items())},
                'where': list(self.where)}


class Search:
    """One key, held in memory only, and the surfaces searched for it. Its repr shows the fingerprint only."""

    def __init__(self, key: str, *, chunk: int | None = None, prefix: str = SYNTHETIC_PREFIX):
        if not isinstance(key, str) or not 16 <= len(key) <= KEY_LIMIT or \
                not all(33 <= ord(c) <= 126 for c in key):
            raise SearchError('KEY_INVALID', 'not one printable key of 16 to 1024 characters')
        self._key, self.prefix = key, prefix
        self._table = needles(key, prefix)
        self._longest = max(len(n) for n in self._table)
        self.fingerprint = fingerprint(key)
        self.chunk = max(int(chunk or CHUNK), self._longest)
        self.surfaces = []
        self.control = None

    def __repr__(self):
        return f'<Search {self.fingerprint}: {len(self.surfaces)} surfaces>'

    # ---- matching

    def holds(self, data) -> bool:
        """True when DATA (bytes or text) holds the key in any form."""
        if isinstance(data, str):
            data = data.encode('utf-8', 'surrogatepass')
        return any(needle in data for needle in self._table)

    def _stream(self) -> _Stream:
        return _Stream(self._table, self._longest)

    def _shown(self, name) -> str:
        """NAME as the report may show it: withheld when it holds a match."""
        text = str(name)
        return WITHHELD if self.holds(text) else text[:200]

    def _merge(self, surface: _Surface, view: str, stream: _Stream, name) -> None:
        if stream.found:
            surface.matched += stream.found
            surface.hits.update(stream.hits)
            surface.views[view].update(stream.hits)
            shown = self._shown(name)
            if len(surface.where) < WHERE_LIMIT and shown not in surface.where:
                surface.where.append(shown)

    def _view(self, surface: _Surface, view: str, data: bytes, name) -> None:
        """One whole byte string through one view."""
        stream = self._stream()
        stream.feed(data)
        surface.bytes[view] += stream.bytes
        self._merge(surface, view, stream, name)

    def _blob(self, surface: _Surface, read, name) -> None:
        """One blob through every view that applies to it. READ(n) returns up to n bytes, b'' at its end."""
        raw, gz, image = self._stream(), None, None
        first = True
        while True:
            data = read(self.chunk)
            if first:
                first = False
                if data.startswith(GZIP_MAGIC):
                    gz = _Gunzip(self._stream(), self.chunk, GZIP_LIMIT)
                if data.startswith(SQLITE_MAGIC):
                    image = bytearray()
            if not data:
                break
            raw.feed(data)
            if gz is not None:
                gz.feed(data)
            if image is not None:
                if len(image) + len(data) > SQLITE_LIMIT:
                    image = None
                    surface.incomplete[f'sqlite: more than {SQLITE_LIMIT} bytes'] += 1
                else:
                    image += data
        surface.bytes['raw'] += raw.bytes
        self._merge(surface, 'raw', raw, name)
        if gz is not None:
            gz.finish()
            surface.bytes['gzip'] += gz.stream.bytes
            self._merge(surface, 'gzip', gz.stream, name)
            if gz.error:
                surface.incomplete[gz.error] += 1
        if image is not None:
            rows = self._stream()
            try:
                for value in _sqlite_values(bytes(image)):
                    if isinstance(value, (str, bytes)):
                        rows.feed((value if isinstance(value, bytes) else value.encode('utf-8', 'surrogatepass'))
                                  + b'\x00')
            except sqlite3.Error as exc:
                surface.incomplete[f'sqlite: {type(exc).__name__}'] += 1
            surface.bytes['sqlite'] += rows.bytes
            self._merge(surface, 'sqlite', rows, name)

    # ---- surfaces

    def _new(self, label: str, kind: str, expect: str) -> _Surface:
        if expect not in ('absent', 'present'):
            raise ValueError(expect)
        surface = _Surface(label, kind, expect)
        self.surfaces.append(surface)
        return surface

    def capture(self, label: str, data: bytes, *, expect: str = 'absent') -> dict:
        """A capture held in memory (a process's output, a record's text)."""
        surface = self._new(label, 'capture', expect)
        surface.items = 1
        self._blob(surface, io.BytesIO(bytes(data)).read, label)
        surface.searched = True
        return surface.report()

    def http(self, label: str, data: bytes, *, expect: str = 'absent') -> dict:
        """One direction of a captured HTTP/1.x exchange: its raw bytes, and each message's body de-chunked and
        decoded from gzip or deflate."""
        surface = self._new(label, 'http', expect)
        data = bytes(data)
        self._blob(surface, io.BytesIO(data).read, label)
        try:
            messages = list(_http_messages(data))
        except ValueError as exc:
            surface.incomplete[f'http: {exc}'] += 1
            messages = []
        surface.items = len(messages)
        for index, (body, coding) in enumerate(messages):
            name = f'{label} message {index + 1}'
            self._view(surface, 'http-body', body, name)
            try:
                decoded = _decode_body(body, coding, GZIP_LIMIT)
            except ValueError as exc:
                surface.incomplete[f'http: {exc}'] += 1
                decoded = None
            if decoded is not None:
                self._view(surface, 'http-decoded', decoded, name)
        surface.searched = True
        return surface.report()

    def file(self, label: str, path, *, expect: str = 'absent') -> dict:
        """One file, by path (never followed if it is a link)."""
        surface = self._new(label, 'file', expect)
        self._entries(surface, [_disk_entry(os.fspath(path), os.path.basename(os.fspath(path)))])
        surface.searched = True
        return surface.report()

    def tree(self, label: str, root, *, expect: str = 'absent') -> dict:
        """Every regular file under ROOT; links and junctions are not followed (counted), their targets searched as
        names; every file's relative path is searched as a name."""
        surface = self._new(label, 'tree', expect)
        root = os.fspath(root)
        if not os.path.isdir(root) or os.path.islink(root) or _junction(root):
            surface.unreadable['not a directory'] += 1
        else:
            self._entries(surface, _walk(root, surface))
        surface.searched = True
        return surface.report()

    def _entries(self, surface: _Surface, entries) -> None:
        """Entries (name, kind, opener, link target): kind file is read through opener; link and special are not
        followed; missing is unreadable."""
        for name, kind, opener, target in entries:
            surface.items += 1
            self._view(surface, 'name', str(name).encode('utf-8', 'surrogateescape'), name)
            if kind == 'link':
                surface.skipped['links'] += 1
                if target is not None:
                    self._view(surface, 'name', str(target).encode('utf-8', 'surrogateescape'), name)
            elif kind == 'special':
                surface.skipped['special files'] += 1
            elif kind == 'missing':
                surface.unreadable['FileNotFoundError'] += 1
            else:
                try:
                    with opener() as handle:
                        self._blob(surface, handle.read, name)
                except OSError as exc:
                    surface.unreadable[type(exc).__name__] += 1

    def tar(self, label: str, data, *, expect: str = 'absent') -> dict:
        """A tar stream (bytes or a binary file object), compressed or not: every member's name and link target,
        and every regular member's content through every view."""
        surface = self._new(label, 'tar', expect)
        fileobj = io.BytesIO(data) if isinstance(data, (bytes, bytearray)) else data
        try:
            with tarfile.open(fileobj=fileobj, mode='r|*') as archive:
                for member in archive:
                    surface.items += 1
                    self._view(surface, 'name', member.name.encode('utf-8', 'surrogateescape'), member.name)
                    if member.issym() or member.islnk():
                        surface.skipped['links'] += 1
                        self._view(surface, 'name', member.linkname.encode('utf-8', 'surrogateescape'),
                                   member.name)
                    elif member.isfile():
                        self._blob(surface, archive.extractfile(member).read, member.name)
                    elif not member.isdir():
                        surface.skipped['special files'] += 1
        except (tarfile.TarError, EOFError, OSError, zlib.error) as exc:
            surface.unreadable[type(exc).__name__] += 1
        surface.searched = True
        return surface.report()

    def environ(self, label: str, mapping=None, *, expect: str = 'absent') -> dict:
        """A process environment (this process's when MAPPING is None), as NAME=VALUE entries."""
        surface = self._new(label, 'environ', expect)
        mapping = os.environ if mapping is None else mapping
        for name, value in sorted(mapping.items()):
            surface.items += 1
            self._blob(surface, io.BytesIO(f'{name}={value}'.encode('utf-8', 'surrogateescape')).read, name)
        surface.searched = True
        return surface.report()

    def objects(self, label: str, kind: str, items, *, expect: str = 'absent', incomplete=()) -> dict:
        """One surface of several named byte strings held in memory, each searched through every view that applies
        to it (E-05.9: a git bundle's pack objects, inflated and with their deltas applied, by integrations/dispatch/
        native_token_search.py). INCOMPLETE names what the caller could not read in full."""
        surface = self._new(label, kind, expect)
        for name, data in items:
            surface.items += 1
            self._blob(surface, io.BytesIO(bytes(data)).read, f'{label} {name}')
        for reason in incomplete:
            surface.incomplete[str(reason)] += 1
        surface.searched = True
        return surface.report()

    # ---- the positive control

    def carriers(self) -> list:
        """(case, bytes): a planted copy of the key in each form, made by the standard library's encoders."""
        key, body = self._key, body_of(self._key, self.prefix)
        k = key.encode('utf-8')
        out = [('raw', b'provider key: ' + k + b'\n'),
               ('json', json.dumps({'api_key': key}).encode('utf-8')),
               ('url-form', urllib.parse.urlencode({'key': key, 'x': 'y'}).encode('ascii')),
               ('url-quote', urllib.parse.quote(key, safe='').encode('ascii')),
               ('hex', b'0x' + k.hex().encode('ascii')),
               ('HEX', binascii.hexlify(k).upper()),
               ('utf-16-le', ('key=' + key).encode('utf-16-le')),
               ('utf-16-be', ('key=' + key).encode('utf-16-be'))]
        for shift in range(3):
            out.append((f'base64@{shift}', base64.b64encode(b'u' * shift + b':' + k + b'\n')))
            out.append((f'base64url@{shift}', base64.urlsafe_b64encode(b'\xfb\xff' * shift + k)))
        out.append(('body', b'Bearer ' + body.encode('utf-8')))
        run = body if len(body) <= FRAGMENT + STRIDE else body[1:FRAGMENT + STRIDE]
        out.append(('fragment', b'...' + run.encode('utf-8') + b'...'))
        return out

    def _split_point(self, data: bytes) -> int:
        """Where to cut a carrier so that no whole copy of a form (fragments aside) lies on either side: the middle
        of the span every such occurrence shares (the body's), else the carrier's middle."""
        spans = []
        for needle, labels in self._table.items():
            if labels == ('fragment',):
                continue
            at = data.find(needle)
            while at != -1:
                spans.append((at, at + len(needle)))
                at = data.find(needle, at + 1)
        low, high = max((a for a, _ in spans), default=0), min((b for _, b in spans), default=len(data))
        return (low + high) // 2 if low < high else len(data) // 2

    def controls(self) -> dict:
        """Plant every carrier in every kind of surface and view, in memory, and search it with a search of the same
        key (the same needles and chunk size). Each case must be found in the view it plants for; the verdict is
        invalid unless every case is."""
        carriers = self.carriers()
        probe = Search(self._key, chunk=self.chunk, prefix=self.prefix)
        cases, failed = [], []

        def case(kind, name, report, view, where, raw_misses=False):
            cases.append(f'{kind}/{name}')
            views = report['matches_by_view']
            ok = bool(views.get(view)) and where in report['where']
            if raw_misses and set(views.get('raw', {})) - {'fragment'}:
                ok = False                       # the raw view found the whole copy: not split as planted
            if not ok:
                failed.append(f'{kind}/{name}')
        for name, data in carriers:
            case('capture', name, probe.capture(name, data), 'raw', name)
            split = self._split_point(data)
            straddle = b'\x00' * (self.chunk - split) + data
            case('chunk-boundary', name, probe.capture(name, straddle), 'raw', name)
            case('gzip', name, probe.capture(name, gzip.compress(b'\x00' * 7 + data, mtime=0)), 'gzip', name)
            surface = probe._new(name, 'file', 'absent')
            probe._entries(surface, [(name, 'file', lambda d=data: io.BytesIO(d), None)])
            surface.searched = True
            case('file', name, surface.report(), 'raw', name)
            case('sqlite', name, probe.capture(name, _sqlite_image(data)), 'sqlite', name)
            case('sqlite-overflow', name, probe.capture(name, _sqlite_image(data, split=split)), 'sqlite', name,
                 raw_misses=True)
            case('http-chunked', name, probe.http(name, _chunked_response(data, split)), 'http-body',
                 f'{name} message 1', raw_misses=True)
            case('http-gzip', name, probe.http(name, _gzip_response(data)), 'http-decoded', f'{name} message 1')
            if name not in ('utf-16-le', 'utf-16-be'):
                case('environ', name, probe.environ(name, {name: data.decode('ascii')}), 'raw', name)
        members = [(f'dir/member-{name}', data) for name, data in carriers]
        surface = probe._new('tree', 'tree', 'absent')
        probe._entries(surface, [(n, 'file', lambda d=d: io.BytesIO(d), None) for n, d in members])
        surface.searched = True
        report = surface.report()
        for n, _ in members:
            case('tree', n, report, 'raw', n)
        for compression in ('', 'gz'):
            report = probe.tar('tar', _tar_image(members, compression))
            for n, _ in members:
                case(f'tar{"-" + compression if compression else ""}', n, report, 'raw', n)
        report = probe.tar('tar-name', _tar_image([('dir/' + self._key, b'nothing here')], 'gz'))
        case('tar-name', 'raw', report, 'name', WITHHELD)
        self.control = {'valid': not failed, 'cases': len(cases), 'failed': failed,
                        'kinds': sorted({c.split('/')[0] for c in cases}),
                        'carriers': [name for name, _ in carriers],
                        'how': "copies of the key made by the standard library's encoders (json, urllib.parse, "
                               'binascii, base64, str.encode), planted in memory in each kind of surface (a '
                               'capture, a file, a tree, a tar stream plain and gzip-compressed, a member name, '
                               'an environment) and each view (a copy across the read boundary; gzip; an SQLite '
                               'row, also split across an overflow page, where the raw view must find no whole '
                               'copy; an HTTP body split across two chunks, likewise, and gzip-encoded), '
                               "and searched with this search's needles and chunk size; nothing written to disk"}
        return self.control

    # ---- the verdict

    def report(self) -> dict:
        surfaces = [s.report() for s in self.surfaces]
        absent = [s for s in surfaces if s['expect'] == 'absent']
        present = [s for s in surfaces if s['expect'] == 'present']
        control = self.control or {'valid': False, 'cases': 0, 'failed': ['not run']}
        missed = [s['label'] for s in present if not s['found']]
        if any(s['found'] for s in absent):
            verdict = 'found'
        elif not control['valid'] or missed:
            verdict = 'invalid'
        elif not absent or not all(s['complete'] for s in surfaces):
            verdict = 'incomplete'
        else:
            verdict = 'not-found'
        total = sum(s['bytes_total'] for s in absent)
        statements = {
            'found': f'the key was found on {sum(1 for s in absent if s["found"])} surface(s) expected not to hold '
                     'it (see matches and where)',
            'invalid': 'the search is not valid: ' + ('a positive control missed a planted copy'
                                                      if not control['valid'] else
                                                      f'the key was not found where it is expected ({missed})'),
            'incomplete': 'not every surface was searched in full (see unreadable and incomplete); nothing is '
                          'claimed for what was not searched',
            'not-found': f'the key ({self.fingerprint}) was not found, raw or in any listed form, in the {total} '
                         f'bytes of the {len(absent)} surface(s) expected not to hold it, and the positive '
                         'controls found every planted copy. This covers those bytes only: it is not proof that '
                         'the key is absent anywhere else (see not_covered)',
        }
        return {'format': FORMAT, 'key': {'fingerprint': self.fingerprint, 'held': 'in memory only'},
                'forms': FORMS, 'views': VIEWS, 'needles': len(self._table), 'controls': control,
                'expected_present': {'surfaces': len(present), 'missed': missed},
                'surfaces': surfaces, 'bytes_searched': total, 'verdict': verdict,
                'statement': statements[verdict], 'not_covered': list(NOT_COVERED)}


# ---------------------------------------------------------------- disk and in-memory images


def _junction(path: str) -> bool:
    isjunction = getattr(os.path, 'isjunction', None)
    return bool(isjunction and isjunction(path))


def _disk_entry(path: str, name: str) -> tuple:
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return (name, 'missing', None, None)
    except OSError:
        return (name, 'file', lambda: open(path, 'rb'), None)   # its error is counted when it is read
    if stat.S_ISLNK(info.st_mode) or _junction(path):
        try:
            target = os.readlink(path)
        except OSError:
            target = None
        return (name, 'link', None, target)
    if not stat.S_ISREG(info.st_mode):
        return (name, 'special', None, None)
    return (name, 'file', lambda: open(path, 'rb'), None)


def _walk(root: str, surface: _Surface):
    """Entries of every file under ROOT, relative names with '/'; directories that are links or junctions are
    yielded as links and not entered."""
    def failed(exc):
        surface.unreadable[type(exc).__name__] += 1
    for here, dirs, files in os.walk(root, followlinks=False, onerror=failed):
        dirs.sort()
        for name in list(dirs):
            path = os.path.join(here, name)
            if os.path.islink(path) or _junction(path):
                dirs.remove(name)
                yield _disk_entry(path, os.path.relpath(path, root).replace(os.sep, '/'))
        for name in sorted(files):
            path = os.path.join(here, name)
            yield _disk_entry(path, os.path.relpath(path, root).replace(os.sep, '/'))


def _sqlite_image(data: bytes, *, split: int | None = None) -> bytes:
    """An SQLite database image in memory holding DATA as text and as a blob; with SPLIT, a blob of 6000 bytes in
    pages of 4096 bytes instead, DATA placed so that the end of the cell's local payload falls at DATA[SPLIT]: the
    file holds it in two pieces (the first overflow page's 4-byte pointer between them; the local payload size of
    SQLite's file format)."""
    connection = sqlite3.connect(':memory:')
    try:
        connection.execute('PRAGMA page_size = 4096')
        if split is not None:
            size = 6000
            header = 1 + (2 if size * 2 + 12 < 16384 else 3)
            payload, usable = header + size, 4096
            least = (usable - 12) * 32 // 255 - 23
            local = least + (payload - least) % (usable - 4)
            local = local if local <= usable - 35 else least
            value = bytearray(b'.' * size)
            at = local - header - split
            value[at:at + len(data)] = data
            connection.execute('CREATE TABLE planted (value BLOB)')
            connection.execute('INSERT INTO planted VALUES (?)', (bytes(value),))
        else:
            connection.execute('CREATE TABLE planted (text_value TEXT, blob_value BLOB)')
            connection.execute('INSERT INTO planted VALUES (?, ?)', (data.decode('latin-1'), data))
        connection.commit()
        return connection.serialize()
    finally:
        connection.close()


def _chunked_response(data: bytes, half: int) -> bytes:
    """An HTTP/1.1 response whose chunked body splits DATA in two chunks at HALF."""
    body = b'%x\r\n%s\r\n%x\r\n%s\r\n0\r\n\r\n' % (half, data[:half], len(data) - half, data[half:])
    return b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nTransfer-Encoding: chunked\r\n\r\n' + body


def _gzip_response(data: bytes) -> bytes:
    body = gzip.compress(data, mtime=0)
    return (b'HTTP/1.1 200 OK\r\nContent-Encoding: gzip\r\nContent-Length: %d\r\n\r\n' % len(body)) + body


def _tar_image(members, compression: str) -> bytes:
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode='w:' + compression) as archive:
        for name, data in members:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return out.getvalue()


# ---------------------------------------------------------------- command line


def parse_surface(value: str) -> tuple:
    """LABEL=KIND:PATH -> (label, kind, path)."""
    label, sep, rest = str(value).partition('=')
    kind, sep2, path = rest.partition(':')
    if not sep or not sep2 or not LABEL.fullmatch(label) or kind not in KINDS or not path \
            or (kind == 'environ' and path != 'self'):
        raise SearchError('SURFACE_INVALID', 'not LABEL=KIND:PATH')
    return label, kind, path


def run(key: str, expected: str, surfaces: list) -> dict:
    """Search SURFACES ([(label, kind, path)]) for KEY after checking its fingerprint; run the controls."""
    check_fingerprint(key, expected)
    labels = [label for label, _, _ in surfaces]
    if not surfaces or len(set(labels)) != len(labels):
        raise SearchError('SURFACE_INVALID', 'give at least one surface, each label once')
    search = Search(key)
    for label, kind, path in surfaces:
        if kind == 'file':
            search.file(label, path)
        elif kind == 'tree':
            search.tree(label, path)
        elif kind == 'tar':
            surface_path = os.fspath(path)
            try:
                with open(surface_path, 'rb') as handle:
                    search.tar(label, handle)
            except OSError as exc:
                surface = search._new(label, 'tar', 'absent')
                surface.unreadable[type(exc).__name__] += 1
                surface.searched = True
        else:
            search.environ(label)
    search.controls()
    report = search.report()
    text = json.dumps(report, indent=2, sort_keys=True)
    if search.holds(text):
        raise SearchError('OUTPUT_WITHHELD', 'the report held the key')
    return report


def main(argv=None, stdin=None, out=None, err=None) -> int:
    parser = argparse.ArgumentParser(prog='inference_key_search.py', description='The provider-key containment '
                                     'search (S-03.2): the synthetic key, raw and in its encodings, on the listed '
                                     'surfaces, with a positive control. Exit 0 not-found, 1 found, invalid or '
                                     'incomplete, 2 refused.')
    sub = parser.add_subparsers(dest='command', required=True)
    search = sub.add_parser('search', help='read the synthetic key from standard input and search the surfaces')
    search.add_argument('--expect-fingerprint', required=True,
                        help="the broker start receipt's provider-key fingerprint, sha256:<16 hex digits>")
    search.add_argument('--surface', action='append', required=True, dest='surfaces',
                        help='LABEL=KIND:PATH, KIND file, tree, tar or environ (PATH self); repeatable')
    args = parser.parse_args(argv)
    stdin = sys.stdin if stdin is None else stdin
    out = sys.stdout if out is None else out
    err = sys.stderr if err is None else err
    try:
        surfaces = [parse_surface(value) for value in args.surfaces]
        if len({label for label, _, _ in surfaces}) != len(surfaces):
            raise SearchError('SURFACE_INVALID', 'each label once')
        if not FINGERPRINT.fullmatch(args.expect_fingerprint):
            raise SearchError('FINGERPRINT_INVALID', 'not sha256:<16 hex digits>')
        report = run(read_key(stdin), args.expect_fingerprint, surfaces)
    except SearchError as exc:
        err.write(f'inference-key-search: {exc}\n')
        return 1 if exc.code == 'OUTPUT_WITHHELD' else 2
    out.write(json.dumps(report, indent=2, sort_keys=True) + '\n')
    err.write(f"inference-key-search: {report['verdict']}: {report['bytes_searched']} bytes on "
              f"{len(report['surfaces'])} surface(s); controls {'valid' if report['controls']['valid'] else 'INVALID'}"
              f" ({report['controls']['cases']} cases)\n")
    return 0 if report['verdict'] == 'not-found' else 1


if __name__ == '__main__':
    sys.exit(main())
