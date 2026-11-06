# Component lock (F-01.2)

The lock pins the upstream composition selected in F-01.1
(`composition/candidates.json`) on the version line fixed by
[decision 0001](../../decisions/0001-agent-server-dispatch-precondition-and-version-line.md).
`components.lock.json` is the entry point. It names every pinned artifact and
points to the hash-locked Python and npm files.

## Resolver command

```
python -I composition/resolve.py --work <empty-or-absent directory outside the checkout>
```

The resolver does five things:

1. It runs `git ls-remote` against each pinned source tag and checks the tag → commit mapping.
2. It downloads every locked Python wheel for each locked target and checks its sha256. It installs the host target's set with
   `pip install --target <work>/python/site --only-binary :all: --require-hashes --no-deps --no-index`
   and reads the installed versions back with `pip inspect --path`.
3. It runs `npm ci --ignore-scripts` from `npm/package-lock.json` with an isolated cache and empty npm config, so npm itself verifies each tarball's integrity. It then compares npm's hidden lockfile and `npm ls --all --json` with the lock. Every locked tarball that npm skips on this host (other OS or CPU optionals, such as `backlog.md-linux-x64` and `-arm64`) is downloaded and integrity-checked separately.
4. It fetches each OCI index and its linux/amd64 and linux/arm64 manifests from the registry by digest and recomputes their sha256. This is a manifest-digest check. No image is pulled and nothing is run.
5. It checks the GitHub release assets against the upstream checksum files, which it downloads and verifies by sha256. Where upstream publishes no checksum file, it uses the GitHub asset digest.

It writes `<work>/report.json`. The main fields are:

| Field | Meaning |
|---|---|
| `resolution` | Every verified digest. It is deterministic for a given lock and host. |
| `resolution_digest` | sha256 of the canonical JSON of `resolution`. |
| `installed` | The versions the installers report. |
| `installed_digest` | sha256 of the canonical JSON of `installed`. |
| `conversation_image` | The verified conversation image digest. |
| `checks` | Each check with a pass or fail status. |
| `observations` | Tag → digest lookups. These are informational and are not included in any digest. |
| `run` | Timestamps and tool versions. |

Two clean runs are equivalent when their `resolution_digest` and `installed_digest` values are equal.

Exit codes:

