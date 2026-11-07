# F-01.1 — Candidate upstream compatibility matrix

| | |
|---|---|
| Task | F-01.1 *Resolve compatible upstream version set* (parent F-01, non-executable) |
| Blueprint authority | `#infrastructure-state`, read with `#components`, `#integration-contracts`, `#conversation`, `#execution-qualification` |
| First retrieval | 2026-11-05T23:52:10Z (UTC) |
| Second resolution | 2026-11-06T00:02:28Z: every identifier re-queried, 51 of 51 checks returned the same value |
| Machine-readable form | [`candidates.json`](candidates.json), with the same selections, identifiers and verdicts |
| Status | **Candidate.** Nothing was installed or run. Every runtime claim is unknown until F-01.2 or later qualification checks it. |

## How to read this document

All identifiers come from upstream primary sources: git refs, the registries, GitHub releases, and the upstream repositories at the tag. **No component was installed or executed.**

| Term | Meaning |
|---|---|
| **pass** | Observed upstream and cross-checked against at least one independent upstream record. |
| **fail** | The identifier could not be obtained, or two upstream records disagree. |
| **unknown** | No upstream record establishes the fact, or it can only be proved by installing and running. |
| **not_run** | Deliberately not checked in F-01.1. Signature verification is the main example. |
| **compatible** | Upstream explicitly declares the pairing at these exact versions. This is a metadata or source fact, not a runtime test. |
| **incompatible** | An upstream constraint excludes the pairing. |
| **unknown** (coupling) | Upstream declares nothing, or only a running system could show the answer. |

## 1. Selection table

| Component (blueprint name) | Upstream name / channel(s) | Version · tag | Commit (tag → commit) | Primary immutable artifact digest | License | Tag→commit | Artifact→commit |
|---|---|---|---|---|---|---|---|
| OpenHands Software Agent SDK | PyPI `openhands-sdk`, `openhands-tools`, `openhands-workspace` | 1.60.1 · `v1.60.1` | `e99e5c71ffe440a0b8d74b695f9307a7e34e4bbd` | wheel `sha256:f6efa8f8428ccc8abebbcf4c424bf3008a66a46f9f2340d37b3b306fcb45eb6b` (all six files in §2.1) | MIT | pass | unknown (no PyPI provenance) |
| OpenHands Agent Server | PyPI `openhands-agent-server`; OCI `ghcr.io/openhands/agent-server`; release binaries | 1.60.1 · `v1.60.1` | `e99e5c71ffe440a0b8d74b695f9307a7e34e4bbd` | OCI index `sha256:b43ee580c2177280c81cb807c9a559d7a14aa13b48dba5040132a6a637bb6d55` | MIT (image bundles third-party CLIs, see §6) | pass | pass (OCI, release); unknown (PyPI) |
| OpenHands TypeScript client | npm `@openhands/typescript-client` | 1.60.1 · `v1.60.1` | `e99e5c71ffe440a0b8d74b695f9307a7e34e4bbd` | `sha512-LysixcYGpHnEcWToGeaNaiduytpo4TiytApBZqE4JSM3sCyu32wFa54R/ycgPwibuisgNpnhVcm+UZClYOYEUA==` | MIT | pass | pass |
| Agent Canvas | npm `@openhands/agent-canvas`; OCI `ghcr.io/openhands/agent-canvas` | 1.36.0 · `v1.36.0` | `d30f1e45bbb67558ec2bfcd639b907ae525f162c` | `sha512-ZumCENrBTfztpXRtRulOmTB/l/pBoOjWUO5x3ySNgOmHkV8OTkbe1WTyZoRbyEVagux/vlEyztuPgz/Ia+ecGQ==` | MIT | pass | pass |
| assistant-ui | npm `@assistant-ui/react` (+ `@assistant-ui/core`) | 0.15.32 · `@assistant-ui/react@0.15.32` | `2769cdf4db1b95f8e3f627910caf12b39a58216e` | `sha512-cw+8UQRnJocyHEaNc3+S+ulZaFp4UoVnbjyRmVFZcq8XSHpe4onz7ZkXkBl7L8IZftgvNdHS9ZEujnqohwzibw==` | MIT | pass | pass |
| OpenSpec | npm `@fission-ai/openspec`; release binaries | 1.16.0 · `v1.16.0` | `27c0515724decc633818c735ee596481eec78a8b` | `sha512-WQVhZoIR5PoacH/H0qh84VKMcXFbKCIKuAI96arHS3KiKYhJStlRrjUKGxLqLYKLym0j+2hAAY5MZUrPE5qXIA==` | MIT | pass | pass |
| Backlog.md | npm `backlog.md` (+ platform packages); release binaries | 1.55.3 · `v1.55.3` | `0cf4fdbc70020327f4366a29d3f405f83d180301` | `sha512-HN37ifPKQR28QAEdKO9g9sF/DjmTaVkBSfMK2BleNrbIShe8evFqoPpGlyvQtAQM1XKW+5guPW3+c5Tt8Mrpew==` | MIT | pass | pass (npm); unknown (release binaries) |
| Gitea | OCI `gitea/gitea` (Docker Hub = `docker.gitea.com`); release binaries | 28.3.0 · `v28.3.0` (annotated tag object `f1cd050b55a46ae556cf992576d01b4a08bd793a`) | `4f5a3e13e5f3aca85d830e3a9024c893b0bbf1e1` | OCI index `sha256:8967bf9deaf3c5c4adae13519436dc1b20c646ac83fe37ae810c933a1045227d` | MIT | pass | unknown |
| *OpenHands Automation*: coupled dependency, **not a selection** | PyPI `openhands-automation` | 1.30.1 · `1.30.1` | `3ddfee594d2177ab368772bc03c25f2dda103c9b` | wheel `sha256:9bbc2bc8b160242139b905a2deedc2127a29a6ffd2cca27569a252c6e27613d8` | MIT | pass | unknown |

