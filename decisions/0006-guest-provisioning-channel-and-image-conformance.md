# 0006 - Guest provisioning channel and image conformance

Status: Accepted (Overseer) - 2026-11-07, after slices (b) and (c) of F-04.1 were evidenced
(`evidence/F-04.1b-provision-moby.md`, `evidence/F-04.1c-agent-server.md`). It implements the Owner's
design direction, and the Owner authorized the actions it depends on (see "Owner authorization" below).
Proposed 2026-11-06.
Gate: architecture consultation before F-04.1, gates C (several plausible provisioning
structures) and G (the isolation boundary of the qualified guest).
Supersedes: none. Refines how [decision 0001](0001-agent-server-dispatch-precondition-and-version-line.md)
item 4 is enforced; its intent is unchanged.

## Context
F-04.1 must get Moby and the pinned OpenHands Agent Server running inside the qualified
strong guest (`profiles/strong-windows-qemu-whpx`). That guest has no egress at any
phase: SLIRP `restrict=on`, `ipv6=off`, and the `provision` endpoint class is deferred
(decision 0003, F-03.3.2). Root exists in the guest only through cloud-init at create;
`agent` has no sudo, root SSH is refused, `/tmp` is a tmpfs, and the exchange carries
bundles only (256 MiB). Moby was not pinned anywhere. The Agent Server image was pinned by
its index digest, which a classic Docker image store cannot resolve offline as a
`repo@sha256` reference.

The Owner's direction (2026-11-06, verbatim, the passages that set the design):

> Trusted host downloads pinned upstream artifacts → existing SSH/SFTP management channel
> transfers them into the isolated guest → native upstream installation tools install
> them inside the guest.
>
> The runtime guest retains its existing default-deny network configuration throughout.
>
> The implementation should reuse existing download, package, container-image,
> integrity-verification, and transfer tools. Do not build custom package resolution,
> OCI registry handling, or a general-purpose provisioning framework.
>
> Host-side retrieval must not require executing untrusted package installation scripts
> or downloaded application code on the trusted host.
>
> **Alternative architectures have a high burden of proof.**
>
> A temporary provisioning proxy is justified only if the Architect demonstrates that
> host-side retrieval and transfer cannot satisfy F-04.1's actual requirements, or would
> require materially more custom code and complexity.
>
> A separate provisioning VM has an even higher bar. Do not introduce one merely for
> additional isolation, architectural elegance, or speculative future requirements. It
> must address a concrete limitation that the existing host-download and guest-transfer
> arrangement cannot reasonably solve.
>
> […]
>
> Do not expand the F-04.1 scope. Do not reopen already-qualified VM isolation without
> evidence of an actual defect.
>
> The objective is to get Moby and the pinned OpenHands Agent Server running inside our
> existing qualified VM, not to design a provisioning platform.

The Architect's consultation (gates C and G), accepted by the Overseer, found no concrete
blocker to that default. It weighed and rejected:
- **A temporary provisioning proxy.** It adds a new guest-to-host path. A QEMU chardev
  `guestfwd` is a single stream (it connects once at QEMU start; F-03.3.2 observed this),
  and the guest would need network on every fresh create.
- **A provisioning VM.** It is a superset of the chosen design: the same pinned
  artifacts, plus a second guest and a second channel.
- **A read-only provisioning medium** (a disk attached at create). Recorded as an
  alternative for R-03.x; it changes `launch.argv` and the qualified device table.
