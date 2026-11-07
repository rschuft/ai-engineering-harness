"""Deterministic cloud-init NoCloud seed generator (plan leaf F-03.2.2).

Implements the generator specification in ``profiles/seed/README.md``:

1. Standard-library Python, run with ``python -I``; needs no host install and writes
   only ``seed.iso`` inside an existing instance directory.
2. Reads the three seed templates a profile pins (``boot_inputs.seed.templates``) and
   refuses when a template's sha256 differs from its pin.
3. Substitutes exactly the documented placeholders: ``{{agent_ssh_public_key}}``,
   ``{{scratch_device}}`` and ``{{provision_manifest}}`` in user-data,
   ``{{instance_id}}`` and ``{{instance_name}}`` in meta-data, nothing in
   network-config. A remaining ``{{`` or an unknown placeholder is an error. The public
   key must be one OpenSSH ``ssh-ed25519`` line. The provisioning manifest (F-04.1,
   decision 0006) is one JSON object, written base64-encoded; without one the value is
   empty and the seeded provisioning units stay inert.
4. Writes ``seed.iso``: ISO 9660 (ECMA-119) with a Joliet supplementary volume
   descriptor, primary volume identifier ``CIDATA``, Joliet volume identifier
   ``cidata``, the files ``user-data``, ``meta-data`` and ``network-config`` in the
   root directory, 2048-byte blocks, no Rock Ridge, no El Torito. Every date is
   1970-01-01T00:00:00Z or "not specified"; the same inputs give the same bytes.
5. Prints the sha256 of ``seed.iso`` (one JSON object on stdout) for the launch record.

Usage (from the repository root):
    python -I -B tools/nocloud_seed.py --profile profiles/strong-windows-qemu-whpx \
        --instance-dir <state_dir>/instances/<name> --instance-name <name> \
        --public-key <state_dir>/instances/<name>/ssh/id_ed25519.pub \
        [--instance-id <name>-<uuid>] [--provision-manifest <file>]

Without ``--instance-id`` a fresh one (the instance name, ``-``, a random UUID) is
generated and printed. Exit status 0 on success; 1 with a ``REFUSED:`` line on stderr
when an input is refused (nothing is written then).
"""
import argparse
import base64
import hashlib
import json
import os
import re
import struct
import sys
import uuid
from pathlib import Path

BLOCK = 2048
SEED_NAME = 'seed.iso'
PRIMARY_VOLUME_ID = 'CIDATA'
JOLIET_VOLUME_ID = 'cidata'
JOLIET_ESCAPE = b'%/E'  # UCS-2 level 3 (Joliet specification)
# Fixed file order: data extents and both directories list the files in this order,
# which is also the identifier sort order ECMA-119 9.3 requires in each tree.
FILES = ('meta-data', 'network-config', 'user-data')
# Primary (ISO 9660 level 1, 8.3 d-characters) identifiers, as genisoimage derives them.
PRIMARY_NAMES = {'meta-data': 'META_DAT.;1', 'network-config': 'NETWORK_.;1',
                 'user-data': 'USER_DAT.;1'}
# The placeholders each template must carry, exactly (profiles/seed/README.md).
PLACEHOLDERS = {
    'user-data': ('agent_ssh_public_key', 'scratch_device', 'provision_manifest'),
    'meta-data': ('instance_id', 'instance_name'),
    'network-config': (),
}
PLACEHOLDER = re.compile(r'\{\{([^{}]*)\}\}')
INSTANCE_NAME_DEFAULT = r'^[a-z][a-z0-9-]{1,40}$'
SCRATCH_DEVICE = re.compile(r'^/dev/[A-Za-z0-9._/-]+$')
KEY_LINE = re.compile(r'^ssh-ed25519 ([A-Za-z0-9+/]+={0,2})(?: ([A-Za-z0-9._@+=-]{1,64}))?$')
KEY_FILE_MAX = 4096
MANIFEST_MAX = 64 * 1024
MANIFEST_SCHEMA = 'ai-engineering-harness/profiles/provision-manifest/v1'
# 7-byte directory-record date (ECMA-119 9.1.5): 1970-01-01 00:00:00, offset 0.
DIR_DATE = bytes([70, 1, 1, 0, 0, 0, 0])
# 17-byte volume-descriptor dates (ECMA-119 8.4.26.1).
VD_DATE_FIXED = b'1970010100000000\x00'
VD_DATE_UNSET = b'0000000000000000\x00'