Every candidate is the **latest stable release** at retrieval time. Each one also matches the pins in its neighbours' metadata, so no upstream constraint forced an older choice. The Automation row appears only because Agent Canvas 1.36.0 pins it and bundles it in its image. The blueprint lists OpenHands Automation as an optional extension that is "adopted on evidence".

**Signatures were not verified for any component (not_run).** I decoded npm SLSA provenance and BuildKit provenance and compared their contents. I did not verify them cryptographically.

## 2. Per-component detail

### 2.1 OpenHands Software Agent SDK and Agent Server: one release unit

- **Source:** <https://github.com/OpenHands/software-agent-sdk>. The tag `v1.60.1` is lightweight and points to commit `e99e5c71ffe440a0b8d74b695f9307a7e34e4bbd`. The GitHub release was published on 2026-11-05T16:32:39Z with `target_commitish` set to the same commit.
- **Runtime:** Python `>=3.12` according to the PyPI `requires_python` field. The Agent Server talks to the Docker Engine API through the Python package `docker<8,>=7.1`.
  - OCI images are published for `linux/amd64` and `linux/arm64`.
  - Single-file Agent Server binaries are published for linux-x86_64, linux-arm64, macos-x86_64, macos-arm64 and windows-x86_64.
- **License:** MIT. Evidence: the `LICENSE` file at the tag and the GitHub `spdx_id`. The PyPI metadata has no license field.
- **Interface:**
  - REST and WebSocket API. The `openapi.json` release asset is `sha256:3de49fac4670eff9c8b6635ffd8bc5b6d4219788877747135333cec9f8c5e0d0`.
  - `ServerInfo.capabilities` includes `conversation_runtime_routes_v1` and `idempotent_conversation_create_v1` (`server_details_router.py` at v1.60.1).
  - Docker selectability is advertised through `available_conversation_runtimes`. That field is `["local","docker"]` only when the server config sets `conversation_runtime_selectable` to true; the default is false.
  - The per-conversation image defaults to `ghcr.io/openhands/agent-server:latest-python` (`config.py`, `DEFAULT_CONVERSATION_IMAGE`).

| Channel | Artifact | Digest |
|---|---|---|
| PyPI | `openhands_sdk-1.60.1-py3-none-any.whl` | `sha256:f6efa8f8428ccc8abebbcf4c424bf3008a66a46f9f2340d37b3b306fcb45eb6b` |
| PyPI | `openhands_sdk-1.60.1.tar.gz` | `sha256:9fed8b24997b083709347ec7a1927249090f3c1af4a28e9cbe06959ae48900fb` |
| PyPI | `openhands_tools-1.60.1-py3-none-any.whl` | `sha256:fc84a55630b46a88cd4b617b00c6511c0cadae5cfb0eeed6b6639e8ac67da93b` |
| PyPI | `openhands_tools-1.60.1.tar.gz` | `sha256:df2f00296875b91911803673db1944040f62afd23ce7207d73143d05961b0135` |
| PyPI | `openhands_workspace-1.60.1-py3-none-any.whl` | `sha256:b4898196621032b67790b73fc013ea17cff19275066328b50b0188212ea6211d` |
| PyPI | `openhands_workspace-1.60.1.tar.gz` | `sha256:9cfde9a4fd347342b7602519052a0837d38f0b36cbd9a09a85f38f47d7bc1e15` |
| PyPI | `openhands_agent_server-1.60.1-py3-none-any.whl` | `sha256:df80a622059f3cce797ab2c08adfc5256a69d7c7a6b4712b2d5147df25be76f6` |
| PyPI | `openhands_agent_server-1.60.1.tar.gz` | `sha256:345d3f89680aaf04a9d595a1ca3a09c33dedde8ea30c88bc4cccef865b0e2484` |
| OCI | `ghcr.io/openhands/agent-server:1.60.1-python` (index) | `sha256:b43ee580c2177280c81cb807c9a559d7a14aa13b48dba5040132a6a637bb6d55` |
| OCI | linux/amd64 manifest | `sha256:8496d13f117827165af5a9c5c2b8ec5a1e52074aaff49a196ce9b000262d6b0c` |
| OCI | linux/arm64 manifest | `sha256:89f694c3a3ec77efeaae7ab4c72352e7a5f2fd606544e6a7123d87be1d467665` |
| Release | `agent-server-1.60.1-linux-x86_64` | `sha256:b2fbcf8cf1495bdbef97f26583917bc188b765c71c181effc3e47c14da08ce72` |
| Release | `agent-server-1.60.1-linux-arm64` | `sha256:cacaf42a648011443f0eba182d4554493d4e000f79e0e9c9263007bb056fcdb0` |
| Release | `SHA256SUMS` (also covers the macOS/Windows binaries and `openapi.json`) | `sha256:6b6e6e3febe2e143f226886d9bac878855ddd3d6108517d815edb03c20fb37e9` |

**How each artifact links to the commit:**

- **OCI:** pass. The `1.60.1-python` index carries a BuildKit SLSA provenance attestation with `OPENHANDS_BUILD_GIT_REF=refs/tags/v1.60.1` and `OPENHANDS_BUILD_GIT_SHA=e99e5c7…`. The image has no OCI revision label.
- **Release binaries:** pass. The GitHub asset digests equal the lines in the upstream `SHA256SUMS` file, and `target_commitish` is the tag commit.
- **PyPI:** unknown. The PEP 740 provenance endpoint returns HTTP 404 for all four packages. Only the version string and the upload time (16:46Z) tie the files to the tag.

**Caution:** the image tag `ghcr.io/openhands/agent-server:e99e5c7-python` is built from the same commit but resolves to a **different** index, `sha256:8857fbd2cae6798678f208f18a85d23dc2730a3df8ecdf074373624b69ce675f`. It appears to be a separate main-branch build. Pin the `1.60.1-python` digest.

### 2.2 OpenHands TypeScript client

