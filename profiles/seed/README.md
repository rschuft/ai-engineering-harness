# Guest seed: cloud-init NoCloud

Plan leaf F-03.2.1. These templates are boot inputs (`profiles P9`) of both strong
profiles, pinned by sha256 in each `profile.json`. They carry only the per-instance
public key and non-secret configuration (`profiles P5`).

| File | Content | Substituted at `create` |
|---|---|---|
| [`user-data.tmpl`](user-data.tmpl) | user `agent` (no password, no sudo group, no `sudo:` rule), `disable_root`, sshd drop-in with `PermitRootLogin no`, host keys deleted and regenerated (`ssh_deletekeys`), scratch disk formatted and mounted at `/srv/scratch`, exchange directory `/home/agent/exchange` | `{{agent_ssh_public_key}}`; `{{scratch_device}}` from the profile |
| [`meta-data.tmpl`](meta-data.tmpl) | NoCloud `instance-id` and `local-hostname` | `{{instance_id}}` (instance name plus a fresh UUID at each `create`), `{{instance_name}}` |
| [`network-config.yaml`](network-config.yaml) | network config v2: DHCPv4 on the single NIC; DHCPv6, router advertisements and IPv6 link-local addresses off (`profiles P7`: IPv6 off unless listed) | nothing |

**Identity (`profiles P8`).** Host keys: `ssh_deletekeys: true` with
`ssh_genkeytypes: [ed25519]` regenerates them on first boot. machine-id: the guest's
systemd generates it on first boot when the image ships an empty or uninitialized
`/etc/machine-id`; each instance boots a fresh overlay of the pinned image. Whether the
pinned image ships it empty is **UNKNOWN** until F-03.2.2 compares two instances.
The host learns the regenerated host-key fingerprints from cloud-init's
`BEGIN SSH HOST KEY FINGERPRINTS` block on the guest serial console (a log file in the
instance directory), and writes them to a per-instance `known_hosts` in the state
directory, never to `~/.ssh`.

## Delivery

- **`strong-windows-qemu-whpx`:** a NoCloud seed image attached as a read-only
  virtio disk (`serial=cidata`). No host filesystem share (`profiles P4`). The image is
  generated per instance, and its sha256 is written to the launch record.
- **`strong-incus-vm`:** Incus generates the seed itself from the
  `cloud-init.user-data` and `cloud-init.network-config` instance keys and attaches it
  as the `cloud-init:config` ISO device (Incus `devices_disk` documentation). Incus
  computes that ISO, so its digest is observed, not pinned; the template digests are
  pinned.

## Generator specification (implementation: F-03.2.2)

Not implemented in F-03.2.1: a reviewed ISO 9660 writer with tests is larger than this
leaf allows. F-03.2.1b's paused boot uses the placeholder in
[`../strong-windows-qemu-whpx/PREREQUISITES.md`](../strong-windows-qemu-whpx/PREREQUISITES.md);
a paused boot (`-S`) runs no guest code, so the seed's content is not read.

The generator must:
1. Be stdlib-only Python, run with `python -I`, need no host install, and write only
   inside the instance directory.
2. Read the three templates, check each against the sha256 pinned in the profile, and
   refuse on a mismatch.
3. Substitute exactly the placeholders listed above. A remaining `{{` or an unknown
   placeholder is an error. The public key must be one OpenSSH `ssh-ed25519` line.
4. Write `seed.iso`: ISO 9660 (ECMA-119) with a Joliet supplementary volume
   descriptor, as `cloud-localds` produces with `genisoimage -volid cidata -joliet`:
   - primary volume identifier `CIDATA`, Joliet volume identifier `cidata`;
   - three files in the root directory, Joliet names `user-data`, `meta-data` and
     `network-config`, LF line endings, UTF-8;
   - 2048-byte logical blocks, no Rock Ridge, no El Torito;
   - **deterministic**: every date field zeroed or set to the fixed value
     `1970-01-01T00:00:00Z`, fixed file order, no volume-set or application text that
     varies. The same inputs must give the same bytes.
5. Print the sha256 of `seed.iso` for the launch record.

Its tests must show: determinism (two runs, same digest); a different key gives a
different digest; refusal on a tampered template; and a round-trip read of the volume
descriptors and Joliet directory with a stdlib reader. Whether the Debian guest's
cloud-init accepts the volume is observed in F-03.2.2 (UNKNOWN until then).
