# Hosting-provider prerequisite audit (decision 0017, Consequences)

> **Recorded by the Overseer (2026-11-10).** A Builder's read-only audit at `d95542e`, scheduled by decision 0017 (Consequences). The Overseer spot-checked findings E (inventory, decision 0006 and the log rows) against the tree. **Result: no hosting provider is a prerequisite of operating the system (class P = 0).** Rulings and reconciliation are in [`bootstrap-log.md`](bootstrap-log.md) (Decisions, 2026-11-10, "Hosting-provider prerequisite audit"); the per-finding remedies below are the Builder's suggestions, not decisions. The evidence drafts named in section 4 (d) are kept unchanged, as decision 0017 directs.

Read-only audit. It asks whether any plan leaf, document, tool, task target or test makes a
third-party hosting provider a prerequisite of **operating** the engineering system, as opposed
to publishing this repository. The provider's authentication, API, CLI, Actions/CI, issue
tracker, connectors and URLs are all in scope. Local Gitea is the selected governance service
and is not a finding by itself.

## 1. Method

- **Revision audited:** `main` at `d95542ed0c3510f6058fbcf332722c8201af88ca`. The tracked tree
  was clean (`git status --porcelain --untracked-files=no` was empty). 642 tracked files.
- **Scope:** tracked files only, through `git grep`, `git ls-files`, `git show HEAD:<path>` and
  `sed` line reads of tracked files. I did not open the seed zip, list any untracked file, use
  the network, use a provider tool or credential, or run any test or repository tool. The
  Control Plane Knowledge surface was not used: the dispatch limited this audit to direct
  reading.
- **No `.github/` tree is tracked** (`git ls-files | grep -i .github` is empty). No workflow,
  CODEOWNERS or Dependabot file is tracked.
- **Pass 1, provider terms.** Case-insensitive, tracked files:
  `git grep -I -i -c -E 'github|gitlab|bitbucket|azure devops|glab|ghcr\.io|GITHUB_TOKEN|codeowners|dependabot|workflow_dispatch|gh pr|githubusercontent'`
  matched **2,114 lines in 73 files**. Separate fixed-string counts were also taken for
  `api.github.com`, `github cli`, `gh auth`, `gh api`, `gh issue`, `gh release`, `GH_TOKEN`,
  `dev.azure`, `github actions` and `gh cli`. The last eight have 0 hits outside the counted
  set.
- **CLI check:** `git grep -E "['\"]gh['\"]|which\(.gh|\bgh (auth|api|repo|pr|issue|release|run|workflow)\b|GH_TOKEN|GH_HOST|GITHUB_(API_URL|SERVER_URL|REPOSITORY)"`
  found no invocation of a provider CLI. The only `'gh'` is a Python module alias in a Gitea
  test, at `integrations/gitea/tests/test_gitea_host.py:1158`.
- **Provider git-token settings:** `provider_tokens|git_provider|git provider|ProviderType|GITLAB_TOKEN|BITBUCKET`
  had 0 hits. No OpenHands git-provider integration is configured anywhere.
- **Pass 2, external publication language, provider-neutral.**
  `upstream report|to be filed|ready to file|filing|file the|upstream issue|pull request|open a pr|upstream pr|publication|issue tracker|report upstream`
  was searched across the plan JSON (counted by term, then read by leaf), `task_prompts/`, the
  projections, `docs/`, the root documents, `decisions/`, `security/`, `policy/`, `profiles/`,
  `tools/`, `integrations/`, `composition/` and `evidence/bootstrap-log.md`.
- **Large files** were searched by term and read by leaf or line:
  - the plan JSON, by task id (E-01.4.3, F-10.6, R-05.4.x, R-05, R-02.2, G-04.4.2 and the
    review-Skill leaf);
  - the blueprint, with a URL tally by repository and a tag-stripped prose search;
  - the CSV and HTML projections.
