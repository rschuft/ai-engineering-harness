# strong-windows-qemu-whpx

Plan leaf F-03.2.1. The Windows reference profile of the `strong` tier, selected by the
Owner (decision 0003, W1). Files:

| File | Holds |
|---|---|
| [`profile.json`](profile.json) | The declaration: labels, pins, ceilings, network, identity, lifecycle bindings and the QEMU command line. |
| [`qemu-msys2-ucrt64.lock.json`](qemu-msys2-ucrt64.lock.json) | The QEMU artifact pin: 159 MSYS2 packages with sha256, their signing key, how the closure was resolved, and the extraction and link policy. |
| [`PREREQUISITES.md`](PREREQUISITES.md) | Owner acts A1, A2, A3 and the F-03.2.1b validation commands. |
| [`validation/netprobe/netprobe.py`](validation/netprobe/netprobe.py) | **Test only.** The guest-root network probe of `tools/guest.py netprobe` (F-03.3.2), pinned by sha256. Ordinary operation never reads it. |
| [`QUALIFICATION.md`](QUALIFICATION.md) | The provider-profile qualification record (F-03.4): P1 to P12 with verdict, leaf and evidence; the host it was qualified on; limitations; platform adaptation points. |
| [`../seed/`](../seed/README.md) | Seed templates shared with `strong-incus-vm`, and the seed generator specification. |

**Status.** Declared and pinned; `tools/check_profile.py --strict` passes. Provider
validation **passed** on 2026-11-06 (F-03.2.1b, after A1 to A3):
[`evidence/F-03.2.1b-provider-validation.md`](../../evidence/F-03.2.1b-provider-validation.md).
Lifecycle: [`tools/guest.py`](../../tools/guest.py) and the `guest:*` Task targets
(F-03.2.2). Two disposable guests were booted, inspected and destroyed on 2026-11-06:
[`evidence/F-03.2.2b-guest-lifecycle.md`](../../evidence/F-03.2.2b-guest-lifecycle.md).
F-03.3.1 declared the guest's volume and mount table (`guest_storage`) and the exchange
bounds (`exchange`), and added `exchange-push`, `exchange-pull` and the startup test
`check-surfaces`. On 2026-11-06 two fresh guests passed profiles P3, P4, P5 and P6:
[`evidence/F-03.3.1-guest-surfaces.md`](../../evidence/F-03.3.1-guest-surfaces.md).
F-03.3.2 qualified the network enforcement point (SLIRP `restrict=on`, `ipv6=off`,
guest-to-host only through `guestfwd` to 127.0.0.1): with routes installed by guest
root, every probed path was denied, also from a namespace behind guest NAT, while one
test `guestfwd` carried a nonce exchange:
[`evidence/F-03.3.2-guest-network.md`](../../evidence/F-03.3.2-guest-network.md).
F-03.4 proved P10: `tools/guest.py smoke` (create, inspect, stop, start, inspect,
forced stop, recreate, inspect, destroy) passed end to end twice, once beside a running
sibling instance and once beside a stopped one. No durable source changed, and recreate
reproduced the observed state except identity:
[`evidence/F-03.4-teardown-qualification.md`](../../evidence/F-03.4-teardown-qualification.md);
qualification record: [`QUALIFICATION.md`](QUALIFICATION.md).
Not operational until S-02.x also passes (C6).

## Open items for F-03.2.2

1. **`-mon` is deprecated in QEMU 11.1.3. Resolved in F-03.2.2a.** The paused boot
   warned: `'-mon' is deprecated, use '-object' with 'monitor-hmp' or 'monitor-qmp'
   types instead`. `launch.argv` now creates the QMP monitor with
   `-object monitor-qmp,id=qmp-monitor,chardev=qmp`, the form the pinned binary
   documents (`-object monitor-qmp,help`; `deprecated.html`: "`-mon mode=control` is
   replaced by `-object monitor-qmp`"). The paused-boot validation (PREREQUISITES.md,
   F-03.2.1b step 4) was re-run with the changed argv and a generated seed: no
   deprecation warning, QMP answered on the new monitor
   ([evidence](../../evidence/F-03.2.2a-seed-and-monitor.md)).
