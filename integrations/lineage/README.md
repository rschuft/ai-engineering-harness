# Lineage references

Plan leaf P-03.1, blueprint section
[`#authority`](../../AI_Engineering_Open_Source_Blueprint_Architecture_Deep_Review_2026-10-31.html#authority):
"Each source record keeps its native ID. The integration only needs a small envelope
containing stable pointers, not a replicated object tree", and "Other systems carry
references and projections, not competing lifecycle states". This directory is that
envelope. It defines a typed source reference for every kind of record the Owner's intent
passes through, and a read-only resolver interface. P-03.2 builds the traversal from an
Owner statement through design, task and attempt on top of it.

It is Python standard library only, plus git and the tools named below. It creates no
identifier where a product has a native one, and it never reads, derives or reports a
status.

## Files

| Path | What |
|---|---|
| `lineage_schema.json` | The machine-readable schema (`lineage-reference-schema/v1`): one entry per kind, with its authority, stable identity, revision anchor, pinning, validation rule, status, the leaves that supply it, citations and open points |
| `lineage.py` | The typed references, their canonical text (parser and formatter), the span anchor, `Resolution`, the `Resolver` protocol, the `Registry` and the schema check. It runs no tool and opens no store. |
| `lineage_resolve.py` | The four read-only resolvers and the command line (`schema`, `parse`, `resolve`) |
| `tests/test_references.py` | Round trip of every kind, malformed references, the schema check (and the defects it catches), the span anchor, `Resolution` and `Registry` contracts |
| `tests/test_resolvers.py` | Every outcome of each resolver, against throwaway git repositories, the P-02 fake Backlog.md and its recorded fixtures, and F-05.2 effects-store fixtures; read-only checks; the command line |
| `tests/test_live_lineage.py` | Live, against the pinned Backlog.md 1.55.3 and OpenSpec 1.16.0; skipped unless `AIEH_BACKLOG` and `AIEH_OPENSPEC` are set |

## Reference kinds

| Kind | Canonical form | Authority | Stable identity | Revision anchor | Pinning | Status |
|---|---|---|---|---|---|---|
| `conversation` | `conversation:<thread>[@<message>]` | Owner conversation store (assistant-ui local persistence) | native thread id | the thread through one message | optional | authority unavailable: U-02.1, U-02.2 |
| `message` | `conversation:<thread>/<message>[#sha256:<hex> \| #span:<start>+<length>:sha256:<hex>]` | Owner conversation store | native thread and message ids | content digest, or a span anchor | optional | authority unavailable: U-02.1, U-02.2 |
| `objective` | `outcome:<outcome-id>[@<commit>]` | OpenSpec | the outcomeId assigned on acceptance | OpenSpec commit | (not settled) | **unknown**: the outcomeId is not settled |
| `design` | `openspec:changes/<change>/<artifact>@<commit>#sha256=<hex>` | OpenSpec (git) | change id and artifact path (P-02.1) | commit and blob sha256 | required | implemented |
| `work` | `backlog:<TASK-ID>[@<commit>]` | Backlog.md | Backlog.md task id | commit of the repository holding Backlog.md's files | optional | implemented |
| `attempt` | `openhands:conversation/<uuid>[@<event>]` | OpenHands Agent Server | native conversation id (the reserved UUID, decision 0001) | native event id | optional | authority unavailable: E-01.3.1, E-01.4.1 |
| `commit` | `git:<repository>@<commit>` | Git | repository name and full commit id | the commit id itself | required | implemented |
| `review` | `gitea:<owner>/<name>/pulls/<index>/reviews/<id>@<commit>` | Gitea | repository, pull index, review id | the reviewed commit | required | authority unavailable: E-03.3.1, E-03.3.2, D-01.1 |
| `ci` | `gitea:<owner>/<name>/actions/runs/<run>@<commit>` | Gitea Actions | repository and native run id | the tested commit | required | authority unavailable: Q-03.1, Q-03.2 |
| `authorization` | `gitea:<owner>/<name>/branches/<branch>@<commit>#sha256:<hex>` | Gitea (Owner-only merge onto a protected branch) | repository, protected branch, merge commit | merge commit and manifest sha256 | required | authority unavailable: G-03.1, G-04.3.1 |
| `effect-receipt` | `effect:<fx1-key>[@<seq>#sha256:<hex>]` | effects store (protected executor) | one-time effect key | a journal event of the receipt and its chain hash | optional | implemented (fixtures) |
| `release` | none | Git / Gitea | **unknown** | | | **unknown**: R-01.1, R-02.2.1, R-05.4.2 |
| `catalog` | none | Gitea catalog repository | **unknown** | | | **unknown**: A-01.1 |

Each kind's validation rule, its citations and its open points are in the schema. Derived
records (episodes, the search index, Knowledge providers, the integration store's attempt
receipts, traces) carry references but are never an authority; the schema lists them under
`non_authoritative`.

## Canonical grammar

- A reference is `<scheme>:<body>`; the scheme selects the kind (`gitea` selects among
  `review`, `ci` and `authorization` by its body).
- A **segment** is a native ID the authority assigns: its UTF-8 bytes, each byte outside
  `A-Z a-z 0-9 - . _ ~` written `%XX` with upper-case hex. Any other spelling is refused,
  so a text and its value correspond one to one.
- A **commit** is a full commit id: 40 lower-case hex digits, or 64 in a SHA-256
  repository. Never a branch, a tag or an abbreviation.
- A **sha256** is 64 lower-case hex digits. A **repository** is a name of
  `[A-Za-z0-9_][A-Za-z0-9._-]*` parts separated by `/`; Gitea kinds take exactly
  `owner/name`.
- Every accepted text is canonical: `format(parse(text)) == text`.
- Every kind except `design` satisfies intent-record/v1's reference grammar
  (`^[a-z][a-z0-9+.-]*:[^\s=,]+$`), so it can be an intent record's `source`,
  `acceptance` or `resolution`. The `design` pointer keeps the P-02.1 form unchanged; its
  `=` is outside that grammar.

## Span anchor (message kind)

Overseer ruling D2, carried from P-01.2: a U+00A0 did not survive the model channel, so the
integration fills quotes mechanically from the durable source, and the model references
message spans.

```
conversation:<thread>/<message>#span:<start>+<length>:sha256:<hex>
```

| Part | Rule |
|---|---|
| content | the message text as UTF-8 bytes, exactly as the durable store returns it: no Unicode normalisation, no newline conversion, no trimming |
| `<start>` | byte offset, an integer >= 0 in canonical decimal |
| `<length>` | byte length, an integer >= 1 in canonical decimal |
| `<hex>` | the sha256 of exactly `content[start : start + length]`; always required with a span |
| boundaries | the span lies within the content and starts and ends on UTF-8 character boundaries |

`lineage.span_reference` makes an anchor from the durable bytes, `check_message_content`
applies the rule (otherwise `digest-mismatch`: `SPAN_DIGEST_MISMATCH`, `SPAN_OUT_OF_RANGE`,
`SPAN_NOT_ON_CHARACTER_BOUNDARY`), and `span_bytes` returns the verified quote. The tests
show that a source whose U+00A0 became U+0020 fails the check. Reading the message from a
store and writing the quote into a proposal are not built here (U-02.x, P-03.2).

## Resolution

`resolve(reference)` answers for the pinned revision when the reference has one;
`current(reference)` answers for the same identity at the authority's current revision, so
that a caller can see that a newer revision exists.

| Outcome | Meaning |
|---|---|
| `resolved` | the authority answered, the identity exists and every pinned anchor matches; `observed_revision` and `observed_digest` report what it showed |
| `missing` | the authority does not hold the identity (at the pinned revision, when pinned) |
| `revision-mismatch` | the authority does not hold the pinned revision |
| `digest-mismatch` | the pinned revision exists but its content has another digest |
| `authority-unavailable` | the authority could not be asked: absent, not configured, refused access, failed, or its own integrity check failed |
| `unsupported-kind` | the kind's identity is not settled, or no kind uses the scheme |
| `ambiguous` | the identity matches more than one record |

Every outcome but `resolved` carries a stable `code`. A `Resolution` has no truth value
(`bool()` raises), so it cannot pass for a success. The `Registry` refuses a resolver whose
outcomes or authority differ from the schema, and an answer outside the resolver's contract.

## Resolvers

| Kind | How | Outcomes and codes |
|---|---|---|
| `design` | `planning_adapter.resolve_pointer` (P-02.1) on git objects only; `current` builds the pointer at `HEAD` | `missing` POINTER_ARTIFACT_MISSING; `revision-mismatch` POINTER_REVISION_MISSING; `digest-mismatch` POINTER_DIGEST_MISMATCH (with the observed digest); `authority-unavailable` PROJECT_UNAVAILABLE, GIT_FAILED |
| `work` | Backlog.md's `task view <id> --json` and `task list --json` through the P-02 wrapper, limited to those two commands. A pinned reference is read by Backlog.md from a `git archive` export of that commit in a temporary directory; the pinned Backlog.md answered there and wrote nothing (observed live). | `missing` WORK_MISSING; `revision-mismatch` WORK_REVISION_MISSING; `ambiguous` WORK_AMBIGUOUS; `authority-unavailable` PROJECT_UNAVAILABLE, BACKLOG_UNAVAILABLE, BACKLOG_VIEW_FAILED, BACKLOG_LIST_FAILED |
| `commit` | `git rev-parse --verify <commit>^{commit}` and `git cat-file -t` in the clone registered for the repository name | `missing` COMMIT_MISSING, COMMIT_NOT_A_COMMIT, COMMIT_ID_MISMATCH; `authority-unavailable` REPOSITORY_NOT_REGISTERED, REPOSITORY_UNAVAILABLE, GIT_FAILED |
| `effect-receipt` | the effects store opened by the caller's `open_store` (its location and custody checks apply), then only `verify_chain`, `get`, `events`, `open_epochs`, `high_water_mark` | `missing` EFFECT_RECEIPT_MISSING (never evidence that the effect did not happen, decision 0004 point 7); `revision-mismatch` EFFECT_EVENT_MISSING; `digest-mismatch` EFFECT_EVENT_DIGEST_MISMATCH; `authority-unavailable` EFFECTS_STORE_UNAVAILABLE, EFFECTS_CHAIN_INVALID |

The work resolver never reads a status: Backlog.md's verdicts stay Backlog.md's (P-02.2).
Backlog.md 1.55.3 refuses `task list --json` when two tasks share an id, so a live duplicate
answers `authority-unavailable` (BACKLOG_LIST_FAILED) with Backlog.md's message; the
`ambiguous` outcome is shown with the fake Backlog.md, which lists both.

## Commands

Run from the repository root (`python3` outside Windows):

```
python -I -B integrations/lineage/lineage_resolve.py schema                       # task lineage:schema
python -I -B integrations/lineage/lineage_resolve.py parse REF [REF ...]
python -I -B integrations/lineage/lineage_resolve.py resolve REF [REF ...] [--current] [--project DIR] [--backlog CMD] [--repo NAME=DIR ...] [--effects-root DIR [--effects-principal SID]]   # task lineage:resolve -- ...
python -I -B -m unittest discover -s integrations/lineage/tests -v                # task lineage:test
```

`--project` enables `design` (and, with `--backlog`, `work`); `--repo` registers a clone
for `commit`; `--effects-root` enables `effect-receipt` with the effects store's live
location policy and custody template, exactly as the effects command line uses them.
Exit status: 0 PASS (all parsed, or all resolved), 1 FAIL, 2 could not run.

## Not yet verified

- Every kind whose status is authority unavailable or unknown: no resolver exists, and
  each answers so explicitly.
- Effect receipts on a live store. None exists (decision 0004, point 4). On the live store,
  OS custody denies ordinary integration processes, so a resolver not run under the store's
  custody identity answers `authority-unavailable`; live resolution belongs with G-04.2.1
  and G-04.2.2. The store's only open path, `open_effects_store`, applies pending
  migrations in a write transaction; at the current schema it changes no content (tested),
  but it is not a strictly read-only open.
- Any host but Windows 11 x86_64 (git 2.52.0, Node 24.19.0), Backlog.md's cross-branch
  lookup (`check_active_branches`) on an exported commit, and repositories large enough
  for the per-resolution `git archive` to matter.
- The `ambiguous` work outcome against the live Backlog.md (it refuses to list instead).