- **Counting unit:** one matched line, with each line assigned to exactly one class. A line
  that mixes contexts (for example, the plan HTML's embedded JSON at line 8577) takes the class
  of its dominant context.
- **Class A** is split in two:
  - **A0** is a term match that is not a hosting-provider dependency of any kind: Gitea's
    GitHub-compatible names, secret-detector token shapes, synthetic canaries, negative tests,
    provider-neutrality statements and substring false positives such as "throu**gh pr**oduct".
    These need no action. They are listed by group in section 2.4.
  - **A1** is a genuinely ambiguous hit. There are none.

## 2. Counts and individual findings

### 2.1 Counts

| Class | Pass 1 (provider terms), lines | Pass 2 (publication language), additional findings |
|---|---|---|
| **P**: prerequisite of operating | **0** | 0 |
| **R**: publishing or hosting this repository | 52 | (not counted) |
| **U**: upstream reference or pinned fetch | 1,952 | (not counted) |
| **E**: external publication or reporting | 21 | 9 findings (E-1 to E-9 below cover both passes) |
| **A0**: non-dependency match, no action | 89 | n/a |
| **A1**: ambiguous | 0 | 0 |
| **Total** | **2,114** | |

### 2.2 P findings

**None.** No plan leaf, tool, task target, test or document requires a hosting provider's
authentication, API, CLI, Actions or issue tracker for the engineering system to work. The
closest cases are pinned fetches whose origin is a provider host. Those are class U and are
listed as notable in section 3.

### 2.3 E findings

The table states for each finding whether its remedy would touch an integrity-tracked (IT)
file.

| # | Location | Quote (25 words or fewer) | Why E | Suggested remedy |
|---|---|---|---|---|
| E-1 | Plan JSON, leaf **E-01.4.3**: `action` (line 3343), `artifact` (3344), `proof` (3345), execution copies (3354, 3361, 3362), prompt (3375); amendment log, line 45 | "File the upstream report and record its reference; the report does not discharge this leaf." Proof: "…and the upstream report reference is recorded." | The action mandates filing an upstream report. The proof requires an upstream issue-tracker reference, which in practice is a GitHub issue or PR. The leaf PASSED on 2026-11-09 without filing, because an equivalent record (BerriAI/litellm#48292) already existed. The text still contradicts 0017 points 2 and 3. | Through the integrity process: reword the action, artifact and proof to "record any equivalent upstream record found; an external report is deferred and optional (decision 0017) and is not part of acceptance". **IT: yes**: the plan JSON, its HTML and CSV projections, `task_prompts/E-01.4.3.md`, and the `task_manifest.json` and `SEED_MANIFEST.json` hashes. The leaf has passed, so this is consistency only and blocks nothing. |
| E-2 | Projections of E-1: plan HTML lines 3570, 3582, 3585, 3612, 8577; CSV row 71 (line 71); `task_prompts/E-01.4.3.md` lines 13, 16, 43 | "File the upstream report and record its reference…" / "…the upstream report reference." | The same mandate in the projections and the dispatch prompt. | Covered by E-1's amendment. **IT: yes.** |
| E-3 | `security/inventory.json:1929` (limit `fd-outer-server-local-recovery`, `detail`), rendered as `security/README.md:302` | "Upstream report to be filed against 1.60.1 (skip local recovery for Docker-backed conversations, or confine it to the status repair…" | A live security-inventory record that reads as **pending** external filing (OA-03). OA-03's authority was withdrawn by 0017. | Reword to "an upstream report is prepared (`evidence/OA-03-openhands-resume-report.md`) and deferred, optional external reporting (decision 0017)". Then re-render the README with the inventory's render check. **IT: no** (ordinary records). |
| E-4 | `decisions/0006-guest-provisioning-channel-and-image-conformance.md:322` | "Recorded limit: `fd-outer-server-local-recovery` … An upstream report is to be filed." | An accepted decision record that states filing as pending. 0017 says "where an earlier record … disagrees, this record governs and the other is the defect." | A dated Overseer or Owner note on 0006 that points to 0017: the report is deferred and optional. **IT: no**, but `decisions/` is the Owner's record, so the edit needs Owner direction. |
| E-5 | `evidence/OA-03-openhands-resume-report.md` lines 3–15 (status header), and lines 13, 44, 179, 189, 191, 197, 246 in Pass 1 | "Status: draft, ready for the Owner's decision. Not filed. … Filing is an external publication and needs the Owner's authorization (OA-03)." | Its status line still presents the draft as awaiting an Owner decision. 0017 deliberately left the evidence files unchanged, and the bootstrap log's Resolved table governs. | None required (0017: "their evidence files are unchanged"). Optional: one superseding status line pointing to 0017, if the Owner wants the file to stand alone. **IT: no**; evidence is Owner-reserved. |
| E-6 | `evidence/E-01.4.3-start-race.md` §13: lines 463, 486, 489, 490, 509 | "**Filing:** not possible from this session. No authenticated GitHub tool is available…"; "OA-02 … revised for accuracy … ready to file" | Filing-preparation text that names a GitHub tool as the blocker and calls the draft "ready to file". Lines 465, 472 and 475, which cite the litellm upstream fix records, are U: the addendum allows tracking known upstream issues. | Same as E-5: no change required; an optional pointer to 0017. **IT: no.** |
| E-7 | `evidence/F-10.6-transports.md`: lines 14, 304, 322, 425–427 | "Upstream report: Dulwich `extra_headers` (draft, not filed: filing is the Owner's act)" | A prepared upstream report. "Filing is the Owner's act" reads as an outstanding Owner act. | Same as E-5. **IT: no.** |
| E-8 | `evidence/bootstrap-log.md`, Leaves table: line 131 (E-01.2.2), line 144 (F-10.6), line 135 (E-01.4.3) | "upstream reports not yet filed" (131); "ready-to-file draft in the evidence (Owner action OA-09)" (144); "the companion note is OA-02, informational" (135) | Leaf verdict rows that still describe filing as outstanding. The Resolved table (lines 70–72) records the withdrawal. | Optional: append "(publication authority withdrawn, decision 0017)" to the three rows. **IT: no**; the bootstrap log is Owner-reserved evidence. |
| E-9 | `evidence/bootstrap-log.md`, Owner-action Resolved rows 70, 71, 72 and Decisions history at lines 249, 269, 272, 344–371, 422, 434, 476–486 | "Filing waits only for an authenticated GitHub tool" (row 71, after "History:") | Historical verbatim directions and the rows' "History:" clauses. Each row's leading resolution is "Publication authority withdrawn, unexercised". | None: this is a correct historical record, and the Decisions section is a verbatim log. |

### 2.4 A0 (non-dependency matches; no action), by group

- **Gitea Actions' GitHub-compatible names (Gitea is the selected service):**
  - `decisions/0016-…` lines 29, 31, 36, 39, 94, 120, 123, 136, 157, 161, 173, 220, 226;
  - `policy/README.md` 667, 711, 717, 735, 737, 742;
  - `policy/ci-token-secret-policy.json` 21, 26, 147, 149, 154;
  - `policy/ci-runner-profile.json` 152, 182, 191;
  - `policy/ci/workflows/validation.yml:13`;
  - `security/README.md` 171, 211, 212;
  - `security/inventory.json` 731, 746, 1699;
  - `tools/check_ci_policy.py` 28, 131, 1096–1100;
  - `evidence/Q-02.1-hostile-ci-policy.md` 34, 36, 41, 81, 103.

  This group covers `GITHUB_TOKEN` as Gitea's job-token alias, the `/twirp/github.actions…`
  route, `workflow_dispatch` and `DEFAULT_ACTIONS_URL`.

  It is also a **positive control**. `policy/ci-runner-profile.json:135` sets
  `"default_actions_url": "self"`. `tools/check_ci_policy.py:807-809` and `:1125` fail a policy
  that would let a `uses:` reach github.com: "no uses: anywhere: nothing is fetched at run
  time". CI therefore has no runtime dependency on GitHub.
- **Negative tests of that policy:** `tools/tests/test_check_ci_policy.py` 161, 376–380, 411,
  493 (`default_actions_url = 'github'` must FAIL).
- **Secret-detector shapes and synthetic canaries:**
  - `tools/guest.py` 1981, 2056;
  - `tools/guest_drill.py` 132, 144;
  - `tools/tests/test_guest.py` 1047, 1320;
  - `tools/tests/test_publication_gate.py` (10 lines, synthetic `ghp_` token);
  - `evidence/F-03.3.1-guest-surfaces.md` 167, 217, 251, 268, 374.
- **Provider-neutrality statements and denials:**
  - `decisions/0017-…` 10, 11, 16, 28;
  - `evidence/bootstrap-log.md` 844, 846, 847, 876, 1007 (the Owner's verbatim 0017
    directions);
  - `evidence/S-03.1-owner-authorization-request.md:31` ("no GitHub");
  - plan JSON 9760 and 9771 (review Skill "without assuming GitHub-only APIs");
  - `integrations/lineage/tests/test_references.py:527`, which asserts that a `'GitHub'`
    commit authority is **refused**.
- **Substring false positives** ("throu*gh pr*…"):
  - `policy/README.md:174`;
  - `policy/role-tokens.json:132`;
  - `evidence/F-10.6-transports.md:46`.

## 3. Aggregates for R and U

### R: publishing or hosting this repository (52 lines)

| Area | Lines | Content |
|---|---|---|
| Root docs | `CONTRIBUTING.md:17`; `docs/development.md` 25, 1706, 1735–1741 | The public clone URL; the "GitHub push protection" backstop for this repository; the gate's limits ("edits made on GitHub, issue and PR text"). |
| Policy | `policy/README.md` (8), `policy/role-tokens.json` (8), `policy/network-matrix.json` (6), `policy/ci-token-secret-policy.json:107` | `cred-owner-github` (Owner role, "the Owner's own account at the provider"); `nm-ext-owner-github` (Owner push, behind the gate); `external:github` = "The public GitHub origin of this repository". |
| Security | `security/inventory.json` (12), `security/README.md` 163, 198, 259 | `op-git-push-public`, `repo-github-public`, `cred-owner-github` custody "not inspected". |
| Decisions, evidence, tests | `decisions/0016:44`; `evidence/S-01.4-network-matrix.md` 58, 296; `evidence/bootstrap-log.md:154` (F-02 reconciled with the existing repository); `tools/tests/test_check_ci_policy.py` 829–830; `tools/tests/test_check_security_inventory.py:162` | The same identities. |

Note (no finding): the public-origin identities are provider-named (`external:github`,
`cred-owner-github`, `repo-github-public`). They describe where this repository is published,
which 0017 point 6 allows. Nothing in operation consumes them. If 0017 point 7's "provider-neutral
at the semantic boundary" is later read to cover identifiers, renaming them to something like
`external:public-origin` would be an ordinary policy change, not an integrity-tracked one. That
is a redesign question for the Overseer, not a defect.

### U: upstream reference or pinned fetch (1,952 lines)

| Area | Lines | Nature |
|---|---|---|
| `composition/inventory/generated/grant-summary.json` | 1,254 | SBOM licence-scan output: Go module paths `github.com/...` and 21 `github-action:` package ids found inside upstream images. Data only. |
| npm locks (`composition/lock/npm/package-lock.json`, `apps/owner-host/package-lock.json`) | 321 | `funding` metadata (`type: github`, sponsor URLs). No `resolved` URL points at GitHub, so there are no git dependencies. |
| Blueprint | 74 | Source citations to about 45 upstream repositories. Prose at lines 950, 982 and 1894 says OpenHands' PR-posting is "GitHub-specific" and that Gitea uses the Skill with a narrow adapter **rather than** the GitHub Action, which is a provider-neutral stance. |
| `composition/` (compatibility matrix, candidates, components lock, lock README, resolve.py, inventory ledger, scan manifest, Grant config, publication audit, component inventory) | 182 | Pins, source repositories, release-asset URLs, checksum files, the GHCR image ref and recorded resolution commands. |
| `profiles/` (matrix, `provision.lock.json`, msys2 lock, `profile.json`, PREREQUISITES) | 33 | Licence links; the agent-server binary and crane from GitHub releases; the image from `ghcr.io`; the MSYS2 keyring; the disabled litellm cost-map fetch. |
| `decisions/` 0001, 0003, 0006, 0015 | 14 | Image refs, upstream sources, the litellm `raw.githubusercontent.com` start-up fetch that is denied and disabled (`LITELLM_LOCAL_MODEL_COST_MAP`). |
| `docs/development.md` | 10 | Lines 79, 247, 254, 280, 854, 1504–1511, 1608, 1620: the network notes for inventory, Gitea install and upgrade, provision-fetch, Task and Gitleaks. |
| `Taskfile.yml:499`; `integrations/gitea/README.md:40`; `integrations/repository/README.md` 483–484; `catalog/README.md:50`; `CONTRIBUTING.md:32` | 6 | Gitea install "Network (GitHub, once)"; F-10.6 anonymous ls-remote; upstream links. |
| Tools and tests | 18 | `tools/publication_gate.py` 61, 65; `tools/guest.py` 5003, 5144; the pinned URL and host assertions in `test_gitea_host.py:240`, `test_provision_fetch.py`, `test_check_profile.py`, `test_guest.py`, `test_image_inspect.py`, `test_provision.py`. |
| Plan and projections, F-10.6 | 8 | "with network authorized, ls_remote the eight locked source tags on GitHub" (plan JSON 2672, 2681, 2703; HTML 2863, 2875, 8577; CSV line 57; `task_prompts/F-10.6.md:13`). The proof has an escape: "or G14 is recorded as not established". |
| `evidence/` (F-04.1a, F-04.1b, F-04.1c, F-04.2, F-06.1, F-10.1, S-03.3, dulwich inventory, Q-02.1 17 and 212, E-01.4.3 173, 272, 465, 472 and 475, F-10.6 217, bootstrap-log 75, 121, 195 and 198) | 32 | Observed fetches, digests and upstream fix records. |

**U entries that need a provider credential: none.**

- `composition/resolve.py` runs git and HTTP in a scrubbed environment ("no inherited
  variables, hence no credentials or tokens", line 410).
- Its OCI tokens are anonymous and held in memory only (lines 34 and 694).
- The `github-asset-digest` method calls `api.github.com` **unauthenticated**
  (`composition/lock/README.md:62`: "unauthenticated, 2 API calls").
- GHCR pulls use anonymous pull tokens (`composition/compatibility-matrix.md:321`).
- The Gitleaks, Gitea and provision downloads send no `Authorization` header. The only Basic
  auth in these tools goes to the local Gitea (`gitea_host.py:834`).

**Notable U: a provider host is the only fetch origin** (anonymous reachability, not an
account):

1. **Publication-safety gate.** `tools/publication_gate.py:65` sets
   `RELEASE_BASE = 'https://github.com/gitleaks/gitleaks/releases/download/v…'`. The `install`
   subcommand has no `--from-file` option (lines 863–864). Every clone therefore needs
   github.com once before its first commit (the AGENTS.md rule). This concerns developing this
   repository rather than operating the system.

   Optional remedy: a `--from-file` path verified against the same pins, as `gitea_host.py`
   already has. **IT: no.**
2. **Guest provisioning.** `guest:provision-fetch` downloads the agent-server binary and crane
   from github.com and the image from ghcr.io (`docs/development.md:280`;
   `profiles/strong-windows-qemu-whpx/provision.lock.json` 193–360). No local-source argument
   was found (`tools/guest.py:12977-12987`). Provisioning a fresh execution guest is therefore an
   operating step that needs anonymous reach to GitHub and GHCR for these pinned artifacts.
   This is a pinned-artifact fetch, which is U by the dispatch's definition. It is recorded here
   because the fetch origin is a provider host and there is no observed alternative origin.
3. **Gitea install and upgrade** (`Taskfile.yml:499`; `docs/development.md` 247, 254) fetch from
   github.com, but have a `--from-file` alternative. Not a dependency.
4. **Component resolution** (`task resolve` / `task qualify`) needs `api.github.com`
   (unauthenticated) for three lock entries: Backlog.md's two bun binaries and Gitea's source
   tarball (`components.lock.json` 486–524). It also needs `git ls-remote` against github.com
   (R11). This is qualification and release time, and is subject to GitHub's anonymous API rate
   limit; `evidence/E-01.4.3-start-race.md` records one search being cut off by it.

## 4. Specific answers

**(a) Does any plan leaf's acceptance or proof require a hosting provider's CI, API, CLI or
issue tracker?**

No CI, API or CLI requirement exists. One leaf touches an issue tracker:

- **E-01.4.3**'s action says "File the upstream report", and its proof says "the upstream
  report reference is recorded". That requires an upstream issue-tracker reference, so it is
  class E (E-1, E-2).
- It passed by recording an existing upstream record, without filing. Its text still conflicts
  with 0017, and amending it is an integrity-tracked change.
- **F-10.6**'s proof reads upstream tags on GitHub anonymously, with an escape ("or G14 is
  recorded as not established"). It is U.
- The release leaves (R-05.4.1, R-05.4.2, R-05.4, R-05) publish to **Gitea** ("publish Gitea
  tag/artifacts"; adoption "Gitea tagged artifacts").
- The review leaf (plan JSON 9760) explicitly says "without assuming GitHub-only APIs".
- No leaf names GitHub Actions. The CI policy forbids GitHub action fetches
  (`default_actions_url: self`, no `uses:`).

**(b) Does any tool or Taskfile target call a provider API or need a provider credential?**

No tool or target needs a provider credential, and none invokes a provider CLI. One tool calls
a provider API anonymously:

- `composition/resolve.py` calls the GitHub releases API (`release_api`, `github-asset-digest`)
  for three pinned assets, and the GHCR registry API with anonymous tokens. It runs only under
  `task resolve` / `task qualify`.
- Other targets download from provider hosts as plain HTTPS: `hooks:install`, `gitea:install`
  and `gitea:upgrade`, `guest:provision-fetch`, and the SBOM inventory's Syft and Grant. These
  are not API calls.

All of these are class U.

**(c) Does any document tell an operator that a provider account or CLI is required to operate
(not to contribute)?**

No. The documents name GitHub only:

- for this repository: the clone URL and the "GitHub push protection" backstop (R);
- as anonymous download origins: "Network (GitHub, once)" and similar (U).

The Owner's `cred-owner-github` is described as the push credential for the public repository
(R). No operating step requires it.

**(d) Does anything remaining from the withdrawn OA-02/OA-03/OA-09 publication path read as
pending work rather than deferred internal knowledge?**

Yes. Ordered by how live the record is:

1. `security/inventory.json:1929` and its rendering `security/README.md:302`: "Upstream report
   to be filed against 1.60.1" (E-3). This is a current security record.
2. `decisions/0006-…:322`: "An upstream report is to be filed." (E-4)
3. Plan leaf E-01.4.3 and its projections and prompt: "File the upstream report…" (E-1, E-2).
   The leaf passed, so this is historical, but it is integrity-tracked text.
4. Evidence drafts that read as awaiting the Owner:
   - the `evidence/OA-03-…` status header (E-5);
   - `evidence/E-01.4.3-…` §13, "ready to file" (E-6);
   - `evidence/F-10.6-…`, "filing is the Owner's act" (E-7).

   0017 states that these files stay unchanged, so this is by design. Optional pointer lines
   would remove the ambiguity.
5. The bootstrap log's Leaves rows 131, 135 and 144 (E-8).

The Owner-action queue itself is correct. OA-02, OA-03 and OA-09 sit in the Resolved table,
headed "Publication authority withdrawn, unexercised" (rows 70–72), and no "Needs Owner now"
row refers to them. Their "History:" clauses and the verbatim Decisions log are history (E-9).

## 5. What I could not determine

- **Whether `guest:provision-fetch` can run offline.** I did not determine whether it reuses an
  already-staged, verified state directory without network, or whether any alternative origin
  for the agent-server binary, crane and image is supported. Only its CLI arguments were read.
  Settling this would need a deeper read of `tools/guest.py` around lines 5371–5457.
- **Whether the pre-commit hook fails closed when Gitleaks is absent.** If it does, committing
  in a clone strictly depends on one github.com fetch. The hook logic in `.githooks/` and in
  `tools/publication_gate.py` beyond the CLI was not read.
- **Exact line-to-class assignment inside very long lines.** Blueprint lines and plan HTML line
  8577 each embed many contexts, so each was classed once by its dominant context. The counts
  are exact per matched line, not per occurrence.
- **Hits that use neither the term set nor the publication-language set.** For example, a
  provider reached only by IP address or a vanity domain would be missed. The six release and
  external-state leaves were read to bound this.
- **Runtime behaviour.** Nothing was executed, so the claims about anonymity and absent
  credentials rest on reading the code and the recorded evidence. They were not observed live.