class Refused(Exception):
    """An input the specification refuses; nothing has been written."""


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------- inputs


def load_profile(profile_path):
    """Return (profile, repository root) for a profile directory or profile.json."""
    path = Path(profile_path)
    if path.is_dir():
        path = path / 'profile.json'
    path = path.resolve()
    try:
        profile = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise Refused(f'profile {path}: cannot read ({exc})') from exc
    root = path.parents[2]
    if path.parent.parent != root / 'profiles':
        raise Refused(f'profile {path}: not at profiles/<name>/profile.json')
    return profile, root


def seed_declaration(profile):
    seed = (profile.get('boot_inputs') or {}).get('seed') or {}
    templates = seed.get('templates') or {}
    if sorted(templates) != sorted(FILES):
        raise Refused(f'boot_inputs.seed.templates: expected {sorted(FILES)}, '
                      f'found {sorted(templates)}')
    return seed


def read_templates(profile, root):
    """Read each pinned template and refuse unless its sha256 matches the pin."""
    seed = seed_declaration(profile)
    out = {}
    for name in FILES:
        entry = seed['templates'][name]
        rel, pin = entry.get('path'), entry.get('sha256')
        if not isinstance(rel, str) or not isinstance(pin, str) or \
                not re.fullmatch(r'[0-9a-f]{64}', pin):
            raise Refused(f'boot_inputs.seed.templates.{name}: path and sha256 required')
        path = (root / rel).resolve()
        if root.resolve() not in path.parents:
            raise Refused(f'boot_inputs.seed.templates.{name}: {rel} is outside the checkout')
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise Refused(f'template {rel}: cannot read ({exc})') from exc
        got = sha256_bytes(raw)
        if got != pin:
            raise Refused(f'template {rel}: sha256 {got} does not match the pinned {pin}')
        if b'\r' in raw:
            raise Refused(f'template {rel}: carries CR bytes (LF line endings required)')
        try:
            out[name] = raw.decode('utf-8')
        except UnicodeDecodeError as exc:
            raise Refused(f'template {rel}: not UTF-8 ({exc})') from exc
    return out


def parse_public_key(text):
    """Return the single OpenSSH ssh-ed25519 public-key line, or refuse."""
    if text.endswith('\r\n'):
        text = text[:-2]
    elif text.endswith('\n'):
        text = text[:-1]
    if '\n' in text or '\r' in text:
        raise Refused('public key: exactly one line required')
    match = KEY_LINE.fullmatch(text)
    if not match:
        raise Refused('public key: not one OpenSSH "ssh-ed25519 <base64> [comment]" line '
                      '(no options, one comment token of [A-Za-z0-9._@+=-] at most)')
    try:
        blob = base64.b64decode(match.group(1), validate=True)
    except ValueError as exc:
        raise Refused(f'public key: base64 does not decode ({exc})') from exc
    # RFC 8709: string "ssh-ed25519", string key (32 bytes).
    expected_type = b'ssh-ed25519'
    head = struct.pack('>I', len(expected_type)) + expected_type + struct.pack('>I', 32)
    if len(blob) != len(head) + 32 or not blob.startswith(head):
        raise Refused('public key: the key blob is not an ssh-ed25519 key of 32 bytes')
    return text


def read_public_key(path):
    try:
        with open(path, 'rb') as handle:
            raw = handle.read(KEY_FILE_MAX + 1)
    except OSError as exc:
        raise Refused(f'public key {path}: cannot read ({exc})') from exc
    if len(raw) > KEY_FILE_MAX:
        raise Refused(f'public key {path}: larger than {KEY_FILE_MAX} bytes')
    try:
        text = raw.decode('ascii')
    except UnicodeDecodeError as exc:
        raise Refused(f'public key {path}: not ASCII') from exc
    return parse_public_key(text)


