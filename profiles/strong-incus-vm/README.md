# strong-incus-vm

Plan leaf F-03.2.1. The Linux and remote profile of the `strong` tier: one Incus
profile for the local server and for a named remote (contract sections 6 and 8).
The contract and the provider matrix name this profile `strong-incus-vm`.

| File | Holds |
|---|---|
| [`profile.json`](profile.json) | The harness declaration: labels, pins, ceilings, network, identity and lifecycle bindings. |
| [`incus-profile.yaml`](incus-profile.yaml) | The Incus profile itself (limits, nesting mask, root disk, NIC, seed and agent CD-ROMs), in YAML's JSON-compatible flow style so the standard-library checker reads it. |
| [`image-metadata.yaml`](image-metadata.yaml) | `metadata.yaml` for importing the pinned Debian image as an Incus split image. |
| [`vendor-data.yaml`](vendor-data.yaml) | Incus-only cloud-init vendor data that installs the Incus agent from the `agent:config` CD-ROM. |

**Status: provider validation UNKNOWN.** No Incus server, local or remote, is
available. The schema check passes with four inputs declared `unknown` (it reports
them as UNRESOLVED, and `--strict` fails on them):
- the `incus` client binary digest (pinned by version: Incus 7.0.2 LTS);
- the provider binary digest (the same pin);
- the Incus image fingerprint, which the server computes at import;
- the UEFI firmware, which the server's packaging supplies.

Each is recorded at `preflight` once a server exists, and from then on is required.
Not operational until F-03.3.1, F-03.3.2, F-03.4 and S-02.x pass (C6).

## Pins

- **Image:** the same Debian 13 genericcloud qcow2 as `strong-windows-qemu-whpx`, by
  URL, sha512 and sha256, imported with the committed `image-metadata.yaml` (pinned
  by sha256) and launched by its fingerprint, never by alias.
- **Seed:** the shared templates in [`../seed/`](../seed/README.md) plus
  `vendor-data.yaml`, all pinned by sha256. Incus builds the `cloud-init:config` ISO
  from the instance keys, so that ISO's digest is observed, not pinned.
- **Provider:** Incus 7.0.2 (7.0 LTS, supported until June 2031). `preflight` refuses
  any other server version and checks the floors (kernel 6.12 or later, QEMU 8.2 or
  later).
- **Ceilings:** as the Windows profile: `limits.cpu` 8, `limits.memory` 16GiB, root
  disk 40GiB, scratch block volume 120GiB per instance.
- **Virtualization extensions:** `security.nesting=false` turns off the vmx and svm
  flags on a VM (Incus instance options).

## Validation (when a server exists)

Contract section 10: the server accepts the profile and `incus config show --expanded`
round-trips it.

```sh
incus project create aieh
incus profile create strong-incus-vm --project aieh
incus profile edit strong-incus-vm --project aieh < profiles/strong-incus-vm/incus-profile.yaml
incus profile show strong-incus-vm --project aieh
```

then an instance created with `incus init` (not started), and
`incus config show <instance> --expanded --project aieh` compared with the declared
config and devices. Expected outcome: UNKNOWN.

## Findings for the Overseer

- **Disk devices beyond root and scratch.** The contract allows only root and scratch
  disk devices for Incus (sections 6 and 7, `profiles P4`). A Debian cloud image needs
  the `cloud-init:config` CD-ROM for its seed, and the Incus agent needs `agent:config`
  or Incus's default 9p share named `config`. Incus documents that it "provides the
  agent primarily through a remote 9p file system with mount name config". This
  profile declares both CD-ROMs (generated, read-only, not host paths), and the 9p
  share as `provider_implicit_shares` with status UNKNOWN. The contract text is
  unchanged.
- **The bridge, its ACLs and IPv6 off** are network-level objects outside this profile
  (`aieh-br0`); F-03.3.2 qualifies them.