- The npm package `@openhands/typescript-client` 1.60.1 was published 2026-11-05T16:47:05Z under the MIT license. It declares no `engines` field. Its dependencies are `@openrouter/sdk ^1.2.11` and `ws ^8.20.0`.
- **Source:** `software-agent-sdk/clients/typescript`. npm `gitHead` and the SLSA provenance `gitCommit` are both `e99e5c71ffe440a0b8d74b695f9307a7e34e4bbd`, and the provenance subject sha512 equals `dist.integrity`.
- The package's `config.agentServerImage` is `ghcr.io/openhands/agent-server:1.60.1-python`.
- **Integrity:** `sha512-LysixcYGpHnEcWToGeaNaiduytpo4TiytApBZqE4JSM3sCyu32wFa54R/ycgPwibuisgNpnhVcm+UZClYOYEUA==`.
- The former repository <https://github.com/OpenHands/typescript-client> is **archived**. See §5.

### 2.3 Agent Canvas

What upstream ships under this name:

- **Name:** upstream calls the product **"Agent Canvas"**, the same name the blueprint uses.
- **npm package:** `@openhands/agent-canvas`, with the CLI `agent-canvas` and library exports.
- **OCI image:** `ghcr.io/openhands/agent-canvas`, an all-in-one image of Agent Server, Automation and the frontend.
- **Source repository:** <https://github.com/OpenHands/OpenHands>.
- **Desktop and Linux packages** (`.dmg`, `.exe`, `.deb`, `.AppImage`) are also released. They are not a channel this architecture consumes, so no digests are recorded for them.

Release details:

- **Tag:** `v1.36.0` (lightweight) points to `d30f1e45bbb67558ec2bfcd639b907ae525f162c`. The release was published 2026-11-05T21:38:50Z.
- **Runtime:** Node `>=24`; `packageManager` is `npm@11.12.1`.
  - Peer dependencies are **exact**: `react 19.3.1`, `react-dom 19.3.1`, `react-router 8.5.0`.
  - The launcher's Python request is `>=3.12,<3.15`.
  - OCI images are published for `linux/amd64` and `linux/arm64`.
- **Library exports:** `.`, `./browser`, `./conversation`, `./files`, `./settings`, `./sidebar`, `./terminal`, `./i18n`, `./styles.css`. `src/lib/index.ts` at the tag exports `AgentServerUIProviders` and `AgentServerUIRoot`, as the blueprint expects.
- **Backend pins** in `config/defaults.json` at the tag, which `docs/DEVELOPMENT.md` names as the source of truth:
  - `versions.agentServer` = 1.60.1
  - `versions.automation` = 1.30.1
  - `compatibility.minimumAgentServer` = 1.59.0
  - `@openhands/typescript-client` is pinned exactly to 1.60.1 in `package.json`.

| Channel | Artifact | Digest |
|---|---|---|
| npm | `@openhands/agent-canvas@1.36.0` | `sha512-ZumCENrBTfztpXRtRulOmTB/l/pBoOjWUO5x3ySNgOmHkV8OTkbe1WTyZoRbyEVagux/vlEyztuPgz/Ia+ecGQ==` |
| OCI | `ghcr.io/openhands/agent-canvas:1.36.0` (index) | `sha256:27bce1829a469551dd24ab6d07ece64a1fb9ce485a64f4d65d49deb816e4241f` |
| OCI | linux/amd64 manifest | `sha256:b1221a6face64ed0706ef0b4459114f14f1f067294c5f7c5f89a873da02f368d` |
| OCI | linux/arm64 manifest | `sha256:2ebb1c0458906ba2afc29ebc05158502f45ea841032a484588285e3afd7c8ed2` |

**Link to the commit: pass.** Four records agree on `d30f1e4…`:

- npm `gitHead`;
- the npm SLSA provenance (workflow ref `refs/tags/v1.36.0`);
- the OCI label `org.opencontainers.image.revision`;
- the BuildKit provenance.

The Canvas image was built `FROM ghcr.io/openhands/agent-server:1.60.1-python`. It references that base **by tag** and sets `AUTOMATION_VERSION=1.30.1`.

### 2.4 assistant-ui

- **Source:** <https://github.com/assistant-ui/assistant-ui>, a monorepo with per-package tags. The tags `@assistant-ui/react@0.15.32` and `@assistant-ui/core@0.3.32` both point to `2769cdf4db1b95f8e3f627910caf12b39a58216e`. npm published the packages on 2026-10-28.
- **Runtime:** peer dependencies `react ^18 || ^19` and `react-dom ^18 || ^19`. No engines field.
- **Interface at the commit:** `packages/react/src/index.ts` exports `useLocalRuntime`, `ChatModelAdapter`, `ThreadHistoryAdapter`, `RemoteThreadListAdapter`, `useRemoteThreadListRuntime`, `useExternalStoreRuntime` and `ExternalStoreAdapter`. These are the adapters the blueprint's UI-02 decision names.
- **License:** MIT. Dependencies include `assistant-cloud ^0.2.9`, a client for a hosted service; its terms were not assessed here.
- **Integrity:**
  - `@assistant-ui/react@0.15.32`: `sha512-cw+8UQRnJocyHEaNc3+S+ulZaFp4UoVnbjyRmVFZcq8XSHpe4onz7ZkXkBl7L8IZftgvNdHS9ZEujnqohwzibw==`
  - `@assistant-ui/core@0.3.32`: `sha512-eEOuM3K0HWoetfFW8WwGJrhFu7lAfn/Su9us6xMk9HbHUc3/5jL6EOa2VsxrWeZbPqu/yXxGT2KaaFVvzZtCbA==`
- **Link to the commit: pass.** The npm SLSA provenance `gitCommit` is `2769cdf…` (built from `refs/heads/main` at that commit), and the subjects equal `dist.integrity`. npm `gitHead` is absent.

### 2.5 OpenSpec

- **Source:** <https://github.com/Fission-AI/OpenSpec>. The tag `v1.16.0` (lightweight) points to `27c0515724decc633818c735ee596481eec78a8b`. Released 2026-10-30.
- **Runtime:** Node `>=22.12.0`. Standalone release binaries are published for darwin, linux (glibc and musl) and windows, on x64 and arm64.
- **License:** MIT.
- **Interface** (verified in the documentation at the tag):
  - `openspec status --change <name> [--json]` and other `--json` commands (`docs/cli.md`, `README.md`).
  - Top-level `x-` change-metadata fields (`docs/cli.md`).

