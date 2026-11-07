# Publication licensing audit (2026-11-06)

An Owner-directed audit. The question: does anything this public repository has
already published, in the current tree or in its history, violate or leave
unresolved a third-party redistribution requirement? It separates current
publication obligations from the obligations of future packaging and distribution.

Audited state: `main` at `b366576`. The repository has 53 commits, 255 tracked paths
and 392 blobs. No path was ever deleted, so history holds no file that the tree does
not. This is an engineering audit, not legal advice. It reuses
[`LEDGER.md`](LEDGER.md) and the generated SBOM and Grant outputs, and does not
re-resolve dependencies.

## Verdicts

**Current publication: no violation found, and no Owner escalation is needed for
published content.**

- Nothing committed, now or in history, is third-party source, a binary, an archive
  or a vendored dependency.
- Third-party components are only *referenced*, by name, version, hash, digest or
  URL, in the locks and inventories. Their content is not redistributed.
- The few third-party-derived fragments that are published are functional, factual
  or attributed quotations. None of them triggers a notice obligation (C3–C6).
- Two documentation defects were corrected in the commit that adds this report:
  - the MIT statements did not separate repository-owned content from third-party
    material (C7);
  - the ledger misstated the licence of func-timeout (C8).

  The commit adds no `NOTICE` file, because no published content requires one.

