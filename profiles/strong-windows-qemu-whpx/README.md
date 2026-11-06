# strong-windows-qemu-whpx

Plan leaf F-03.2.1. The Windows reference profile of the `strong` tier, selected by the
Owner (decision 0003, W1). Files:

| File | Holds |
|---|---|
| [`profile.json`](profile.json) | The declaration: labels, pins, ceilings, network, identity, lifecycle bindings and the QEMU command line. |
| [`qemu-msys2-ucrt64.lock.json`](qemu-msys2-ucrt64.lock.json) | The QEMU artifact pin: 159 MSYS2 packages with sha256, their signing key, how the closure was resolved, and the extraction and link policy. |
| [`PREREQUISITES.md`](PREREQUISITES.md) | Owner acts A1, A2, A3 and the F-03.2.1b validation commands. |
| [`../seed/`](../seed/README.md) | Seed templates shared with `strong-incus-vm`, and the seed generator specification. |

**Status.** Declared and pinned; `tools/check_profile.py --strict` passes. Provider
validation **passed** on 2026-11-06 (F-03.2.1b, after A1 to A3):
[`evidence/F-03.2.1b-provider-validation.md`](../../evidence/F-03.2.1b-provider-validation.md).
Not operational until F-03.3.1, F-03.3.2, F-03.4 and S-02.x pass (C6).

## Open items for F-03.2.2

1. **`-mon` is deprecated in QEMU 11.1.3.** The paused boot warned: `'-mon' is
   deprecated, use '-object' with 'monitor-hmp' or 'monitor-qmp' types instead`.
   F-03.2.2 moves `launch.argv` to the non-deprecated QMP monitor form and re-runs the
   paused-boot validation (PREREQUISITES.md, F-03.2.1b step 4) with the changed argv in
   the same run. The argv is unchanged until then, so the recorded validation still
   applies to it (Overseer decision, 2026-11-06).
2. **`warning: Ignoring request for interrupt vector 0`.** Printed once during the
   paused boot, before any guest code ran. Observe on a real boot whether it recurs.

## Choices