| Channel | Artifact | Digest |
|---|---|---|
| npm | `@fission-ai/openspec@1.16.0` | `sha512-WQVhZoIR5PoacH/H0qh84VKMcXFbKCIKuAI96arHS3KiKYhJStlRrjUKGxLqLYKLym0j+2hAAY5MZUrPE5qXIA==` |
| Release | `openspec-linux-x64.tar.gz` | `sha256:f27fb2ff5c6c4aafb207cb0b797189215adb3a1150d4b4600a2d6a0b6e192ae1` |
| Release | `openspec-linux-arm64.tar.gz` | `sha256:b9b61371a7caa1819da34f766cc24896cfe7a743841f53121b66bd1e2f1b9e93` |
| Release | `SHA256SUMS` | `sha256:6cc4af0875c3fb58a0e1ca1dc02873a976c6c9b811585d59f47d3c647ec76bf7` |

**Link to the commit: pass.** The npm provenance `gitCommit` and the release `target_commitish` are both `27c0515…`, and the asset digests equal `SHA256SUMS`.

### 2.6 Backlog.md

- **Source:** <https://github.com/MrLesk/Backlog.md>. The tag `v1.55.3` (lightweight) points to `0cf4fdbc70020327f4366a29d3f405f83d180301`. Released 2026-10-23.
- **Runtime:** the npm wrapper `backlog.md` has no engines field. Through `optionalDependencies` it selects a Bun-compiled platform package, `backlog.md-<os>-<cpu>`, for linux, darwin and windows on x64 and arm64.
- **License:** MIT. The platform packages carry no license field.
- **Interface:** `CLI-INSTRUCTIONS.md` at the tag documents the following:
  - `backlog task list --json`, `backlog task view <id> --json` and `backlog task <id> --json`;
  - the envelope `{ "schemaVersion": 1, "kind": … }`;
  - the fields `isReady`, `readiness` and `dependencyGraph`.

  These are exactly the read surfaces the blueprint names.

| Channel | Artifact | Digest |
|---|---|---|
| npm | `backlog.md@1.55.3` | `sha512-HN37ifPKQR28QAEdKO9g9sF/DjmTaVkBSfMK2BleNrbIShe8evFqoPpGlyvQtAQM1XKW+5guPW3+c5Tt8Mrpew==` |
| npm | `backlog.md-linux-x64@1.55.3` | `sha512-UBBNFDWmiJhkAqKy0jE39meVTF587EA8hh2qLk9Ag/mGosMpK5QdFqPqRafCIaowgxZCp0y++Vy5ZID2zoMpZg==` |
| npm | `backlog.md-linux-arm64@1.55.3` | `sha512-EoHqKYU80UNyCa7l/nhuEyztW1GCxG9O9S6wm167Vxf6ZRD8fwWrTgqGnvWbesbUrgOshw3OShAbGYRHyWie/g==` |
| Release | `backlog-bun-linux-x64` | `sha256:c20d5c51aa95b66d5c89428927bb0a16dc7beb9110683d66387e0514925f274a` |
| Release | `backlog-bun-linux-arm64` | `sha256:8b8928bf0dcbc83f82cbd2c77668799fe9b3463511acdf62fe3f02fb0a486aa9` |

**Link to the commit:**

- **npm:** pass. `gitHead` and the SLSA provenance (workflow ref `refs/tags/v1.55.3`) both give `0cf4fdb…`, and the platform packages' `gitHead` is also `0cf4fdb…`.
- **Release binaries:** unknown. The GitHub release's `target_commitish` reads `a9d4ab6fd13987231f32d794e42fd612efacb1a2`, which is not the tag commit, and upstream publishes no checksum file. The digests above are GitHub-computed only.

### 2.7 Gitea

- **Source:** <https://github.com/go-gitea/gitea>. The tag `v28.3.0` is annotated: tag object `f1cd050b55a46ae556cf992576d01b4a08bd793a` peels to commit `4f5a3e13e5f3aca85d830e3a9024c893b0bbf1e1`. The GitHub `git/tags` API agrees. GitHub reports the tag signature as `unknown_key`, so it is unverified. Released 2026-11-01; the release is marked `immutable: true`.
- **Runtime:**
  - Building from source needs Go `1.27` (toolchain `go1.27.3`); the module path is now `gitea.dev`.
  - Images are published for linux/amd64, linux/arm64 and linux/riscv64.
  - Static binaries are released.
- **Interface:** REST `/api/v1`, webhooks and protected branches, per upstream docs. The 28.3.0 OpenAPI document was not located at its historical path and was **not retrieved**, so API-level detail is unknown.
- **License:** MIT.
- **Security:** 28.3.0 is above the patched versions of the two advisories the blueprint cites: GHSA-r9ch-mqjm-g67v (patched 1.27.2) and GHSA-w5pg-649r-p6gg (patched 1.27.0).

| Channel | Artifact | Digest |
|---|---|---|
| OCI | `gitea/gitea:28.3.0` (index; identical on `docker.gitea.com/gitea:28.3.0`) | `sha256:8967bf9deaf3c5c4adae13519436dc1b20c646ac83fe37ae810c933a1045227d` |
| OCI | linux/amd64 manifest | `sha256:411af83e9be78029c0047a5f5a72f1d91b7c793ba5e5813b4e70a6bb8e4a0738` |
| OCI | linux/arm64 manifest | `sha256:0543eb2049bacecb24645d023c5b3cddbd77bc47d35b2761d0b4c63cc4667292` |
| OCI | `gitea/gitea:28.3.0-rootless` (index) | `sha256:40c5a68a0463c0940e1ae32626c8300dd0572f3558e390073ad8379ca67c0e1d` |
| OCI | rootless linux/amd64 manifest | `sha256:481be76469179d4edd90e40209c14d63759be0e5fbc57d567c0fb860df762e24` |
| OCI | rootless linux/arm64 manifest | `sha256:226f6b90b42e9d9158d230f7b6015d7cca72c5e3018cc0f85cdeb30294fd0aaf` |
| Release | `gitea-28.3.0-linux-amd64` | `sha256:5f834e8f04986f3b9206cf14743b5a6e6996ceddc238dac6409866ebda2a0686` |
| Release | `gitea-28.3.0-linux-arm64` | `sha256:24d146e8f5c986b86e5a3311e3ec349ded35202cba056952ab5b585511ace82d` |
| Release | `gitea-28.3.0-windows-amd64.exe` | `sha256:4003c068ef0a7d8145ef8c85b8aab052bf1bbf9226f2d0058572f013e096ee06` |
| Release | `gitea-src-28.3.0.tar.gz` | `sha256:a632833d5ae02a18e8f7ed79177763801604de6ef6f6d1c1405029d28de9d3a4` |

