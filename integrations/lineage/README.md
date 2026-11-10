# Lineage references

Plan leaf P-03.1, blueprint section
[`#authority`](../../AI_Engineering_Open_Source_Blueprint_Architecture_Deep_Review_2026-10-31.html#authority):
"Each source record keeps its native ID. The integration only needs a small envelope
containing stable pointers, not a replicated object tree", and "Other systems carry
references and projections, not competing lifecycle states". This directory is that
envelope. It defines a typed source reference for every kind of record the Owner's intent
passes through, and a read-only resolver interface (P-03.1). On top of it, plan leaf P-03.2
adds the read-only traversal from an Owner statement through objective, design, task and
attempt, and its projection with broken-link semantics
([Lineage traversal](#lineage-traversal-p-032)).

It is Python standard library only, plus the shared repository-access module (Dulwich, from
the Python tools set; [decision 0014](../../decisions/0014-dulwich-adoption-scope-and-repository-access-contracts.md))
and the tools named below; it starts no git. It creates no
identifier where a product has a native one, and it never reads, derives or reports a
status.

## Files

| Path | What |
|---|---|
| `lineage_schema.json` | The machine-readable schema (`lineage-reference-schema/v1`): one entry per kind, with its authority, stable identity, revision anchor, pinning, validation rule, status, the leaves that supply it, citations and open points |
| `lineage.py` | The typed references, their canonical text (parser and formatter), the span anchor, `Resolution`, the `Resolver` protocol, the `Registry` and the schema check. It runs no tool and opens no store. |
| `lineage_resolve.py` | The five read-only resolvers (design, objective, work, commit, effect-receipt) and the command line (`schema`, `parse`, `resolve`) |
| `lineage_trace.py` | The read-only traversal from one outcome id and its projection (`lineage-projection/v1`), `Authorities` and the read-only integration-store view; the command line (`trace`) |
| `lineage_samples.py` | The two **SAMPLE** authorities used only by the example and the tests: a statement store over the P-01.2 corpus and attempt records shaped like F-04.2's conversation info |
| `examples/projection-sample-authorities.json` | The example projection with the sample authorities: the whole chain resolves, and is marked sample |
| `examples/projection-real-registry.json` | The same example with the real registry only: statements and attempts are `authority-unavailable` |
| `tests/test_references.py` | Round trip of every kind, malformed references, the schema check (and the defects it catches), the span anchor, `Resolution` and `Registry` contracts |
| `tests/test_resolvers.py` | Every outcome of each resolver, against throwaway git repositories, the P-02 fake Backlog.md and its recorded fixtures, and F-05.2 effects-store fixtures; read-only checks; the command line |
| `tests/test_trace.py` | The traversal: the example (regenerated and compared), read-only proof, every negative resolution fixture, the sample authorities and the command line |
| `tests/test_traversal_git.py` | The traversal's repository access (F-09.4, F-10.3): one opened repository per traversal, closed on a normal end, an exception and a damaged repository (`GIT_FAILED` at once), nothing kept between traversals, no git launched; a resolver call as its own operation; OpenSpec change folders whose names hold a space, resolved as before the batch reader; and the `performance` benchmark `OneTraversal`, whose result is the launch count of one traversal of the example (none with Backlog.md answered in the test process, its three reads with it launched; at most 10) with projections equal to `examples/` byte for byte, and its repository access against the git oracle, interleaved in the same run: git's answers equal, the traversal's access at least 4x faster and a one-shot resolve at least 8x faster (decision 0014) |
| `tests/lineage_example.py` | Builds the example's throwaway sources, traces them and (with `--record`) writes `examples/` |
| `tests/fixtures/sample-attempts.json` | The sample attempt records (`lineage-sample-attempts/v1`, `"sample": true`) |
| `tests/test_live_lineage.py` | Live, against the pinned Backlog.md 1.55.3 and OpenSpec 1.16.0 (including the traversal over live tasks and after a real `openspec archive`); skipped unless `AIEH_BACKLOG` and `AIEH_OPENSPEC` are set |

## Reference kinds

| Kind | Canonical form | Authority | Stable identity | Revision anchor | Pinning | Status |
|---|---|---|---|---|---|---|
| `conversation` | `conversation:<thread>[@<message>]` | Owner conversation store (assistant-ui local persistence) | native thread id | the thread through one message | optional | authority unavailable: U-02.1, U-02.2 |
| `message` | `conversation:<thread>/<message>[#sha256:<hex> \| #span:<start>+<length>:sha256:<hex>]` | Owner conversation store | native thread and message ids | content digest, or a span anchor | optional | authority unavailable: U-02.1, U-02.2 |
| `objective` | `outcome:<uuid>[@<commit>]` | OpenSpec (the declaring change's intent record and `.openspec.yaml`) | the outcome id: a lower-case UUID minted when an Objective item's acceptance is recorded, declared under `x-outcomes` (decision 0008) | project repository commit; observed digest: the declaring `proposal.md` | optional | implemented |
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
- An **outcome id** is a random UUID in canonical lower-case text (8-4-4-4-12 hex), as
  [decision 0008](../../decisions/0008-outcome-identity-assignment-form-and-record.md)
  assigns it; the blueprint's illustrative `outcome:O-101` is refused.
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
store and writing the quote into a proposal are not built here (U-02.x). The P-03.2
traversal locates an original quote's bytes in its message to derive and verify a span
([Lineage traversal](#lineage-traversal-p-032)).

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
| `objective` | git objects only, at the pinned commit or at `HEAD` (decision 0008, point 6): every `openspec/changes/<change>/.openspec.yaml` and `openspec/changes/archive/<dated-change>/.openspec.yaml` is read with a strict reader of the `x-outcomes` block (`read_x_outcomes`); exactly one change must declare the id; its proposal is parsed with the intent-record/v1 parser (`tools/check_intent_record.py`) and the declared item must be an Objective item with `authority: accepted` and the declared acceptance. A resolved answer carries `facts`: the change, item, statement, acceptance, source and the accepted Acceptance Criteria citing the item; `observed_digest` is the sha256 of `proposal.md`. It never runs openspec or reads the working tree. | `missing` OUTCOME_MISSING, OUTCOME_NOT_ACCEPTED; `revision-mismatch` OUTCOME_REVISION_MISSING; `ambiguous` OUTCOME_AMBIGUOUS; `authority-unavailable` PROJECT_UNAVAILABLE, GIT_FAILED, OUTCOME_METADATA_INVALID |
| `work` | Backlog.md's `task view <id> --json` and `task list --json` through the P-02 wrapper, limited to those two commands. A pinned reference is read by Backlog.md from an export of that commit in a temporary directory (blob bytes, decision 0014 section 4; a `git archive` export before F-10.3); the pinned Backlog.md answered there and wrote nothing (observed live). | `missing` WORK_MISSING; `revision-mismatch` WORK_REVISION_MISSING; `ambiguous` WORK_AMBIGUOUS; `authority-unavailable` PROJECT_UNAVAILABLE, BACKLOG_UNAVAILABLE, BACKLOG_VIEW_FAILED, BACKLOG_LIST_FAILED |
| `commit` | `<commit>^{commit}` and, when that is no commit, the object's type, read through the P-02.1 repository access (the shared module over Dulwich, as `git rev-parse` and `git cat-file` answer) in the clone registered for the repository name | `missing` COMMIT_MISSING, COMMIT_NOT_A_COMMIT, COMMIT_ID_MISMATCH; `authority-unavailable` REPOSITORY_NOT_REGISTERED, REPOSITORY_UNAVAILABLE, GIT_FAILED |
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
python -I -B integrations/lineage/lineage_trace.py trace OUTCOME --project DIR [--backlog CMD] [--store DB]   # task lineage:trace -- ...
python -I -B integrations/lineage/tests/lineage_example.py [--record]            # task lineage:example
python -I -B -m unittest discover -s integrations/lineage/tests -v                # task lineage:test
```

`--project` enables `design` (and, with `--backlog`, `work`); `--repo` registers a clone
for `commit`; `--effects-root` enables `effect-receipt` with the effects store's live
location policy and custody template, exactly as the effects command line uses them.
Exit status: 0 PASS (all parsed, or all resolved), 1 FAIL, 2 could not run.

`trace` prints the projection as JSON and one `UNCERTAIN` line per uncertainty on stderr.
It uses the real authorities only, never a sample. Exit status: 0 the projection is
complete, 1 it carries uncertainty, 2 could not run. `lineage_example.py` rebuilds the
example offline and prints each projection's verdict and counts; `--record` rewrites
`examples/`.

## Observed live (OpenSpec 1.16.0, Windows 11)

- `openspec validate <change> --strict` exits 0 with an `x-outcomes` declaration in the
  change's `.openspec.yaml`.
- `openspec archive <change> --yes` moves the change to
  `openspec/changes/archive/<YYYY-MM-DD>-<change>/` with `.openspec.yaml` byte for byte
  unchanged (it also writes the change's specs into `openspec/specs/`), and the outcome
  then resolves at the archived path, current and pinned.

## Lineage traversal (P-03.2)

`lineage_trace.trace(outcome, authorities, project=..., backlog=..., store=...)` follows the
blueprint's minimal relationship contract (`#authority`) from one outcome id, read-only, and
returns a projection. "If a source relationship was never recorded, the UI must show missing
provenance, not invent a causal history": every link the traversal cannot establish is an
explicit uncertainty, and the verdict is `complete` only when there is none.

### The chain and the record that asserts each edge

| Edge | Relation | Asserted by (provenance) |
|---|---|---|
| statement → objective | `originates` | the Objective item's `source` in the declaring change's intent record (`proposal.md`), read from git at the objective's observed revision, with that blob's sha256. A local item id that names an **Original Quote** item (for example `Q1`) is followed to the quote's own `source` message (`via`); other local items are not followed |
| objective → statement | `accepted_by` | the Objective item's `acceptance`, bound by the `x-outcomes` declaration (decision 0008, point 4) |
| objective → design | `shaped_by` | the declaring change's files at that revision, as P-02.1 pointers (`.openspec.yaml` is metadata, not an artifact) |
| objective → work | `fulfilled_by` | a Backlog.md task's own references (`task list --json`), when one is the outcome (`outcome:<id>`, any revision) or a pointer into the declaring change; or an attempt reservation that cites both the outcome and the task |
| work → design | `cites` | the same task's references: the design pointers it was pinned to |
| work → attempt | `executed_by` | an integration-store attempt reservation (F-05.1): its operation key, intent digest and reservation event (`seq` 0 and its journal `event_id`) |

Backlog.md has no reverse index from a design or an outcome to its tasks, so the traversal
enumerates the tasks with Backlog.md's own `task list --json`, the supported read, and reads
only each task's `id` and `references`, never a status (P-02.2's discipline). The attempt's
identity is the reservation's `conversation_id` (`openhands:conversation/<uuid>`, decision
0001). The reservation's intent is read at two keys only, `workRef` (a `backlog:` reference)
and `outcomeRef` (an `outcome:` reference). These are the names of the blueprint's
illustrative correlation receipt (`#integration-contracts`); no accepted record fixes the
intent's shape yet, and the dispatcher that writes it (E-01.x) must use them or this reader
changes with it. A key present with another kind of value is a `malformed-reference`
uncertainty.

### Projection (`lineage-projection/v1`)

```
{format, root, verdict: complete|incomplete,
 sources: {project_head, backlog, store_schema_version},
 authority_modes: {authoritative: n, sample: n, unavailable: n},
 nodes: [{reference, kind, role, authority, authority_mode, pinned,
          resolution: {query, outcome, code, detail, observed_revision, observed_digest},
          current: {...the same, at the authority's current revision},
          freshness, [facts], [quotes], [moved_to]}],
 edges: [{from, to, relation, provenance: [{record, authority, revision, ...}]}],
 uncertainties: [{reference, reason, code, detail, [outcome]}]}
```

- `role` is `statement`, `objective`, `design`, `work`, `attempt` or `other`.
- `authority_mode` is `authoritative` (a real authority answered), `sample` (a sample
  authority answered) or `unavailable` (the authority could not be asked).
- `freshness` compares the reference as written with the authority's current revision:
  `current` (same digest), `superseded` (another digest now), `moved`, `moved-changed`,
  `gone` (design pointers, below) or `unknown`.
- `facts` is the objective's resolved record (decision 0008, point 6): the pinned reading,
  so the projection shows what was known at the pin.
- `quotes` (statement nodes reached through an Original Quote): the span anchor the
  traversal derived by locating the quote's bytes in the durable message content, and its
  check (Overseer decision D2). It is checked only when the statement's authority returns
  content; today only the sample does.
- Nodes, edges and uncertainties are sorted, so a projection is reproducible.

Uncertainty reasons (closed list) and their codes:

| Reason | Codes |
|---|---|
| `unresolved` | the resolution code: for example `MESSAGE_MISSING`, `SPAN_DIGEST_MISMATCH`, `OUTCOME_MISSING`, `OUTCOME_AMBIGUOUS`, `POINTER_DIGEST_MISMATCH`, `WORK_MISSING`, `ATTEMPT_MISSING`, `AUTHORITY_NOT_YET_AVAILABLE`, `REFERENCE_UNSUPPORTED_SCHEME` |
| `current-unresolved` | the current resolution's code (for example `OUTCOME_MISSING` after the change was removed), `DESIGN_ARCHIVE_AMBIGUOUS`, `GIT_FAILED` |
| `superseded` | `SUPERSEDED`: the pinned reading resolves, the current revision has another digest |
| `moved` / `moved-changed` / `gone` | `DESIGN_ARTIFACT_MOVED`, `DESIGN_ARTIFACT_MOVED_AND_CHANGED`, `DESIGN_ARTIFACT_GONE` |
| `sample-authority` | `SAMPLE_AUTHORITY`: resolved only by a sample |
| `quote-unverified` | `QUOTE_NOT_IN_SOURCE`, `QUOTE_SPAN_AMBIGUOUS`, `QUOTE_MISSING`, `QUOTE_SOURCE_NOT_A_MESSAGE`, `QUOTE_SOURCE_UNREADABLE` |
| `missing-link` | `NO_SOURCE_STATEMENT`, `SOURCE_ITEM_MISSING`, `NO_TASK_FOR_OBJECTIVE`, `NO_ATTEMPT_FOR_TASK`, `DESIGN_ARCHIVED_AT_REVISION`, `INTENT_RECORD_CHANGED`, `INTENT_RECORD_UNREADABLE` |
| `malformed-reference` | `REFERENCE_MALFORMED`, `TASK_REFERENCES_MALFORMED`, `INTENT_REFERENCE_MALFORMED` |
| `enumeration-unavailable` | `PROJECT_UNAVAILABLE`, `BACKLOG_NOT_CONFIGURED`, `BACKLOG_LIST_FAILED`, `BACKLOG_UNAVAILABLE`, `STORE_NOT_CONFIGURED`, `STORE_UNAVAILABLE`, `GIT_FAILED` |

### Moved versus gone

After `openspec archive`, a design pointer still resolves at its pinned commit, but its
`current()` answers `missing` (`POINTER_ARTIFACT_MISSING`) because the artifact's path
moved. For exactly that code the traversal looks, in git at `HEAD`, for
`openspec/changes/archive/<YYYY-MM-DD>-<change>/<artifact>`:

- one copy whose blob has the pointer's sha256: `moved` (`moved_to` names the path,
  revision and digest);
- one copy with another sha256: `moved-changed`;
- two or more copies: `current-unresolved` `DESIGN_ARCHIVE_AMBIGUOUS`;
- none: `gone`.

Each is an uncertainty, `moved` included: the pointer no longer resolves at its own path,
so the projection says where the bytes went rather than counting it as current. The
P-02.1 pointer format is unchanged. An objective whose declaring change is archived at the
revision read still resolves (decision 0008, point 6), but its artifacts cannot be written
as P-02.1 pointers, so the design is then reached only through task references
(`DESIGN_ARCHIVED_AT_REVISION`). This was shown live after a real `openspec archive`.

### Authorities and samples

`Authorities(registry, samples)` asks the P-03.1 `Registry` and reports each answer's
`authority_mode`. Two kinds have no local authority yet: statements (`conversation`,
`message`: the assistant-ui conversation store, U-02.x) and attempts (`attempt`: the
OpenHands Agent Server, E-01.x). The real registry answers `authority-unavailable` for
them, which is the explicit uncertainty P-03 asks for. To show the whole chain,
`lineage_samples.py` provides two **sample** authorities. `Authorities` accepts a sample only
for a kind whose schema status is `authority-unavailable`, and only when its authority
label starts with `SAMPLE`. The default registry and the command line never use one.

- `SampleStatementStore`: the committed P-01.2 corpus
  (`tools/tests/fixtures/intent_qualification/corpus/`, LF on every host), so message bytes
  are exact and digests and span anchors verify.
- `SampleAttemptRecords`: `tests/fixtures/sample-attempts.json`, records keyed by the
  reserved conversation id carrying only fields F-04.2 recorded for the Agent Server's
  conversation info (`id`, `title`, `tags`, `created_at`, `workspace`). `execution_status`
  is left out on purpose: the projection carries identity and provenance, not another
  product's state. The sample has no events, as F-04.2 observed for a conversation with no
  message.

Every node a sample answers is `authority_mode: sample` and a `sample-authority`
uncertainty, so a projection that uses a sample is never `complete`.

### Read-only

- Git objects only, read in this process through the P-02.1 repository access (the shared
  module over Dulwich, decision 0014: object reads, file lists and blob-bytes exports, as
  `rev-parse`, `cat-file`, `ls-tree` and, before F-10.3, `archive` answered), never the
  working tree; no git is launched and OpenSpec is never run.
- One operation per traversal (plan leaf F-09.4): `Traversal.run` is one adapter operation
  (`planning_adapter.operation`) in which every resolver and the enumeration share one
  `planning_adapter.Git` per project (one work-tree check) with one read session: one opened
  repository, objects memoized by full commit id and each revision resolved once (a snapshot
  for the traversal); Backlog.md's reads are made once each. The operation closes every
  session when the traversal ends, normally or by an exception; nothing is kept for the next
  traversal. One traversal of the example launches no process with Backlog.md answered in the
  test process, and 3 with the fake Backlog.md launched (its `task list` once and `task view`
  once per task), against 4 and 7 with the F-09.4 batch reader and 70 and 79 before it. A
  resolver called outside a traversal is its own operation.
- Backlog.md: `task list --json` and `task view --json` only (`ReadOnlyBacklog`).
- Integration store: `ReadOnlyIntegrationStore`. The store's own `open_store` migrates in a
  write transaction and creates an absent file, so it is not used. Instead the existing
  file is opened with SQLite's `mode=ro` (`storecore.open_read_only`), `query_only` is set,
  and `storecore.check_current` verifies the store kind and its migrations without
  migrating; a store that would need a migration, an absent file and a database of another
  kind are each `STORE_UNAVAILABLE`, unchanged. Only `attempts` and `events` are exposed.
  The tests show the database file's bytes and canonical content unchanged, also beside an
  open writer whose latest reservation is still only in the WAL file (it is read). As with any SQLite
  reader of a WAL database, the read creates or updates the `-wal` and `-shm` sidecar files
  (observed: a cleanly closed store gains an empty `-wal` and a `-shm`); no database page
  changes.

### The example

`tests/lineage_example.py` builds, in a throwaway directory: the P-02.1 project repository
(its reproducible design commit `8eacfa8…`) and a second commit that declares outcome
`5c6f4c1e-8d3a-4a3b-9b2e-1f0e7d6c5b4a` for O1 (as the acceptance recorder would);
Backlog.md's own recorded output for the two P-02.1 tasks, replayed by the fake Backlog.md;
and an integration store with one reservation per task (`work-TASK-<n>/implement/revision-1`,
intent `{workRef, outcomeRef}`). It traces `outcome:<id>@<declaring commit>` twice:

| Node | Sample authorities | Real registry |
|---|---|---|
| `conversation:qual-02/message-1` (via Q1; quote span `#span:0+198` verified) | sample, resolved | unavailable (U-02.1, U-02.2) |
| `conversation:qual-02/message-2` (source and acceptance) | sample, resolved | unavailable (U-02.1, U-02.2) |
| the outcome (O1 of `qual-02-search-freshness`) | authoritative, resolved, current | the same |
| six design pointers: proposal, design and spec at the design commit (cited by the tasks) and at the declaring commit (the change's files) | authoritative, resolved, current | the same |
| `backlog:TASK-1`, `backlog:TASK-2` | authoritative, resolved | the same |
| two `openhands:conversation/<reserved uuid>` | sample, resolved | unavailable (E-01.3.1, E-01.4.1) |

Both verdicts are `incomplete`: four `sample-authority` uncertainties with the samples,
four `unresolved` (`AUTHORITY_NOT_YET_AVAILABLE`) with the real registry. The edges are
identical in both: they are asserted by records, not by the authorities.

## Not yet verified

- Every kind whose status is authority unavailable or unknown: no resolver exists, and
  each answers so explicitly.
- Effect receipts on a live store. None exists (decision 0004, point 4). On the live store,
  OS custody denies ordinary integration processes, so a resolver not run under the store's
  custody identity answers `authority-unavailable`; live resolution belongs with G-04.2.1
  and G-04.2.2. The store's only open path, `open_effects_store`, applies pending
  migrations in a write transaction; at the current schema it changes no content (tested),
  but it is not a strictly read-only open.
- Any host but Windows 11 x86_64 (git 2.52.0, Dulwich 1.2.21, Node 24.19.0), Backlog.md's
  cross-branch lookup (`check_active_branches`) on an exported commit, and repositories large
  enough for the per-resolution export to matter.
- The `ambiguous` work outcome against the live Backlog.md (it refuses to list instead).
- The outcome id's acceptance recorder is built by plan leaf P-04.1
  ([`integrations/owner/`](../owner/README.md)) and has run on throwaway fixture repositories
  only: no Owner acceptance has been recorded with it, so declarations exist only in the tests'
  throwaway repositories.
- The traversal against live statement and attempt authorities: none exists, so every
  full-chain run rests on the sample authorities, and the real registry answers
  `authority-unavailable` for both.
- The attempt reservation's intent keys `workRef` and `outcomeRef`: they follow the
  blueprint's illustrative correlation receipt; no accepted record fixes the intent's shape,
  and no dispatcher writes reservations yet (E-01.x).
- Tasks Backlog.md does not list with `task list --json` (for example archived tasks) are
  not enumerated; which tasks that excludes was not examined.
- A live integration store at its trusted-host location: only fixture stores in throwaway
  directories were read.
