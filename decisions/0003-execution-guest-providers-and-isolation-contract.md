# 0003 - Execution-guest providers and isolation contract

Status: Accepted by the Overseer, within blueprint #infrastructure-state and
#containment-architecture (SEC-01), 2026-11-06. Realizing the strong tier on the
Windows host still waits for one Owner act (see "Owner act" below).
Gate: architecture consultation before F-03.1, gates C (several plausible provider
structures) and G (isolation boundary).
Supersedes: none.

## Context
F-03.1 must specify, for Windows, Linux and macOS, a provider path that can actually be
realized and an isolation boundary, without assuming nested virtualization. The
blueprint names the providers:
- Linux: Incus.
- macOS: Lima/Colima.
- Windows: "QEMU/WHPX or an appropriate VM manager, or a qualified remote Linux
  worker".

The blueprint also requires that an unsafe fallback is disclosed and refused, and it
classes native WSL2 as an explicitly weaker option for trusted workloads only.

The only available host is Windows 11 Home, build 26300:
- The Hyper-V role is unavailable on this edition.
- The Windows hypervisor already runs, for WSL2.
- Whether the Windows Hypervisor Platform feature is available cannot be determined
  without elevation.
- WSL 2 runs every distribution in one utility VM. That VM's memory, processors and
  networking mode are set VM-wide in the Owner's `.wslconfig` (Microsoft wsl-config).
- Nested virtualization is on by default there: `/dev/kvm` was observed in the
  Owner's distro on 2026-11-06.

## Decision
1. **Trust tiers.** There are two:
   - **strong:** a separate guest kernel, ceilings enforced by the provider, no host
     shares beyond an explicit allowlist, and network policy enforced outside the
     guest.
   - **trusted-workload:** a kernel shared with the host.

   The tier is part of every profile name and appears in every artifact. No default,
   environment variable or automatic selection may choose a tier. When a strong-tier
   request cannot be honoured, it fails with a machine-readable refusal that names the
   Owner act which would make it available.
2. **Providers.**
   - **Linux:** Incus virtual-machine instances. Incus containers count as
     trusted-workload.
   - **macOS:** Lima used directly, with `vz` on macOS 13.5 or later and `qemu`/HVF
     otherwise. The profile overrides Lima's home mount, proxy propagation, agent
     forwarding and fallback port forwarding.
   - **Windows strong tier**, in rank order:
     1. a remote Incus host;
     2. the Hyper-V role (Pro, Enterprise and Education only);
     3. QEMU with WHPX (the reference profile);
     4. Lima or Multipass over HCS (to be qualified; needs elevation at run time);
     5. KVM inside a dedicated WSL2 distro (to be qualified; nested, never the
        specified path);
     6. VirtualBox or VMware on WHP (permitted, not preferred).
   - **Windows trusted-workload:** a dedicated, hardened WSL2 distribution.
   - Docker Desktop and `wslc.exe` are not providers.
3. **Standard guest boundary.** Properties P1 to P12, defined in `profiles/`:
   - P1: a separate kernel.
   - P2: vCPU, memory and disk ceilings enforced by the provider.
   - P3: no automatic host shares.
   - P4: repository exchange and scratch storage only.
   - P5: no Owner secrets.
   - P6: no host-management sockets and no interop.
   - P7: NAT with the host bridge denied by default, explicit endpoint classes, and an
     egress allowlist enforced outside the guest.
   - P8: per-instance identity.
   - P9: pinned boot inputs.
   - P10: disposability.
   - P11: a tier label.
   - P12: no reliance on virtualization extensions.

   **Lifecycle operations:** preflight, create, start, stop, destroy, recreate, inspect,
   exec (operator only), and exchange push/pull. The modes are shared and fresh.
4. **No nested virtualization assumed.** Moby inside the guest needs none. None of the
   following is assumed inside the guest: Kata, Firecracker, Cloud Hypervisor,
   gVisor-KVM, Incus VMs, WSL, or Docker Desktop.
5. **Remote-Linux fallback.** Incus over HTTPS, with these requirements:
   - client certificates added by token and restricted to a project;
   - a dedicated project, storage pool and bridge;
   - no Owner secrets on the remote host;
   - the same lifecycle and inspection operations as local providers.

   It is an explicit profile, never selected automatically.

