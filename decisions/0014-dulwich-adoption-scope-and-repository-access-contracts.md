# 0014 - Dulwich adoption scope, the repository-access contracts, and the retained Git CLI

Status: Proposed (Architect draft, 2026-11-09, with the Overseer's rulings of 2026-11-09), implementing the Owner's architectural direction of 2026-11-08; to be accepted by the Overseer at the completion of F-10.2, whose contract suite proves its contracts. Until then nothing in it is authority.

**Authority:** the Owner's architectural direction of 2026-11-08 on Dulwich (verbatim in `evidence/bootstrap-log.md`, Decisions): adopt Dulwich as the preferred Git implementation for Python components; eliminate the external Git executable dependency where possible; one implementation across Windows, Linux and macOS; no unnecessary subprocess creation and management; simpler installation, testing and maintenance; preserve Git behaviour (paths containing spaces, repository integrity, revision resolution, failure semantics); cross-platform contract tests, measured performance and parity; retain the Git CLI only where a documented compatibility gap justifies it; no silent deferral. This record grants no authority of its own: it applies that direction within blueprint decision card SHIP-02 ("ADOPT Dulwich within Python adapters"), the Repository API policy and `#integration-contracts` ("Our Python adapters require no Git executable. Respect capabilities of pinned Dulwich version"), and SHIP-03 (the release-time licence gate). Where this record and those sources disagree, they govern and this record is the defect.

**Gate:** architecture consultation before the plan amendment, gates B (durable decisions no record settles: the adoption scope, the revision grammar, the export byte contract), C (several viable migration structures) and G (two security controls whose strength must not drop: the publication-safety gate, and the integrity verification of bundles pulled from the untrusted guest). The Overseer's rulings of 2026-11-09 override the Architect's draft where they differ: the revision grammar is preserved, not closed (section 2); required test targets never skip Dulwich-dependent tests (section 9).

**Supersedes:** the F-09.4 evaluation outcome "Dulwich not adopted" (`evidence/F-09.4-batched-git.md`, sections 6 and R.5), which the Owner's direction already superseded; this record is its replacement. It refines no accepted record: decisions 0003 and 0006 (the exchange), 0005 (no redistribution), 0009 (managed root; point 8, the tools venv) and 0013 point 7 (the git plane) are unchanged and relied on.

## Context
The blueprint adopts Dulwich for AI Engineering's own Python repository operations, and the Owner directed the migration on 2026-11-08.

The inventory at `bc9a0f9` (`evidence/dulwich-git-inventory.md`) found:
- eleven repository operations in our own adapters (R1-R11, 838 launches per test run);
- the publication gate (H1, run by git as hooks);
- two bootstrap uses (B1 `verify_seed.py --baseline`, B2 `check_prereqs.py --tier basic`);
- four upstream uses (U, out of scope);
- the test fixtures (T, 597 launches).

Its Dulwich 1.2.21 probe on Windows (149 parity checks) found:
- three hard gaps: G4 hooks, G6 strict fsck, G13 credential helpers;
- two contracts that no record fixes: G2 the revision grammar, G3 the export bytes;
- one configuration-discovery dependence on git's presence (G12);
- the rest as parity differences that adapter code can pin.

Dulwich was 7x faster on the traversal's repository access and 25x on one-shot reads; its import costs about 55 ms in a fresh process.

Three questions had no accepted answer: which rows migrate and which retain git, and why; what the adapter's revision and export contracts are; and where the dependency lives relative to the basic tier.

## Considered options
1. **Per-module migration** (planning, guest, Gitea and test tooling each grow their own Dulwich code) versus **one shared repository-access module** behind a narrow interface.
2. **Dulwich as a basic-tier prerequisite** (every clone installs it before the first verification) versus **Dulwich in the managed-root tools venv** (decision 0009 point 8, the PyYAML precedent), installed by `task setup`, with the basic-tier checks unchanged, versus **vendoring the pure-Python wheel** into the checkout.
3. **A closed revision grammar** (names an object directly and refuses navigation) versus **the preserved grammar** (every form git resolves today, implemented over Dulwich and proven equal to git), versus **an open pass-through** (whatever each Dulwich function happens to accept).
4. **Export as working-tree bytes** (git `archive`'s host-dependent end-of-line conversion) versus **blob bytes** (what the repository stores).
5. For the exchange verifier of untrusted guest bundles: **a Dulwich connectivity walk** replacing `git fsck --strict`, versus **git retained as the integrity authority**.
6. For the publication gate: **migrate its reads to Dulwich** versus **retain git wholesale**.
7. For test fixtures: **build them with Dulwich** versus **keep git-built fixtures as the independent oracle** (F-09.3: "Dulwich is not used for fixtures").

## Decision

### 1. Scope: what migrates, what retains git, and why
| Row | Disposition | Governing reason |
|---|---|---|
| R1 work-tree check | migrate | parity difference G8: `Repo.discover` plus a non-bare, non-`.git`-directory check, pinned by tests |
| R2 revisions and object reads | migrate | the preserved grammar (section 2) resolves G1 and G2; G9 accepted (section 3) |
| R3 file lists | migrate | probe: same answers, spaces and non-ASCII included |
| R4 archive export | migrate | the blob-bytes export contract (section 4) resolves G3 |
| R5 exchange push (bundle creation) | migrate | no gap: a Dulwich-written bundle passed `git bundle verify` (probe); the header, pack trailer and bounds are already checked in Python |
| R6 exchange pull verification (`init --bare`, `fetch`, `bundle verify`, `fsck --strict`) | **retain git** | **hard gap G6** (no strict or connectivity fsck; `porcelain.fsck` crashed on a corrupt pack) and G7 (no `bundle verify`). Git stays the integrity authority; see section 7. |
| R7, R8 profile revision and checkout inventory | migrate | parity differences G11 (rendering) and G12 (configuration), resolved by sections 5 and 8 |
| R9 checkout listing for the secret-leak scan | migrate | probe: the same 537 paths; an ignore-rule corpus test keeps it a superset-or-equal of git's listing |
| R10 profile revision stamp (development tooling) | migrate | through the shared module; an unavailable module records `null` with its reason |
| R11 `ls-remote` tag resolution over HTTPS | migrate **once G14 is established** (peeled tags over HTTPS), in the transport-qualification leaf; retained with G14 recorded until then | G14 was not established by the probe (network not authorized) |
| H1 publication-safety gate | **retain git** | **hard gap G4**: git is the hook runner (`core.hooksPath`, `pre-push`), and the gate reads exactly the index and refs git hands it (G5); G10 (`rev-list --all` order). The gate is stdlib-only by design and runs inside git by construction. Its strength is unchanged. |
| B1 `verify_seed.py --baseline` | **retain git**: an operation that genuinely requires the Git CLI | bootstrap ordering: the basic tier runs before any package is installed, and `verify_seed.py` verifies the very lock files that would pin Dulwich; it is integrity-tracked and stdlib-only by design |
| B2 `check_prereqs.py --tier basic` | **retain git**: an operation that genuinely requires the Git CLI | bootstrap ordering: it checks the basic tier before any package is installed, and git is a basic-tier prerequisite because the clone and the hooks are git acts; it changes only if git ever leaves the basic tier |
| T test fixtures | **retain git, by design** | fixtures built by git are the independent oracle of the differential suite (section 8); F-09.3's statement stands. Not a gap: a deliberate choice. |
| U1-U4 upstream git use | untouched | blueprint: "Do not rewrite adopted products' Git integrations" |
| Future uses: the D-01.1 bot push; the P-04.1 acceptance-recorder commit; the R-02.1.2 backup bundle | **Dulwich** for the push (G13 is a gap only for credential-helper flows; the bot flow holds its token in the dispatcher and sends Basic or `Authorization: token`), for the recorder's commit (hook-free by construction, section 6) and for writing backup bundles; **git retained** for verifying a backup bundle at restore (the R6 class) | SHIP-02's verification ("validate clone/commit/ref/push/auth on target OS and Gitea for pinned Dulwich") is the transport-qualification leaf, which D-01.1 depends on |

"Where possible" is therefore realized as follows:
- The product components (planning, lineage, dispatch, the guest exchange push and snapshots, the Gitea tooling) need no git executable.
- Git remains on the dispatcher host for the exchange verifier (R6), where Gitea needs it anyway (U1).
- Git remains in the basic tier for contributors, because the clone, the commits, the hooks and the gate are git acts.

### 2. The revision grammar (G1, G2): preserved, not closed
The module accepts every revision form git resolves today, implements each one over Dulwich, and proves each equal to git's answer in the differential suite (section 8). Where a commit is expected, the answer equals git's `rev-parse --verify <form>^{commit}`; an object name answers as `git cat-file` does.

The preserved forms:
- a full object id: 40 hex digits, or 64 in a SHA-256 repository (upper case accepted and normalized to lower case);
- an abbreviated object id of at least 4 hex digits that is unique in the repository; an ambiguous abbreviation answers "no such object" (`None`), as today;
- `HEAD`, and `@` as its alias;
- a reference by its full name (`refs/...`) or a short name, resolved in git's order: `refs/<n>`, `refs/tags/<n>`, `refs/heads/<n>`, `refs/remotes/<n>`, `refs/remotes/<n>/HEAD`;
- ancestry navigation: `<rev>~N`, `<rev>^N` (`^` is `^1`), and chains of them (`HEAD^^`, `HEAD~1^2`, `main~0`);
- peeling: `<rev>^{commit}`, `^{tree}`, `^{blob}`, `^{tag}` and `^{}`; an annotated tag is peeled to its target;
- `<rev>:<path>`, with a repository-relative UTF-8 path that may hold spaces and non-ASCII characters, and an empty path for the root tree (`HEAD:`); `<rev>` is any preserved form (`HEAD~1:<path>`);
- the index forms `:<path>` and `:<n>:<path>`, read from the repository's own index, as git reads them;
- the reflog form `<ref>@{N}` (`main@{0}`), and `@{N}` for the current branch, read from the repository's own reflog.

A name that resolves to a tree or a blob answers `None` where a commit is expected, as `git rev-parse <tree>^{commit}` fails today. Refused before any repository access, with `REVISION_INVALID`, as today: empty text, a leading `-`, whitespace, C0 controls or DEL.

**The documented compatibility gaps.** Only forms that need a history search or state outside the repository's objects, refs, index and reflog may be refused. Each raises `REVISION_INVALID` before any repository access:

| Refused form | Reason it is a gap |
|---|---|
| `:/<text>` | a history search: the youngest commit reachable from any ref whose message matches |
| `<rev>^{/<regex>}` | a history search: the youngest commit reachable from `<rev>` whose message matches |
| `<ref>@{<date>}` (`main@{yesterday}`, `@{2026-11-01}`) | needs the reflog interpreted against the current wall clock and the host's time zone, so the answer depends on when and where it is asked |
| `@{upstream}`, `@{u}`, `@{push}` (with or without a ref) | depends on configuration (the branch's `remote` and `merge` settings and, for `@{push}`, `push.default` and the remote's push settings, which may come from the user's or the system's configuration), so the answer changes with configuration, not with the repository's content |
| `@{-N}` | a search of HEAD's reflog messages for earlier checkouts: a record of work-tree activity, not of the repository's content |
| ranges: `A..B`, `A...B`, `^A`, `<rev>^@`, `<rev>^!`, `<rev>^-N` | a range names a set of commits, not one object; no caller takes a range |

`integrations/planning/tests/test_git_batch.py` `Equivalence.test_revisions` keeps every form it exercises (`HEAD`, `main`, `refs/heads/main`, full and abbreviated ids, `@`, `HEAD~0`, `HEAD~1`, `HEAD^2`, missing names, a tree and a blob id, `HEAD:<path>`, `HEAD:openspec`, `main@{0}`, `HEAD^{tree}`, an ambiguous abbreviation) and passes unchanged against the module; none of its forms is in the gap list.

An **object name** is a preserved revision, or `<revision>:<path>` as above. Names outside the grammar are refused with `OBJECT_NAME_INVALID` before any access.

Rejected:
- the closed grammar, because it refuses forms git resolves today and the Owner's direction preserves revision resolution;
- the open pass-through, because each Dulwich function accepts a different subset (probe: `parse_commit` lacks `~` and `^`, `parse_object` lacks abbreviations and misreads `^{commit}`), so it would diverge silently.

### 3. Failure semantics and integrity on read (G9)
- `REVISION_INVALID` and `OBJECT_NAME_INVALID` keep their meaning and are raised before any repository access; `REVISION_INVALID` now also covers the gap forms of section 2.
- "No such object" and "ambiguous" answer `None`, as today.
- `GIT_FAILED` keeps its name: it names the Git repository, not the executable, and `lineage_schema.json` documents it as an `authority-unavailable` code. It means the repository could not be read. It now covers a corrupt or mismatched object (`ChecksumMismatch`, `ObjectFormatException`, `zlib.error`, and any Dulwich or OS error at the module boundary), naming the object.
- **Accepted parity difference (G9):** Dulwich verifies the object id on read where `git cat-file` served mismatched content silently (probe). A visible failure is the behaviour the Owner's "preserve repository integrity" asks for.
- `CannotRun` covers "not a git working tree" and "Dulwich is not importable". The latter has the stable code `REPOSITORY_NEEDS_DULWICH`, naming `task tools:install` and the interpreter it prints (the `CONFIG_NEEDS_YAML` precedent). The lineage resolvers keep mapping `CannotRun` to `PROJECT_UNAVAILABLE`.
- Reads raise no `subprocess.TimeoutExpired`: there is no process to time out. Callers' existing `except` clauses stay harmless.
- The `POINTER_*` family, the lineage outcome codes and the dispatch refusals are unchanged.

### 4. The export byte contract (G3)
An export writes **blob bytes**: each file's stored bytes exactly, with no end-of-line conversion, no `text` or `eol` attribute filtering, no `export-ignore`, no `export-subst` and no pax header.
- Regular files are written with mode 0644, and executables 0755 where the OS supports it.
- A symbolic link entry is written as a link only when its target stays inside the export; otherwise the export is refused.
- A gitlink becomes an empty directory.
- The operation is `export_tree(commit, subtree, destination)`; the tar round trip of `git archive` disappears.

Why: git's `archive` output depends on the host's `core.autocrlf` (on this host every text file came out CRLF; on a Linux host it would be LF), so the current contract is accidental and host-dependent, which contradicts "one implementation across platforms". Blob bytes are deterministic, equal on every host, and equal to what the design pointers already digest (`#sha256=` is the blob's sha256).

Consequences:
- The two consumers, OpenSpec (`instructions apply --json` on an `openspec/` export) and Backlog.md (`task view --json` on a `.` export), must be shown to answer the same on an LF blob export as on today's CRLF export. The live suites on this CRLF-configured host are that proof (F-10.3).
- Files a project marks `export-ignore` now appear in the export (harmless to both consumers; recorded).
- A managed project whose tools require a CRLF working tree is not supported by the export; none is known.

### 5. Configuration discovery (G12)
The module never discovers configuration by finding git on PATH implicitly. Every call site names its configuration policy:
- `host`: the user and system configuration git would read on that host, located as Dulwich's default backends locate them;
- `repository`: the repository's own `config` only;
- `none`.

Evidence records carry `config_sources`, the files actually read. The exchange uses `repository` (today's `GIT_CONFIG_NOSYSTEM` plus a null global); the snapshots of the Owner's checkout use `host` and record it. Behaviour still depends on configuration, as git's does, but which configuration is now explicit and observable. A contract test shows that the `repository` policy answers identically with and without git on PATH.

### 6. Hooks, the gate, and writes (G4)
- The publication-safety gate stays a git hook of this clone and keeps its git reads (H1 retained). Its strength is unchanged: the harness's product code makes no commit or push of this repository; agents and the Owner commit and push through git and its hooks.
- A Dulwich write runs no client hook. To keep G4 fail-closed by construction, **every write operation of the module (the P-04.1 commit, the D-01.1 push) refuses a repository that has client hooks configured** (`core.hooksPath` set, or a non-sample hook present under `<controldir>/hooks/`), with a stable code naming the hook, instead of silently skipping it.
- Commits are built as objects plus a compare-and-set ref update, never through a hook-running porcelain (Dulwich's `do_commit` still attempts hook launches even with `no_verify`).
- The gate's scope is this public repository. Bot pushes to the loopback Gitea (D-01.1) are governed server-side: protected branches, the merge policy (D-01.2), the role tokens (decision 0007, E-01.3.3), the git plane of decision 0013 point 7, and CI (Q-0x). No accepted record requires a client-side secret scan there, so none is weakened (see More information).

### 7. The exchange verifier (G6, G7): git stays the integrity authority
`verify_pulled_bundle` keeps git as the integrity authority: `init --bare`, the prerequisite fetches, `bundle verify`, the fetch into a fresh bare repository, the per-reference comparison, and `fsck --strict --no-progress --no-dangling`.
- A Dulwich connectivity walk is **not a replacement**. `porcelain.fsck` checks objects one by one, with no connectivity, pack-checksum or strict content checks, and it crashed on a one-byte pack corruption (probe). Replacing the first parser of untrusted bytes with a less-exercised one would lower the control's strength even where a walk reports the same verdict on well-formed input.
- A Dulwich walk may only be **added**, before or after git's checks, never instead of them. The control's strength is therefore unchanged.

### 8. Structure
- **One shared repository-access module**, `integrations/repository/` (Python, the standard library plus Dulwich), behind a narrow interface: open and work-tree check, `commit(revision)`, `object_kind(name)`, `blob(commit, path)`, `files(commit, directory)`, `export_tree`, `head()`, `status(paths, untracked)`, `index_entries()`, `listing(cached, others, exclude_standard)`, bundle header parsing, the pack trailer and `write_bundle`.
  - Transports (`ls_remote`, `push`) and writes (`commit`) are added by the leaves that first need them, and never elsewhere.
  - The module is owned by the blueprint's "Repository <-> integration" contract and is a replaceable adapter like the others.
  - The planning adapter's `Git` becomes a thin facade over it, so that lineage, dispatch and readiness keep their calls and codes. `tools/guest.py` loads it by path, as it loads other modules.
- `BatchReader`, the `cat-file` protocol, `Git._run` and the git one-shots leave the planning adapter. `ProcessTree` and `run_tree` **stay**, with their tests, as the launcher-safe runner for the remaining upstream CLI launches (Backlog.md, OpenSpec, node shims). Those launches move onto `run_tree` (F-10.3), which repairs the launcher-orphan shape that F-09.4 fixed for git.
- The **differential contract suite** (recorded expectations that need no git, plus a comparison against git's one-shot answers when git is on PATH, over the probe's corpus) is built before any caller migrates. It is **kept** afterwards as the standing cross-implementation check for every Dulwich pin change. The old product git path is **removed** when its row migrates: no second product implementation remains.
- A **launch census guard** test enumerates every `git` process launch in the tracked Python sources and fails when a site outside the retained list of section 1 appears.
- Cross-platform claims are bounded to observed platforms: Windows (this host) and the Linux verification guest (the disposable Debian guest, Owner decision of 2026-11-07), with the wheel transferred by the decision 0006 pattern (host download, hash check, SFTP, native install or zipimport of the pure wheel). The guest run carries repository test content into the guest, so it needs the Owner's recorded approval for that run (a per-act approval); without it Linux is recorded as not verified. macOS is recorded as not yet verified until a Mac is available.

### 9. The dependency, the tiers and the test targets
- Dulwich **1.2.21** and urllib3 **2.8.0** are pinned, hash-locked and wheels-only, in the `python-tools` set (decision 0009 point 8; the PyYAML precedent) and in the `python-dev-tools` set, with the contract test that keeps the two sets' hashes equal extended to them.
  - Every file PyPI publishes for each version is listed, so pip selects the platform wheel on Windows, manylinux_2_28 (x86_64, aarch64) and macOS, and the pure wheel elsewhere.
  - Hashes are verified independently of the lock tool against PyPI's JSON API (the F-09.2 method). No sdist is built.
- Licence: Dulwich is `Apache-2.0 OR GPL-2.0-or-later`; **Apache-2.0 is elected** and recorded in the lock README, `composition/candidates.json` and the inventory ledger for SHIP-03's release-time gate. Under decision 0005 nothing is redistributed.
- **The basic-tier checks are unchanged**: CPython 3.12+ and git in a full clone, standard library, offline. `check_prereqs.py`, `verify_seed.py` and the publication gate stay stdlib-only and offline.
- **The product components need the tools venv**, and the development reference says so in a new tier row. Product modules import Dulwich from the running interpreter.
- **No silent coverage loss.** Required test targets never skip Dulwich-dependent tests:
  - `task setup` installs the `python-tools` set (hash-locked, wheels-only; network once, as `test:all` already needs `dev:install`);
  - `task test` and `task setup` run the unittest suites under the tools interpreter, which the Taskfile resolves as it resolves the dev venv's (`tools_install.py --python`);
  - a Dulwich-dependent test run without Dulwich fails with `REPOSITORY_NEEDS_DULWICH`, naming `task tools:install`; it never skips.
- Rejected:
  - Dulwich as a basic-tier prerequisite (a network install before the first verification, and the B1 ordering problem);
  - vendoring the pure wheel (decision 0005 and `AGENTS.md`: upstream sources stay external, pinned in `composition/`);
  - a git-CLI fallback inside the product when Dulwich is absent (two implementations and silent divergence);
  - skipping the dependent suites where Dulwich is absent (silent coverage loss).

## Consequences
- New plan group F-10 with six Small leaves (the plan amendment of 2026-11-09):
  - F-10.1 pins Dulwich and urllib3 and makes the required test targets run under the tools interpreter;
  - F-10.2 builds the module and its differential contract suite;
  - F-10.3 migrates the planning adapter (R1-R4) and the upstream CLI launches onto `run_tree`;
  - F-10.4 migrates the exchange push, the snapshots and the listing (R5, R7-R10) and keeps the verifier (R6);
  - F-10.6 qualifies the transports against the host Gitea (SHIP-02; G13, G14; R11);
  - F-10.5 runs the suite on the Linux verification guest, adds the launch census guard and records the evidence.
- Dependencies: D-01.1 depends on the transport qualification (F-10.6), P-04.1 on the planning migration (F-10.3), R-02.1.2 on the bundle writer (F-10.4). E-01.2.2 (in progress) and G-04.3.x gain no dependency. D-01.1's push is the module's push, qualified by F-10.6.
- Measured criteria carried by the leaves:
  - zero product-attributed git launches from the migrated rows;
  - the traversal's repository access at least 4x faster, and a one-shot resolve at least 8x faster, than the git oracle measured interleaved on the acceptance host (probe: 7x and 25x);
  - the wall times of the exchange push and the inventory snapshot recorded against the git path;
  - projections byte-equal to `integrations/lineage/examples/`;
  - budgets re-proposed, and the F-09 gate (serial `task test` at most 150 s) kept.
- Documentation: the planning and lineage READMEs, `lineage_schema.json`'s open notes on git, the development reference's tiers and verification tables, `AGENTS.md`'s command list, and the README's component status.

## Owner confirmation
None is needed for acceptance. The one Owner act this record requires is the per-run approval of the Linux guest run at F-10.5 (section 8); without it the leaf records Linux as not verified and does not pass.

The retentions of section 1 (R6, H1, B1, B2, T and U) and the export contract of section 4 were accepted by the Overseer's rulings of 2026-11-09 within the Owner's direction. The security strength of the exchange verifier is unchanged, because git remains its integrity authority (section 7).

## Evidence
The record is confirmed by the F-10 leaves' evidence: the differential contract suite, the launch census guard, the exchange tests (tampered and incremental bundles), the hooks refusal test on a repository with `core.hooksPath` set, and the recorded measurements on Windows and the Linux verification guest.

Sources:
- `evidence/dulwich-git-inventory.md` (`89cdd56`); `evidence/F-09.4-batched-git.md` sections 6 and R.5; `evidence/F-03.3.1-guest-surfaces.md` (the exchange verification as accepted).
- The blueprint's SHIP-02, SHIP-03, Repository API policy and `#integration-contracts`.
- Decisions [0003](0003-execution-guest-providers-and-isolation-contract.md), [0005](0005-distribution-model-upstream-download-no-redistribution.md), [0006](0006-guest-provisioning-channel-and-image-conformance.md), [0009](0009-managed-data-root-and-configuration-contract.md) and [0013](0013-owner-ui-session-access-and-management-key-custody.md).
- `integrations/planning/planning_adapter.py`, `integrations/planning/tests/test_git_batch.py`, `tools/guest.py`, `tools/publication_gate.py`, `tools/verify_seed.py`, `tools/check_prereqs.py`, `integrations/paths/tools_install.py`, `composition/lock/README.md`.
- Dulwich 1.2.21 source as installed by the probe (`objectspec`, `refs.check_ref_format`, `repo.Repo.discover`, `bundle`, `config.StackedConfig`, `hooks`).

## More information
- **Not proposed: a dispatcher-side secret scan of bot pushes.** The Architect's draft asked whether one is wanted as a new control. No record requires it, and the Owner's direction does not ask for it; it is not part of this decision and not an Owner confirmation. Bot pushes stay governed server-side (section 6).
- **Unrelated but detected (routed to F-10.3):** `Backlog.run` and `openspec_apply_state` launch the upstream CLIs with plain `subprocess.run(timeout=120)`. A `.cmd` npm shim selected by `tool_argv` has the launcher-orphan shape that F-09.4 fixed for git.
