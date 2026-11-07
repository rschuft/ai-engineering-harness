# Guest seed: cloud-init NoCloud

Plan leaf F-03.2.1. These templates are boot inputs (`profiles P9`) of both strong
profiles, pinned by sha256 in each `profile.json`. They carry only the per-instance
public key and non-secret configuration (`profiles P5`).

| File | Content | Substituted at `create` |
|---|---|---|
| [`user-data.tmpl`](user-data.tmpl) | user `agent` (no password, no sudo group, no `sudo:` rule), `disable_root`, sshd drop-in with `PermitRootLogin no`, host keys deleted and regenerated (`ssh_deletekeys`), scratch disk formatted and mounted at `/srv/scratch`, exchange directory `/home/agent/exchange`; the provisioning files of F-04.1 (below), inert in an ordinary guest | `{{agent_ssh_public_key}}`; `{{scratch_device}}` from the profile; `{{provision_manifest}}` (base64; empty unless `create --provision`) |
| [`meta-data.tmpl`](meta-data.tmpl) | NoCloud `instance-id` and `local-hostname` | `{{instance_id}}` (instance name plus a fresh UUID at each `create`), `{{instance_name}}` |
| [`network-config.yaml`](network-config.yaml) | network config v2: DHCPv4 on the single NIC; DHCPv6, router advertisements and IPv6 link-local addresses off (`profiles P7`: IPv6 off unless listed) | nothing |

**Identity (`profiles P8`).** Host keys: `ssh_deletekeys: true` with
`ssh_genkeytypes: [ed25519]` regenerates them on first boot. machine-id: the guest's
systemd generates it on first boot when the image ships an empty or uninitialized
`/etc/machine-id`; each instance boots a fresh overlay of the pinned image. **Observed
in F-03.2.2b** on two instances of the QEMU profile: systemd logged
`Initializing machine ID from random generator.` on first boot, and the two
machine-ids differed
([evidence](../../evidence/F-03.2.2b-guest-lifecycle.md)).
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

## Generator specification (implemented: F-03.2.2a)

**Implemented** in [`tools/nocloud_seed.py`](../../tools/nocloud_seed.py), tested by
[`tools/tests/test_nocloud_seed.py`](../../tools/tests/test_nocloud_seed.py)
(F-03.2.2a, [evidence](../../evidence/F-03.2.2a-seed-and-monitor.md)). F-03.2.1b's
paused boot used a zero-filled placeholder; F-03.2.2a's paused boot used a generated
`seed.iso` ([`PREREQUISITES.md`](../strong-windows-qemu-whpx/PREREQUISITES.md),
step 4). A paused boot (`-S`) runs no guest code, so the seed's content is not read.

```
python -I -B tools/nocloud_seed.py --profile profiles/strong-windows-qemu-whpx \
    --instance-dir <state_dir>/instances/<name> --instance-name <name> \
    --public-key <state_dir>/instances/<name>/ssh/id_ed25519.pub [--instance-id <name>-<uuid>]
```

It prints one JSON object: `sha256` of `seed.iso` (for the launch record), `size_bytes`,
`instance_id` (generated as the name plus a random UUID when not given), and the
sha256 of each template and rendered file. A refused input prints `REFUSED: <reason>`
on stderr, exits 1 and writes nothing; an existing `seed.iso` is never overwritten.
Implementation choices within the specification: the primary (ISO 9660 level 1) names
are `META_DAT.;1`, `NETWORK_.;1` and `USER_DAT.;1`, as `genisoimage` derives them; the
Joliet names carry no `;1` version; the creation and modification dates are
1970-01-01T00:00:00Z and the expiration and effective dates are "not specified"; the
image is not padded beyond its last file block. The public key is one
`ssh-ed25519 <base64> [comment]` line whose blob decodes to the type string and a
32-byte key, with at most one comment token of `[A-Za-z0-9._@+=-]` (no options).

The generator must:
1. Be stdlib-only Python, run with `python -I`, need no host install, and write only
   inside the instance directory.
2. Read the three templates, check each against the sha256 pinned in the profile, and
   refuse on a mismatch.
3. Substitute exactly the placeholders listed above (three in user-data since F-04.1b). A remaining `{{` or an unknown
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
descriptors and Joliet directory with a stdlib reader. `tools/tests/test_nocloud_seed.py`
shows each, plus refusal of an unknown, missing or leftover placeholder and of malformed
public keys, and a pinned digest for a fixed input. **Observed in F-03.2.2b:** the
Debian guest's cloud-init 25.1.4 accepted the volume on two instances
(`DataSourceNoCloud [seed=/dev/vdc]`, `status: done`, no errors), applied the
instance id and hostname from meta-data, and applied the user, sshd drop-in, scratch
file system and directories from user-data.

## Provisioning files (F-04.1 slice (b), decision 0006)

The user-data template also writes the single-use root provisioning step. Every guest
gets the files; only a guest made with `tools/guest.py create --provision` gets a
manifest, and without one nothing runs:

| Path | Content |
|---|---|
| `/etc/aieh/provision.json` (root, `0600`) | the manifest: `{{provision_manifest}}`, base64 of one JSON object of schema `ai-engineering-harness/profiles/provision-manifest/v1` (each file to upload with role, size and sha256; the packages; the image's locked config digest, the archive's tags and the local immutable tag; the declared `daemon.json`). Empty in an ordinary guest. |
| `/usr/local/sbin/aieh-provision` (root, `0755`) | the root step (Python 3, standard library): `provision` copies the upload into `/var/lib/aieh/provision-staging` (root `0700`), verifies every sha256 against the manifest, writes `/etc/docker/daemon.json`, installs the `.deb` files with `apt-get install --no-install-recommends ./…` (no `apt-get update`, no network), `docker load`s the image, checks its ID, keeps only the local tag, runs it once (`--entrypoint true`), enables the facts unit, deletes the staging directory and the upload, disables the trigger, and writes `/var/lib/aieh/provision/RESULT.json` last; `facts` writes the boot-time report `/run/aieh/docker-facts.json` |
| `/etc/systemd/system/aieh-provision.path` | `PathExists=/srv/scratch/agent/provision/READY`, single use |
| `/etc/systemd/system/aieh-provision.service` | oneshot, output to the journal and the console |
| `/etc/systemd/system/aieh-docker-facts.service` | oneshot at every boot after `docker.service`; enabled only by a successful root step |

**Ordinary guests are unaffected.** The manifest is empty, both provisioning units carry
`ConditionFileNotEmpty=/etc/aieh/provision.json`, and `runcmd` enables the trigger only
when the manifest is not empty (`[ -s … ]`), so no unit watches the upload path and no
root code can be triggered from the guest. The root step also refuses to run twice
(`ConditionPathExists=!…/RESULT.json`, and it checks for the result and the staging
directory itself). The generator's refusals apply to the manifest too: it must be one
ASCII JSON object of the manifest schema, without CR, at most 64 KiB.

The user-data template's header comment no longer names the placeholders as
`{{…}}`: literal substitution used to copy the public key and the device path into
that comment (F-03.2.2a defect, repaired in F-03.2.2b; the template is re-pinned in
both profiles).
