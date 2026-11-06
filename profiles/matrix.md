# Platform-provider compatibility and fallback matrix

Plan leaf F-03.1. This is the companion to the execution-profile contract in
[`README.md`](README.md); the property ids (`profiles P1` to `profiles P12`) and Owner
conditions (C1 to C7) are defined there. The providers and their rank come from
[decision 0003][D3].

**Specification only.** No provider here has been installed, configured or run for
this leaf. Every runtime claim is UNKNOWN until F-03.2.x, F-03.3.x, F-03.4 and S-02.x
produce evidence.

## Reading the matrix

**Status on this host** is one of:
- `observed`: recorded as an observation in [decision 0003][D3];
- `unknown`: depends on a fact that has not been determined;
- `unverified`: not checked on any host.

**Disposition** is one of:
- `reference`: the specified path;
- `supported`: a contract path, not yet qualified;
- `qualify`: permitted only after a qualification record;
- `unsupported`;
- `not a provider`.

**Citations.** Every cell that is not "unverified" cites a source: a URL, a blueprint
anchor, or [decision 0003][D3]. The Tier column and the rank in Disposition come from
[D3] in every row. The bracketed labels are listed under
[Sources](#sources). Everything about macOS, native Linux, Pro editions, VirtualBox,
VMware and Multipass installer privileges is **unverified**.

## This host's facts

These are taken from [decision 0003][D3], observed on 2026-11-06, and were not
re-probed for this leaf.
- Windows 11 Home, build 26300.
- The Windows hypervisor is present (it runs for WSL2).
- WSL2 is active. `/dev/kvm` was observed in the Owner's distribution.
- No third-party hypervisor is installed.
- The Windows Hypervisor Platform (WHP) feature state cannot be determined without
  elevation (open item; decision rule in [D3]).
- The Hyper-V role is unavailable on Home ([ms-hyperv]).

## Windows

| Provider | Tier | Isolation mechanism | Provider-enforced ceilings | Shares | Network | Native CLI | Licence | Owner-host impact | Status on this host | Disposition |
|---|---|---|---|---|---|---|---|---|---|---|
| Remote Incus (see [Remote](#remote)) | strong | Incus VM on an Owner-controlled Linux/KVM host [incus-req] | `limits.cpu`, `limits.memory`, root `size` [incus-opts] [incus-disk] | none beyond root and scratch disk devices [incus-disk] | remote NAT bridge with ACLs [incus-acl] | `incus` client; Windows client via winget [incus-install] | Apache-2.0 [incus-licence] | client install and client key only; the daemon runs only on Linux [incus-install] | unknown: no remote host provided [D3] | supported; rank 1 [D3] |
| Hyper-V role | strong | Hyper-V VM: unverified | unverified | unverified | unverified | unverified | part of Windows; editions per [ms-hyperv] | role install on Windows 10/11 Pro or Enterprise [ms-hyperv]; Education unverified | observed unavailable: Home edition [D3] [ms-hyperv] | supported on Pro and Enterprise; rank 2 [D3] |
| **QEMU + WHPX** | strong | QEMU VM on the WHPX accelerator [qemu-intro], using the Windows Hypervisor Platform API [ms-whp] | `-smp`, `-m`, image virtual size [qemu-invocation] | **none**: no `-virtfs`, no SMB (contract `profiles P4`; [D3] open items) | user-mode `-nic user,restrict=on`; `hostfwd` on 127.0.0.1; `guestfwd` to a host proxy [qemu-invocation] | `qemu-system-x86_64`, `qemu-img`, QMP [qemu-invocation] | GPL-2.0 [qemu-licence] | A1 enable `HypervisorPlatform` and restart; A2 user-scoped pinned QEMU; A3 guest-state directory: each needs separate Owner approval [D3] | unknown: WHP state undetermined; A1-A3 pending [D3] | **reference** (Owner-selected W1); rank 3 [D3] |
| Lima / Multipass over HCS | strong | Lima `vmType: hcs` on the Windows HCS API, **experimental**, Lima ≥ 2.3 on Windows 11 [lima-hcs]; Multipass mechanism unverified | Lima `cpus`/`memory`/`disk` [lima-default]; honoured under hcs: unverified | Lima hcs: plain mode only, no file mount [lima-hcs] | fixed HCN subnet, one instance at a time, explicit DNS, no dynamic port forwarding [lima-hcs] | `limactl` [lima-hcs]; `multipass` unverified | Lima Apache-2.0 [lima-licence]; Multipass GPL-3.0 [multipass-licence] | **run-time elevation**: membership of Hyper-V Administrators and an Administrator shell [lima-hcs]; Multipass installer privileges unverified | unknown: not installed; HCS availability on Home not determined [D3] | qualify; experimental; rank 4 [D3] |
| KVM in a dedicated WSL2 distribution | strong (nested) | QEMU/KVM inside a WSL2 distribution: nested inside the WSL utility VM [ms-wsl-config] (`nestedVirtualization`) | inner QEMU `-smp`/`-m` [qemu-invocation], inside VM-wide WSL limits shared with every distribution [ms-wsl-config] [ms-wsl-compare] | WSL automount on by default, must be disabled per distribution [ms-wsl-config] | inside the shared WSL network namespace [ms-wsl-compare] | `wsl.exe` [ms-wsl-basic] plus QEMU [qemu-invocation] | WSL MIT [wsl-licence]; QEMU GPL-2.0 [qemu-licence] | shares the Owner's WSL VM; relies on the VM-wide `nestedVirtualization` default (true, Windows 11) [ms-wsl-config]; must never touch the Owner's distribution (C1) | observed capability: `/dev/kvm` present in the Owner's distribution [D3]; dedicated distribution not created | qualify; **never the specified path**; `nesting: nested`; rank 5 [D3] |
| VirtualBox / VMware on WHP | strong | unverified | unverified | unverified | unverified | unverified | unverified | admin kernel drivers: unverified | observed not installed (no third-party hypervisor) [D3] | permitted, not preferred; rank 6 [D3] |
| Dedicated hardened WSL2 distribution | trusted-workload | a separate distribution in the shared WSL 2 VM; shares the kernel, CPU, memory, swap and network namespace [ms-wsl-compare] | VM-wide `.wslconfig` `memory`/`processors`, shared; observed only [ms-wsl-config] (C1) | `[automount] enabled=false`, `mountFsTab=false` in its own `wsl.conf` [ms-wsl-config] | VM-wide `networkingMode` (default NAT), observed only [ms-wsl-config]; no egress enforcement outside the guest | `wsl --import`, `--terminate`, `--unregister` [ms-wsl-basic] | MIT [wsl-licence] | an imported distribution only; never `.wslconfig`, never `wsl --shutdown` [ms-wsl-basic] (C1) | WSL2 active [D3]; dedicated distribution not created | supported as trusted-workload only [D3] [bp-infra] [bp-contain] |
| Docker Desktop; `wslc.exe` | — | — | — | — | — | — | — | — | — | **not a provider** [D3]. Docker Desktop is optional, not a prerequisite [bp-infra]; `.wslconfig` does not apply to `wslc.exe` containers [ms-wsl-config] |

## Linux

| Provider | Tier | Isolation mechanism | Provider-enforced ceilings | Shares | Network | Native CLI | Licence | Owner-host impact | Status on this host | Disposition |
|---|---|---|---|---|---|---|---|---|---|---|
| Incus VM | strong | QEMU VM managed by Incus; kernel ≥ 6.12, QEMU ≥ 8.2 [incus-req] | `limits.cpu`, `limits.memory`, root `size` [incus-opts] [incus-disk] | root and scratch disk devices only [incus-disk] | managed NAT bridge with network ACLs; baseline DHCP/DNS rules cannot be blocked by ACLs [incus-acl] | `incus` [incus-install] | Apache-2.0 [incus-licence] | Incus daemon install, Linux only [incus-install]; `/dev/kvm` access: unverified on any host | unverified (no Linux host) | supported (the Linux strong path) [D3] |
| Incus container | trusted-workload | system container sharing the host kernel [bp-infra] | cgroup `limits.cpu`, `limits.memory` [incus-opts] | root and scratch disk devices only [incus-disk] | managed bridge with ACLs [incus-acl] | `incus` [incus-install] | Apache-2.0 [incus-licence] | Incus daemon install: unverified on any host | unverified (no Linux host) | supported as trusted-workload only [D3] |

## macOS

| Provider | Tier | Isolation mechanism | Provider-enforced ceilings | Shares | Network | Native CLI | Licence | Owner-host impact | Status on this host | Disposition |
|---|---|---|---|---|---|---|---|---|---|---|
| Lima `vz` | strong | Virtualization.framework VM; `vz` is the default on macOS 13.5 or later [lima-default] [lima-vz] | `cpus`, `memory`, `disk` [lima-default] | builtin default none, but the default template inherits a read-only home mount; override with `mounts: []` [lima-default] | user-mode network; `networkOpts.hostLoopback: false` (vz only, Lima ≥ 2.3) [lima-default]; egress enforcement point open (F-03.3.2) | `limactl`, `limactl validate` [lima-validate] | Apache-2.0 [lima-licence] | user-level install: unverified; `LIMA_HOME` set to the harness state directory | unverified (no macOS host) | supported [D3] |
| Lima `qemu` | strong | QEMU with HVF [qemu-intro] [lima-default] | `cpus`, `memory`, `disk` [lima-default] | as for `vz`; 9p by default for QEMU mounts, if any were declared [lima-default] | user-mode network; `hostLoopback` not supported [lima-default]; egress enforcement point open (F-03.3.2) | `limactl` [lima-validate] | Apache-2.0 [lima-licence]; QEMU GPL-2.0 [qemu-licence] | QEMU install required for the QEMU driver [lima-install]; method unverified | unverified (no macOS host) | supported (macOS before 13.5) [D3] |
| Colima | — | Lima-based: unverified | — | `$HOME` mounted writable by default [colima-defaults] | — | `colima` [colima-faq] | MIT [colima-licence] | publishes the guest Docker socket on the host [colima-faq] | unverified | **unsupported** for the strong tier (contract section 7) |

## Remote

| Provider | Tier | Isolation mechanism | Provider-enforced ceilings | Shares | Network | Native CLI | Licence | Owner-host impact | Status on this host | Disposition |
|---|---|---|---|---|---|---|---|---|---|---|
| Remote Incus | strong | Incus VM on an Owner-controlled Linux/KVM host [incus-req] | `limits.cpu`, `limits.memory`, root `size`, project quotas [incus-opts] [incus-disk] | root and scratch only [incus-disk] | dedicated NAT bridge with ACLs [incus-acl]; API at `core.https_address` over an authenticated path [incus-expose] | `incus remote add <name> <token>` [incus-expose]; certificate `restricted` to a project [incus-auth] | Apache-2.0 [incus-licence] | client key held in the harness state directory; no Owner secrets on the remote (contract section 8) | unknown: no remote host provided [D3] | supported; explicit profile, never automatic [D3] |

## Fallback rules

Fallback is never automatic (contract section 4). When the requested strong profile is
unavailable, `create` refuses with `TIER_UNAVAILABLE` and `preflight` names the Owner act.

| Host | Preferred strong path | If unavailable |
|---|---|---|
| Windows Pro or Enterprise | Hyper-V role or QEMU + WHPX | Owner act (role or A1-A3), or an explicit remote Incus profile |
| Windows Home (this host) | QEMU + WHPX (reference, W1) | A1-A3 with separate approvals (C2); or an explicit remote Incus profile; otherwise only the explicitly named trusted-workload WSL2 profile |
| Linux with `/dev/kvm` | Incus VM | — |
| Linux without `/dev/kvm` | none locally | explicit remote Incus profile; locally, trusted-workload Incus containers only |
| macOS 13.5 or later | Lima `vz` | Lima `qemu`; or an explicit remote Incus profile |
| macOS before 13.5 | Lima `qemu` | explicit remote Incus profile |
| CI or cloud VM without nesting | none locally | explicit remote Incus profile |

## Leaf proof self-check (specification only)

The leaf's proof asks for a contract that "specifies a realizable provider path and
isolation boundary for Windows, Linux and macOS without assuming nested
virtualization". The table shows that path for each platform. Every runtime claim is
**UNKNOWN**: this leaf proves the specification only.

| Platform | Non-nested realizable strong path | Prerequisites | Unverified / UNKNOWN |
|---|---|---|---|
| Windows | QEMU + WHPX (`strong-windows-qemu-whpx`), the reference. A remote Incus host is the explicit alternative. | Windows 11 x86_64; firmware virtualization on; the WHP feature available and enabled (A1); a pinned user-scoped QEMU (A2); a guest-state directory outside the Owner's profile (A3); each with separate Owner approval (C2) | WHP availability on Home (open item in [D3]); WHPX runtime behaviour; the SLIRP `restrict=on` and `guestfwd` enforcement (F-03.3.2); masking of the extensions (`profiles P12`); all of P1-P12 at run time |
| Linux | Incus VM (`strong-incus-vm` on `local`) | `/dev/kvm` access; kernel ≥ 6.12 and QEMU ≥ 8.2, per the pinned Incus release [incus-req] | no native Linux host has been used; the bridge ACL enforcement and its baseline-service caveat (F-03.3.2); all of P1-P12 at run time |
| macOS | Lima `vz` (macOS 13.5 or later), or Lima `qemu` with HVF | Lima ≥ 2.3; `LIMA_HOME` in the harness state directory; the section 7 overrides | no macOS host has been used; Lima's numeric macOS floor (not published); the egress enforcement point outside the guest (open, F-03.3.2); all of P1-P12 at run time |

No path relies on `/dev/kvm`, Kata, Firecracker, Cloud Hypervisor, gVisor-KVM, Incus
VMs, WSL, Docker Desktop, Hyper-V isolated containers or nested QEMU/KVM inside the
guest (contract section 5). The one nested candidate, KVM inside WSL2, is `qualify` and
never the specified path.

## Sources

Fetched 2026-11-05 over HTTPS. Upstream "main" or "master" documents can change; the
F-03.2.1 pins decide what is actually used.

- [D3]: [decision 0003](../decisions/0003-execution-guest-providers-and-isolation-contract.md),
  including its host observations and the Owner selection.
- [bp-infra]: blueprint
  [#infrastructure-state](../AI_Engineering_Open_Source_Blueprint_Architecture_Deep_Review_2026-10-31.html#infrastructure-state).
- [bp-contain]: blueprint
  [#containment-architecture](../AI_Engineering_Open_Source_Blueprint_Architecture_Deep_Review_2026-10-31.html#containment-architecture).
- [ms-wsl-config]: <https://learn.microsoft.com/en-us/windows/wsl/wsl-config>. The
  `wsl.conf` `[automount]` and `[interop]` keys; `.wslconfig` is global for all WSL 2
  distributions; `nestedVirtualization` defaults to true and is Windows 11 only;
  `networkingMode`; `.wslconfig` does not apply to `wslc.exe`.
- [ms-wsl-basic]: <https://learn.microsoft.com/en-us/windows/wsl/basic-commands>.
  `--import`, `--terminate`, `--unregister`; `--shutdown` terminates all distributions.
- [ms-wsl-compare]: <https://learn.microsoft.com/en-us/windows/wsl/compare-versions>.
  WSL 2 distributions share the network namespace and the CPU, kernel, memory and swap.
- [ms-hyperv]:
  <https://learn.microsoft.com/en-us/windows-server/virtualization/hyper-v/get-started/install-hyper-v>.
  "Windows 10 (Pro or Enterprise), or Windows 11 (Pro or Enterprise)"; "The Hyper-V role
  can't be installed on Windows 10 Home or Windows 11 Home."
- [ms-whp]:
  <https://learn.microsoft.com/en-us/virtualization/api/hypervisor-platform/hypervisor-platform>.
  The WHP API for third-party virtualization stacks.
- [qemu-intro]: <https://www.qemu.org/docs/master/system/introduction.html>. Supported
  accelerators include WHPX on Windows and HVF on macOS.
- [qemu-invocation]: <https://www.qemu.org/docs/master/system/invocation.html>. `-S`;
  `-nic user` with `restrict=on` ("does not affect any explicitly set forwarding rules"),
  `hostfwd`, `guestfwd`.
- [qemu-licence]: <https://github.com/qemu/qemu/blob/master/LICENSE>. "The QEMU emulator
  as a whole is released under the GNU General Public License, version 2."
- [incus-req]: <https://linuxcontainers.org/incus/docs/main/requirements/>. "The minimum
  supported kernel version is 6.12"; "For virtual machines, QEMU 8.2 or higher is
  required."
- [incus-opts]: <https://linuxcontainers.org/incus/docs/main/reference/instance_options/>.
  `limits.cpu`, `limits.memory`; `security.nesting` (default true for VMs; false turns
  off svm/vmx).
- [incus-disk]: <https://linuxcontainers.org/incus/docs/main/reference/devices_disk/>.
  `size`, root disk.
- [incus-acl]: <https://linuxcontainers.org/incus/docs/main/howto/network_acls/>. Bridge
  ACLs; their limitations, including that baseline service rules cannot be blocked.
- [incus-auth]: <https://linuxcontainers.org/incus/docs/main/authorization/>. Restricted
  TLS clients confined to projects.
- [incus-expose]: <https://linuxcontainers.org/incus/docs/main/howto/server_expose/>.
  `core.https_address`; trust tokens; `incus remote add`.
- [incus-install]: <https://linuxcontainers.org/incus/docs/main/installing/>. "The Incus
  daemon only works on Linux"; Windows client via Chocolatey and winget.
- [incus-licence]: <https://github.com/lxc/incus/blob/main/COPYING>. Apache-2.0 (GitHub
  licence metadata).
- [lima-default]: <https://raw.githubusercontent.com/lima-vm/lima/master/templates/default.yaml>.
  `vmType`, `cpus`/`memory`/`disk`, `mounts` and the `_default/mounts` base,
  `ssh.forwardAgent`, `portForwards` `ignore`, `propagateProxyEnv`, `plain`,
  `nestedVirtualization`, `networkOpts.hostLoopback`, `images[].digest`, and the
  `_config/default.yaml` and `override.yaml` merge rules.
- [lima-hcs]: <https://lima-vm.io/docs/config/vmtype/hcs/>. Experimental; Lima ≥ 2.3 and
  Windows 11; plain mode only; Hyper-V Administrators group and an Administrator shell;
  one instance at a time.
- [lima-vz]: <https://lima-vm.io/docs/config/vmtype/vz/>. `vz` needs macOS 13 or later;
  an issue fixed in 13.5.
- [lima-install]: <https://lima-vm.io/docs/installation/>. "macOS (the latest version is
  recommended)"; QEMU required only for the QEMU driver.
- [lima-validate]: <https://lima-vm.io/docs/reference/limactl_validate/>. "Validate YAML
  templates."
- [lima-licence]: <https://github.com/lima-vm/lima/blob/master/LICENSE>. Apache-2.0
  (GitHub licence metadata).
- [colima-defaults]: <https://raw.githubusercontent.com/abiosoft/colima/main/embedded/defaults/colima.yaml>.
  "Colima default behaviour: $HOME is mounted as writable."
- [colima-faq]: <https://raw.githubusercontent.com/abiosoft/colima/main/docs/FAQ.md>. The
  Docker socket is located at `$HOME/.colima/default/docker.sock`.
- [colima-licence]: <https://github.com/abiosoft/colima/blob/main/LICENSE>. MIT (GitHub
  licence metadata).
- [multipass-licence]: <https://github.com/canonical/multipass/blob/main/LICENSE>.
  GPL-3.0 (GitHub licence metadata).
- [wsl-licence]: <https://github.com/microsoft/WSL/blob/master/LICENSE>. MIT (GitHub
  licence metadata).

[D3]: ../decisions/0003-execution-guest-providers-and-isolation-contract.md
[bp-infra]: ../AI_Engineering_Open_Source_Blueprint_Architecture_Deep_Review_2026-10-31.html#infrastructure-state
[bp-contain]: ../AI_Engineering_Open_Source_Blueprint_Architecture_Deep_Review_2026-10-31.html#containment-architecture
[ms-wsl-config]: https://learn.microsoft.com/en-us/windows/wsl/wsl-config
[ms-wsl-basic]: https://learn.microsoft.com/en-us/windows/wsl/basic-commands
[ms-wsl-compare]: https://learn.microsoft.com/en-us/windows/wsl/compare-versions
[ms-hyperv]: https://learn.microsoft.com/en-us/windows-server/virtualization/hyper-v/get-started/install-hyper-v
[ms-whp]: https://learn.microsoft.com/en-us/virtualization/api/hypervisor-platform/hypervisor-platform
[qemu-intro]: https://www.qemu.org/docs/master/system/introduction.html
[qemu-invocation]: https://www.qemu.org/docs/master/system/invocation.html
[qemu-licence]: https://github.com/qemu/qemu/blob/master/LICENSE
[incus-req]: https://linuxcontainers.org/incus/docs/main/requirements/
[incus-opts]: https://linuxcontainers.org/incus/docs/main/reference/instance_options/
[incus-disk]: https://linuxcontainers.org/incus/docs/main/reference/devices_disk/
[incus-acl]: https://linuxcontainers.org/incus/docs/main/howto/network_acls/
[incus-auth]: https://linuxcontainers.org/incus/docs/main/authorization/
[incus-expose]: https://linuxcontainers.org/incus/docs/main/howto/server_expose/
[incus-install]: https://linuxcontainers.org/incus/docs/main/installing/
[incus-licence]: https://github.com/lxc/incus/blob/main/COPYING
[lima-default]: https://raw.githubusercontent.com/lima-vm/lima/master/templates/default.yaml
[lima-hcs]: https://lima-vm.io/docs/config/vmtype/hcs/
[lima-vz]: https://lima-vm.io/docs/config/vmtype/vz/
[lima-install]: https://lima-vm.io/docs/installation/
[lima-validate]: https://lima-vm.io/docs/reference/limactl_validate/
[lima-licence]: https://github.com/lima-vm/lima/blob/master/LICENSE
[colima-defaults]: https://raw.githubusercontent.com/abiosoft/colima/main/embedded/defaults/colima.yaml
[colima-faq]: https://raw.githubusercontent.com/abiosoft/colima/main/docs/FAQ.md
[colima-licence]: https://github.com/abiosoft/colima/blob/main/LICENSE
[multipass-licence]: https://github.com/canonical/multipass/blob/main/LICENSE
[wsl-licence]: https://github.com/microsoft/WSL/blob/master/LICENSE