**Future distribution: not ready.** Any release that ships wheels, images, guest
images or installers will redistribute third-party content (F1–F6). Two licence
terms cannot be established yet: `lmnr-claude-code-proxy` and
`@anthropic-ai/claude-agent-sdk` (U1, U2). These items belong to the existing leaves
G-02.1, R-04.1, R-04.2 and R-03.x; see [Leaf mapping](#leaf-mapping).

**2026-11-06, after the audit: Owner resolutions.**
- Future-distribution readiness is conditional on
  [decision 0005](../../decisions/0005-distribution-model-upstream-download-no-redistribution.md).
  The project downloads third-party dependencies from upstream onto the user's machine
  and does not redistribute them. So F1–F6, and the redistribution side of U1 and U2,
  trigger only when a concrete design actually proposes redistribution.
- U1 and U3 are resolved; U2 stays carried. See [Resolutions](#resolutions-2026-11-06).

## Findings

### CURRENT: content already published

| ID | Artifact | Source and holder | Licence evidence | Obligation | Action |
|---|---|---|---|---|---|
| C1 | Whole tree and history (`git rev-list --all`, 392 blobs) | Repository-owned | No blob contains a NUL byte. The only compressed data are the 12 `generated/*.gz` files. No path with an archive, wheel, executable, image, font or PDF extension was ever added. | None | None |
| C2 | `generated/sbom-*.cdx.json.gz`, `generated/grant-*.json.gz`, `generated/grant-summary.json`, `component-inventory.json` (every historical blob decompressed) | Syft and Grant output about third-party packages | The documents carry only metadata: licence ids, names and expressions; package names, versions, hashes and PURLs; short `author` and `description` strings. No `licenses[].text` field exists, and no string of 400 characters or more is a licence text. `component-inventory.json` already replaces tiktoken's full licence text with a placeholder. | None. Factual metadata, not redistribution of the packages. | None |
| C3 | `generated/grant-default-config.yaml` (blob `86fba9ee`, added `b4f4f4b`) | Output of Grant 0.7.0 `grant config`. Its comment strings come from `cmd/grant/cli/command/config.go` in anchore/grant v0.7.0 (Apache-2.0; no `NOTICE` file at that tag). | The file's own header says `See: https://github.com/anchore/grant`. | None confirmed. It is generated, functional configuration of 32 lines, produced by the tool so that users can keep it. | Provenance recorded in the ledger. |
| C4 | `catalog/openspec/schemas/intent-driven/` (schema and templates; added `db82899`) | Follows the OpenSpec 1.16.0 schema format. The template section headings and YAML keys match OpenSpec's built-in `spec-driven` schema (MIT, "Copyright (c) 2024 OpenSpec Contributors"). | Measured overlap:<br>- `design.md`: 6 of 15 lines (headings);<br>- `proposal.md`: 7 of 83 lines (headings);<br>- `spec.md`: 1 of 6 lines;<br>- `schema.yaml`: 25 of 100 lines, all YAML keys.<br>The longest common run is 10 words; the prose is original. | None confirmed. This is the interface structure OpenSpec's parser requires, not a substantial portion. | Courtesy attribution added to [`catalog/README.md`](../../catalog/README.md). |
| C5 | `catalog/skills/intent-normalization/` | Follows the Agent Skills format (specification repository agentskills/agentskills, Apache-2.0) | No copied text: the longest common run with the specification page is 2 words. `SKILL.md` declares `license: MIT`. | None | None |
| C6 | `evidence/F-03.2.1b-provider-validation.md` (QEMU `-accel help` banner), `profiles/matrix.md` (one sentence quoted from QEMU's `LICENSE`, with its URL), and short attributed quotations of the Incus and QEMU documentation in `profiles/` | QEMU project, Incus project | The quotations are short, attributed and factual. The banner keeps its copyright line. | None | None |
| C7 | MIT statements in `README.md`, `CONTRIBUTING.md`, `docs/development.md` and `catalog/README.md` | Repository owner | `README.md` already separated third-party content. `CONTRIBUTING.md` did not. `docs/development.md` called the repository "MIT-licensed" as a whole, although it publishes third-party metadata. `catalog/README.md` said nothing about licensing. | Accurate licence scope | Corrected in this commit. `LICENSE` is unchanged. |
| C8 | Ledger item 1, func-timeout licence "LGPLv2 / LGPL-2.1" (from `b4f4f4b`) | Tim Savannah, func_timeout 4.3.5 | The sdist's `LICENSE` file (sha256 `da7eabb7…`) is byte-identical to the upstream `LICENSE` at tag 4.3.5, and is the **LGPL version 3** text. Every module header says "Licensed under the Lesser GNU Public License Version 3, LGPLv3". Only `PKG-INFO` (LGPLv2) and the `setup.py` header (LGPLv2.1) say otherwise. GitHub reports `lgpl-3.0`. | Accurate inventory | Ledger corrected. The same old statement remains in `../lock/README.md` (line 127), `../lock/components.lock.json` (`reviewed_sdists[0].license`), decision 0002 (line 21) and the bootstrap log. Those files are outside this task's write scope. |
| C9 | Locks: `../lock/python/*.txt`, `../lock/npm/package-lock.json`, `../lock/components.lock.json`, `profiles/strong-windows-qemu-whpx/qemu-msys2-ucrt64.lock.json` | Registries and mirrors | The locks record names, versions, hashes, digests, URLs and declared licences. No package content. | None. Every install downloads from upstream on the user's machine. | None |

### FUTURE: triggered by packaging, images or binary distribution

**2026-11-06: conditional on decision 0005.** These items trigger only on actual
redistribution: when a concrete design proposes vendoring, mirroring, publishing
modified third-party artifacts, or bundling them into distributable images or
installers. They are re-evaluated at that point, through R-04.x. Pulling or downloading
from upstream on the user's machine does not trigger them.

| ID | Component | Licence evidence | Obligation when redistributed | Leaf |
|---|---|---|---|---|
| F1 | func-timeout 4.3.5, in a wheelhouse, the Linux guest install or a built image (the Agent Canvas image already contains it) | LGPL-3.0 text (C8) | Ship the LGPL-3.0 and GPL-3.0 texts and a prominent notice. Keep the module replaceable. As pure Python, the module is its own source. Repository code that imports it stays MIT. | R-04.1, R-04.2, R-03.1.1, R-03.3.1 |
| F2 | OCI images `agent-server` 1.60.1-python, `agent-canvas` 1.36.0, `gitea` 28.3.0 and `-rootless`, referenced by digest | SBOMs here: many GPL and LGPL Debian packages; ACP CLIs; U1 and U2 inside | Mirroring, re-publishing or building `FROM` these images inherits the GPL/LGPL source and notice duties and the U1 and U2 terms. Pulling the images from upstream does not. | F-04.1 (pull only), R-04.1, R-04.2 |
| F3 | The QEMU closure for `strong-windows-qemu-whpx`: 159 MSYS2 packages, including QEMU (GPL-2.0-or-later AND …), `db` (AGPL-3.0-or-later) and 10 packages declared "custom"; also the Debian cloud image | Licences per package in the lock | Bundling them in an installer requires source offers, licence texts and notices. Today `tools/msys2_lock.py` downloads each package from `repo.msys2.org` on the user's machine. | R-03.3.1, R-04.1 |
| F4 | Backlog.md platform binaries (6 npm packages) | `MrLesk/Backlog.md` `LICENSE` at v1.55.3 is MIT (`2039a3f5…`). The platform packages declare no licence (metadata gap). Syft reports the embedded Bun runtime as unlicensed. | Confirm that the MIT licence covers the platform builds, and the terms of the bundled Bun runtime, before shipping the binaries. | R-04.1 |
| F5 | Weak copyleft (ledger item 7): MPL-2.0 `lightningcss`, `dompurify`, `certifi`, `tqdm` and `orjson` | Declared metadata | MPL-2.0 file-level notice and source availability for shipped copies | R-04.1 |
| F6 | Provider and service terms (ledger items 5, 6 and 10): ACP CLIs, `assistant-cloud`, PostHog, Laminar | Not assessed | A provider-terms inventory before any shipped default enables them | R-04.1, R-04.2 |

### UNRESOLVED: terms that cannot yet be established

| ID | Component | Evidence | Why it is unresolved | What would resolve it |
|---|---|---|---|---|
| U1 | `lmnr-claude-code-proxy` 0.2.0 (platform wheels and an sdist on PyPI). It is a mandatory transitive dependency: `openhands-sdk` 1.60.1 → `lmnr` 0.7.67 (Apache-2.0, requires `lmnr-claude-code-proxy>=0.1.22`). It is installed in the host Python set and present in the Canvas image. | The wheel's `licenses/LICENSE.md` (`fc1b52dc…`) says: "© LMNR AI, Inc. All rights reserved. Use is subject to Laminar's [Terms of Service](https://laminar.sh/policies/terms)." Those Terms (last updated 2026-08-11) license the Content "solely for your personal use or internal business purpose" and say no Content may be "distributed, sold, licensed, or otherwise exploited for resale or redistribution without our express prior written permission". PyPI's Terms of Use say that an uploader of content without a free-redistribution licence grants "all other users of the web site an irrevocable, worldwide, royalty-free, nonexclusive license to reproduce, distribute … the Content", in the exact uploaded form. | Two sources conflict on redistribution. Use is limited to personal or internal-business purposes, and that affects everyone who reproduces the install, not only distributors. **Nothing of this package is published in this repository.** | An Owner decision on use (ledger item 2). Before any redistribution (R-04.2): written permission from Laminar, an upstream clarification from OpenHands, or an architectural change, which would need the Architect. |
| U2 | `@anthropic-ai/claude-agent-sdk` 0.3.220, inside the referenced agent-server image (ledger item 5) | `package/LICENSE.md` (`8ce94b94…`): "© Anthropic PBC. All rights reserved. Use is subject to the Legal Agreements outlined here: https://code.claude.com/docs/en/legal-and-compliance." | Those agreements are not assessed. The package arrives with the upstream image; this repository does not publish it. | The R-04.1 provider-terms inventory, then an R-04.2 decision |
| U3 | MIT scope wording | `LICENSE` grants rights in "this software and associated documentation files". `README.md` and `CONTRIBUTING.md` say "Repository-owned code". | Whether repository-owned documentation, such as the blueprint, the plan and the decision records, is also offered under MIT is the Owner's statement to make. It is not a violation either way. | One Owner sentence, then a one-line wording change |

#### Resolutions (2026-11-06)

The table above is kept as the audit found it. The Owner resolved two of its items
after the audit:

- **U1: resolved by the Owner.** Local use of the pinned OpenHands dependency chain,
  including `lmnr-claude-code-proxy`, is accepted under the applicable upstream terms,
  with no replacement. Laminar's use restriction (personal or internal business
  purposes) remains a recorded usage restriction. The distribution model is
  [decision 0005](../../decisions/0005-distribution-model-upstream-download-no-redistribution.md):
  the redistribution question is re-evaluated, through R-04.x, only if a concrete design
  proposes redistribution.
- **U2: still carried** to R-04.1, for a review of its terms for the intended *use*. Its
  redistribution side is conditional on decision 0005, like F1–F6.
- **U3: resolved.** Everything authored for this repository, code and documentation
  alike, is MIT as `LICENSE` states; third-party material keeps its own licence. The
  wording now says "repository-authored code and documentation" in `README.md`,
  `CONTRIBUTING.md`, `docs/development.md` and `catalog/README.md`. `LICENSE` is
  unchanged.

Metadata gaps that this audit verified upstream and are therefore **not** unresolved:

| Component (ledger items 3 and 8) | Licence at the locked tag | Upstream `LICENSE` sha256 |
|---|---|---|
| openhands-sdk, -tools, -workspace, -agent-server 1.60.1 | MIT ("Copyright (c) 2026 OpenHands contributors") | `14a9b631…` |
| agent-client-protocol 0.12.1 | Apache-2.0 | `cfc7749b…` |
| socksio 1.0.0 | MIT (PyPI classifier and repository) | `7087f0f5…` |
| npm `format` 0.2.2 | MIT, declared in the legacy `licenses` field, which scanners do not read | none fetched |

## Leaf mapping

| Leaf | Carries |
|---|---|
| G-02.1 (pinned supply-chain and licence scanners) | Read declared licences *and* licence files, so that cases like C8 and the metadata gaps above are caught. Configure a project licence policy in place of Grant's default (ledger). |
| R-04.1 (per-artifact SBOM, licence and provider inventory) | F1–F6, U2, and the notices file for every shipped artifact |
| R-04.2 (distribution decision gates) | U1 and U2 redistribution decisions; F2 if images are re-published |
| R-03.1.1, R-03.3.1 (packaging) | F1 and F3: whether packaging bundles or downloads; notices and source offers if it bundles |
| F-04.1 | F2: pull by digest only; no re-publication |
| Owner | U1 (use), U3 (wording) |

**2026-11-06:** the Owner row is resolved (see [Resolutions](#resolutions-2026-11-06)).
Under decision 0005, the R-04.1, R-04.2 and R-03.x items for F1–F6, U1 and U2
redistribution apply only if a concrete design proposes redistribution. R-04.1 still
carries U2's terms for the intended use. F-04.1 pulls by digest, which the model
permits.

## Method and limits

1. Scope:
   - `git ls-files` and `git rev-list --all --objects` at `b366576`;
   - every blob read through `git cat-file`;
   - the 14 gzip blobs (current and historical) decompressed in a scratch directory.

   The scan looked for binaries, copyright, licence and SPDX headers, and "copied/adapted/derived from" notes, then reviewed each hit by hand.
2. Generated artifacts: every JSON string of 400 characters or more was enumerated, and the CycloneDX licence fields were counted.
3. Copied-content checks:
   - The catalog was compared line by line and by longest common word run with OpenSpec 1.16.0's built-in schema. The npm tarball matched the lock's sha512 integrity.
   - The Skill was compared the same way with the Agent Skills specification page.
   - `.gitleaks.toml` extends the Gitleaks defaults by reference (`[extend] useDefault = true`). Its 16 rules are repository-authored, and no default rule is copied.
4. Upstream evidence was fetched on 2026-11-06. The copies, with their sha256, are kept outside the repository and are listed in the Builder's report.
   - PyPI JSON for `lmnr-claude-code-proxy` 0.2.0, `lmnr` 0.7.67, `func-timeout` 4.3.5, `openhands-sdk` 1.60.1, `agent-client-protocol` 0.12.1 and `socksio` 1.0.0.
   - The locked files themselves, each matched against its lock hash:
     - `lmnr_claude_code_proxy-0.2.0-cp312-cp312-win_amd64.whl` (`33629350…`);
     - `func_timeout-4.3.5.tar.gz` (`74cd3c42…`).
   - <https://laminar.sh/policies/terms> and <https://policies.python.org/pypi.org/Terms-of-Use/>.
   - Repository `LICENSE` files at the locked tags:
     - `kata198/func_timeout` 4.3.5;
     - `OpenHands/software-agent-sdk` v1.60.1;
     - `MrLesk/Backlog.md` v1.55.3;
     - `agentclientprotocol/python-sdk` 0.12.1;
     - `sethmlarson/socksio` 1.0.0;
     - `anchore/grant` v0.7.0;
     - `Fission-AI/OpenSpec` v1.16.0.
   - npm `@anthropic-ai/claude-agent-sdk` 0.3.220 and the registry metadata of `format` 0.2.2 and Backlog.md.

**Limits.**

- The audit did not open the OCI images' layers or the Linux and Debian guest contents. It relies on the existing SBOMs and their stated coverage gaps; see the ledger.
- Licences were verified upstream only for the components named above. Every other declared licence is taken as declared.
- The "functional, not substantial" judgements in C3 and C4 are engineering judgements, based on the measured overlap. They are not legal opinions.