**Artifact digests: pass.**

- For the binaries, three sources agree: the GitHub asset digest, the upstream `.sha256` file on GitHub, and the `.sha256` file on `dl.gitea.com`.
- The Windows binary `gitea-28.3.0-windows-amd64.exe` (122,948,608 bytes) was added on 2026-11-07 for host-loopback Gitea (plan leaf F-06.1), with the Owner's approval of the same day. The same three sources agree, and the two `.sha256` files are byte-identical. The release publishes no `windows-4.0-amd64` variant. It is consumed by `integrations/gitea/gitea_host.py` from `../lock/components.lock.json`.
- For the image, Docker Hub and `docker.gitea.com` serve the same index digest.

**Link to the commit: unknown.** The images have no revision label or provenance, and the release's `target_commitish` is `main`.

Choosing between the root and rootless image variants is a deployment decision for F-01.2 or later, not a compatibility question.

### 2.8 OpenHands Automation (coupled dependency, not selected)

- **Source:** <https://github.com/OpenHands/automation>. The tag `1.30.1` has no `v` prefix and points to `3ddfee594d2177ab368772bc03c25f2dda103c9b`. PyPI upload 2026-11-05T17:49:25Z. License MIT (`license_expression`).
- **Requirements:** `requires_dist` pins `openhands-sdk==1.60.1` and `openhands-workspace==1.60.1`.
- **Digests:**
  - wheel `openhands_automation-1.30.1-py3-none-any.whl`: `sha256:9bbc2bc8b160242139b905a2deedc2127a29a6ffd2cca27569a252c6e27613d8`
  - sdist `openhands_automation-1.30.1.tar.gz`: `sha256:b1fc3f93d1e05d5f5191cbc501837ba18a0784dddba708f0dae2a6f561ee620a`
- PEP 740 provenance exists: the publisher is `OpenHands/automation`, workflow `pypi-release.yml`, and the subject equals the wheel's sha256. The statement names no commit, so the link from the artifact to the commit is **unknown**.

## 3. Pairwise compatibility

"Runtime" is **not_run** for every row. Nothing in this section was installed or executed.

| A | B | Contract | Verdict | Evidence |
|---|---|---|---|---|
| openhands-sdk 1.60.1 | openhands-agent-server 1.60.1 | One release unit; the server imports the SDK and tools in-process | **compatible** | Both were built from `v1.60.1` @ `e99e5c7…`. However, PyPI `requires_dist` for agent-server, workspace and tools names its sibling packages **without version constraints**. Only an explicit lock holds them together. |
| agent-server 1.60.1 | typescript-client 1.60.1 | Agent Server OpenAPI (REST/WS) | **compatible** | The client was built from the same commit, and its `config.agentServerImage` is `agent-server:1.60.1-python`. |
| agent-canvas 1.36.0 | agent-server 1.60.1 | `defaults.json` `versions.agentServer` and `minimumAgentServer`; enforced by `assertAgentServerVersionIsSupported()` | **compatible** | Pinned to 1.60.1 with a floor of 1.59.0, and the Canvas image is built on `agent-server:1.60.1-python`. Upstream warns that meeting the floor does not guarantee every feature; floors for individual features inside the client were not enumerated, so **per-feature parity is unknown**. |
| agent-canvas 1.36.0 | typescript-client 1.60.1 | Exact npm pin | **compatible** | `package.json` `"@openhands/typescript-client": "1.60.1"` |
| agent-canvas 1.36.0 | automation 1.30.1 | `defaults.json` `versions.automation`; automation pins the SDK exactly | **compatible** | Pinned to 1.30.1, and automation requires `openhands-sdk==1.60.1`. |
| agent-canvas 1.36.0 | assistant-ui 0.15.32 | Both hosted in one React app (UI-01 / UI-02) | **unknown** | The peer ranges are satisfiable only at React 19.3.1, the exact version Canvas pins inside assistant-ui's `^18 \|\| ^19`. zustand `^5.0.16` and Canvas's 5.0.16 also intersect. Canvas further requires react-router 8.5.0. Bundle collisions, CSS isolation (`[data-agent-server-ui]` scope plus Google Fonts imports) and selecting an existing session can only be shown at runtime; the blueprint already lists these as "Not proven". |
| assistant-ui 0.15.32 | React 19.3.1 | `peerDependencies` | **compatible** | `react: ^18 \|\| ^19` |
| Node runtime | Canvas and OpenSpec | `engines.node` | **compatible** | Canvas needs `>=24` and OpenSpec `>=22.12.0`, so one Node ≥24 satisfies both. assistant-ui and the TS client declare no engines. Backlog.md ships its own Bun binary. |
| Python runtime | SDK, Agent Server, Automation and the Canvas launcher | `requires_python` and `python.uvxRequest` | **compatible** | CPython 3.12–3.14 (`>=3.12` everywhere; the launcher caps at `<3.15`). |
| OpenSpec 1.16.0 | Backlog.md 1.55.3 | None upstream; cross-references are owned integration (`#integration-contracts`) | **unknown** | No upstream coupling exists. |
| Gitea 28.3.0 | every other component | Git hosting, REST `/api/v1`, webhooks | **unknown** | No upstream declares a pairing; the integration is ours to own. |
| agent-server 1.60.1 | Docker Engine (`conversation_runtime=docker`) | Docker API through the `docker<8,>=7.1` client; selectable runtime is gated by server config | **unknown** | Docker selection must be enabled explicitly. Upstream declares no Moby version range. |

