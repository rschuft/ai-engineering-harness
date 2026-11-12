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
| `/etc/aieh/provision.json` (root, `0600`) | the manifest: `{{provision_manifest}}`, base64 of one JSON object of schema `ai-engineering-harness/profiles/provision-manifest/v1` (each file to upload with role, size and sha256; the packages; the image's locked config digest, the archive's tags and the local immutable tag; the declared `daemon.json`; the Agent Server's binary name and sha256, its non-secret config, its scratch directories and its listener). No secret. Empty in an ordinary guest. |
| `/usr/local/sbin/aieh-provision` (root, `0755`) | the root step (Python 3, standard library): `provision` copies the upload into `/var/lib/aieh/provision-staging` (root `0700`), verifies every sha256 against the manifest, writes `/etc/docker/daemon.json` and `/etc/sysctl.d/90-aieh-moby.conf` (no IPv6 on `docker0` and `veth*`), installs the `.deb` files with `apt-get install --no-install-recommends ./…` (no `apt-get update`, no network), replaces containerd's packaged `config.toml` (CRI plugin off; only when it is still the packaged file) and restarts containerd and the daemon, `docker load`s the image, checks its ID, keeps only the local tag, runs it once (`--entrypoint true`), installs the Agent Server (system user `openhands`, no login, group `docker`; its directories under `/srv/scratch/openhands`; the release binary at `/opt/aieh/agent-server/agent-server`, hashed again; `/etc/aieh/agent-server/config.json`), generates `OH_SECRET_KEY` and the session API key into `/etc/aieh/agent-server/secrets.env` (root `0600`) and the session key into `/var/lib/aieh/agent-server/session.key` (`root:agent` `0440`), starts the service and checks its only listener, enables the facts unit, deletes the staging directory and the upload, disables the trigger, and writes `/var/lib/aieh/provision/RESULT.json` last; `facts` writes the boot-time report `/run/aieh/docker-facts.json`, with the Agent Server's facts, its secret fingerprints and its start-up log, every secret value counted and redacted |
| `/etc/systemd/system/aieh-provision.path` | `PathExists=/srv/scratch/agent/provision/READY`, single use |
| `/etc/systemd/system/aieh-provision.service` | oneshot, output to the journal and the console |
| `/etc/systemd/system/aieh-docker-facts.service` | oneshot at every boot after `docker.service` and `aieh-agent-server.service`; enabled only by a successful root step |
| `/etc/systemd/system/aieh-agent-server.service` | the Agent Server as `openhands`: `--host 127.0.0.1 --port 8000`, `EnvironmentFile=` the root-only secrets file, `OPENHANDS_AGENT_SERVER_CONFIG_PATH`, data on scratch, hardened (`provisioning.agent_server.service.hardening` in the profile); conditional on the installed binary; enabled only by a successful root step |
| `/usr/local/sbin/aieh-agent-server-ready` (root, `0755`) | the unit's `ExecStartPost` (argv `127.0.0.1 8000 280 30 ${MAINPID}`: listener, ceiling, slow threshold, main PID): polls `GET /ready` on the loopback listener every 0.5 s until 200, under the 280 s ceiling; sends no credential. It stops at once when the main process has exited (gone, a zombie, or another process). One outcome line per start: `ready start=<class> seconds=<s> restarts=<n>`, `<class>` `clean` only when ready within 30 s and the unit's `NRestarts` is 0, else the comma-joined `retried`, `slow`, `unverified`; or `not ready start=main-exited` or `start=timeout` (exit 1). E-01.4.3 (`provisioning.agent_server.service.readiness`) |

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

## The opt-in inference composition (S-03.2 slice 2, decision 0015)

A guest created with `tools/guest.py create --provision --inference` (and the generator's
`--inference` option, which needs a provisioning manifest) gets the guest composition of
the inference endpoint; no other guest does. **Planned, not verified in a guest:**
applying it is the Owner's guest hardening act. The composition is the pinned overlay
[`inference-overlay.json`](inference-overlay.json) (`network.inference_composition.seed_overlay`
in the QEMU profile): an ordered list of exact edits to the user-data template, each an
anchor of whole lines that must occur exactly once at the time it applies and its
replacement, in which `{{inference_address}}` and `{{inference_port}}` are filled from the
profile's inference endpoint before the template's own placeholders are substituted. It
changes three seeded files only:

| Path | Change |
|---|---|
| `/etc/ssh/sshd_config.d/10-aieh.conf` | `AllowTcpForwarding no` becomes `AllowTcpForwarding remote`, `GatewayPorts clientspecified` and `PermitListen 172.17.0.1:8090`; local forwarding stays refused |
| `/usr/local/sbin/aieh-container-guard` | one ACCEPT after the container guard's RETURN, IPv4 only, for new TCP from `docker0` to `172.17.0.1:8090`; installed and verified per family; the egress guard's allowlist stays empty, and its header comment says so (the template's own comment, which still names an inference allowlist entry, is left as it is so that the default bytes do not change) |
| `/usr/local/sbin/aieh-provision` | the boot facts gain an `inference` section: `sshd -T`'s forwarding directives |

The composition's `daemon.json` keys (`bip`, `dns`) travel in the provisioning manifest.
Without the option nothing is read from the overlay and every file of the seed is
byte-identical to an ordinary provisioned guest's; the template and its pin are unchanged.

## The CI guest seed (Q-02.2.1)

[`ci/user-data.tmpl`](ci/user-data.tmpl) is the user-data template of the CI profile variant
[`strong-windows-qemu-whpx-ci`](../strong-windows-qemu-whpx-ci/README.md) (decision 0016
section 2), pinned by that profile with the shared `meta-data.tmpl` and `network-config.yaml`.
It has the same three placeholders and the same generator, and it follows the pattern above:
the user `agent`, the scratch disk, the inert-without-a-manifest provisioning files, and the
container and egress guards with their units, byte for byte. It differs in:

| Path | Content |
|---|---|
| `/etc/ssh/sshd_config.d/10-aieh.conf` | `AllowTcpForwarding remote`, `GatewayPorts clientspecified` and `PermitListen 127.0.0.1:13300`: the one listener of the `ci-control` remote forward, which the dispatcher holds (an Owner act, A-1); local forwarding stays refused |
| `/usr/local/sbin/aieh-provision` | the CI root step: the execution seed's functions for the upload, Moby, the guards and the image, verbatim (a test compares them), then `ci-runner-install` (the system user `aieh-ci-runner` in group `docker`, the release binary hashed again, its state and work directories; the seeded `config.yaml` checked against the manifest; the unit left disabled) and `wheels` (the hash-locked wheel set copied, hashed again, into the root-owned directory jobs mount read-only). Modes `provision` and `facts` only; no secret is generated, read or written |
| `/etc/systemd/system/aieh-docker-facts.service` | after `docker.service` only; the report holds the guards and the runner, the runner file by its metadata |
| `/etc/aieh/ci-runner/config.yaml` | the runner's declared configuration (`provisioning.ci_runner.config`), as `json.dumps(config, indent=2)` |
| `/etc/systemd/system/aieh-ci-runner.service` | the runner as `aieh-ci-runner`, hardened, the loopback only; conditional on the runner file that registration writes (Q-02.2.2) |
| runcmd | the exchange directory is `0755`, so that a job's non-root user reads the staged bundle through its read-only mount |

There is no Agent Server, no conversation-facts or egress-route unit, and no registration token
anywhere in the seed. **Not verified in a guest**: no CI guest has been created (the CI
bindings of `tools/guest.py` are a later slice).