def provision_manifest_value(manifest):
    """The base64 text substituted for {{provision_manifest}}: '' without a manifest, else
    the manifest bytes, which must be one ASCII JSON object of the provision-manifest
    schema, LF only, at most MANIFEST_MAX bytes."""
    if manifest is None:
        return ''
    if not isinstance(manifest, bytes):
        raise Refused('provision manifest: bytes required')
    if not manifest or len(manifest) > MANIFEST_MAX or b'\r' in manifest:
        raise Refused(f'provision manifest: empty, larger than {MANIFEST_MAX} bytes or has CR')
    try:
        data = json.loads(manifest.decode('ascii'))
    except (UnicodeDecodeError, ValueError) as exc:
        raise Refused(f'provision manifest: not one ASCII JSON document ({exc})') from exc
    if not isinstance(data, dict) or data.get('schema') != MANIFEST_SCHEMA:
        raise Refused(f'provision manifest: not a {MANIFEST_SCHEMA} object')
    return base64.b64encode(manifest).decode('ascii')


def read_provision_manifest(path):
    try:
        with open(path, 'rb') as handle:
            raw = handle.read(MANIFEST_MAX + 1)
    except OSError as exc:
        raise Refused(f'provision manifest {path}: cannot read ({exc})') from exc
    return raw


def check_instance_name(profile, name):
    pattern = (profile.get('identity') or {}).get('instance_name_pattern') \
        or INSTANCE_NAME_DEFAULT
    if not isinstance(name, str) or not re.fullmatch(pattern, name):
        raise Refused(f'instance name {name!r} does not match {pattern}')
    return name


def new_instance_id(name):
    """The instance name plus a fresh UUID (profiles/seed/README.md, meta-data)."""
    return f'{name}-{uuid.uuid4()}'


def check_instance_id(name, instance_id):
    prefix = f'{name}-'
    if not isinstance(instance_id, str) or not instance_id.startswith(prefix):
        raise Refused(f'instance id {instance_id!r} must be "{prefix}<uuid>"')
    tail = instance_id[len(prefix):]
    try:
        canonical = str(uuid.UUID(tail))
    except ValueError as exc:
        raise Refused(f'instance id {instance_id!r}: {tail!r} is not a UUID') from exc
    if canonical != tail:
        raise Refused(f'instance id {instance_id!r}: UUID must be canonical lowercase')
    return instance_id


def scratch_device(profile):
    seed = seed_declaration(profile)
    value = (seed.get('substitutions') or {}).get('scratch_device')
    if not isinstance(value, str) or not SCRATCH_DEVICE.fullmatch(value):
        raise Refused(f'boot_inputs.seed.substitutions.scratch_device {value!r} is not a '
                      '/dev path')
    return value


def substitute(name, template, values):
    """Replace exactly the placeholders this template must carry; refuse anything else."""
    expected = PLACEHOLDERS[name]
    found = PLACEHOLDER.findall(template)
    unknown = sorted({p for p in found if p not in expected})
    if unknown:
        raise Refused(f'{name}: unknown placeholder(s) {unknown}')
    missing = [p for p in expected if p not in found]
    if missing:
        raise Refused(f'{name}: placeholder(s) {missing} missing from the template')
    rendered = PLACEHOLDER.sub(lambda m: values[m.group(1)], template)
    if '{{' in rendered or '}}' in rendered:
        raise Refused(f'{name}: a placeholder delimiter remains after substitution')
    return rendered


def render(templates, values):
    """Return {file name: UTF-8 bytes} for the three seed files."""
    out = {}
    for name in FILES:
        text = substitute(name, templates[name], values)
        if '\r' in text:
            raise Refused(f'{name}: CR in the rendered file')
        out[name] = text.encode('utf-8')
    return out


# ---------------------------------------------------------------- ISO 9660


def both16(value):
    return struct.pack('<H', value) + struct.pack('>H', value)


def both32(value):
    return struct.pack('<I', value) + struct.pack('>I', value)