- **A golden image.** Left to R-03.x.
- For the image tool: **skopeo** has no Windows binary, and **`docker save`** needs a
  daemon on the host (there is none, and the Owner's WSL is protected). `regctl` is the
  fallback if crane fails.

## Owner authorization (2026-11-06)
The Owner answered "A and B (Recommended)" to the Overseer's F-04.1 question, verbatim:

> Part A, host side:
> - Download pinned files into D:\aieh-guest-state\provision\, from original upstreams
>   with hashes checked: Debian docker.io and docker-cli packages, and their signed index,
>   from snapshot.debian.org; the agent-server container image by its locked digest from
>   ghcr.io (likely several GB); the agent-server release binary from GitHub.
> - Run one pinned, checksum-verified upstream tool, `crane` (Google go-containerregistry),
>   from the state directory without installing it. It only fetches the image, the same
>   way uv, syft and Gitleaks are used.
> - Nothing else downloaded executes on the host: no .deb is unpacked, no image is run,
>   no admin rights, no PATH, registry, firewall or WSL changes.
> - Plus one ordinary disposable guest (non-root, no network) that resolves the package
>   list with apt against the pushed index.
>
> Part B, guest side:
> - A new single-use root step, set up by cloud-init at guest creation: after the files
>   arrive over the existing SSH/SFTP channel, it copies and sha256-verifies them, then
>   installs Moby with apt and loads the image with `docker load`.
> - It also installs the Agent Server as a service under a dedicated no-login user, and
>   generates guest-local secrets that never leave the guest except a per-instance
>   session key.
> - Then it deletes the uploaded files and disables itself.
> - Moby and the Agent Server then run in the guest for F-04.1/F-04.2 inspection only: no
>   LLM, no repository content, no untrusted workload.
>
> Unchanged throughout: no guest network at any phase, no guestfwd, no host shares, the
> QEMU command line, and the tier stays not operational.
>
> Selected option text: "Authorize both, repeatable under the existing guest-validation
> conditions, which are amended to allow this root provisioning step and the Moby/Agent
> Server inspection workload. Any guest network, guestfwd, host share, LLM credential or
> new host port still needs separate approval."

## Decision
1. **Provisioning channel.** The host downloads pinned upstream artifacts (0005). They
   enter the guest over the management SSH/SFTP forward into the agent-owned scratch
   directory. A one-shot root unit seeded by cloud-init at create, triggered once by a
   host marker, copies, verifies against seed-pinned sha256 values, and installs with
   native tools, then deletes the upload and disables itself. The guest has no egress at
   any phase; the `provision` endpoint class stays deferred and unused.
2. **Artifacts and tools.** Debian docker.io, docker-cli and their closure from
   snapshot.debian.org at one timestamp, resolved by apt inside a disposable guest
   against the signature-verified pinned index, and downloaded by URL and sha256. The
   agent-server image by locked index digest through pinned crane, verified by config
   digest (image ID) and layer digests. The agent-server release binary by SHA256SUMS.
   Pins live in `profiles/strong-windows-qemu-whpx/provision.lock.json`;
   `components.lock.json` records the image's linux/amd64 config digest. No custom
   resolver, registry client or repository.
3. **Image conformance** (refines the enforcement in 0001 s4; the intent is unchanged).
   The locked digest is enforced by image ID: `conversation_image` names a local
   immutable tag whose image ID equals the config digest under the locked index, and
   every conversation container's `.Image` must equal it (F-04.2, E-01.5). A verbatim
   `repo@sha256` reference is adopted only if a later probe shows it resolving offline.
4. **Guest composition.** Moby from Debian, with data-root on scratch, unix socket only,
   default runtime runc. The Agent Server release binary as a systemd service under
   `openhands` (system user, group docker). `agent` is never in docker. `OH_SECRET_KEY`
   and the session API key are guest-generated, labelled guest-local secrets (P5); the
   former never leaves the guest. Explicit per-conversation caps inside the guest
   ceilings. All conversation state and worktrees on scratch.
5. **Modes and recovery.** `shared` is the reference; `fresh` re-provisions from the host
   cache. Recovery is recreate and provision; the cache is rebuilt only when pins change.
6. **Not chosen:** a temporary provisioning proxy; a provisioning VM; a read-only
   provisioning medium (recorded alternative for R-03.x); a golden image (R-03.x).

## Consequences
- **Decision 0001 item 4** is enforced by image ID plus a local immutable tag instead of
  a literal `repo@sha256` reference, because the classic image store cannot resolve that
  reference offline. The intent (only the locked image conforms; the floating
  `latest-python` default is non-conforming) is unchanged. `components.lock.json` keeps
  the index digest as the locked reference and now also records the linux/amd64 config
  digest.
- **The bootstrap-log obligation** "run resolve.py inside the Linux guest (CPython 3.12)"
  is re-scoped by the Overseer to the first leaf that runs SDK Python in the guest. The
  release binary makes guest-side wheels unnecessary for F-04.1.
- **The Agent Server API hostfwd is deferred.** F-04.1 does not need it; it is requested
  only when the host-side dispatcher needs it, and it needs separate approval (a new host
  port).
- **The guest-validation conditions** of decision 0003 are amended by the Owner
  authorization above for this root provisioning step and the Moby/Agent Server
  inspection workload only. Guest network, a `guestfwd`, a host share, an LLM credential
  or a new host port still need separate approval. `launch.argv` is unchanged and the
  tier stays not operational (C6).
- **The resolved closure is relative to the base image.** apt resolved it against the
  installed set of Debian 13 genericcloud build 20261103-2651. A different base image, or
  a new snapshot timestamp, needs a new resolution and a new lock.
- **Builder constraints for slices (b) and (c):** no network in the guest, ever; no
  `launch.argv` change; root consumes only seed-pinned hashes (copy, then verify, then
  install); every digest the guest enforces traces to the committed lock through the
  seed; no code from downloaded artifacts runs on the host (crane is a pinned, verified
  tool); uploads are deleted after install and daemon state is root-only;
  `conversation_image` resolves offline; `agent` is never in docker; failed and unknown
  outcomes are preserved.
- Migrate this record into OpenSpec when adopted.

## Current facts (2026-11-06, F-04.1 slice (a))
Detail and raw outputs: [`evidence/F-04.1a-provision-pins-fetch.md`](../evidence/F-04.1a-provision-pins-fetch.md).
- **Decision 0001 s1 revisit check.** `composition/resolve.py` exited 0 with 348 checks,
  0 failed, and the F-01.2 `installed_digest` `2ee95857…329757`. Its `resolution_digest`
  differs from F-01.2 only through the lock file's own hash (the licence-text correction
  of `a7a419c`): recomputed with the F-01.2-era lock files it equals F-01.2's
  `b23c42b2…94e1ce`. No upstream pin changed.