2. **`warning: Ignoring request for interrupt vector 0`. Observed in F-03.2.2b:
   harmless so far.** Printed once during the paused boot, before any guest code ran,
   and again in F-03.2.2a's paused boot. On the two real boots of F-03.2.2b it was
   printed once per launch, in the same second as the QEMU start, and never again
   while the guests ran. Both guests booted, ran and shut down normally
   ([evidence](../../evidence/F-03.2.2b-guest-lifecycle.md)).

## Open items after F-03.2.2b

The tier stays not operational (C6). The
[F-03.2.2b evidence](../../evidence/F-03.2.2b-guest-lifecycle.md) has the detail.

3. **Provider compatibility limitation: XSAVE under WHPX with `-cpu max`.** Recorded
   only. `-cpu` and `launch.argv` are unchanged (Overseer decision, 2026-11-06;
   decision 0003, "Current facts").
   - **Observed** on this host (AMD, XSAVES present) with QEMU 11.1.3 WHPX,
     `-cpu max,vmx=off,svm=off` and the Debian 13 kernel 6.12.115:
     - every boot logs `x86/fpu: misordered xstate at 1408`, then
       `WARNING: … at arch/x86/kernel/fpu/xstate.c:254 fpu__init_system_xstate` with a
       call trace;
     - this is the kernel's one-time warning that the XSAVE component offsets reported
       in CPUID leaf 0xD are not ascending;
     - no `XSAVE consistency problem` was logged. XSAVE stayed enabled (x87, SSE, AVX,
       AVX-512 opmask, Hi256 and ZMM_Hi256, CET user), and the guest ran normally in
       both F-03.2.2b cycles.
   - **Upstream, related but distinct.** The qemu-devel patch
     "[PATCH v2 12/18] whpx: i386: forward the dynamic EBX of CPUID[0xD] sub-leaves 0 and
     1, not 1 and 2" (2026-10-27,
     <https://www.mail-archive.com/qemu-devel@nongnu.org/msg1238937.html>) reports:
     - on hosts **without** XSAVES (reproduced on Intel Haswell, Windows 11 build 26300,
       QEMU 11.1.2, "unchanged on master"), XSAVE-capable CPU models, including `max`,
       give `XSAVE consistency problem: size 832 != kernel_size 576` at `xstate.c:638`,
       XSAVE disabled, and a kernel panic;
     - an AMD host with XSAVES was unaffected.

     Our symptom differs (another line, another message, no consistency failure), so
     the warning is **not** attributed to that defect (inference). The pinned 11.1.3 is
     presumed to carry that defect: the patch postdates 11.1.2 and says the code is
     unchanged on master. We have not verified the 11.1.3 source, so this is
     **UNKNOWN**.
   - **Impact:**
     - **Isolation properties P1 to P12:** none identified.
     - **Portability:** on Windows hosts without XSAVES, this profile with `-cpu max` is
       expected to panic at boot. **Detected since F-03.4:** `preflight`'s `host-xsaves`
       check asks the hypervisor platform (`WHvGetCapability`,
       `WHvCapabilityCodeProcessorXsaveFeatures`, bit `XsaveSupervisorSupport`;
       read-only, nothing installed) and reports such a host `unavailable`, so `create`
       refuses with `TIER_UNAVAILABLE`. If the query itself fails, the check is
       `unknown`, disclosed and not refused. On this host the mask was `0x41ffffdf`
       (XSAVES present). Its 24 named bits matched the guest's `/proc/cpuinfo` flags
       exactly, which corroborates the bit layout used.
     - **Detector (F-03.4):** `inspect` reads the guest kernel's messages from
       `serial.log` on the host side (the guest's `dmesg_restrict=1` hides `dmesg` from
       `agent`). It reports `XSAVE consistency problem` or `XSAVE disabled` as FAIL
       (the operation exits 1, and `smoke` fails) and `x86/fpu: misordered xstate` as a
       labelled LIMITATION. All 10 F-03.4 inspects showed `misordered-xstate` only, with
       XSAVE enabled in the compacted format.
     - **Runtime correctness:** the misordered-offset warning means the kernel's layout
       assumption is violated on this host. Extended-register state correctness
       (AVX-512) under signal delivery and context switches is unqualified.
   - **Obligations carried:**
     - The Windows packaging leaves (R-03.x) qualify the CPU model choice (`max` or a
       named model) with evidence. F-03.4 added the preflight XSAVES check and the
       detector, and recorded `max` as qualified on this AMD host only, with the
       misordered-offset limitation ([`QUALIFICATION.md`](QUALIFICATION.md)).
     - Re-evaluate when a QEMU containing the upstream fix is pinned.
     - No unreviewed upstream patch is applied.