**Guest image: Debian 13 genericcloud amd64, build 20261103-2651.** A maintained
stable release with systemd and cgroups v2 by default, cloud-init 25.1.4 and kernel
6.12.115 (from the build's package manifest), and Moby supports it. `genericcloud`
carries a reduced driver set aimed at virtual machines; virtio is all this profile
uses. The same file is pinned by `strong-incus-vm`. Pinned by URL, by the sha512 from
Debian's `SHA512SUMS`, and by the sha256 of the file downloaded and checked here.
**Debian publishes no signature for current cloud images**: its download page says
the safest method is TLS from `cloud.debian.org` or `cdimage.debian.org`, and only the
legacy OpenStack images carry `SHA512SUMS.sign`. So provenance rests on TLS. As a
cross-check, `SHA512SUMS` was fetched from both hosts (identical), and the build's
JSON manifest carries the same sha512. Debian prunes older builds from that directory
(the oldest kept today is 20261001), so the URL will stop resolving; the state
directory keeps the verified copy, and a re-pin is a profile change.

**Firmware: SeaBIOS** (`bios-256k.bin` from the pinned QEMU package). The image boots
by BIOS or UEFI (it ships `grub-pc-bin` and `grub-efi-amd64`). BIOS avoids a
per-instance writable UEFI variable store. The firmware is pinned by its own sha256
and by the package digest; every other data file QEMU loads comes from that package,
and the virtio-net option ROM is turned off.

**Seed: a NoCloud volume on a read-only virtio disk.** No host filesystem share of any
kind (contract section 6). The templates are pinned; the per-instance volume is
deterministic, so its digest is recorded at `create`. The generator is specified in
[`../seed/README.md`](../seed/README.md) and built in F-03.2.2.

**Ceilings: 8 vCPU, 16 GiB memory, 40 GiB root disk, 120 GiB scratch disk.** The host
has 32 logical CPUs, 62 GB of RAM and about 750 GB free on D:. One guest leaves 24 CPUs
and about 46 GB to Windows and the Owner's WSL VM. The disks are thin qcow2, so one
instance can grow to 160 GiB at most. Two instances at full memory beside a fully used
WSL VM would overcommit RAM, so the reference mode is one `shared` instance. Whether
Windows charges the full 16 GiB to the commit limit at launch is UNKNOWN until
F-03.2.2.

**Network: SLIRP user networking with `restrict=on` and `ipv6=off`.** Inbound only by
`hostfwd` bound to `127.0.0.1` (management SSH, also used for exchange). QMP listens
on `127.0.0.1` and is not reachable from the guest. `inference` and `provision`
endpoints are declared as classes with `guestfwd` to `127.0.0.1` as the mechanism, and
their addresses are left to F-03.3.2. Until then the guest has no outbound path at
all. Loopback ports can be reached by any local process; that is disclosed. Python's
standard library has no `AF_UNIX` on Windows, which rules out a socket file for QMP.

**Accelerator: `-accel whpx`, exactly once, with no fallback.** QEMU uses TCG when no
accelerator is named, and tries a second accelerator if the first fails, so the
command line names exactly one and `-machine` names none. A missing WHPX is a launch
failure, reported as `TIER_UNAVAILABLE` naming A1.

**Virtualization extensions (`profiles P12`): masked.** `-cpu max,vmx=off,svm=off`
and `nested_virt_exposed: false`. F-03.2.1b's paused boot observed this at the
configuration level: WHPX accepted `max` with these flags off, QOM `vmx` and `svm` are
false on every vCPU, and `filtered-features` is all zero. The guest-visible CPUID is
unobserved until F-03.2.2's guest-side check.

**Other boot settings.** `-nodefaults` and `-no-user-config`; machine `pc-q35-11.1`
(the versioned type, so the hardware is reproducible); `-display none`; no USB, audio,
VGA, HMP monitor, virtio-serial or guest agent; serial console to a file in the
instance directory; virtio-rng for first-boot key generation. The root overlay's
backing node is bound explicitly to the pinned image, so the overlay header's backing
path is never trusted.

## QEMU for Windows: channels compared (2026-11-06)

| | MSYS2 `mingw-w64-ucrt-x86_64-qemu` | qemu.weilnetz.de installer | Scoop `main/qemu` | winget `SoftwareFreedomConservancy.QEMU` |
|---|---|---|---|---|
| Current release | **11.1.3-1** (QEMU's current stable is 11.1.3, download.qemu.org) | 11.1.0 (`qemu-w64-setup-20260811.exe`); "I typically only build installers based on the master branch, but not for bugfix releases" | 11.1.0: wraps the weilnetz installer | 11.1.0: wraps the weilnetz installer |
| Checksum or signature | Signed repository database and a detached OpenPGP signature per package, by an MSYS2 developer key certified by three master keys. **Verified**: database signature good; 160/160 packages of the first closure match the database sha256 and carry a valid signature; the 159 locked after the re-resolution (F-03.2.1 correction: `sqlite3` is replaced by `sqlite`) are among them. | `.sha512` beside the installer, served over HTTPS, unsigned. **Verified**: sha512 `5bcf9eed…16bf543` matches. Authenticode: the signing certificate (Universität Mannheim, GEANT Code Signing CA 4) expired 2023-12-09; `Get-AuthenticodeSignature` reports `UnknownError` ("not within its validity period"), so the signature does not verify. | sha512 in the manifest, equal to the weilnetz one | sha256 in the manifest, equal to the sha256 of the downloaded installer (`f98a8aeb…e59f`) |
| Administrator rights | **No** | **Yes**: QEMU's `qemu.nsi` sets `RequestExecutionLevel admin`, installs to `$PROGRAMFILES64\qemu` and writes HKLM | No, but Scoop and its 7-Zip must be installed first | Yes: `Scope: machine`, `InstallerType: nullsoft` |
| User-scoped or extract-only | **Yes**: plain `.pkg.tar.zst` archives, extracted by Windows' built-in `tar.exe` (bsdtar 3.8.9 with zstd); no MSYS2 or pacman install needed | Only by extracting the NSIS installer with 7-Zip, which is not on this host | Yes (7-Zip extraction into the user's Scoop directory) | No |
| WHPX in the build | **Yes**: the package's `msys2.readme.txt` documents `-accel whpx`; the pinned binary contains the WHPX accelerator's messages, including `WHPX: No accelerator found` | Yes, documented as experimental in the weilnetz FAQ ("enabled with `--accel whpx`") | as weilnetz | as weilnetz |
| Licence | QEMU: GPL-2.0 (its `LICENSE`); package metadata `GPL-2.0-or-later AND LGPL-2.1-or-later AND BSD-2-Clause AND BSD-3-Clause AND MIT`; dependencies under their own licences, listed per package in the lock | GPL-2.0 | GPL-2.0-only (manifest) | as weilnetz (same installer) |

**Recommended: MSYS2 ucrt64, QEMU 11.1.3-1**, installed into the A3 directory by
`tools/msys2_lock.py` (the built-in `tar.exe` decodes the archives, the tool writes
the files). It is the only channel that is current, cryptographically signed end to
end, and installable without administrator rights or any new tool. Its cost is size:
159 packages (about 267 MB compressed), because QEMU links its GTK, SDL, SPICE and
GStreamer front ends even when `-display none` is used. No link is created on disk.
The `iso-codes` package is checked but not extracted: its 470 entries are symbolic
links, which the link policy refuses, and it holds data only. The hardlinks in
`libdeflate`, `tcl`, `tk` and `tzdata` (1,562) are written as copies of their
in-package targets. pacman's post-install hooks (GTK, GIO, fontconfig and gdk-pixbuf
caches) do not run; a `-display none` guest does not use them.