## Owner act (gates F-03.2.1 on this host)
The reference profile `windows-qemu-whpx` needs the Owner to:
- **A1:** enable the `HypervisorPlatform` optional feature and restart;
- **A2:** accept a user-scoped, pinned QEMU;
- **A3:** designate a guest-state directory outside the Owner's profile.

Until such an act is recorded in `evidence/bootstrap-log.md`, the host counts as
unsupported for the strong tier. Only `windows-wsl2-distro` may be exercised, and only
when named explicitly and labelled trusted-workload. If the Owner instead selects the
nested WSL2 candidate or the trusted-workload profile as the F-03.2.x reference, that
choice is recorded here as an Owner clarification, because it changes what the F-03
evidence establishes.

## Owner selection (2026-11-06)
The Owner selected **W1**: QEMU with the Windows Hypervisor Platform (WHPX) is the
reference Windows provider for the strong tier. The selection carries these binding
conditions, recorded here and in the execution-profile contract:
1. The Owner's existing WSL2 Ubuntu environment is preserved, with no modification or
   disruption. Probes, provisioning and tests must not start, configure or depend on
   it, and the harness never writes `%USERPROFILE%\.wslconfig`.
2. Selecting a provider authorizes no installation, no change to Windows features, no
   reboot and no other privileged host change. Each such act (A1 enabling
   `HypervisorPlatform` and restarting; A2 installing QEMU; A3 creating the
   guest-state directory) needs its own Owner approval at the point it is actually
   required, and that approval is recorded in `evidence/bootstrap-log.md`.
3. QEMU releases are pinned and checksum-verified, and the configuration is
   reproducible.
4. Guest storage is kept separate from the Owner's existing repositories and
   environments.
5. Untrusted workloads get no host directories, credentials, management interfaces or
   unrestricted networking (P3 to P7).
6. The strong-security profile is not declared operational until observable isolation
   tests pass. Those are F-03.3.1, F-03.3.2, F-03.4 and S-02.x, cited by property id.
7. No dependence on nested virtualization.

## Consequences
- **F-03.1 artifact:** `profiles/README.md` (the contract) and `profiles/matrix.md` (the
  compatibility and fallback matrix), with property ids that later leaves cite. Exact
  provider pins belong to F-03.2.1.
- **Later leaves:**
  - F-03.2.1 declares the Linux Incus VM profile and the Windows reference profile.
  - F-03.3.1 and F-03.3.2 test P3 to P7.
  - F-03.4 proves P10.
  - P2 meets decision 0001's resource-cap obligation.
- **Open items:**
  - Whether WHP is available on this edition. The rule for deciding: an elevated
    `Get-WindowsOptionalFeature -Online -FeatureName HypervisorPlatform` that returns a
    State means it is available; an unknown-feature error means it is not.
  - QEMU host sharing on Windows is not relied on.
  - macOS and native Linux remain unverified.
- **Detected, not changed:**
  - Blueprint `#platforms` ("Linux container via WSL2 or container VM") and SHIP-01
    ("behind Windows WSL2/VM") read as though WSL2 were a peer of a VM. SEC-01 forbids
    treating WSL settings as an equivalent host-security guarantee. This is maintenance
    item M-2: a reconciliation note made through the authority-class process.
  - F-03.1's required input "pinned provider versions" did not exist yet. It is
    resolved here as version floors plus a pin rule, with the exact pins left to
    F-03.2.1.

## Evidence
- **Blueprint:** #infrastructure-state, #containment-architecture, #platforms, extracted
  2026-11-06.
- **Plan and records:** plan leaves F-03.1 to F-03.4, F-04.1 and R-03.x; the obligations
  in decision 0001.
- **Host probes, 2026-11-06:** run non-elevated. The Owner's WSL distro was started for
  read-only inspection and stopped again.
- **Microsoft Learn:** wsl-config, networking, basic-commands, install-hyper-v,
  hypervisor-platform.
- **qemu.org:** system/introduction and system/invocation.
- **linuxcontainers.org (Incus):** requirements, instance_options, network_acls,
  authorization, server_expose, installing.
- **Lima and Colima:** lima-vm.io `templates/default.yaml` and `config/vmtype/hcs`;
  github.com/abiosoft/colima defaults.