4. **Egress: off-link destinations never left the guest. Resolved in F-03.3.2.**
   With a default route, resolvers and an IPv6 route installed by guest root, the NIC's
   tx counter rose and SLIRP reset every off-link TCP connection and dropped UDP, ICMP
   and IPv6; see "Network qualification" below.
   SLIRP's DHCP lease (with
   `restrict=on`) carries no router and no DNS server, so the guest has no default
   route. Probes to 1.1.1.1, 8.8.8.8 and the host's LAN address failed in the guest
   with `Network is unreachable`. Only the on-link SLIRP addresses (10.0.2.2, 10.0.2.3)
   exercised `restrict=on`: TCP was refused and UDP DNS got no reply. A guest root
   could add a route, so F-03.3.2 must test the outside-the-guest enforcement for
   off-link destinations with a route in place.
   From the unprivileged `agent` account, egress was observed blocked. The case of a
   guest root with a default route is owned by F-03.3.2, and is required before any
   strong-tier claim.
5. **P6 wording: `/tmp/.X11-unix`. Resolved 2026-11-06 (Overseer decision as contract
   owner).** The contract's P6 inspection asked for that path to be absent. In this
   guest it exists as an empty directory (no socket), created by the guest's own
   `/usr/lib/tmpfiles.d/x11.conf`, and `inspect` reported FAIL. The inspection now asks
   for **no socket under `/tmp/.X11-unix`**: nothing in it but directories, and the
   path not a symlink (`profiles/README.md` P6, decision 0003, "Current facts").
   `tools/guest.py` checks exactly that. **Observed on real guests in F-03.3.1:** the
   probe printed `type=directory` then `end` on both guests, and the P6 check passed
   ([evidence](../../evidence/F-03.3.1-guest-surfaces.md)).
6. **Commit charge.** Whether Windows charges the full 16 GiB to the commit limit at
   launch remains UNKNOWN; it was not measured.

## Open items after F-03.3.1

The [F-03.3.1 evidence](../../evidence/F-03.3.1-guest-surfaces.md) has the detail.
P3 to P6 passed on two fresh guests; P7 (F-03.3.2) and P10 (F-03.4) have since passed;
S-02.x remains (C6).

