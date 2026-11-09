# strong-windows-qemu-whpx: provider-profile qualification record

Plan leaf F-03.4. What has been proved for this profile, property by property, on which
host, and where it does not yet apply.

**Why a separate file, not a `qualification` block in `profile.json`.** `profile.json`
is the declaration that launches guests: `create` records its sha256 in every
`launch.json`. A qualification is evidence *about* that declaration, and it is redone
on every new host, pin or leaf. Keeping it here means re-qualifying never changes the
launch input, and its limits and adaptation points can be stated in prose. The
profile's `status.qualification` points here. Nothing in it is machine-checked:
`tools/check_profile.py` does not read it.

**Not operational.** `status.operational` stays `false`. Condition C6 still needs
S-02.x (S-02.1, S-02.2) for P3 to P7, cited by property id.

## Host it was qualified on

| | |
|---|---|
| OS | Windows 11 Home, build 26300 (x86_64) |
| CPU | AMD, family 26 (0x1A), model 68: Zen 5, 16 cores, 32 logical CPUs |
| Hypervisor platform | WHPX: `HypervisorPlatform` enabled (Owner act A1). `WHvGetCapability` reports a hypervisor present, vendor AMD, and XSAVE features `0x41ffffdf`, including XSAVES and XSAVEC. |
| Provider | QEMU 11.1.3 (MSYS2 `mingw-w64-ucrt-x86_64-qemu` 11.1.3-1), `-accel whpx`, `-cpu max,vmx=off,svm=off`, machine `pc-q35-11.1` |
| Guest | Debian 13 genericcloud amd64 build 20261103-2651, kernel 6.12.115, cloud-init 25.1.4 |
| Memory | about 62 GB; two 16 GiB guests ran at once only for the F-03.4 sibling check, with 42 GiB free |

## Properties

| Property | Verdict | Leaf | Evidence |
|---|---|---|---|
| P1 Separate kernel | PASS | F-03.2.2b (observed); F-03.4 (formal) | [F-03.2.2b](../../evidence/F-03.2.2b-guest-lifecycle.md); [F-03.4](../../evidence/F-03.4-teardown-qualification.md): enabled `whpx` and a Linux guest kernel in every inspect, stable across start and recreate |
| P2 Provider-enforced ceilings | PASS | F-03.2.1 (declared); F-03.2.2b (observed); F-03.4 (stable) | [F-03.2.1b](../../evidence/F-03.2.1b-provider-validation.md), [F-03.2.2b](../../evidence/F-03.2.2b-guest-lifecycle.md), [F-03.4](../../evidence/F-03.4-teardown-qualification.md) |
| P3 No automatic host shares | PASS | F-03.3.1; S-02.1, S-02.2 remain | [F-03.3.1](../../evidence/F-03.3.1-guest-surfaces.md); re-run in every F-03.4 inspect |
| P4 Repository exchange and scratch only | PASS | F-03.3.1; S-02.1, S-02.2 remain | [F-03.3.1](../../evidence/F-03.3.1-guest-surfaces.md); re-run in every F-03.4 inspect |
| P5 No Owner secrets | PASS (as `agent`) | F-03.3.1; S-02.1, S-02.2 remain | [F-03.3.1](../../evidence/F-03.3.1-guest-surfaces.md); with a canary set in every F-03.4 smoke inspect |
| P6 No host-management sockets or interop | PASS | F-03.3.1; S-02.1, S-02.2 remain | [F-03.3.1](../../evidence/F-03.3.1-guest-surfaces.md); re-run in every F-03.4 inspect |
| P7 Network posture | PASS: enforcement point qualified | F-03.3.2; S-02.1, S-02.2 remain | [F-03.3.2](../../evidence/F-03.3.2-guest-network.md) |
| P8 Identity | PASS | F-03.2.2b; F-03.4 (fresh across recreate, kept across start) | [F-03.2.2b](../../evidence/F-03.2.2b-guest-lifecycle.md), [F-03.4](../../evidence/F-03.4-teardown-qualification.md) |
| P9 Pinned boot inputs | PASS | F-03.2.1 (declared); F-03.2.2b; F-03.4 (`start` re-hashes every input); E-01.2.2c (re-declared: the seed template's new pin) | [F-03.2.1b](../../evidence/F-03.2.1b-provider-validation.md), [F-03.2.2b](../../evidence/F-03.2.2b-guest-lifecycle.md), [F-03.4](../../evidence/F-03.4-teardown-qualification.md), [E-01.2.2c](../../evidence/E-01.2.2c-fix-requalification.md): every `inspect` of seven guests PASS with the new pin |
| P10 Disposability | PASS | F-03.4; E-01.2.2c (re-observed) | [F-03.4](../../evidence/F-03.4-teardown-qualification.md): two `smoke` runs PASS end to end (one with a running sibling, one with a stopped sibling); no durable source changed. [E-01.2.2c](../../evidence/E-01.2.2c-fix-requalification.md): `smoke --provision` PASS end to end after the seed change |
| P11 Tier label | PASS | every leaf; F-03.4 (schema check of every record and log header) | [F-03.4](../../evidence/F-03.4-teardown-qualification.md) |
| P12 Virtualization extensions | PASS: masked | F-03.2.1b (configuration); F-03.2.2b (guest) | [F-03.2.1b](../../evidence/F-03.2.1b-provider-validation.md), [F-03.2.2b](../../evidence/F-03.2.2b-guest-lifecycle.md) |

The repeatable check is `tools/guest.py smoke` (Task `guest:smoke`). It gives one
machine verdict: PASS, with P10, only when every step passes.

**Requalified after the E-01.2.2 seed change (2026-11-09).** The seed template now starts
the Agent Server only behind `Requires=` on `docker.service` and on the root quiesce step
`aieh-agent-server-quiesce.service`, which runs before every server start
(`provisioning.agent_server.quiesce`). The new template pin was re-observed on fresh guests:
`smoke --provision` PASS (start and recreate compared), `conversation-smoke --restart`,
`admission-probe` and `job-access-probe` PASS, and every `inspect` PASS with the quiesce check
([E-01.2.2c](../../evidence/E-01.2.2c-fix-requalification.md)). The first provisioned smoke
after S-01.4 exposed a comparison defect in `inspect`'s egress check (per-boot times in a
stable view), fixed forward before the passing run.