- **Resolution guest** (ordinary, disposable, `agent` uid 1000, no network): Debian 13.7,
  kernel `6.12.115+deb13.1-cloud-amd64`, apt 3.0.3 verifying with `sqv` 1.3.0 and
  `debian-archive-keyring` 2025.1. `/var/lib/apt/lists` is empty in the image. Present:
  GNU tar 1.35, python3 3.13.5, iptables 1.8.11; absent: git. `overlay`, `br_netfilter`,
  `nf_tables`, `iptable_nat`, `veth`, `bridge`, `nf_nat`, `nft_chain_nat` and
  `xt_MASQUERADE` exist as loadable modules (none built in, none loaded; `overlay` is not
  yet in `/proc/filesystems`).
- **Signature.** `apt-get update` as `agent` stored both InRelease files only after `sqv`
  verified them (the signer fingerprints are in the lock); a copy of the main InRelease
  with one changed byte was refused ("Message has been manipulated", update exit 100, no
  lists stored).
- **Closure** at snapshot `20261106T143859Z`, `--no-install-recommends`: runc
  1.1.15+ds1-2+b4, containerd 1.7.24~ds1-6+deb13u1, tini 0.19.0-3+b8, docker.io
  26.1.5+dfsg1-9+deb13u1, docker-cli 26.1.5+dfsg1-9+deb13u1 (66,670,140 bytes). The
  main-only resolution gives the identical set. apt 3.0.3 `--print-uris` prints MD5Sum
  only, so the sha256 values come from `apt-cache show` over the verified lists and were
  cross-checked on the host against the pinned `Packages.xz`.
- **Image.** Index `sha256:b43ee580…` → linux/amd64 manifest `sha256:8496d13f…` → config
  `sha256:e8959dfc8e184f629b63dcd709f39b1cb0c804c8d19f34ba7a9e2cc8854042cb` (the image
  ID), 22 layers (20 distinct), 1,272,014,245 compressed bytes; read with crane 0.22.1.
