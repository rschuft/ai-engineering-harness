# Execution-profile contract

Plan leaf F-03.1. This contract defines the standard guest boundary, the guest
lifecycle, the host virtualization prerequisites, and the rules for selecting a
platform provider. It also records the unsupported cases and the remote-Linux
fallback. It is a **specification only**. Nothing here has been provisioned, and
every runtime claim is UNKNOWN until the leaves named in each property have run.

Authority:
- [Decision 0003](../decisions/0003-execution-guest-providers-and-isolation-contract.md),
  Accepted and binding, including its Owner selection and seven conditions.
- [Decision 0001](../decisions/0001-agent-server-dispatch-precondition-and-version-line.md)
  and its obligations in [`evidence/bootstrap-log.md`](../evidence/bootstrap-log.md).
- Blueprint
  [#infrastructure-state](../AI_Engineering_Open_Source_Blueprint_Architecture_Deep_Review_2026-10-31.html#infrastructure-state),
  [#containment-architecture](../AI_Engineering_Open_Source_Blueprint_Architecture_Deep_Review_2026-10-31.html#containment-architecture)
  (SEC-01:
  [#containment-final-decision](../AI_Engineering_Open_Source_Blueprint_Architecture_Deep_Review_2026-10-31.html#containment-final-decision),
  [#proof-SEC-01](../AI_Engineering_Open_Source_Blueprint_Architecture_Deep_Review_2026-10-31.html#proof-SEC-01))
  and [#platforms](../AI_Engineering_Open_Source_Blueprint_Architecture_Deep_Review_2026-10-31.html#platforms).

Companion files:
- [`matrix.md`](matrix.md): the platform-provider compatibility and fallback matrix,
  with a source for every cell.
- [`properties.json`](properties.json): the properties, tiers and lifecycle in
  machine-readable form.

Exact provider versions, image digests and profile instances belong to F-03.2.1. Task
targets belong to F-03.2.2. The choice of egress mechanism belongs to F-03.3.2.

**Identifiers.** Properties are cited as `profiles P1` to `profiles P12`. That keeps
them apart from other "P" labels in this repository: plan priorities (P0, P1) and the
dispatch preconditions P1-P5 that `evidence/bootstrap-log.md` assigns to E-01.3.1 and
E-01.5. Owner conditions are cited as C1 to C7.

## 1. Trust tiers

There are exactly two tiers. Nothing is in between.

| Tier | Boundary | Blueprint containment profile |
|---|---|---|
| `strong` | A separate guest kernel. Ceilings enforced by the provider. No shares beyond the allowlist. Network policy enforced outside the guest. The provider cannot be controlled from inside the guest. | **Standard autonomous** (`shared` mode) and **Elevated isolation** (`fresh` mode) |
| `trusted-workload` | A kernel shared with the host or with another guest the Owner uses. | **Trusted fast path**: explicit opt-in, with the residual risk recorded |

The blueprint's Inspect-only profile runs no repository code, so it needs no
execution guest. Its Privileged operation profile runs outside the agent environment,
so it is not an execution profile.

Neither tier is a principal boundary on the host. The `strong` tier buys a kernel
boundary, and the provider still runs as some host principal, which every record
discloses (`profiles P8`).

## 2. The standard guest boundary: properties P1 to P12

The inspection methods are what `inspect` records (section 3) and what the named test
leaves exercise. Values marked "observed only" are read and recorded, never written.

### P1 Separate kernel
- **strong:** the guest runs its own kernel under a hypervisor.
- **trusted-workload:** the kernel is shared, either with the host (an Incus container)
  or with the WSL utility VM, which also runs the Owner's distributions.
- **Inspect:** the provider type from a provider query. Compare `uname -r` inside the
  guest with the host kernel, or for WSL with the Owner's WSL kernel. For `strong`,
  also check that the provider reports a VM instance type.

### P2 Provider-enforced ceilings
- **strong:** vCPU, memory, root disk and scratch disk are set outside the guest:
  - Incus: `limits.cpu`, `limits.memory`, and the root disk device `size`.
  - QEMU: `-smp`, `-m`, and the image's virtual size from `qemu-img info`.
  - Lima: `cpus`, `memory`, `disk`.
- **trusted-workload:**
  - Incus container: cgroup limits from the same `limits.*` keys.
  - WSL: the ceilings are VM-wide and shared with every distribution, including the
    Owner's. They are observed only (C1).
- **Inspect:** a provider query (`incus config show --expanded`, the QEMU command line
  and QMP `query-cpus-fast`/`query-memory-size-summary`, `limactl list --json`).
  Then inside the guest:
  - `nproc` equals the declared vCPU count;
  - `MemTotal` in `/proc/meminfo` is between 85 % and 100 % of the declared memory
    (firmware and kernel reservations). F-03.2.2 may narrow this tolerance with a
    recorded reason, never widen it;
  - `lsblk -b` shows the root and scratch disks at their declared sizes.
- **Why it matters:** these are the outer caps that decision 0001's uncapped
  per-conversation overrides rely on. Moby's per-container caps (F-04.1) sit inside them.
- **Moby inside the ceilings (amended 2026-11-06, F-04.1):** in a provisioned guest,
  Moby's daemon, its containers and its data root (on the scratch disk) consume the
  guest's own vCPU, memory and disks. They add no provider resource: the ceilings above
  bound them all, and any per-container caps are set inside them.

### P3 No automatic host shares
- **strong:** no provider share exists except the one allowlisted exchange directory, if
  the profile declares one (`profiles P4`). For the Windows QEMU profile, none exists.
- **trusted-workload:** the same allowlist. For WSL, drive automount and fstab mounting
  are disabled in the distribution's own `/etc/wsl.conf` (section 6).
- **Inspect:** `findmnt -t 9p,virtiofs,drvfs,fuse.sshfs,cifs,nfs,smb3` shows nothing
  beyond the allowlist, and `/mnt/c` is absent. The full `findmnt -J` table is also
  compared with the profile's declared mount table, so a share of an unlisted type is
  still caught.

### P4 Repository exchange and scratch only
- **Exchange** is guest-owned storage, populated over the management channel: git over
  SSH on a loopback forward, or `incus file push`. A provider share is allowed only as
  one explicit, allowlisted directory outside the Owner's profile.
- **The Windows QEMU strong profile uses no host filesystem share at all.**
- **Scratch** is a second guest disk, sized by `profiles P2` and removed by `destroy`.
- **Configuration media** are the only other disk devices allowed: read-only media that
  the harness or the provider generates to deliver configuration. They are the QEMU
  NoCloud seed on a read-only virtio disk, and the Incus `cloud-init:config` and
  `agent:config` disk devices, which Incus presents as read-only CD-ROMs. Their content
  is limited by `profiles P5`, and each one is listed in the profile's declared devices
  (QEMU: `launch.argv`; Incus: the Incus profile's `devices`). They are not shares: the
  Incus 9p `config` share and any host filesystem share stay forbidden.
- **trusted-workload:** the same model. For WSL, the exchange is inside the dedicated
  distribution's own filesystem, never under `/mnt`.
- **Inspect:** the provider's device list shows only the root and scratch disks and the
  declared configuration media, each medium read-only (plus the allowlisted share, if
  any). Inside the guest, `findmnt` shows exchange and scratch at their declared mount
  points.

### P5 No Owner secrets
- **Launch:** the provider's launch environment is scrubbed to an allowlist. The seed
  and cloud-init hold only the per-instance public key and non-secret configuration.
- **Allowed and labelled:** per-instance guest-local secrets, namely the guest's SSH
  keypair and `OH_SECRET_KEY` (decision 0001), and in a provisioned guest the Agent
  Server's session API key (amended 2026-11-07, F-04.1). Provider and LLM credentials
  never enter the guest. They are used only behind the brokered `inference` endpoint
  class (`profiles P7`).
- **Custody of the Agent Server's two secrets (amended 2026-11-07, F-04.1).** The root
  step generates `OH_SECRET_KEY` and the session API key inside the guest. Both live only
  in a root-only environment file that systemd reads for the service; neither is in the
  seed, the manifest, a log or a record (records carry fingerprints only).
  `OH_SECRET_KEY` never leaves the guest. The session API key alone is exported, by SFTP
  as `agent` over the management channel, into the instance directory, which `destroy`
  removes.
- **trusted-workload:** the same rule.
- **Inspect:** inside the guest, scan pid 1's environment, the `agent` login shell's
  environment, every home directory and `/etc` for Owner-class patterns:
  - private-key headers;
  - cloud and Git-host token formats;
  - LLM-provider key formats;
  - the Owner's host account name and host profile path.

  A positive control plants a canary of each class in a scratch file, confirms that the
  scan reports it, and removes it. Without the positive control the result is UNKNOWN.
- **Inspect, provisioned guest (amended 2026-11-07):** `agent` cannot open the
  environment file or the service's process environments. Neither secret appears in the
  instance directory on the host, the collection above or the guest's own records. The
  session key is searched for as a literal, and `OH_SECRET_KEY` by its fingerprint over
  every 43-character window.

### P6 No host-management sockets or interop
- **strong:**
  - No docker, podman, incus or libvirt socket from the host is reachable in the guest.
  - No X11 or WSLg sockets.
  - **The guest's own Moby (amended 2026-11-06, F-04.1).** A provisioned guest runs Moby
    inside its own kernel. Its daemon socket `/run/docker.sock` (`root:docker`, `0660`),
    containerd's `/run/containerd/containerd.sock` (`root:root`, `0660`) and every other
    socket under `/run/docker` and `/run/containerd` are the guest's own, declared in the
    profile (`provisioning.moby.sockets`). They are not host sockets and are allowed. Each
    is owned by root, with group root or docker, and none is writable by others
    (connecting to a unix socket needs write permission); the declared ones give others
    no access at all. Neither the daemon nor containerd listens on a TCP port
    (containerd's CRI plugin is off). `agent` is not in group `docker` and cannot connect
    to any of them.
  - **The Agent Server's service user (amended 2026-11-07, F-04.1).** The system user
    `openhands` has no login shell and is in group `docker`. It is the guest's own
    service principal and reaches only the guest's own daemon socket. `agent` stays
    outside `docker`.
  - **Never inside a conversation container (amended 2026-11-07, S-01.4).** The guest's
    own Moby is reachable only from the guest itself, and never inside a conversation
    container: no engine socket, no engine TCP endpoint (S-01.3.2).
  - **The management principal starts only behind its controls (amended 2026-11-09,
    E-01.2.2).** The Agent Server's unit requires, and starts after, Moby (which requires
    the container guard) and a root quiesce step that runs before every server start: it
    removes every container, then neutralizes the job-writable stored state the server
    would act on in its own process (a `running` record becomes `error`; a record that is
    a link, a hard link, of another owner or of another conversation's id is moved into a
    root-only quarantine, never deleted). If any of them fails, the server does not start.
    The profile declares the step (`provisioning.agent_server.quiesce`) and `inspect`
    compares it with the boot facts.
  - A provider agent channel (incus-agent, QEMU guest agent) is declared, and is
    host→guest only.
- **trusted-workload (WSL):**
  - `interop.enabled=false` and `appendWindowsPath=false` in the distribution's
    `/etc/wsl.conf`.
  - WSLg (`guiApplications`) is VM-wide in `.wslconfig`, so it is observed and disclosed,
    never written (C1).
- **Inspect:**
  - `find / -xdev -type s` and `ss -xl`, checked against the declared agent channel;
  - the absence of `DOCKER_HOST`, `/var/run/docker.sock` from the host and `/mnt/wslg`;
  - no socket under `/tmp/.X11-unix`: nothing in it but directories, and the path
    itself not a symlink. The guest's own `tmpfiles.d` may create it as an empty
    directory, which is not a display or IPC channel (amended 2026-11-06, decision
    0003 "Current facts");
  - for WSL, launching a Windows `.exe` from inside the guest fails;
  - for a provisioned guest: the declared Moby sockets with their owner, group and mode;
    from root's boot-time report, no socket under `/run/docker` or `/run/containerd`
    writable by others; as `agent`, `connect()` to each declared socket fails with `EACCES` and
    `docker info` is refused; `agent` is not in group `docker`; and no TCP listener
    belongs to dockerd, containerd or docker-proxy;
  - for a provisioned guest's conversation containers (amended 2026-11-07, S-01.4, from
    S-01.3.2): from inside each container as its default user, every declared engine
    socket path is absent (Docker, containerd, Podman, BuildKit, CRI-O) and every socket
    found refuses; the engine ports 2375 and 2376 refuse at `host.docker.internal`, every
    guest address, the container's own loopback and SLIRP's `10.0.2.2` and `10.0.2.3`;
    and no engine variable is set (`job-access-probe`, and `inspect`'s conversation
    containers entry).

### P7 Network posture
- **Shape:** NAT or a managed bridge, never bridged onto the Owner's LAN. Inbound
  traffic arrives only through explicit forwards bound to host `127.0.0.1`.
- **Endpoint classes.** Guest→host is denied by default, except for four endpoint
  classes, which each profile enumerates with address, port and protocol:
  - `management`: the provider's control channel and SSH over the loopback forward;
  - `exchange`: repository exchange (`profiles P4`);
  - `inference`: the brokered LLM endpoint, the only path to provider credentials;
  - `provision`: package and image sources needed while provisioning. This class may be
    phase-limited and closed after provisioning.
- **Egress allowlist.** It is enforced **outside the guest**, and every profile names its
  enforcement point. Candidates for F-03.3.2 to qualify:
  - Incus bridge network ACLs. Caveat from the Incus documentation: on a bridge, the
    ACLs act only at the bridge-host boundary, and baseline network service rules
    (DHCP, DNS) are added before the ACL rules and cannot be blocked by them. Those
    baseline services must therefore be declared, or turned off on the bridge.
  - QEMU SLIRP `restrict=on`, with `guestfwd` to a host-side allowlisting proxy.
    `restrict=on` does not affect explicitly set forwarding rules, so each forward is an
    enumerated endpoint.
  - For Lima, see section 6. No Lima-native egress allowlist is identified, so that
    enforcement point is an open F-03.3.2 item.
- **Containers inside the guest.** Denial must hold **from inside a container in the
  guest**. Decision 0001's `host.docker.internal:host-gateway` resolves to the guest,
  not to the host, so a container must not reach the host through the guest either.
  (Amended 2026-11-07, S-01.4.)
  - **The guest's own listeners and the peer container are denied.** Their enforcement
    points are the container guard (every new connection from a container bridge to any
    address of the guest is refused) and `icc` off on Moby's bridge (no connection
    between two containers).
  - **Container egress** is enforced at the egress guard: every new connection that a
    container bridge forwards out of the guest is refused, except to the allowlist, which
    is exactly the endpoint classes the profile enables for containers (`inference`, and
    `provision` while it is open). None is enabled today, so the allowlist is empty.
- **IPv6** is off unless the profile lists it.
- **Guest-internal listeners (amended 2026-11-07, F-04.1).** A provisioned guest's Agent
  Server listens on the guest's own `127.0.0.1` only, at the port the profile declares
  (`provisioning.agent_server.listener`, class management, guest-local). It is not
  forwarded to the host: there is no `hostfwd` and no new host port, and the Agent
  Server forward stays deferred (decision 0006). Every other TCP listener in a
  provisioned guest must belong to the base image (`sshd`, `systemd-resolved`), except
  the bounded allowance below.
- **Conversation container listeners (amended 2026-11-07, F-04.2).** While conversation
  containers owned by the Agent Server run, each may have exactly one listener on the
  guest's `127.0.0.1` at an ephemeral port (inside the guest's `ip_local_port_range`),
  owned by `docker-proxy` or `dockerd` and mapped to that container's port 8000 (the
  1.60.1 Docker runtime publishes `-p 127.0.0.1::8000`). "Owned" means the container
  carries the Agent Server's owner label (`provisioning.agent_server.conversations`).
  There is no other Moby listener and never a non-loopback bind, and the listener is
  never forwarded to the host: no `hostfwd` and no new host port.
- **trusted-workload:**
  - WSL `networkingMode` is VM-wide, so it is observed only (C1).
  - Egress is not enforced outside the distribution, and the network namespace is
    shared with the Owner's distributions. This is disclosed on every run.
- **Inspect:**
  - connection attempts to the host gateway and the host's other addresses fail, both
    from the guest and from a container inside it;
  - for a provisioned guest (amended 2026-11-07, S-01.4): the container guard's and the
    egress guard's chains in both IP families, verified by the root step, the boot facts
    and `inspect`; from inside a container, the guest's listeners and the peer container
    refuse or do not answer, and the egress sweep (public addresses, SLIRP's aliases, an
    unconfigured guestfwd-class address) is refused by the egress guard, whose counters
    rise;
  - a positive control to one allowlisted endpoint succeeds;
  - `ip route`, `ip addr` and `ip -6 addr` are recorded;
  - for a provisioned guest: root's boot-time `ss -ltnp` shows no Moby listener. Root's
    current `ss -ltnp`, from the on-demand conversation facts (amended 2026-11-07,
    F-04.2), shows exactly the declared Agent Server bind for that process; any Moby
    listener only inside the conversation-container allowance (its `docker-proxy` argv
    names the address of a running owned container and port 8000, at most one per
    container); and no listener of any other process beyond the base image's. `agent`
    sees the same set.

### P8 Identity
- **Per instance:** a unique instance name. machine-id and SSH host keys are
  regenerated at `create`.
- **Guest user:** `agent`, non-root, with no sudo by default. Root SSH login is
  disabled.
- **Keys:** the per-instance SSH key is held in the harness state directory (section
  11), never in `~/.ssh`.
- **Host principal:** the provider's host principal is recorded and disclosed. For
  example, user-scoped QEMU runs as the Owner's Windows account. The strong tier buys a
  kernel boundary, not a principal boundary.
- **trusted-workload:** the same rules inside the distribution or container.
- **Inspect:** `/etc/machine-id` and host-key fingerprints differ between two instances
  and across `recreate`. `id agent` shows no sudo group. `sshd -T` shows
  `permitrootlogin no`. The provider query names the host principal.

### P9 Pinned boot inputs
- **Pinned:**
  - the image URL and sha256;
  - the firmware;
  - the kernel and initrd, if booting directly;
  - the seed digest;
  - the provider binary version;
  - the profile's git revision.
- **Reported:** the provider reports the digest it booted:
  - Incus: the image fingerprint;
  - Lima: `images[].digest`, verified on download;
  - QEMU: the harness hashes the image file immediately before launch, and records
    `qemu-img info`.
- **trusted-workload:** WSL imports a pinned tar by sha256.
- **Inspect:** the launch record lists each input with its digest. A mismatch refuses
  the launch.

### P10 Disposability
- **Rule:** `destroy` removes the instance and its storage and nothing else. `recreate`
  reproduces the same observed state. The Owner's data roots are untouched.
- **trusted-workload:** the same. For WSL, `destroy` is
  `wsl --unregister <dedicated name>` and nothing broader (C1).
- **Inspect:** F-03.4 proves this. It inventories the Owner's data roots before and
  after, and compares the `inspect` records across `recreate`.

### P11 Tier label
- **Rule:** every artifact (launch record, `inspect` record, evidence, log header)
  carries:
  - `tier`: `strong` or `trusted-workload`;
  - `provider`: for example `incus-vm`, `qemu-whpx` or `wsl2-distro`;
  - `nesting`: `none`, or `nested` when the provider's VM itself runs inside another VM
    (for example, KVM inside WSL2).
- **Inspect:** a schema check of every artifact.

### P12 Virtualization extensions
- **Rule:** the guest never relies on them.
- **Declared:** each profile declares `nested_virt_exposed`.
- **Observed:** `grep -c -E 'vmx|svm' /proc/cpuinfo` inside the guest.
- **strong:** strong profiles should mask the extensions. For example, Incus
  `security.nesting=false` on a VM turns off the svm and vmx flags (the VM default is
  `true`). F-03.2.1 decides, per profile, whether to mask or to declare exposure.
- **trusted-workload:** observed and declared only. WSL's `nestedVirtualization` is
  VM-wide, defaults to true and is never written (C1).

### Test leaves per property

| Property | Tested by |
|---|---|
| P1 | F-03.2.2 (observed state), F-03.4 |
| P2, P8, P9, P12 | F-03.2.1 (declared), F-03.2.2 (observed) |
| P3, P4, P5 | F-03.3.1; S-02.1, S-02.2 |
| P6 | F-03.3.1; S-01.3.1, S-01.3.2, S-01.4; S-02.1, S-02.2 |
| P7 | F-03.3.2; S-01.3.1, S-01.3.2, S-01.4; S-02.1, S-02.2 |
| P10 | F-03.4 |
| P11 | every leaf that produces an artifact |

## 3. Lifecycle

The operations form a closed set. A provider binding implements each one with the
provider's own CLI or API (blueprint
[#infrastructure-state](../AI_Engineering_Open_Source_Blueprint_Architecture_Deep_Review_2026-10-31.html#infrastructure-state),
"use upstream-native declarations").

| Operation | Contract |
|---|---|
| `preflight` | Prints the capability report (section 4). Changes nothing on the host. |
| `create` | Creates and boots a new instance from the pinned inputs (`profiles P9`), with fresh identity (`profiles P8`). **Refuses if the name already exists.** |
| `start` | Starts a stopped instance with its recorded configuration. |
| `stop` | Graceful shutdown first (Incus `stop`, QMP `system_powerdown`, `limactl stop`, `wsl --terminate <dedicated name>`). After the profile's `stop_timeout_s` (contract default 120 s, at most 300 s) it is forced. `wsl --shutdown` is never used, because it stops every distribution, including the Owner's (C1). |
| `destroy` | Idempotent. Removes only the instance and its storage. Destroying an absent instance succeeds and reports `absent`. |
| `recreate` | `destroy`, then `create` under the same name and profile. The result must match the previous `inspect` record, except for identity (`profiles P8`). |
| `inspect` | Emits a machine-readable record of P1 to P12: the declared value, the observed value, the method used, and PASS, FAIL or UNKNOWN for each, labelled per `profiles P11`. |
| `exec` | Runs a command in the guest, **for operators and provisioning only**. It is never offered to agents, who reach the guest only through the Agent Server path. |
| `exchange push` | Copies a bounded repository snapshot into the guest's exchange storage over the management channel. |
| `exchange pull` | Copies candidate revisions and evidence out to a harness-owned staging location, as data. It never writes into the Owner's repositories. |

**Modes:**
- `shared`: one long-lived guest, reused for approved work in one trust domain
  (Standard autonomous).
- `fresh`: a new guest per attempt or per trust domain, destroyed after its evidence is
  exported (Elevated isolation).

There is no snapshot or restore operation.

## 4. Disclose and refuse

1. **Explicit tier.** The tier is in the profile name and in its front matter. Profile
   names have the form `<tier>-<host>-<provider>`, for example
   `strong-windows-qemu-whpx`, `trusted-workload-windows-wsl2-distro` and
   `strong-incus-vm`. Decision 0003's short names (`windows-qemu-whpx`,
   `windows-wsl2-distro`) are the `<host>-<provider>` part. No default, environment
   variable or automatic selection picks a tier or a profile.
2. **Capability report.** `preflight` prints a report for each provider. Each entry gives
   `available` or `unavailable`, the reason, and **the exact Owner act that would change
   it**, for example "A1: enable the `HypervisorPlatform` optional feature and restart".
3. **No substitution.** A `strong` `create` with no strong provider available exits
   non-zero with the machine-readable refusal `TIER_UNAVAILABLE`, naming the profile, the
   reason and the Owner act. It never substitutes another tier, provider or remote.
4. **Explicit trusted-workload.** A `trusted-workload` profile runs only when the
   invocation names it. Every run prints, and every artifact records, the disclosure that
   it is **not VM-grade isolation**.
5. **Explicit remote.** The remote fallback (section 8) is an explicit profile and remote
   name. It is never chosen automatically when a local provider is unavailable.

**Windows rank order.** Decision 0003 ranks the Windows strong-tier candidates as
follows. The rank is guidance for the Owner's choice; selection is never automatic.
1. A remote Incus host.
2. The Hyper-V role.
3. QEMU with WHPX: **the reference profile, selected by the Owner (W1)**.
4. Lima or Multipass over HCS (to be qualified).
5. KVM inside a dedicated WSL2 distribution (to be qualified; nested, never the
   specified path).
6. VirtualBox or VMware on WHP (permitted, not preferred).

## 5. Nested virtualization

**The guest needs none.** Moby inside the guest runs on runc, cgroups v2, namespaces,
overlayfs and netfilter, and F-04.1 keeps `default-runtime: runc`.

**Never assumed inside the guest:**
- `/dev/kvm`;
- Kata, Firecracker, Cloud Hypervisor, gVisor-KVM;
- Incus VMs;
- WSL or Docker Desktop;
- Hyper-V isolated containers;
- nested QEMU/KVM.

The only provider that is itself nested is KVM inside a dedicated WSL2 distribution. It
is a QUALIFY candidate, labelled `nesting: nested` (`profiles P11`), and never the
specified path (C7).

## 6. Provider-specific requirements

Each requirement cites the Owner conditions in section 9.

### Windows: QEMU with WHPX (reference; W1)
- **Owner acts first:** A1 (enable `HypervisorPlatform` and restart), A2 (a user-scoped,
  pinned QEMU) and A3 (a guest-state directory outside the Owner's profile). Each needs
  its own recorded approval (C2). Until then, `preflight` reports `unavailable`.
- **Pinning:** QEMU is pinned and checksum-verified, and the full command line is
  generated from the profile, so it is reproducible (C3).
- **Storage:** guest images, scratch disks and keys live under the A3 directory (C4).
- **No host filesystem share** of any kind: no `-virtfs`, no SMB, no 9p (`profiles P4`,
  C5). The NoCloud seed is a read-only configuration medium (`profiles P4`), not a share.
- **Network:** user-mode networking with `restrict=on`. `hostfwd` binds only to
  `127.0.0.1` (management, exchange). `guestfwd` points to host-side endpoints for
  `inference` and `provision` (`profiles P7`, C5).
- **Agent channel:** the QEMU guest agent, if used, is declared and host→guest only
  (`profiles P6`).
- **Accelerator:** `whpx`. The profile never relies on `/dev/kvm` inside the guest
  (C7). F-03.2.1 records whether the extensions are masked (`profiles P12`).
- **Not operational** until F-03.3.1, F-03.3.2, F-03.4 and S-02.x pass (C6).

### Windows: dedicated hardened WSL2 distribution (trusted-workload only)
- **Separate distribution.** A separate distribution is imported from a pinned tar under
  its own name. The harness never starts, configures, stops or depends on the Owner's
  distribution, and never writes `%USERPROFILE%\.wslconfig` (C1).
- **Its own `/etc/wsl.conf`:**
  - `[automount] enabled=false`, `mountFsTab=false`;
  - `[interop] enabled=false`, `appendWindowsPath=false`.
- **Observed only:** the VM-wide `.wslconfig` values (`memory`, `processors`,
  `networkingMode`, `nestedVirtualization`, `guiApplications`) are observed, recorded
  and disclosed. They are **never written** (C1).
- **Shared VM.** All WSL 2 distributions share one utility VM: the kernel, CPU, memory,
  swap and network namespace. This profile can therefore never be `strong`, whatever
  its settings.
- **Destroy:** `wsl --unregister <dedicated name>` only. Never `wsl --shutdown` (C1).

### Linux and remote: Incus virtual machine
- **Instance:** an Incus VM instance with `limits.cpu`, `limits.memory`, a sized root
  disk and one scratch disk. **No other disk devices** except the read-only
  configuration media `cloud-init:config` and `agent:config`. The 9p `config` share is
  not allowed (`profiles P3`, `profiles P4`).
- **Masking:** `security.nesting=false` is the candidate mask for `profiles P12`.
- **Network:** a managed NAT bridge with network ACLs as the candidate enforcement
  point (`profiles P7`, with the baseline-service caveat).
- **One profile, two targets.** The native Linux profile and the remote profile are one
  Incus profile, addressed to different remotes (`local`, or a named remote).
- An Incus container on the same host is `trusted-workload`.

### macOS: Lima, used directly
- **Machine type:** `vmType: vz` on macOS 13.5 or later, otherwise `qemu` with HVF.
- **Overrides:** see section 7.
- **Lima's own configuration directory.** Lima combines `mounts` and other lists from
  `$LIMA_HOME/_config/default.yaml` and `override.yaml` with the instance template.
  The harness therefore sets `LIMA_HOME` to its own state directory (section 11), so
  that no Owner-level Lima configuration applies. `inspect` reads the *effective*
  configuration.
- **The template must not inherit `template:_default/mounts`.** Lima's default template
  inherits a read-only home mount through that base.
- **Host loopback.** `networkOpts.hostLoopback: false` stops the guest reaching host
  loopback services through `host.lima.internal`. It exists since Lima 2.3 and only with
  `vmType: vz`, and does not cover the host's other addresses. It is a candidate for
  F-03.3.2 to qualify. The egress enforcement point outside the guest for Lima is
  **open**: F-03.3.2 must name and qualify one. Until it does, the macOS strong profile
  is not operational (C6).

## 7. Default-share overrides, by name

| Provider | Required overrides |
|---|---|
| Lima | `mounts: []` (and no `_default/mounts` base). `propagateProxyEnv: false`. `ssh.forwardAgent: false`. `nestedVirtualization: false`. A catch-all `portForwards` rule with `ignore: true` after any explicit forwards. `images[].digest` is mandatory. `plain: true` is preferred, to be qualified in F-03.2.1. |
| Colima | **Excluded from the strong tier.** By default it mounts `$HOME` writable and publishes the guest's Docker socket on the host at `$HOME/.colima/<profile>/docker.sock`. |
| WSL (trusted-workload) | In the distribution's own `/etc/wsl.conf`: `automount.enabled=false`, `automount.mountFsTab=false`, `interop.enabled=false`, `interop.appendWindowsPath=false`. |
| Incus | No disk devices beyond root, scratch and the read-only `cloud-init:config` and `agent:config` media (`profiles P4`). No 9p `config` share. |
| QEMU | No `-virtfs`, no SMB, no host-directory block device. `-nic user,restrict=on` with loopback-bound `hostfwd` only. |

## 8. Remote-Linux fallback: minimum contract

The remote fallback is an explicit profile (`strong-incus-vm` addressed to a named
remote), never selected automatically.

1. **Host.** An Owner-controlled Linux host with KVM, meeting the pinned Incus floors
   (section 10).
2. **API exposure.** `core.https_address` is reachable only over an authenticated path,
   for example a VPN or an SSH tunnel. It is never exposed on an open network.
3. **Client trust.** The client is added with a one-time trust token. Its certificate is
   `restricted` to one dedicated project.
4. **Client key.** The client key is a harness credential held on the Owner host, in the
   harness state directory, outside any guest.
5. **No Owner secrets.** The remote holds no Owner secrets, and Incus runs there under
   its own OS user, not the Owner's.
6. **Isolation on the remote.** A dedicated project, a quota'd storage pool, and a NAT
   bridge with ACLs.
7. **Same operations.** The same lifecycle and inspection operations (section 3), run
   remotely.
8. **Records.** Every record names the remote's hostname and its server certificate
   fingerprint.
9. **One profile.** The native Linux profile and the remote profile are one Incus
   profile, addressed to different remotes.

## 9. Owner conditions (decision 0003, Owner selection 2026-11-06)

These conditions bind every profile and provider requirement above.

- **C1.** The Owner's existing WSL2 Ubuntu environment is preserved, with no
  modification or disruption. Probes, provisioning and tests must not start, configure
  or depend on it. **The harness never writes `%USERPROFILE%\.wslconfig`.** WSL
  VM-wide values are observed and never written.
- **C2.** Selecting a provider authorizes no installation, no change to Windows
  features, no reboot and no other privileged host change. Each such act needs its own
  Owner approval at the point it is actually required, recorded in
  `evidence/bootstrap-log.md`:
  - A1: enable `HypervisorPlatform` and restart;
  - A2: install QEMU;
  - A3: create the guest-state directory.
- **C3.** QEMU releases are pinned and checksum-verified, and the configuration is
  reproducible.
- **C4.** Guest storage is kept separate from the Owner's existing repositories and
  environments.
- **C5.** Untrusted workloads get no host directories, credentials, management
  interfaces or unrestricted networking (`profiles P3` to `profiles P7`).
- **C6.** The strong-security profile is not declared operational until observable
  isolation tests pass: F-03.3.1, F-03.3.2, F-03.4 and S-02.x, cited by property id.
- **C7.** No dependence on nested virtualization.

## 10. Version floors and the pin rule

**Pin rule.** F-03.2.1 pins exact provider versions, binary hashes and image digests.
A provider binary that does not match its pin is refused by `preflight`.

**Floors**, below which no pin may go:
- **Incus:** as documented by its pinned release. Today that is kernel ≥ 6.12, and
  QEMU ≥ 8.2 for VMs.
- **QEMU (Windows):** the current stable release with the WHPX accelerator.
- **Lima:** ≥ 2.3, and HCS only if it is ever qualified. On macOS: `vz` on 13.5 or later.
  Lima publishes no numeric minimum macOS version ("the latest version is recommended"),
  so F-03.2.1 records the tested macOS version as the floor.
- **WSL:** 2.x, using the Windows 11 configuration keys.

### What "passes provider configuration validation" means for F-03.2.1

The provider's own parser accepts the declared configuration, without starting any
untrusted workload:
- **Incus:** the server accepts the profile, and `incus config show --expanded`
  round-trips it.
- **Lima:** `limactl validate`.
- **QEMU:** a paused boot (`-S`) with the full command line, then QMP `quit`.
- **WSL (trusted-workload profile only, and only with Owner authorization, because of
  C1):** import the pinned tar under a scratch name, read back `/etc/wsl.conf`, then
  unregister that scratch name.

In addition, a harness schema check confirms that every boot input (`profiles P9`) is
pinned by digest.

## 11. Host state directory

Images, disks, per-instance keys, the remote client key, `LIMA_HOME` and launch records
live in one harness state directory:
- **outside the checkout;**
- **outside the Owner's profile:** not under `%USERPROFILE%` or `$HOME`. On Windows,
  this is A3;
- named explicitly by the Owner, never defaulted.

None of it is committed. Profile *declarations* (F-03.2.1) are committed under
`profiles/`. Their *instances* and records are not.

## 12. Unsupported cases

In each case, `preflight` reports `unavailable` with the reason. A strong request
refuses with `TIER_UNAVAILABLE`.

| Case | Consequence |
|---|---|
| Firmware virtualization off | No local provider. Owner act: enable it in firmware. |
| Windows Home without WHP enabled or authorized, and no remote host provided | No strong tier. Owner act: A1 (and A2, A3), or provide a remote Incus host. |
| Windows 10 | Unsupported. The Windows 11 configuration keys and the Lima HCS requirement are not met, and nothing is qualified there. |
| Windows on Arm64 | Unsupported by this contract: not qualified, and the component lock pins Windows x86_64 only. Upstream QEMU lists WHPX on Arm, so this is a scope limit, not an upstream one. |
| The Hyper-V role on Home | Unavailable. Microsoft documents that it cannot be installed on Home editions. |
| Linux without `/dev/kvm` access | `trusted-workload` Incus containers only. |
| Below the pinned Incus kernel or QEMU floors | Refused by `preflight`. |
| macOS below Lima's supported versions | Refused by `preflight` (`vz` needs 13.5 or later). |
| A provider binary that is not the pinned version | Refused by `preflight`. |
| CI or cloud VMs without nested virtualization | No local strong provider (the provider would itself need nesting). Use a remote Incus host. |
| Docker Desktop | Not a provider in this contract. |