## Limitations

1. **XSAVE under WHPX with `-cpu max`** (README, open item 3).
   - On this AMD host, every boot logs `x86/fpu: misordered xstate at 1408` and a WARN
     at `xstate.c:254`. XSAVE stays enabled (`Enabled xstate features 0x8e7 … using
     'compacted' format`). `inspect` labels this finding `misordered-xstate`: a
     LIMITATION, recorded and not failed. It was observed on all 10 F-03.4 inspects.
   - On hosts **without XSAVES**, the upstream report (qemu-devel, "[PATCH v2 12/18]
     whpx: i386: forward the dynamic EBX of CPUID[0xD] sub-leaves 0 and 1, not 1 and 2",
     2026-10-27) leads us to expect `XSAVE consistency problem`, XSAVE disabled and a
     kernel panic.
     - `preflight` now asks the hypervisor platform (`WHvGetCapability`, read-only) and
       reports such a host `unavailable`.
     - `inspect` FAILs on `XSAVE consistency problem` or `XSAVE disabled`.
     - That behaviour on a host without XSAVES is **not observed** here; it is
       inferred from the upstream report.
   - Extended-register state correctness (AVX-512) under signal delivery and context
     switches is **unqualified**.
   - `-cpu` is unchanged. Choosing a named CPU model is R-03.x's.
2. **Containers were approximated.** F-03.3.2 used a network namespace behind guest NAT
   in place of a container; Docker is not in the image. A real container is S-02.x's.
3. **The P5 scan reads what `agent` can read.** Root-only guest files are not read
   (README, open item 8). The guest kernel log is one of them: `dmesg_restrict=1`, so
   the XSAVE detector reads the guest console from the host-side `serial.log`.
4. **The guest's MemTotal is not exact across boots.** It moved between 16382784 and
   16382796 kB (always within the 85 to 100 % band). The exact ceiling is QMP
   `base-memory`, 16 GiB on every boot.
5. **Commit charge** (README, open item 6) remains unmeasured.

## Platform adaptation points (not qualified)

| Case | What changes, and what must be re-proved |
|---|---|
| Other Windows 11 editions (Pro, Enterprise, Education) and other x86_64 hosts | Owner acts A1 to A3 as in PREREQUISITES.md. Re-run `preflight` (including `host-xsaves`) and `guest:smoke`. The ceilings (8 vCPU, 16 GiB) assume about 62 GB of RAM and 32 logical CPUs. |
| Intel hosts, and any host without XSAVES | `preflight` refuses (`host-xsaves` fail). The profile needs a CPU model qualified for that host (R-03.x), or a QEMU pin that carries the upstream CPUID[0xD] fix, then re-qualification. |
| Intel hosts with XSAVES | Not observed. The same `preflight`, `smoke` and inspect XSAVE detector apply. Whether the misordered-offset warning appears there is unknown. |
| A re-pinned QEMU, image or kernel | `guest_storage`'s pseudo mounts and `CHECK_CLASSES` were derived on this build (README, open item 10). Re-run `smoke`; an unclassified or changed check fails it. |
| Windows 10, Windows on Arm64 | Unsupported (contract section 12). |
| Linux: `strong-incus-vm` | Declared only (F-03.2.1). No Incus host has run it; no lifecycle, surface, network or teardown leaf has run on it. |
| macOS: Lima | No profile yet. The egress enforcement point is open (contract section 6). |
| Remote Linux (Incus over an authenticated path) | Contract section 8 only. |