## 4. Excluded combinations

| Excluded | Reason (upstream evidence) |
|---|---|
| Agent Canvas 1.36.0 with Agent Server **< 1.59.0**, including the blueprint's qualification pin **v1.58.2** | Below `compatibility.minimumAgentServer` 1.59.0; `assertAgentServerVersionIsSupported()` rejects it at runtime. No Canvas release ever pinned 1.58.2: v1.32.0–v1.34.0 pinned 1.58.1, and v1.35.0 pinned 1.59.0. |
| Agent Canvas 1.36.0 with `@openhands/typescript-client` ≠ 1.60.1 | The pin is exact. Upstream `docs/DEVELOPMENT.md` calls mixing client and backend pins "unsupported". |
| openhands-automation 1.30.1 with openhands-sdk or openhands-workspace ≠ 1.60.1 | `requires_dist` pins `==1.60.1`. |
| openhands-sdk, -tools, -workspace and -agent-server at **differing** versions | They form one release unit. The Canvas launcher installs all four from the same version or ref "so inter-package APIs stay in sync", but PyPI metadata does **not** enforce this. |
| Any OpenHands component taken from a floating `main` or a floating image tag (`latest-python`, or sha-tags of main builds) | Upstream `DEVELOPMENT.md` and blueprint `#components` both say "do not combine floating upstream main branches". The Agent Server's default conversation image is the floating `latest-python`. |
| Host React ≠ 19.3.1, or react-router ≠ 8.5.0, when Canvas is embedded | Canvas `peerDependencies` are exact. |
| Node < 24 for the Canvas host or launcher; Node < 22.12.0 for OpenSpec | `engines.node` |
| CPython < 3.12 or ≥ 3.15 under the Canvas launcher | `requires_python >=3.12`; `uvxRequest <3.15` (upstream OpenHands/OpenHands#18654) |
| `@openhands/typescript-client` taken from the archived `OpenHands/typescript-client` repository | The repository is archived; current releases are built from `software-agent-sdk/clients/typescript`. |
| Gitea ≤ 1.27.1 | Affected by GHSA-r9ch-mqjm-g67v and/or GHSA-w5pg-649r-p6gg, both cited by the blueprint. |
| The OpenHands/OpenHands release `pr19394-evidence` | A temporary PR-evidence release, not a version tag. |

**Overall:** a mutually compatible set exists. In this set, every pairing that upstream explicitly declares is compatible. The remaining pairings are unknown, and the evidence does not show any of them to be incompatible.

## 5. Blueprint vs upstream: divergences

None of these changes the architecture, so none is a STOP item. They are notes.

1. **Version drift from the blueprint's qualification pin.**
   - The blueprint's source qualification and its probe (`#execution-qualification`) target Agent Server **v1.58.2**, and it cites v1.57.0 release notes.
   - The compatible current unit is **1.60.1**, and Canvas 1.36.0 *excludes* 1.58.2 (see §4).
   - The blueprint's v1.58.2 source findings must be re-checked at 1.60.1 during later qualification: the arbitrary host `working_dir` bind-mount, uncapped CPU and memory overrides, and the `host.docker.internal` / no `--network none` flags. They were not re-examined here.
2. **Capability token name.**
   - The blueprint gates Docker dispatch on a server that "advertises `selectable_conversation_runtime_v1`".
   - That string does not appear in `server_details_router.py` at either v1.58.2 or v1.60.1.
   - Upstream instead advertises selection through `ServerInfo.available_conversation_runtimes`, which is `["local","docker"]` only when `conversation_runtime_selectable` is set and is off by default.
   - `idempotent_conversation_create_v1` **is** advertised, as the blueprint expects.
3. **TypeScript client repository moved.**
   - The blueprint's "maintained `@openhands/typescript-client`" is still accurate as an npm package.
   - Its old standalone repository is archived, and releases now come from `software-agent-sdk/clients/typescript`.
4. **Floating default sandbox image.** Agent Server 1.60.1 defaults per-conversation Docker sandboxes to `ghcr.io/openhands/agent-server:latest-python`. The blueprint's "approved image digests" requirement in `#infrastructure-state` therefore depends on an explicit override.
5. **"Agent Canvas" naming matches upstream.**
   - The name is used by the npm package, the OCI image, the desktop apps and the docs.
   - The product lives in the `OpenHands/OpenHands` repository.
   - The blueprint's description holds at the tag: `config/defaults.json` backend pins, a separately pinned TS client, a minimum Agent Server floor, and `AgentServerUIProviders` / `AgentServerUIRoot` with scoped `styles.css`.
6. **The Agent Server remains separable from the SDK.** It has its own PyPI package, OCI image and binaries. A native UI that consumes it, Agent Canvas, exists. No STOP condition applies.
7. **Gitea versioning.** Gitea moved from 1.27.x to 28.x (28.0.0 on 2026-09-29). The blueprint already cites the 28.0 and 28.2 release posts alongside the 1.27 docs, so this is consistent.

## 6. Notes for F-01.2 (lock, resolver, SBOM, license)

- **Python lock:** pin all four OpenHands packages to `==1.60.1` with `--hash` values from §2.1. Their metadata does not constrain each other.
- **Sandbox image:** set the Agent Server's `conversation_image` (`OH_CONVERSATION_IMAGE`) to `ghcr.io/openhands/agent-server@sha256:b43ee580c2177280c81cb807c9a559d7a14aa13b48dba5040132a6a637bb6d55`. Never rely on the `latest-python` default.
- **OCI pinning:** pin by **index digest** (multi-arch) and record the per-platform digests for observation.
  - Do not use `e99e5c7-python`; it is a different build of the same commit.
  - The Canvas image references its Agent Server base by tag at build time, so its layers are fixed only by the Canvas index digest itself.
- **SBOM and provenance input:** OCI index entries with platform `unknown/unknown` are BuildKit attestation manifests (SLSA provenance), and the Canvas build ran `buildkit-syft-scanner`. Syft-format SBOMs may already be attached; this was not inspected.
- **npm:** lock by `dist.integrity` (sha512). For Backlog.md, also lock the platform package that will be resolved (`backlog.md-linux-x64` / `-arm64`).
- **Provenance gaps:**
  - PyPI SDK wheels have no PEP 740 provenance; establishing the link to the commit would need a rebuild from `e99e5c7` and a comparison.
  - Gitea images and Backlog.md release binaries cannot be linked to a commit from upstream metadata.
- **Signatures:** no npm provenance (Sigstore), Cosign or GPG signature was verified. A tool such as `npm audit signatures` could do this during install.
- **Inputs for the Grant license scan:**
  - The SDK packages have no PyPI license metadata.
  - The Backlog.md platform packages have no license field.
  - The Agent Server image installs third-party ACP CLIs (`INSTALL_ACP_PROVIDERS=claude-code,codex,gemini-cli`) whose terms are not MIT.
  - assistant-ui depends on `assistant-cloud`.
- **Telemetry:** the Canvas image and launcher embed a PostHog telemetry configuration. This is an egress-policy qualification item.
- **Freshness:**
  - The OpenHands release v1.60.1 and Agent Canvas v1.36.0 were both published on 2026-11-05, less than a day before retrieval.
  - The previous coherent upstream set is Canvas **v1.35.0**: agentServer 1.59.0, typescript-client 1.59.0, automation 1.26.1, floor 1.59.0, React 19.3.1. Its identifiers were **not** resolved here.
- **Updatecli:** the natural sources are the following.
  - `git ls-remote` tags for each repository;
  - Canvas `config/defaults.json` (`versions.*`, `compatibility.minimumAgentServer`) and `package.json`;
  - the registry digests listed above.

  Treat a Canvas release as the driver of the OpenHands unit, because the SDK and automation pins follow from it.

## 7. Reproduction commands

No credentials were used. The only bearer tokens were the anonymous pull tokens that GHCR and Docker Hub issue for public images; they were not printed or stored. `gh` is not installed on this host, so unauthenticated `curl` against `api.github.com` was used instead.

```sh
# Tag -> commit (peeled "^{}" line present only for annotated tags)
git ls-remote https://github.com/OpenHands/software-agent-sdk.git 'refs/tags/v1.60.1' 'refs/tags/v1.60.1^{}'
git ls-remote https://github.com/OpenHands/OpenHands.git          'refs/tags/v1.36.0' 'refs/tags/v1.36.0^{}'
git ls-remote https://github.com/OpenHands/automation.git         'refs/tags/1.30.1'  'refs/tags/1.30.1^{}'
git ls-remote https://github.com/assistant-ui/assistant-ui.git    'refs/tags/@assistant-ui/react@0.15.32' 'refs/tags/@assistant-ui/core@0.3.32'
git ls-remote https://github.com/Fission-AI/OpenSpec.git          'refs/tags/v1.16.0' 'refs/tags/v1.16.0^{}'
git ls-remote https://github.com/MrLesk/Backlog.md.git            'refs/tags/v1.55.3' 'refs/tags/v1.55.3^{}'
git ls-remote https://github.com/go-gitea/gitea.git               'refs/tags/v28.3.0' 'refs/tags/v28.3.0^{}'
curl -s https://api.github.com/repos/go-gitea/gitea/git/tags/f1cd050b55a46ae556cf992576d01b4a08bd793a   # object.sha, verification

# PyPI sha256 (urls[].digests.sha256) and requires_dist / requires_python
curl -s https://pypi.org/pypi/openhands-sdk/1.60.1/json
curl -s https://pypi.org/pypi/openhands-tools/1.60.1/json
curl -s https://pypi.org/pypi/openhands-workspace/1.60.1/json
curl -s https://pypi.org/pypi/openhands-agent-server/1.60.1/json
curl -s https://pypi.org/pypi/openhands-automation/1.30.1/json
# PEP 740 provenance (404 for the four SDK packages; 200 for automation)
curl -s -H 'Accept: application/vnd.pypi.integrity.v1+json' \
  https://pypi.org/integrity/openhands-sdk/1.60.1/openhands_sdk-1.60.1-py3-none-any.whl/provenance

# npm dist.integrity, gitHead, engines, peerDependencies
curl -s https://registry.npmjs.org/@openhands%2Fagent-canvas         # versions['1.36.0']
curl -s https://registry.npmjs.org/@openhands%2Ftypescript-client    # versions['1.60.1']
curl -s https://registry.npmjs.org/@assistant-ui%2Freact             # versions['0.15.32']
curl -s https://registry.npmjs.org/@assistant-ui%2Fcore              # versions['0.3.32']
curl -s https://registry.npmjs.org/@fission-ai%2Fopenspec            # versions['1.16.0']
curl -s https://registry.npmjs.org/backlog.md                        # versions['1.55.3']
curl -s https://registry.npmjs.org/backlog.md-linux-x64/1.55.3
curl -s https://registry.npmjs.org/backlog.md-linux-arm64/1.55.3
# npm provenance (decode bundle.dsseEnvelope.payload; compare subject sha512 with dist.integrity, read resolvedDependencies gitCommit)
curl -s https://registry.npmjs.org/-/npm/v1/attestations/@openhands%2Fagent-canvas@1.36.0
curl -s https://registry.npmjs.org/-/npm/v1/attestations/@openhands%2Ftypescript-client@1.60.1
curl -s https://registry.npmjs.org/-/npm/v1/attestations/@assistant-ui%2Freact@0.15.32
curl -s https://registry.npmjs.org/-/npm/v1/attestations/@assistant-ui%2Fcore@0.3.32
curl -s https://registry.npmjs.org/-/npm/v1/attestations/@fission-ai%2Fopenspec@1.16.0
curl -s https://registry.npmjs.org/-/npm/v1/attestations/backlog.md@1.55.3

# OCI index digest: Docker-Content-Digest header, cross-checked as sha256 of the returned body
ACCEPT='application/vnd.oci.image.index.v1+json,application/vnd.docker.distribution.manifest.list.v2+json'
T=$(curl -s 'https://ghcr.io/token?scope=repository:openhands/agent-server:pull' | jq -r .token)
curl -s -D- -H "Authorization: Bearer $T" -H "Accept: $ACCEPT" https://ghcr.io/v2/openhands/agent-server/manifests/1.60.1-python
curl -s -D- -H "Authorization: Bearer $T" -H "Accept: $ACCEPT" https://ghcr.io/v2/openhands/agent-server/manifests/e99e5c7-python
T=$(curl -s 'https://ghcr.io/token?scope=repository:openhands/agent-canvas:pull' | jq -r .token)
curl -s -D- -H "Authorization: Bearer $T" -H "Accept: $ACCEPT" https://ghcr.io/v2/openhands/agent-canvas/manifests/1.36.0
T=$(curl -s 'https://auth.docker.io/token?service=registry.docker.io&scope=repository:gitea/gitea:pull' | jq -r .token)
curl -s -D- -H "Authorization: Bearer $T" -H "Accept: $ACCEPT" https://registry-1.docker.io/v2/gitea/gitea/manifests/28.3.0
curl -s -D- -H "Authorization: Bearer $T" -H "Accept: $ACCEPT" https://registry-1.docker.io/v2/gitea/gitea/manifests/28.3.0-rootless
curl -s -D- -H "Accept: $ACCEPT" https://docker.gitea.com/v2/gitea/manifests/28.3.0
# Image provenance: fetch the unknown/unknown attestation manifest from the index, then its
# in-toto SLSA layer blob; read build-arg:OPENHANDS_BUILD_GIT_REF / OPENHANDS_BUILD_GIT_SHA.
# Canvas label: amd64 manifest -> config blob -> config.Labels["org.opencontainers.image.revision"].

# Release asset digests (assets[].digest) and upstream checksum files
curl -s https://api.github.com/repos/OpenHands/software-agent-sdk/releases/tags/v1.60.1
curl -s https://api.github.com/repos/OpenHands/OpenHands/releases/tags/v1.36.0
curl -s https://api.github.com/repos/Fission-AI/OpenSpec/releases/tags/v1.16.0
curl -s https://api.github.com/repos/MrLesk/Backlog.md/releases/tags/v1.55.3
curl -s https://api.github.com/repos/go-gitea/gitea/releases/tags/v28.3.0
curl -sL https://github.com/OpenHands/software-agent-sdk/releases/download/v1.60.1/SHA256SUMS
curl -sL https://github.com/Fission-AI/OpenSpec/releases/download/v1.16.0/SHA256SUMS
curl -sL https://github.com/go-gitea/gitea/releases/download/v28.3.0/gitea-28.3.0-linux-amd64.sha256
curl -sL https://github.com/go-gitea/gitea/releases/download/v28.3.0/gitea-28.3.0-linux-arm64.sha256
curl -s  https://dl.gitea.com/gitea/28.3.0/gitea-28.3.0-linux-amd64.sha256
curl -sL https://github.com/go-gitea/gitea/releases/download/v28.3.0/gitea-28.3.0-windows-amd64.exe.sha256   # F-06.1
curl -s  https://dl.gitea.com/gitea/28.3.0/gitea-28.3.0-windows-amd64.exe.sha256                           # F-06.1

# Interface/contract sources at the candidate revision
curl -s https://raw.githubusercontent.com/OpenHands/OpenHands/v1.36.0/config/defaults.json
curl -s https://raw.githubusercontent.com/OpenHands/OpenHands/v1.36.0/package.json
curl -s https://raw.githubusercontent.com/OpenHands/OpenHands/v1.36.0/docs/DEVELOPMENT.md
curl -s https://raw.githubusercontent.com/OpenHands/OpenHands/v1.36.0/src/lib/index.ts
curl -s https://raw.githubusercontent.com/OpenHands/OpenHands/v1.35.0/config/defaults.json   # also v1.31.0..v1.34.0
curl -s https://raw.githubusercontent.com/OpenHands/software-agent-sdk/v1.60.1/clients/typescript/package.json
curl -s https://raw.githubusercontent.com/OpenHands/software-agent-sdk/v1.60.1/openhands-agent-server/openhands/agent_server/server_details_router.py
curl -s https://raw.githubusercontent.com/OpenHands/software-agent-sdk/v1.58.2/openhands-agent-server/openhands/agent_server/server_details_router.py
curl -s https://raw.githubusercontent.com/OpenHands/software-agent-sdk/v1.60.1/openhands-agent-server/openhands/agent_server/config.py
curl -s https://raw.githubusercontent.com/assistant-ui/assistant-ui/2769cdf4db1b95f8e3f627910caf12b39a58216e/packages/react/src/index.ts
curl -s https://raw.githubusercontent.com/MrLesk/Backlog.md/v1.55.3/CLI-INSTRUCTIONS.md
curl -s https://raw.githubusercontent.com/Fission-AI/OpenSpec/v1.16.0/docs/cli.md
curl -s https://raw.githubusercontent.com/go-gitea/gitea/v28.3.0/go.mod
curl -s https://api.github.com/repos/go-gitea/gitea/security-advisories/GHSA-r9ch-mqjm-g67v
curl -s https://api.github.com/repos/go-gitea/gitea/security-advisories/GHSA-w5pg-649r-p6gg
curl -s https://api.github.com/repos/OpenHands/typescript-client   # archived: true
```

### Second resolution

At 2026-11-06T00:02:28Z, a stdlib-only script re-queried every commit, tag object, PyPI sha256, npm integrity, OCI index and platform digest, and GitHub release asset digest recorded in `candidates.json`. It ran against the upstream sources listed above. **51 checks, 0 differences.**

Separately, the raw `git ls-remote` output for all seven repositories was captured a second time at 2026-11-06T00:03Z. It was **byte-identical** to the first capture, taken during the retrieval session that began at 2026-11-05T23:52:10Z: 10 refs.
