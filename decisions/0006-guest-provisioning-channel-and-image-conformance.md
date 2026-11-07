# 0006 - Guest provisioning channel and image conformance

Status: Proposed (Overseer) - 2026-11-06. The Overseer accepts it once slices (b) and (c)
of F-04.1 are evidenced. The Owner has already authorized the actions it depends on (see
"Owner authorization" below).
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

## Evidence
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