- **Fetch.** `tools/guest.py provision-fetch` staged 13 files (1,486,878,064 bytes) under
  `D:\aieh-guest-state\provision\f02e430a…8168e0\` in 43.5 s, including a 21.6 s
  `crane pull`. Every file matched the lock; the archive's config and layer members
  matched the lock. A second run re-verified and reused the stage in 1.8 s with no
  download.
- **For slice (b):** the crane archive's `manifest.json` carries
  `RepoTags: ["ghcr.io/openhands/agent-server:i-was-a-digest"]` (go-containerregistry's
  placeholder for a digest reference), so `docker load` creates that tag. The root step
  must remove it and keep only the local immutable tag, whose image ID is checked.

## Current facts (2026-11-06, F-04.1 slice (b))
Detail and raw outputs: [`evidence/F-04.1b-provision-moby.md`](../evidence/F-04.1b-provision-moby.md).
- **Root step.** The seed (`profiles/seed/user-data.tmpl`) always carries
  `/usr/local/sbin/aieh-provision`, `aieh-provision.path` (`PathExists=…/READY`),
  `aieh-provision.service` and `aieh-docker-facts.service`; only `create --provision`
  seeds a manifest (base64, root `0600`), and without one the units are inert. The step
  copies into a root-only staging directory, verifies every sha256 against the seeded
  manifest, writes `daemon.json` and a sysctl drop-in, installs with `apt-get install
  --no-install-recommends ./…` from local files (no `apt-get update`, no `--force-*`, no
  network), replaces containerd's packaged config, loads the image, checks its ID, keeps
  only the local tag, runs it once, deletes the upload, disables its trigger and writes
  `RESULT.json` last.
- **Observed** in three fresh guests (two runs and `smoke --provision`, whose recreate
  provisions again): upload of 7 files, 1,476,711,620 bytes, by one `sftp -b` batch in
  10.8 to 12.6 s (about 125 MiB/s over SLIRP); root step 77.4 to 77.9 s, of which
  `docker load` about 60 s. Moby: docker.io 26.1.5+dfsg1 (containerd 1.7.24~ds1, runc
  1.1.15+ds1), data root `/srv/scratch/docker`, overlay2, runc, cgroup v2 with the systemd
  driver, security options apparmor, seccomp (builtin), cgroupns, no-new-privileges; dockerd
  loaded overlay, br_netfilter, bridge and the netfilter NAT modules itself. Image ID
  `sha256:e8959dfc…42cb` = the locked config digest; only `aieh/agent-server:1.60.1-b43ee580`
  remains; `docker run --rm --entrypoint true` exited 0. `agent` is not in group docker,
  `connect()` to both daemon sockets is `EACCES` and `docker info` is refused; no TCP
  listener of Moby; no IPv6 on `docker0`. P1 to P9, P11 and P12 PASS after provisioning,
  after a restart (Moby and the image back) and after recreate; the smoke test passed.
- **Found and fixed forward:** Debian's containerd enables the CRI plugin, whose
  streaming server listened on the guest's `127.0.0.1`; `docker0` took an IPv6
  link-local address after a container ran. Both are now turned off by declared files
  (`provisioning.moby.containerd_config`, `provisioning.moby.sysctl`).
- **Not yet:** the Agent Server service, its configuration and secrets (slice (c)).
  `conversation_image` is the local tag; item 3 holds as observed.

## Current facts (2026-11-07, F-04.1 slice (c))
Detail and raw outputs: [`evidence/F-04.1c-agent-server.md`](../evidence/F-04.1c-agent-server.md).
- **Service.** The same single-use root step now:
  - installs the release binary `agent-server-1.60.1-linux-x86_64` at
    `/opt/aieh/agent-server/agent-server` (`root:root` `0755`, sha256 `b2fbcf8c…ce72` =
    the lock) as `aieh-agent-server.service`;
  - runs it under the system user `openhands`: shell `/usr/sbin/nologin`, password locked,
    groups `openhands` and `docker`; `agent` stays outside `docker`;
  - binds it with `--host 127.0.0.1 --port 8000`;
  - hardens the unit with `NoNewPrivileges`, an empty capability set,
    `ProtectSystem=strict` (writable only `/srv/scratch/openhands`), `ProtectHome`,
    `PrivateTmp`, `PrivateDevices`, `ProtectProc=invisible`, `RestrictNamespaces`,
    `@system-service` and `IPAddressDeny=any` with `IPAddressAllow=localhost`;
  - configures it through `OPENHANDS_AGENT_SERVER_CONFIG_PATH`: `conversation_runtime`
    docker, not selectable, `conversation_image` `aieh/agent-server:1.60.1-b43ee580`,
    caps 4g / 2.0 CPUs / 512 pids with `max_concurrent_runs` 3, every data path under
    `/srv/scratch/openhands`, no webhook, telemetry exporter none, no VSCode, no tool
    preload;
  - generates `OH_SECRET_KEY` and the session API key in the guest into a `root:root`
    `0600` environment file.

  `provision` fetches the session key alone into the instance directory. The server
  was ready about 5 s after the step began. The root step took 87.5 s in all.
- **Observed** (`/server_info`, as `agent` on the guest loopback): `version` 1.60.1
  (with SDK, tools and workspace 1.60.1), `conversation_runtime` docker,
  `available_conversation_runtimes` [], and `capabilities` including
  `conversation_runtime_routes_v1` and `idempotent_conversation_create_v1`. Decision 0001
  s2's conditions hold. The session key is enforced: 200 with it, 401 without it or with
  a wrong one. The engine endpoint is `unix:///var/run/docker.sock`: there is no
  `DOCKER_*` variable, and `openhands` reaches Moby 26.1.5+dfsg1. At start-up the
  server ran `docker ps -aq --filter …` and logged no warning. The configured image
  resolves offline to the locked image ID.