| Code | Meaning |
|---|---|
| 0 | All artifacts verified and every locked set fully installed. |
| 1 | Any mismatch or failure. |
| 2 | Usage or prerequisite error. |
| 3 | All artifacts verified, but a `known_gaps` entry with severity `blocking` leaves an installed set incomplete. This is the current state; see [Known gaps](#known-gaps). |

**Host prerequisites** (the resolver checks each one):

- CPython 3.12 with pip ≥ 23.1
- Node.js ≥ 24 with npm ≥ 11
- git
- HTTPS access to:
  - pypi.org and files.pythonhosted.org
  - registry.npmjs.org
  - github.com and api.github.com (unauthenticated, 2 API calls)
  - ghcr.io
  - registry-1.docker.io and auth.docker.io

Registry tokens are anonymous, held in memory and never printed. No credentials are used. The resolver never imports or executes installed package code.

## Files

| File | Pins | Count |
|---|---|---|
| `components.lock.json` | The umbrella lock, with these sections:<ul><li>`sources`: tag → commit</li><li>`release_line` and `provenance_notes`</li><li>`conversation_image`</li><li>`python`: direct pins, the coupled pin and the blocked sdist</li><li>`npm`: direct and pinned packages</li><li>`oci`: index and platform digests</li><li>`release_assets`</li><li>`tools`: uv, Syft and Grant, with sha256</li><li>`known_gaps`</li></ul> | <ul><li>8 source tags</li><li>4 OCI indexes</li><li>12 release assets</li><li>3 tools</li></ul> |
| `python/requirements.in` | The four OpenHands packages, each `==1.60.1`. | 4 direct |
| `python/excludes.txt` | `func-timeout`, which is excluded from wheel-only resolution (see Known gaps). | 1 |
| `python/windows-x86_64.txt` | The hash-locked closure for win_amd64, CPython 3.12. | 195 pins: 4 direct, 191 transitive |
| `python/linux-x86_64.txt` | The hash-locked closure for manylinux (glibc ≥ 2.28) x86_64, CPython 3.12. | 194 pins: 4 direct, 190 transitive |
| `python/linux-aarch64.txt` | The hash-locked closure for manylinux (glibc ≥ 2.28) aarch64, CPython 3.12. | 194 pins: 4 direct, 190 transitive |
| `npm/package.json` | Eight exact direct dependencies:<ul><li>`@openhands/typescript-client` 1.60.1</li><li>`@openhands/agent-canvas` 1.36.0</li><li>`@assistant-ui/react` 0.15.32</li><li>`@fission-ai/openspec` 1.16.0</li><li>`backlog.md` 1.55.3</li><li>`react` and `react-dom` 19.3.1, plus `react-router` 8.5.0 (Canvas's exact peers)</li></ul> | 8 direct |
| `npm/package-lock.json` | lockfileVersion 3. Each entry carries a `dist.integrity` (sha512) and a registry.npmjs.org URL. The 6 bundled entries are covered by their parent tarball. Six platform packages are recorded, including `backlog.md-linux-x64` and `backlog.md-linux-arm64`. | 721 entries: 8 direct, 713 transitive, 57 optional |

The three Python files contain the same version of every package they share. They differ only by platform-conditional packages:

| Target | Platform-only packages |
|---|---|
| windows-x86_64 | `colorama`, `pywin32`, `pywin32-ctypes` |
| linux | `jeepney`, `secretstorage` |

Each pin lists the hashes of every file PyPI publishes for that version. Installation uses wheels only.

## Coverage

| Area | Coverage |
|---|---|
| Python | CPython 3.12 only. Locked targets are windows-x86_64, linux-x86_64 and linux-aarch64 (manylinux, glibc ≥ 2.28). Other CPython minor versions (the Canvas launcher allows 3.12–3.14) and musl are not covered. |
| npm | The lockfile is platform-independent. Node ≥ 24 is required (Canvas `engines`). |
| OCI | The linux/amd64 and linux/arm64 manifests under each index digest. |
| Install verification | Only the resolving host can be install-verified. The F-01.2 evidence host is Windows 11 x86_64. For non-host targets, artifacts are downloaded and hash-verified but not installed. **Linux-guest installation (F-03/F-04) is unknown** until the resolver runs there. |

## conversation_image

The locked conversation image is
`ghcr.io/openhands/agent-server@sha256:b43ee580c2177280c81cb807c9a559d7a14aa13b48dba5040132a6a637bb6d55`.
This is the 1.60.1-python multi-arch index. These references are **non-conforming**:

- The Agent Server's built-in default `ghcr.io/openhands/agent-server:latest-python`, which is a floating tag
- `…:e99e5c7-python`, a different index
- Any `latest-*` or other tag reference

This lock does not configure any server. F-04.1 sets `conversation_image` to the locked reference, and F-04.2 and E-01.5 observe it (decision 0001 §4).

## Provenance notes

- **Version line.** OpenHands 1.60.1 (e99e5c7), Agent Canvas 1.36.0 (d30f1e4), and openhands-automation 1.30.1. Automation is a **coupled pin**: its wheel is locked and verified but not installed. Its own closure is not locked.
- **Canvas floor.** Canvas `compatibility.minimumAgentServer` is **1.59.0**.
- **Revisit rule (decision 0001 §1).** Re-resolve this lock on any upstream pin change before F-04.1. On a version-attributable live failure, fall back to the 1.59.0 / Canvas 1.35.0 set, **never** to 1.58.2.
- **Automation coherence.** Adding Automation to the Python resolution changes no existing pin; it adds 19 packages. The check is recorded in `components.lock.json`.
- **Signatures.** No signature (Sigstore, Cosign or GPG) is verified. Integrity rests on digests only.

## Known gaps

`python-func-timeout-sdist-only` is **blocking** for a complete Python install. `openhands-tools` 1.60.1 requires `func-timeout>=4.3.5`. PyPI publishes every func-timeout release (3.0.0 through 4.3.5) as an sdist only, and building it would execute `setup.py`.

What the lock and resolver do with func-timeout:

- The lock pins it by sdist sha256 `74cd3c42…5575dd`.
- The resolver downloads that sdist and verifies its hash.
- The resolver never builds or installs it.

So the installed host set is the locked set minus func-timeout, and the resolver exits 3. The disposition needs an Overseer decision. Note also that func-timeout is LGPLv2/2.1.

## Regenerating the lock

Regenerate only under the revisit rule, using the tools pinned in `components.lock.json` (`tools`). Verify each tool's sha256 before running it.

```
# Python (repeat for each target, and its output file):
#   x86_64-pc-windows-msvc  -> windows-x86_64.txt
#   x86_64-manylinux_2_28   -> linux-x86_64.txt
#   aarch64-manylinux_2_28  -> linux-aarch64.txt
UV_NO_CONFIG=1 UV_PYTHON_DOWNLOADS=never UV_CACHE_DIR=<empty dir> \
  uv pip compile python/requirements.in --excludes python/excludes.txt --python-version 3.12 \
    --python-platform <target> --no-build --generate-hashes --no-header --no-annotate -o python/<file>

# npm (from composition/lock/npm, with empty config files and an empty cache):
npm install --package-lock-only --ignore-scripts --no-audit --no-fund \
  --registry https://registry.npmjs.org/ --cache <empty dir> --userconfig <empty file> --globalconfig <empty file>
```

After regenerating, update `components.lock.json`, which records pin and entry counts and the direct integrities, and run the resolver.
