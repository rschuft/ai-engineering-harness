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

## Owner authorization: guest validation (2026-11-06)
The Owner approved F-03.2.2: create, boot, inspect, stop and destroy disposable Debian 13 guests using the
pinned QEMU/WHPX configuration. The approval covers repeatable, non-privileged guest-validation cycles under
these conditions, without approval for each routine boot:
1. Use only the verified Debian image, the verified QEMU installation and the approved profile (8 vCPU, 16 GiB).
2. Keep all instance-specific disks, SSH keys and execution records under `D:\aieh-guest-state\instances\`.
3. Do not mount or share host folders, repositories, credentials or management interfaces with the guest.
4. Restrict SSH to 127.0.0.1 and verify the effective binding.
5. Keep guest networking blocked from outbound access, and verify the restriction is effective rather than
   relying on configuration alone.
6. Do not modify Windows, WSL2, host firewall rules, system services or other host configuration. Stop if
   Windows requests firewall authorization.
7. Use fresh per-instance credentials. Destroy each disposable instance and its credentials after validation,
   preserving the verified base image and shared installation.
8. Run no untrusted agent workloads during this infrastructure validation.
9. Record actual boot, inspection, isolation and teardown evidence. Do not declare the strong tier verified
   until its required negative tests pass (C6).

Any expansion of host access, network permissions or VM privileges, or execution of untrusted workloads,
needs separate authorization.

## Owner authorization: network validation (2026-11-06)
The Owner authorized both F-03.3.2 network validation tests, repeatable under the guest-validation
conditions above, with these further constraints:
1. Guest-root testing only inside disposable test VMs. It may configure guest routes and interfaces, but must
   not modify the Windows host, WSL2, the host firewall or the persistent VM profile.
2. Prove outbound denial even when guest root establishes a default route. Test IPv4, IPv6, DNS and
   direct-IP paths. Do not rely solely on the guest's lack of a default route.
3. A temporary QEMU guestfwd only to a purpose-built test listener bound to 127.0.0.1, on an ephemeral port.
4. The test listener exposes no credentials, files, repositories, management interfaces or existing host
   services. It only exchanges a recognizable test payload.
5. Positive and negative controls: the authorized test connection succeeds, while unrelated destinations
   remain inaccessible, including other host-loopback services.
6. No general host networking, unrestricted outbound access, host-folder sharing, elevated privileges or
   persistent firewall exceptions.
7. Capture the effective QEMU configuration and the observed network results. If isolation cannot be
   demonstrated, report failure rather than weakening the profile.
8. After each cycle, destroy disposable guests, terminate the temporary listener, remove temporary
   credentials, and verify cleanup.

Broader guest-to-host access, production network connectivity, or a change to the approved isolation
profile needs separate authorization.

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

## Current facts (2026-11-06, F-03.1 source check)
- Microsoft Learn lists the Hyper-V role for Windows 10/11 Pro and Enterprise. Education is not
  listed, so the matrix marks it unverified.
- The WHP API reference does not document the `HypervisorPlatform` optional-feature name, how to
  enable it, or which editions provide it. The A1 decision rule therefore rests on this record and
  on the elevated read the Owner performs.
- Profile names carry the tier prefix: `strong-windows-qemu-whpx`, `trusted-workload-windows-wsl2-distro`.
  The short names above are the host-provider part of those names.
- macOS strong is not operational until F-03.3.2 qualifies an egress enforcement point: Lima has no
  native egress allowlist (condition 6).
- **2026-11-06, F-03.2.1b: configuration media amendment (Overseer decision in F-03.2.1a).** The
  contract allowed only root and scratch disk devices (P4; sections 6 and 7 for Incus). A Debian
  cloud image needs a seed medium, and the Incus agent needs `agent:config` or the 9p `config`
  share, so neither reference profile could meet that wording. The contract now also allows
  read-only configuration media generated by the harness or the provider: the QEMU NoCloud seed on
  a read-only virtio disk, and the Incus `cloud-init:config` and `agent:config` disk devices
  (read-only CD-ROMs). Their content stays bound by P5, and each is listed in the profile's
  declared devices so `inspect` can compare against it. The Incus 9p `config` share and any host
  filesystem share remain forbidden (P3, P4).
- **2026-11-06, F-03.2.2b: P6 wording amended (Overseer decision as contract owner).** P6's
  inspection asked for "the absence of … `/tmp/.X11-unix`". The first real boots found that
  path as an empty directory (no socket), created by the guest's own
  `/usr/lib/tmpfiles.d/x11.conf`, so `inspect` reported P6 FAIL
  (`evidence/F-03.2.2b-guest-lifecycle.md`, Findings 3). P6 protects against host display
  and IPC channels, and an empty directory is not one. The inspection now asks for **no
  socket under `/tmp/.X11-unix`**: nothing in it but directories, and the path itself not a
  symlink (`profiles/README.md` P6, `profiles/properties.json`, `tools/guest.py`).
- **2026-11-06, F-03.2.2b: WHPX XSAVE limitation of the reference profile.** Recorded only;
  `-cpu` and `launch.argv` are unchanged.
  - **Observed** on this host (AMD, XSAVES present) with QEMU 11.1.3 WHPX,
    `-cpu max,vmx=off,svm=off` and the Debian 13 kernel: every boot logs
    `x86/fpu: misordered xstate at 1408` and the WARN at `xstate.c:254`
    (`fpu__init_system_xstate`). That is the kernel's one-time warning that the XSAVE
    component offsets in CPUID leaf 0xD are not ascending. There is no
    `XSAVE consistency problem`: XSAVE stays enabled, and the guests ran normally in both
    cycles (`evidence/F-03.2.2b-guest-lifecycle.md`, Findings 4).
  - **Upstream, related but distinct:** qemu-devel "[PATCH v2 12/18] whpx: i386: forward
    the dynamic EBX of CPUID[0xD] sub-leaves 0 and 1, not 1 and 2" (2026-10-27). It reports
    that hosts *without* XSAVES get `XSAVE consistency problem` (`xstate.c:638`) and a
    kernel panic with XSAVE-capable models, including `max`. **Inference:** our symptom
    differs, so the warning is not attributed to that defect. The pinned 11.1.3 is presumed
    to carry it (**UNKNOWN**: its source is not verified).
  - **Impact:** no isolation property (P1 to P12) is affected that we know of. On hosts
    without XSAVES, `max` is expected to panic at boot, and preflight does not detect that.
    Extended-register state correctness on this host is unqualified.
  - **Carried:**
    - F-03.4 and R-03.x qualify the CPU model (`max` or a named model), and add a host
      XSAVES preflight check or disclose `TIER_UNAVAILABLE`;
    - re-evaluate when a QEMU with the upstream fix is pinned;
    - no unreviewed upstream patch is applied.
    Detail: `profiles/strong-windows-qemu-whpx/README.md`, open item 3.
- **2026-11-06, F-04.1b: contract and profile amendments for a provisioned guest
  (Overseer decision as contract owner, under the Owner's F-04.1 authorization).** The
  Owner authorized a single-use root provisioning step and the Moby/Agent Server
  inspection workload in the qualified guest, repeatable under the guest-validation
  conditions above as amended for that step and workload only (decision 0006, "Owner
  authorization (2026-11-06)", Part B). Guest network, a `guestfwd`, a host share, an LLM
  credential or a new host port still need separate approval; `launch.argv` is unchanged
  and the tier stays not operational (C6). The contract and the QEMU profile now say:
  - **P6:** a provisioned guest's own Moby sockets (`/run/docker.sock` `root:docker`
    `0660`, containerd's socket `root:root` `0660`, and every socket under `/run/docker`
    and `/run/containerd` root-owned and not writable by others) are declared
    (`provisioning.moby.sockets`) and allowed; they are not host sockets. Negative checks:
    `agent` is not in group `docker`, its `connect()` to each declared socket fails with
    `EACCES`, `docker info` as `agent` is refused, and no TCP listener belongs to dockerd,
    containerd or docker-proxy (`profiles/README.md` P6, `profiles/properties.json`).
  - **P2:** Moby's daemon, containers and data root consume the guest's own resources
    inside the ceilings; they add no provider resource.
  - **P3, P4 (`guest_storage`):** Moby's own mounts are declared as optional patterns
    (overlay under `/srv/scratch/docker/overlay2/*/merged`, `nsfs` under
    `/run/docker/netns/*`, container `shm` under `/srv/scratch/docker/containers/*/mounts/shm`),
    and the root-owned directories `/srv/scratch/docker` (data root, on scratch) and
    `/var/lib/aieh` (the root step's state, on root) are declared `provisioned_only`.
    `tools/check_profile.py` checks them and the new `provisioning` block.
  - **P7:** unchanged. To keep it, the root step turns containerd's CRI plugin off (its
    streaming server listened on the guest's `127.0.0.1`) and IPv6 off on `docker0` and
    `veth*` (the first run found a link-local address on `docker0`); both are declared
    in `provisioning.moby` with the observation that required them.
  - **P5:** unchanged. Slice (b) generates no secret; the session API key and
    `OH_SECRET_KEY` belong to slice (c).
  - Ordinary guests are unaffected: their seed carries an empty manifest and the seeded
    units stay inert (`profiles/seed/README.md`).
- **2026-11-07, F-04.1c: contract amendments for the Agent Server in a provisioned guest
  (Overseer decision as contract owner, under the same Owner authorization).** The root
  step now also installs the OpenHands Agent Server release binary as a hardened systemd
  service under the system user `openhands`, with a non-secret configuration and two
  guest-generated secrets. Guest network, a `guestfwd`, a host share, an LLM credential
  and a new host port still need separate approval. `launch.argv` is unchanged, and the
  tier stays not operational (C6). The contract and the QEMU profile now say:
  - **P5:** the Agent Server's session API key joins the allowed, labelled guest-local
    secrets, beside the SSH keypair and `OH_SECRET_KEY`. Both secrets are generated in
    the guest into a root-only environment file. Neither is ever in the seed, the
    manifest, a log or a record; records carry fingerprints only. `OH_SECRET_KEY` never
    leaves the guest. The session key alone is exported, by SFTP as `agent`, into the
    instance directory, which `destroy` removes. The inspection adds: `agent` cannot
    open the environment file or the service's process environments, and neither value
    appears on the host or in the guest's records.
  - **P6:** `openhands` (system user, no login) is in group `docker`, as the guest's own
    service principal. `agent` stays outside `docker`.
  - **P7:** the Agent Server's listener on the guest's own `127.0.0.1` (class management,
    guest-local) is declared (`provisioning.agent_server.listener`). It is not forwarded:
    no `hostfwd` and no new host port; the Agent Server forward stays deferred (decision
    0006). Any other TCP listener in a provisioned guest must belong to the base image.
  - **P3, P4 (`guest_storage`):** the service's scratch directories under
    `/srv/scratch/openhands` (role `agent-server`, `provisioned_only`, owner
    `openhands`) are declared. Every data path of the configuration is one of them.
- **2026-11-07, F-04.2: P7 allowance for conversation containers (Overseer decision as
  contract owner, under the same Owner authorization).** The 1.60.1 Docker runtime publishes
  every conversation container with `-p 127.0.0.1::8000` (`docker_runtime/registry.py`), so
  `docker-proxy` holds a TCP listener on the guest's own `127.0.0.1` while a conversation
  runs. F-04.1c recorded that this breaks the P7 checks as written. Guest network, a
  `guestfwd`, a host share, an LLM credential and a new host port still need separate
  approval; `launch.argv` is unchanged and the tier stays not operational (C6). The
  contract and the QEMU profile now say:
  - **P7:** while conversation containers owned by the Agent Server run, each may have
    exactly one listener on the guest's `127.0.0.1` at an ephemeral port (inside
    `ip_local_port_range`), owned by `docker-proxy` or `dockerd` and mapped to that
    container's port 8000. There is no other Moby listener, never a non-loopback bind,
    and it is never forwarded to the host. The inspection now reads root's current
    `ss -ltnp` and the `docker-proxy` argv from an on-demand report; the boot-time report
    must still show no Moby listener.
  - **Root-only container facts on demand** (`provisioning.agent_server.conversations.facts`):
    `agent` creates a request file in a `root:agent 0730` directory under `/var/lib/aieh`
    (declared in `guest_storage`, role `facts-request`); a path unit starts a root oneshot
    that removes it unread, runs `docker ps` and `docker container inspect` only, for the
    containers carrying the server's owner label, and writes an agent-readable report
    (environment by name only, secret values counted and redacted). At most 20 runs in
    60 s; beyond that the units fail closed until the next boot.
  - **Conversation mount policy** (`provisioning.agent_server.conversations.mounts`): the
    effective mounts of a conversation container must equal the declared list exactly:
    three binds under `/srv/scratch/openhands` (the conversation's event store, its runtime
    home and the server-provisioned workspace). Never the Docker or containerd socket,
    `/srv/scratch/docker`, `/etc/aieh`, `/var/lib/aieh` or another host path. The image
    must be the locked image ID (decision 0006 item 3).
  - **Recorded, not failed** (decision 0001 s3, upstream behaviour): `--add-host
    host.docker.internal:host-gateway` on every container, no `--network none`, and
    request caps that replace the server's. They are carried to S-01.3.x and E-01.2.2.
  - P3 and P4 are unchanged: a conversation container's binds live in its own mount
    namespace, and the guest's mount table already declares Moby's own mounts.

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