- **Egress at start-up.** LiteLLM tried to fetch its model cost map from
  raw.githubusercontent.com. Name resolution failed (the guest's resolver has no
  upstream), LiteLLM fell back to its bundled copy, and the server came up without
  network. No other outbound attempt was logged.
- **Secrets.** `agent` gets `EACCES` on the environment file and on the service's
  process environments. Neither value appears:
  - in the instance directory on the host (14 files; `OH_SECRET_KEY` searched by
    fingerprint);
  - in the 612-member collection read as `agent`;
  - in RESULT.json, the config, the manifest, cloud-init's logs, the start-up log or
    the facts report.
- **Item 3** holds with the Agent Server configured: `conversation_image` is the local
  tag whose image ID is the locked config digest. No conversation was created (F-04.2).
- P1 to P9, P11, P12 and the provisioning entry PASS, also after a restart and after
  recreate in `smoke --provision` (evidence section 7: run 4 PASS after a fix forward of
  the comparison of the unit's address sets). Not operational (C6).

## Evidence
- [`evidence/F-04.1c-agent-server.md`](../evidence/F-04.1c-agent-server.md): the
  slice (c) runs, the `/server_info` JSON, the configuration, the secret custody, the
  declared-versus-observed table for the F-04.1 proof and the smoke test.
- [`evidence/F-04.1b-provision-moby.md`](../evidence/F-04.1b-provision-moby.md): the
  slice (b) runs, timings, RESULT.json, inspect verdicts and the smoke test.
- [`evidence/F-04.1a-provision-pins-fetch.md`](../evidence/F-04.1a-provision-pins-fetch.md):
  the resolve.py run, the resolution guest, the lock, the fetch runs and the tests.
- [`profiles/strong-windows-qemu-whpx/provision.lock.json`](../profiles/strong-windows-qemu-whpx/provision.lock.json),
  pinned by `provider.provision_lock` in the profile and checked by
  `tools/check_profile.py`.
- The Owner's direction and authorization of 2026-11-06, quoted above.
- The Architect's F-04.1 consultation (gates C and G), as accepted by the Overseer.
- Upstream: snapshot.debian.org (`archive/debian` and `archive/debian-security` at
  `20261106T143859Z`); github.com/google/go-containerregistry release v0.22.1
  (`checksums.txt`); github.com/OpenHands/software-agent-sdk release v1.60.1
  (`SHA256SUMS`); ghcr.io/openhands/agent-server.