def blocks(size):
    return max(1, -(-size // BLOCK))


def a_field(text, length):
    data = text.encode('ascii')
    if len(data) > length:
        raise ValueError(f'{text!r} longer than {length}')
    return data + b' ' * (length - len(data))


def ucs2_field(text, length):
    data = text.encode('utf-16-be')
    if len(data) > length:
        raise ValueError(f'{text!r} longer than {length}')
    pad = b'\x00\x20' * length
    return (data + pad)[:length]


def dir_record(identifier, extent, size, is_dir):
    """ECMA-119 9.1 directory record, without a system use area (no Rock Ridge)."""
    length = 33 + len(identifier)
    pad = b'\x00' if len(identifier) % 2 == 0 else b''
    length += len(pad)
    return (bytes([length, 0]) + both32(extent) + both32(size) + DIR_DATE +
            bytes([0x02 if is_dir else 0x00, 0, 0]) + both16(1) +
            bytes([len(identifier)]) + identifier + pad)


def directory(own_extent, entries):
    """One-block root directory: '.', '..' (the root itself), then the entries."""
    data = dir_record(b'\x00', own_extent, BLOCK, True) + \
        dir_record(b'\x01', own_extent, BLOCK, True)
    for identifier, extent, size in entries:
        data += dir_record(identifier, extent, size, False)
    if len(data) > BLOCK:
        raise ValueError('root directory does not fit one block')
    return data + b'\x00' * (BLOCK - len(data))


def path_table(root_extent, big_endian):
    """A path table holding only the root directory (ECMA-119 9.4)."""
    fmt = '>' if big_endian else '<'
    entry = bytes([1, 0]) + struct.pack(fmt + 'I', root_extent) + \
        struct.pack(fmt + 'H', 1) + b'\x00' + b'\x00'
    return entry


def volume_descriptor(joliet, space_blocks, pt_size, l_pt, m_pt, root_extent):
    field = ucs2_field if joliet else a_field
    vd = bytearray(BLOCK)
    vd[0] = 2 if joliet else 1
    vd[1:6] = b'CD001'
    vd[6] = 1
    vd[8:40] = field('', 32)                                   # system identifier
    vd[40:72] = field(JOLIET_VOLUME_ID if joliet else PRIMARY_VOLUME_ID, 32)
    vd[80:88] = both32(space_blocks)
    if joliet:
        vd[88:88 + len(JOLIET_ESCAPE)] = JOLIET_ESCAPE
    vd[120:124] = both16(1)                                    # volume set size
    vd[124:128] = both16(1)                                    # volume sequence number
    vd[128:132] = both16(BLOCK)                                # logical block size
    vd[132:140] = both32(pt_size)
    vd[140:144] = struct.pack('<I', l_pt)
    vd[148:152] = struct.pack('>I', m_pt)
    vd[156:190] = dir_record(b'\x00', root_extent, BLOCK, True)
    vd[190:318] = field('', 128)                               # volume set identifier
    vd[318:446] = field('', 128)                               # publisher
    vd[446:574] = field('', 128)                               # data preparer
    vd[574:702] = field('', 128)                               # application
    vd[702:739] = field('', 37)                                # copyright file
    vd[739:776] = field('', 37)                                # abstract file
    vd[776:813] = field('', 37)                                # bibliographic file
    vd[813:830] = VD_DATE_FIXED                                # creation
    vd[830:847] = VD_DATE_FIXED                                # modification
    vd[847:864] = VD_DATE_UNSET                                # expiration
    vd[864:881] = VD_DATE_UNSET                                # effective
    vd[881] = 1                                                # file structure version
    return bytes(vd)


def terminator():
    vd = bytearray(BLOCK)
    vd[0] = 255
    vd[1:6] = b'CD001'
    vd[6] = 1
    return bytes(vd)


def build_iso(files):
    """Return the ISO 9660 + Joliet image bytes for {name: bytes} (names in FILES)."""
    if sorted(files) != sorted(FILES):
        raise ValueError(f'files must be exactly {FILES}')
    # Layout: 0-15 system area, 16 PVD, 17 Joliet SVD, 18 terminator, 19-22 path
    # tables (primary L, M; Joliet L, M), 23 primary root, 24 Joliet root, then the
    # file data in FILES order, each from a block boundary, shared by both trees.
    pvd_at, svd_at, term_at = 16, 17, 18
    p_lpt, p_mpt, j_lpt, j_mpt = 19, 20, 21, 22
    p_root, j_root = 23, 24
    extent, extents = 25, {}
    for name in FILES:
        extents[name] = extent
        extent += blocks(len(files[name]))
    space = extent
    pt_size = len(path_table(p_root, False))
    primary = directory(p_root, [(PRIMARY_NAMES[n].encode('ascii'), extents[n],
                                  len(files[n])) for n in FILES])
    joliet = directory(j_root, [(n.encode('utf-16-be'), extents[n], len(files[n]))
                                for n in FILES])
    image = bytearray(space * BLOCK)

    def put(block, data):
        image[block * BLOCK:block * BLOCK + len(data)] = data

    put(pvd_at, volume_descriptor(False, space, pt_size, p_lpt, p_mpt, p_root))
    put(svd_at, volume_descriptor(True, space, pt_size, j_lpt, j_mpt, j_root))
    put(term_at, terminator())
    put(p_lpt, path_table(p_root, False))
    put(p_mpt, path_table(p_root, True))
    put(j_lpt, path_table(j_root, False))
    put(j_mpt, path_table(j_root, True))
    put(p_root, primary)
    put(j_root, joliet)
    for name in FILES:
        put(extents[name], files[name])
    return bytes(image)


# ---------------------------------------------------------------- generator


def generate(profile_path, instance_dir, instance_name, public_key_path, instance_id=None,
             provision_manifest=None):
    """Validate every input, then write <instance_dir>/seed.iso exclusively.

    ``provision_manifest`` is the manifest bytes of a provisioned instance (F-04.1) or None.
    Returns a dict for the launch record: the seed path, its sha256, the instance id,
    the sha256 of each template and rendered file and of the manifest (None without one).
    """
    profile, root = load_profile(profile_path)
    name = check_instance_name(profile, instance_name)
    if instance_id is None:
        instance_id = new_instance_id(name)
    check_instance_id(name, instance_id)
    templates = read_templates(profile, root)
    values = {
        'agent_ssh_public_key': read_public_key(public_key_path),
        'scratch_device': scratch_device(profile),
        'provision_manifest': provision_manifest_value(provision_manifest),
        'instance_id': instance_id,
        'instance_name': name,
    }
    rendered = render(templates, values)
    image = build_iso(rendered)
    target_dir = Path(instance_dir)
    if not target_dir.is_dir():
        raise Refused(f'instance directory {target_dir} does not exist')
    target = target_dir / SEED_NAME
    partial = target_dir / (SEED_NAME + '.partial')
    if target.exists() or partial.exists():
        raise Refused(f'{target} (or its .partial) already exists; it is never overwritten')
    with open(partial, 'xb') as handle:
        handle.write(image)
        handle.flush()
        os.fsync(handle.fileno())
    os.rename(partial, target)  # fails rather than replace an existing file
    if sha256_bytes(target.read_bytes()) != sha256_bytes(image):
        raise Refused(f'{target}: written bytes differ from the generated image')
    return {
        'seed_iso': str(target),
        'sha256': sha256_bytes(image),
        'size_bytes': len(image),
        'instance_id': instance_id,
        'templates': {n: profile['boot_inputs']['seed']['templates'][n]['sha256']
                      for n in FILES},
        'rendered_sha256': {n: sha256_bytes(rendered[n]) for n in FILES},
        'provision_manifest_sha256': None if provision_manifest is None
        else sha256_bytes(provision_manifest),
    }


def main(argv=None):
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--profile', required=True, help='profile directory or profile.json')
    ap.add_argument('--instance-dir', required=True,
                    help='existing instance directory; seed.iso is written here only')
    ap.add_argument('--instance-name', required=True)
    ap.add_argument('--public-key', required=True,
                    help='file holding one OpenSSH ssh-ed25519 public-key line')
    ap.add_argument('--instance-id', help='<name>-<uuid>; generated when omitted')
    ap.add_argument('--provision-manifest',
                    help='a provision-manifest JSON file (F-04.1); omitted for an ordinary guest')
    args = ap.parse_args(argv)
    try:
        manifest = read_provision_manifest(args.provision_manifest) \
            if args.provision_manifest else None
        result = generate(args.profile, args.instance_dir, args.instance_name,
                          args.public_key, args.instance_id, manifest)
    except Refused as exc:
        print(f'REFUSED: {exc}', file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