7. **Exchange staging is inside the instance directory.** Pushed bundles, pulled files
   and their verification repositories live in `<instance>\exchange\`, under the state
   directory and never in an Owner repository, as the binding requires. `destroy`
   removes them with the instance. Where exported evidence should be kept after a
   `fresh`-mode guest is destroyed is not decided.
8. **The P5 scan reads what `agent` can read.** Root-only guest files are not read:
   `/proc/1/environ`, `/etc/shadow`, cloud-init's `user-data.txt` and logs, and the
   journal. The seed they come from is scanned on the host. A guest-root view belongs
   with the guest-root tests of F-03.3.2 and S-02.x.
9. **The P6 socket check is a deny-list.** The guest's own sockets (systemd, dbus, udev,
   uuidd, `/run/ssh-unix-local/socket`, the agent's user `openssh_agent`) are recorded,
   but they are not compared with an exact allowlist. The decisive checks are the
   absence of channel devices and of a guest-to-host vsock transport.
   - `/dev/vsock` exists, and the `vsock`, `vsock_loopback` and
     `vmw_vsock_vmci_transport` modules are loaded.
   - The local CID is 1, so no transport reaches the host.
10. **Pseudo mounts come from one image.** The pseudo-mount entries of `guest_storage`
    were taken from the Debian 13 build pinned here. A re-pinned image or kernel needs
    them re-derived; until then the exact comparison FAILs.
11. **`strong-incus-vm` declares no volume table.** There is no Incus host, so its
    effective mounts cannot be observed. `tools/check_profile.py` requires
    `guest_storage` and `exchange` for QEMU profiles only.

## Network qualification (F-03.3.2)

The [F-03.3.2 evidence](../../evidence/F-03.3.2-guest-network.md) has the detail;
`profile.json` `network` carries the enforcement point, the reachability table and the
IPv6 statement.

12. **The enforcement point is qualified.** `tools/guest.py netprobe` (test only;
    decision 0003, "Owner authorization: network validation") booted a disposable guest
    whose seed adds a pinned root probe and whose `-netdev` adds one
    `guestfwd=tcp:10.0.2.100:7000-tcp:127.0.0.1:<test listener>`, beside a TCP and a
    UDP decoy on 127.0.0.1. 58 denied paths from the guest and 30 from a namespace
    behind guest NAT were denied; both positive controls exchanged a nonce that the
    listener logged from QEMU's chardev only. The ordinary `launch.argv` and seed
    templates are unchanged; an ordinary guest passed `check-surfaces` and its
    unprivileged egress probes.
13. **Containers were approximated.** A network namespace with a veth pair and guest
    MASQUERADE stands in for Docker's default bridge; Docker is not in the image.
    IPv6 was not configured in the namespace. A real container is S-02.x's.
14. **`inference` and `provision` stay deferred.** They will use the qualified
    mechanism, a `guestfwd` to a 127.0.0.1 broker or proxy, but each needs separate
    Owner authorization to enter `launch.argv`; `tools/check_profile.py` FAILs a
    `guestfwd` without an active endpoint. A guestfwd chardev is opened once when QEMU
    starts, so the broker must run before the guest and for its whole life.
15. **Validation instances are marked and single-boot.** `launch.json` records the
    `validation` block and the full effective argv; `launch` refuses an undeclared
    `guestfwd`; `start` refuses a validation instance. Destroy it after the cycle.

## Teardown and inspectability (F-03.4)

The [F-03.4 evidence](../../evidence/F-03.4-teardown-qualification.md) has the detail.

16. **`smoke` is the repeatable P10 test.** `tools/guest.py smoke` (Task `guest:smoke`)
    runs preflight, create, inspect, graceful stop, start from `launch.json`, inspect,
    forced stop, recreate, inspect, destroy and destroy again, and gives one verdict.
    - It compares the inspect records across the start (every field equal) and across
      the recreate: stable fields equal, per-instance fields (machine-id, host keys,
      cloud-init instance id, SSH key, seed) different.
    - It inventories the durable sources before and after each destroy and recreate:
      the checkout, the pinned image, the provider prefix, the other `instances\`
      entries and the operator's `--durable` roots.
    - Two runs passed. The first run failed on a classification defect (MemTotal),
      which was fixed forward.
17. **Guest MemTotal varies per boot.** Observed between 16382784 and 16382796 kB, even
    across a plain restart. The exact memory ceiling is QMP `base-memory`, so the guest
    figure is volatile in the comparison, and its 85 to 100 % verdict must stay equal.
18. **P11 covers the instance's records.** Each launch writes a labelled
    `AIEH-LOG-HEADER` line to `stderr.log`. `inspect` checks the labels of
    `launch.json`, `process.json`, every record and every header. `serial.log`, the
    keys, `known_hosts`, the disks and `seed.iso` are not records and carry no labels.
    A header on `serial.log` would need a change to `launch.argv`.
19. **Line endings.** [`../.gitattributes`](../.gitattributes) (`/seed/**` and
    `/strong-*/**` `-text`) already stores every file pinned by sha256 under `profiles/`
    verbatim. An `autocrlf=true` clone reproduces every pinned digest, and
    `git add --renormalize` changes nothing. Root `.gitattributes` needs no entry.

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
[`../seed/README.md`](../seed/README.md) and implemented in
[`tools/nocloud_seed.py`](../../tools/nocloud_seed.py) (F-03.2.2a).

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
endpoints are declared as classes with `guestfwd` to `127.0.0.1` as the mechanism,
qualified by F-03.3.2; they stay deferred, so the guest has no outbound path at all. Loopback ports can be reached by any local process; that is disclosed. Python's
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
instance directory; virtio-rng for first-boot key generation. QMP is the only
monitor, created with `-object monitor-qmp` on the loopback socket chardev (QEMU 11.1
deprecates `-mon`). The root overlay's backing node is bound explicitly to the pinned
image, so the overlay header's backing path is never trusted.

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
